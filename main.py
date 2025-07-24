import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import json
import os
import asyncio
from typing import Optional
from datetime import datetime, timezone, timedelta

# --- 設定 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HYPIXEL_API_KEY = os.getenv("HYPIXEL_API_KEY")
UPDATE_INTERVAL_MINUTES = 15

# --- ボットの初期設定 ---
intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- データファイルのパス ---
PLAYERS_FILE = 'players.json'
LEADERBOARDS_FILE = 'leaderboards.json'

# --- nest_asyncioの適用 ---
import nest_asyncio
nest_asyncio.apply()

# --- データ管理関数 ---
def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    return {}

def save_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- ヘルパー関数 ---
def get_bedwars_prestige(level: int) -> str:
    if level < 1099: prestige = "✫"
    elif level < 2099: prestige = "✪"
    elif level < 3099: prestige = "⚝"
    else: prestige = "✥"
    return f"[{level}{prestige}]"

def format_hypixel_rank(player_data: dict) -> str:
    rank = player_data.get("rank")
    if rank == "YOUTUBER": return "[YOUTUBE]"
    if rank == "ADMIN": return "[ADMIN]"
    if rank == "MODERATOR": return "[MOD]"
    
    monthly_package_rank = player_data.get("monthlyPackageRank")
    if monthly_package_rank == "SUPERSTAR": return "[MVP++]"
    
    new_package_rank = player_data.get("newPackageRank")
    if new_package_rank == "MVP_PLUS": return "[MVP+]"
    if new_package_rank == "MVP": return "[MVP]"
    if new_package_rank == "VIP_PLUS": return "[VIP+]"
    if new_package_rank == "VIP": return "[VIP]"
    return ""

JST = timezone(timedelta(hours=+9), 'JST')

def get_jst_now() -> datetime:
    return datetime.now(JST)

# --- Hypixel API & Embed生成ヘルパー ---
async def get_player_profile(session, username_input: str) -> Optional[dict]:
    url = f"https://api.mojang.com/users/profiles/minecraft/{username_input}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if isinstance(data, dict):
                    return {'uuid': data.get('id'), 'username': data.get('name')}
    except Exception as e:
        print(f"Mojang APIエラー: {e}")
    return None

async def get_player_data(session, uuid):
    if not uuid: return None
    url = f"https://api.hypixel.net/player?key={HYPIXEL_API_KEY}&uuid={uuid}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if isinstance(data, dict) and data.get('success'):
                    return data.get('player')
            elif response.status == 429:
                await asyncio.sleep(60)
                return "RATE_LIMITED"
    except Exception as e:
        print(f"Hypixel APIエラー: {e}")
    return None

