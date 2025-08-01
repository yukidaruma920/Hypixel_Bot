# -----------------------------------------------------------------------------
# ベースイメージの指定
# -----------------------------------------------------------------------------
# 公式のPython 3.11のスリムバージョンをベースとして使用します。
# 'slim'は本番環境向けに不要なツールが削ぎ落とされた、より軽量なイメージです。
FROM python:3.11-slim

# -----------------------------------------------------------------------------
# 環境変数の設定
# -----------------------------------------------------------------------------
# Pythonのprint()などがバッファリングされず、すぐにログに出力されるようにします。
ENV PYTHONUNBUFFERED=1
# .pycファイルが生成されないようにし、コンテナをクリーンに保ちます。
ENV PYTHONDONTWRITEBYTECODE=1

# -----------------------------------------------------------------------------
# アプリケーションのセットアップ
# -----------------------------------------------------------------------------
# コンテナ内に作業用のディレクトリを作成します。
WORKDIR /app

# 最初に依存関係ファイルだけをコピーします。
# これにより、コードを変更してもrequirements.txtが変わらなければ、
# Dockerのレイヤーキャッシュが効き、ライブラリの再インストールがスキップされ、
# ビルドが高速化します。
COPY requirements.txt .

# pipをアップグレードし、requirements.txtに書かれたライブラリをインストールします。
# --no-cache-dir はイメージサイズを小さく保つためのベストプラクティスです。
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションの残りのファイルを作業ディレクトリにコピーします。
# main.pyや、初期状態のplayers.jsonなどが含まれます。
COPY . .

# -----------------------------------------------------------------------------
# ポートと実行コマンドの設定
# -----------------------------------------------------------------------------
# Koyebのヘルスチェック用Webサーバーがリッスンするポートをドキュメント化します。
# PORT環境変数がなければ、コードは8080をデフォルトとして使います。
EXPOSE 8080

# コンテナが起動したときに実行されるデフォルトのコマンドを指定します。
# これがあなたのボットを起動するメインのコマンドです。
CMD ["python", "main.py"]