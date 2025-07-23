import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import json
import os  # ★ osモジュールをインポート
import asyncio
from typing import Optional

# --- 設定 ---
### ★ 修正点: 環境変数から読み込む ###
# os.getenv('環境変数名') を使って、外部から値を取得します。
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HYPIXEL_API_KEY = os.getenv("HYPIXEL_API_KEY")
UPDATE_INTERVAL_MINUTES = 15

# (以下、コードは同じ)
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

# --- ヘルパー関数 (プレステージとランクのフォーマット) ---
### ★ お客様の変更を反映 ★ ###
def get_bedwars_prestige(level: int) -> str:
    """BedWarsレベルからプレステージアイコンを返します。"""
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

# --- Hypixel API & Embed生成ヘルパー ---
async def get_uuid(session, username):
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if isinstance(data, dict):
                    return data.get('id')
                else:
                    print(f"警告: Mojang APIが予期せぬ形式のデータを返しました: {data}")
                    return None
    except Exception as e:
        print(f"Mojang APIへのリクエスト中にエラーが発生しました: {e}")
    return None

async def get_player_data(session, uuid):
    if not uuid: return None
    url = f"https://api.hypixel.net/player?key={HYPIXEL_API_KEY}&uuid={uuid}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if not isinstance(data, dict):
                    print(f"警告: Hypixel APIが予期せぬ形式のデータを返しました: {data}")
                    return None
                
                if data.get('success'):
                    return data.get('player')
                else:
                    print(f"Hypixel APIエラー: {data.get('cause')}")
                    return None
            elif response.status == 429:
                print("レート制限に達しました。60秒待機します。")
                await asyncio.sleep(60)
                return "RATE_LIMITED"
    except Exception as e:
        print(f"Hypixel APIへのリクエスト中にエラーが発生しました: {e}")
    return None

async def generate_leaderboard_embed(guild: discord.Guild):
    all_players = load_data(PLAYERS_FILE)
    player_list = all_players.get(str(guild.id), [])

    embed = discord.Embed(
        title=f" Bedwarsレベル リーダーボード | {guild.name}",
        description="サーバーに登録されたプレイヤーのBedwarsレベルランキングです。",
        color=discord.Color.gold()
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    if not player_list:
        embed.description = "まだ誰もプレイヤーが登録されていません。\n`/player add` で登録してください。"
        return embed

    leaderboard_data = []
    async with aiohttp.ClientSession() as session:
        for player_info in player_list:
            uuid = player_info.get('uuid')
            username = player_info.get('username')

            player_hypixel_data = None
            while True:
                player_hypixel_data = await get_player_data(session, uuid)
                if player_hypixel_data != "RATE_LIMITED":
                    break
            
            if player_hypixel_data:
                level = player_hypixel_data.get('achievements', {}).get('bedwars_level', 0)
                leaderboard_data.append({
                    'username': username,
                    'level': level,
                    'data': player_hypixel_data
                })
            else:
                print(f"警告: {username} (UUID: {uuid}) のデータ取得に失敗しました。")

            await asyncio.sleep(0.6)

    leaderboard_data.sort(key=lambda x: x['level'], reverse=True)

    if not leaderboard_data:
        embed.description = "リーダーボードのデータを取得できませんでした。Hypixel APIがダウンしているか、有効なプレイヤーが登録されていない可能性があります。"
    else:
        leaderboard_text = ""
        for i, data in enumerate(leaderboard_data[:25]):
            rank_num = i + 1
            prestige_str = get_bedwars_prestige(data['level'])
            rank_str = format_hypixel_rank(data['data'])
            username = data['username'].replace('_', '\\_')
            
            leaderboard_text += f"**#{rank_num}** {prestige_str} {rank_str} {username}\n"
        
        embed.description = leaderboard_text

    embed.set_footer(text=f"最終更新: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    return embed

# --- 自動更新タスク ---
@tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
async def update_all_leaderboards():
    print("自動更新タスクを開始します...")
    leaderboards = load_data(LEADERBOARDS_FILE)
    if not leaderboards:
        print("更新対象のリーダーボードはありませんでした。")
        return

    for guild_id_str, data in list(leaderboards.items()):
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            print(f"Guild {guild_id_str} が見つかりません。データベースから削除します。")
            del leaderboards[guild_id_str]
            continue
        
        try:
            channel = await bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])
            
            print(f"{guild.name} のリーダーボードを更新中...")
            new_embed = await generate_leaderboard_embed(guild)
            await message.edit(embed=new_embed)
        except discord.NotFound:
            print(f"ChannelまたはMessageが見つかりません。{guild.name} のリーダーボードをデータベースから削除します。")
            del leaderboards[guild_id_str]
        except Exception as e:
            print(f"リーダーボード {guild.name} の更新中にエラーが発生しました: {e}")
            
    save_data(leaderboards, LEADERBOARDS_FILE)
    print("自動更新タスクが完了しました。")