async def generate_leaderboard_embed(guild: discord.Guild):
    all_players = load_data(PLAYERS_FILE)
    player_list = all_players.get(str(guild.id), [])

    embed = discord.Embed(
        title=f" Bedwarsレベル リーダーボード | {guild.name}",
        description="サーバーに登録されたプレイヤーのランキングです。",
        color=discord.Color.gold()
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    if not player_list:
        embed.description = "まだプレイヤーが登録されていません。\n`/player add` で登録してください。"
        embed.set_footer(text=f"最終更新: {get_jst_now().strftime('%Y-%m-%d %H:%M:%S JST')}")
        return embed

    leaderboard_data = []
    async with aiohttp.ClientSession() as session:
        for player_info in player_list:
            uuid = player_info.get('uuid')
            username = player_info.get('username')
            player_hypixel_data = await get_player_data(session, uuid)
            
            if player_hypixel_data and player_hypixel_data != "RATE_LIMITED":
                level = player_hypixel_data.get('achievements', {}).get('bedwars_level', 0)
                leaderboard_data.append({'username': username, 'level': level, 'data': player_hypixel_data})
            await asyncio.sleep(0.6)

    leaderboard_data.sort(key=lambda x: x['level'], reverse=True)

    if not leaderboard_data:
        embed.description = "リーダーボードのデータを取得できませんでした。"
    else:
        leaderboard_text = ""
        for i, data in enumerate(leaderboard_data[:25]):
            rank_num = i + 1
            prestige_str = get_bedwars_prestige(data['level'])
            rank_str = format_hypixel_rank(data['data'])
            username_display = data['username'].replace('_', '\\_')
            leaderboard_text += f"**#{rank_num}** {prestige_str} {rank_str} {username_display}\n"
        embed.description = leaderboard_text

    embed.set_footer(text=f"最終更新: {get_jst_now().strftime('%Y-%m-%d %H:%M:%S JST')}")
    return embed

# --- 自動更新タスク ---
@tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
async def update_all_leaderboards():
    print("自動更新タスクを開始します...")
    leaderboards = load_data(LEADERBOARDS_FILE)
    if not leaderboards: return

    for guild_id_str, data in list(leaderboards.items()):
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            del leaderboards[guild_id_str]
            continue
        try:
            channel = await bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])
            new_embed = await generate_leaderboard_embed(guild)
            await message.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"リーダーボード更新中にエラー（削除案件）: {guild.name} ({e})")
            del leaderboards[guild_id_str]
        except Exception as e:
            print(f"リーダーボード {guild.name} の更新中に予期せぬエラー: {e}")
            
    save_data(leaderboards, LEADERBOARDS_FILE)
    print("自動更新タスクが完了しました。")

# --- ボットイベント ---
@bot.event
async def on_ready():
    print(f'{bot.user.name}としてログインしました。(時刻: {get_jst_now().strftime("%H:%M:%S JST")})')
    try:
        synced = await bot.tree.sync()
        print(f'{len(synced)}個のコマンドを同期しました。')
    except Exception as e:
        print(f'コマンドの同期に失敗しました: {e}')
    
    if not update_all_leaderboards.is_running():
        update_all_leaderboards.start()
    print('------')

# --- スラッシュコマンド ---
class PlayerGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="player", description="リーダーボードに登録するプレイヤーを管理します。")

    @app_commands.command(name="add", description="リーダーボードにMinecraftプレイヤーを追加します。")
    @app_commands.describe(username="追加するMinecraftのユーザー名")
    @app_commands.default_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)
        
        async with aiohttp.ClientSession() as session:
            profile = await get_player_profile(session, username)
            if not profile or not profile.get('uuid'):
                return await interaction.followup.send(f"エラー: Minecraftプレイヤー `{username}` が見つかりませんでした。")
        
        exact_username = profile['username']
        uuid = profile['uuid']

        all_players = load_data(PLAYERS_FILE)
        if guild_id_str not in all_players:
            all_players[guild_id_str] = []

        if any(p['uuid'] == uuid for p in all_players[guild_id_str]):
            return await interaction.followup.send(f"エラー: `{exact_username}` は既に追加されています。")

        all_players[guild_id_str].append({'username': exact_username, 'uuid': uuid})
        save_data(all_players, PLAYERS_FILE)
        await interaction.followup.send(f"成功: `{exact_username}` をリーダーボードに追加しました。")

    @app_commands.command(name="remove", description="リーダーボードからMinecraftプレイヤーを削除します。")
    @app_commands.describe(username="削除するMinecraftのユーザー名")
    @app_commands.default_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)
        all_players = load_data(PLAYERS_FILE)
        player_list = all_players.get(guild_id_str, [])
        player_to_remove = next((p for p in player_list if p['username'].lower() == username.lower()), None)
        
        if not player_to_remove:
            return await interaction.followup.send(f"エラー: `{username}` はリストに見つかりませんでした。")
        
        player_list.remove(player_to_remove)
        all_players[guild_id_str] = player_list
        save_data(all_players, PLAYERS_FILE)
        await interaction.followup.send(f"成功: `{player_to_remove['username']}` をリーダーボードから削除しました。")

class LeaderboardGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="leaderboard", description="リーダーボードを管理します。")
    
    @app_commands.command(name="create", description="このサーバーのBedwarsリーダーボードを作成します。")
    @app_commands.default_permissions(manage_guild=True)
    async def create(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel
        guild_id_str = str(interaction.guild.id)
        
        leaderboards = load_data(LEADERBOARDS_FILE)
        if guild_id_str in leaderboards:
            return await interaction.followup.send("エラー: このサーバーには既にリーダーボードが存在します。")
            
        try:
            embed = discord.Embed(title="リーダーボード生成中...", color=discord.Color.blue())
            message = await target_channel.send(embed=embed)
            leaderboards[guild_id_str] = {"channel_id": target_channel.id, "message_id": message.id}
            save_data(leaderboards, LEADERBOARDS_FILE)
            initial_embed = await generate_leaderboard_embed(interaction.guild)
            await message.edit(embed=initial_embed)
            await interaction.followup.send(f"成功: {target_channel.mention} にリーダーボードを作成しました。")
        except Exception as e:
            await interaction.followup.send(f"予期せぬエラー: {e}")

    @app_commands.command(name="remove", description="このサーバーのリーダーボードを削除します。")
    @app_commands.default_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)
        
        leaderboards = load_data(LEADERBOARDS_FILE)
        if guild_id_str not in leaderboards:
            return await interaction.followup.send("エラー: このサーバーにリーダーボードは作成されていません。")
            
        data = leaderboards[guild_id_str]
        try:
            channel = bot.get_channel(data['channel_id']) or await bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
            
        del leaderboards[guild_id_str]
        save_data(leaderboards, LEADERBOARDS_FILE)
        await interaction.followup.send("成功: リーダーボードを削除しました。")

    @app_commands.command(name="refresh", description="リーダーボードを手動で最新の状態に更新します。")
    @app_commands.default_permissions(manage_guild=True)
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)
        leaderboards = load_data(LEADERBOARDS_FILE)
        if guild_id_str not in leaderboards:
            return await interaction.followup.send("エラー: リーダーボードがありません。")
        data = leaderboards[guild_id_str]
        try:
            channel = await bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])
            loading_embed = discord.Embed(title="更新中...", color=discord.Color.blue())
            await message.edit(embed=loading_embed)
            new_embed = await generate_leaderboard_embed(interaction.guild)
            await message.edit(embed=new_embed)
            await interaction.followup.send("成功: 更新しました。")
        except Exception as e:
            await interaction.followup.send(f"エラー: {e}")

class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description="管理者用のデバッグコマンドです。")

    @app_commands.command(name="getfile", description="サーバーに保存されているデータファイルをダウンロードします。")
    @app_commands.describe(filename="ファイル名 (例: players.json)")
    @app_commands.default_permissions(administrator=True)
    async def getfile(self, interaction: discord.Interaction, filename: str):
        if filename not in ['players.json', 'leaderboards.json']:
            return await interaction.response.send_message("エラー: 不正なファイル名です。", ephemeral=True)
        try:
            await interaction.response.send_message(f"`{filename}` を送信します。", file=discord.File(filename), ephemeral=True)
        except FileNotFoundError:
            await interaction.response.send_message(f"エラー: `{filename}` がサーバー上に見つかりませんでした。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"エラーが発生しました: {e}", ephemeral=True)

# --- コマンドをボットに登録 ---
bot.tree.add_command(PlayerGroup())
bot.tree.add_command(LeaderboardGroup())
bot.tree.add_command(AdminGroup())

# --- 実行 ---
if __name__ == "__main__":
    if DISCORD_TOKEN and HYPIXEL_API_KEY:
        bot.run(DISCORD_TOKEN)
    else:
        print("エラー: 必要な環境変数 (DISCORD_TOKEN, HYPIXEL_API_KEY) が設定されていません。")
