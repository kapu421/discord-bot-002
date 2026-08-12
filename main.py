# インストール:
# pip install -U "discord.py>=2.0" python-dotenv
#
# .env の例:
# BOT_TOKEN=your_bot_token_here
# CHANNEL_ID=123456789012345678
#
# 注意:
# - Bot は「applications.commands」スコープで招待し、メッセージ送信権限を付与してください。
# - CHANNEL_ID は転送先のチャンネルの ID（整数）を入れてください。

import os
import logging
import sys

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from keep_alive import keep_alive

# 初期設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID_STR = os.getenv("CHANNEL_ID")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN が .env に設定されていません。")
    sys.exit("BOT_TOKEN is required in .env")

if not CHANNEL_ID_STR:
    logger.error("CHANNEL_ID が .env に設定されていません。")
    sys.exit("CHANNEL_ID is required in .env")

try:
    CHANNEL_ID = int(CHANNEL_ID_STR)
except ValueError:
    logger.error("CHANNEL_ID は整数である必要があります。")
    sys.exit("CHANNEL_ID must be an integer in .env")

# NGワード（必要に応じて追加してください）
NG_WORDS = ["バカ", "アホ", "ばか", "あほ"]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    try:
        # アプリコマンドを同期
        await bot.tree.sync()
        logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
        logger.info("App commands synced.")
    except Exception as e:
        logger.exception("Failed to sync app commands: %s", e)

def contains_ng_word(text: str) -> bool:
    for w in NG_WORDS:
        if w in text:
            return True
    return False

def quoted_block(text: str) -> str:
    # メッセージの各行を引用ブロックとして整形
    lines = text.splitlines() or [text]
    return "\n".join(["> " + line for line in lines])

@bot.tree.command(name="secret-msg", description="匿名で管理者チャンネルにメッセージを送信します")
@app_commands.describe(message="送信したいメッセージ")
async def secret_msg(interaction: discord.Interaction, message: str):
    # このコマンドは実行者本人にだけ見えるレスポンスを返します（ephemeral=True）
    try:
        # NGワードチェック
        if contains_ng_word(message):
            await interaction.response.send_message("不適切な言葉が含まれています", ephemeral=True)
            return

        # Discord のメッセージ上限に近い長さを弾く（安全対策）
        if len(message) > 1900:
            await interaction.response.send_message("メッセージが長すぎます（2000文字以内にしてください）", ephemeral=True)
            return

        # 送信先チャンネル取得（キャッシュに無ければ fetch）
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            try:
                channel = await bot.fetch_channel(CHANNEL_ID)
            except Exception as e:
                logger.exception("転送先チャンネルの取得に失敗: %s", e)
                await interaction.response.send_message("送信に失敗しました（チャンネルが見つかりません）。管理者に連絡してください。", ephemeral=True)
                return

        # チャンネルがテキスト送信可能か確認
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.PartialMessageable, discord.abc.Messageable)):
            await interaction.response.send_message("送信先チャンネルのタイプが不正です。管理者に連絡してください。", ephemeral=True)
            return

        # 送信するメッセージ整形（送信者情報は一切含めない）
        content = "📩 **匿名メッセージが届きました**\n" + quoted_block(message)

        # メッセージ送信
        try:
            await channel.send(content)
        except discord.Forbidden:
            logger.exception("Bot に送信権限がありません。")
            await interaction.response.send_message("ボットにチャンネルへの送信権限がありません。管理者に連絡してください。", ephemeral=True)
            return
        except Exception as e:
            logger.exception("メッセージ送信中にエラーが発生しました: %s", e)
            await interaction.response.send_message("送信中にエラーが発生しました。あとでもう一度試してください。", ephemeral=True)
            return

        # 成功レスポンス（実行者本人のみ表示）
        await interaction.response.send_message("送信しました！", ephemeral=True)

    except Exception as e:
        logger.exception("予期しないエラー: %s", e)
        # interaction.response が既に送られている可能性があるため、try/except で安全にレスポンス送信
        try:
            await interaction.response.send_message("エラーが発生しました。管理者に連絡してください。", ephemeral=True)
        except Exception:
            # ここではログだけ残す
            pass

if __name__ == "__main__":
    try:
        keep_alive()  # UptimeRobotのping用にFlaskサーバーを起動
        bot.run(BOT_TOKEN)
    except Exception as e:
        logger.exception("Bot の実行に失敗しました: %s", e)