# --- ボットイベント ---
@bot.event
async def on_ready():
    print(f'{bot.user.name}としてログインしました。')
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
            uuid = await get_uuid(session, username)
            if not uuid:
                await interaction.followup.send(f"エラー: Minecraftプレイヤー `{username}` が見つかりませんでした。")
                return

        all_players = load_data(PLAYERS_FILE)
        if guild_id_str not in all_players:
            all_players[guild_id_str] = []

        if any(p['uuid'] == uuid for p in all_players[guild_id_str]):
            await interaction.followup.send(f"エラー: `{username}` は既に追加されています。")
            return

        all_players[guild_id_str].append({'username': username, 'uuid': uuid})
        save_data(all_players, PLAYERS_FILE)
        await interaction.followup.send(f"成功: `{username}` をリーダーボードに追加しました。すぐに反映するには `/leaderboard refresh` を実行してください。")

    @app_commands.command(name="remove", description="リーダーボードからMinecraftプレイヤーを削除します。")
    @app_commands.describe(username="削除するMinecraftのユーザー名")
    @app_commands.default_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)
        
        all_players = load_data(PLAYERS_FILE)
        player_list = all_players.get(guild_id_str, [])

        player_to_remove = None
        for p in player_list:
            if p['username'].lower() == username.lower():
                player_to_remove = p
                break
        
        if not player_to_remove:
            await interaction.followup.send(f"エラー: `{username}` はリストに見つかりませんでした。")
            return
        
        player_list.remove(player_to_remove)
        all_players[guild_id_str] = player_list
        save_data(all_players, PLAYERS_FILE)
        await interaction.followup.send(f"成功: `{username}` をリーダーボードから削除しました。すぐに反映するには `/leaderboard refresh` を実行してください。")

class LeaderboardGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="leaderboard", description="リーダーボードを管理します。")
    
    @app_commands.command(name="create", description="このサーバーのBedwarsリーダーボードを作成します。")
    @app_commands.describe(channel="リーダーボードを作成するチャンネル（省略時はこのチャンネル）")
    @app_commands.default_permissions(manage_guild=True)
    async def create(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel
        guild_id_str = str(interaction.guild.id)
        
        leaderboards = load_data(LEADERBOARDS_FILE)
        if guild_id_str in leaderboards:
            await interaction.followup.send("エラー: このサーバーには既にリーダーボードが存在します。`/leaderboard remove`で削除してください。")
            return
            
        try:
            embed = discord.Embed(title="リーダーボード生成中...", description="データを取得しています。しばらくお待ちください...", color=discord.Color.blue())
            message = await target_channel.send(embed=embed)
            
            leaderboards[guild_id_str] = {"channel_id": target_channel.id, "message_id": message.id}
            save_data(leaderboards, LEADERBOARDS_FILE)
            
            initial_embed = await generate_leaderboard_embed(interaction.guild)
            await message.edit(embed=initial_embed)
            
            await interaction.followup.send(f"成功: {target_channel.mention} にリーダーボードを作成しました。{UPDATE_INTERVAL_MINUTES}分ごとに自動更新されます。")
        except discord.Forbidden:
            await interaction.followup.send("エラー: ボットにこのチャンネルでメッセージを送信/編集する権限がありません。")
        except Exception as e:
            print(f"リーダーボード作成中に予期せぬエラーが発生しました: {e}")
            await interaction.followup.send(f"予期せぬエラーが発生しました。ボットのログを確認してください。")

    @app_commands.command(name="remove", description="このサーバーのリーダーボードを削除します。")
    @app_commands.default_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)
        
        leaderboards = load_data(LEADERBOARDS_FILE)
        if guild_id_str not in leaderboards:
            await interaction.followup.send("エラー: このサーバーにリーダーボードは作成されていません。")
            return
            
        data = leaderboards[guild_id_str]
        try:
            channel = bot.get_channel(data['channel_id']) or await bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])
            await message.delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            await interaction.followup.send("警告: リーダーボードメッセージの削除に失敗しました。DBからは削除します。")
        except Exception as e:
            await interaction.followup.send(f"メッセージ削除中にエラーが発生しました: {e}")
            
        del leaderboards[guild_id_str]
        save_data(leaderboards, LEADERBOARDS_FILE)
        await interaction.followup.send("成功: リーダーボードを削除し、自動更新を停止しました。")

    ### ★ 新しいコマンド ★ ###
    @app_commands.command(name="refresh", description="リーダーボードを手動で最新の状態に更新します。")
    @app_commands.default_permissions(manage_guild=True)
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild.id)

        leaderboards = load_data(LEADERBOARDS_FILE)
        if guild_id_str not in leaderboards:
            await interaction.followup.send("エラー: このサーバーにリーダーボードは作成されていません。`/leaderboard create`で作成してください。")
            return

        data = leaderboards[guild_id_str]
        try:
            channel = bot.get_channel(data['channel_id']) or await bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])

            # 更新中であることをユーザーに伝える
            loading_embed = discord.Embed(title="リーダーボード更新中...", description="最新のデータを取得しています...", color=discord.Color.blue())
            await message.edit(embed=loading_embed)
            
            # 新しいリーダーボードを生成してメッセージを更新
            new_embed = await generate_leaderboard_embed(interaction.guild)
            await message.edit(embed=new_embed)

            await interaction.followup.send("成功: リーダーボードを更新しました。")

        except discord.NotFound:
            await interaction.followup.send("エラー: リーダーボードのメッセージが見つかりませんでした。`/leaderboard remove` を実行後、再度作成してください。")
        except discord.Forbidden:
            await interaction.followup.send("エラー: リーダーボードのメッセージを編集する権限がありません。ボットの権限を確認してください。")
        except Exception as e:
            print(f"リーダーボードの手動更新中にエラー: {e}")
            await interaction.followup.send("予期せぬエラーが発生しました。ボットのログを確認してください。")

# --- コマンドをボットに登録 ---
bot.tree.add_command(PlayerGroup())
bot.tree.add_command(LeaderboardGroup())


# --- 実行 ---
if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        print("エラー: Discordトークンが設定されていません。")
    elif not HYPIXEL_API_KEY or HYPIXEL_API_KEY == "YOUR_HYPIXEL_API_KEY":
        print("エラー: Hypixel APIキーが設定されていません。")
    else:
        bot.run(DISCORD_TOKEN)
