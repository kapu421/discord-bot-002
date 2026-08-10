# インストール:
# pip install -U "discord.py>=2.0" python-dotenv
#
# .env の例:
# BOT_TOKEN=your_bot_token_here
# CHANNEL_ID=123456789012345678
#
# 注意:
# - Bot は「applications.commands」スコープで招待し、メッセージ送信権限を付与してください。
# - CHANNEL_ID は「受信用」チャンネル（例: #みんなのお便り）の ID（整数）を入れてください。
#   → ここに匿名メッセージが転送されます。
# - ボタン設置用のコマンド /setup-anonymous を「送信用」チャンネル（例: #お便り箱）で実行してください。

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


# ==============================
# 共通ユーティリティ
# ==============================

def contains_ng_word(text: str) -> bool:
    for w in NG_WORDS:
        if w in text:
            return True
    return False


def quoted_block(text: str) -> str:
    # メッセージの各行を引用ブロックとして整形
    lines = text.splitlines() or [text]
    return "\n".join(["> " + line for line in lines])


async def send_anonymous_message(interaction: discord.Interaction, message: str):
    """
    NGワードチェック・長さチェックを行い、CHANNEL_ID の受信用チャンネルへ
    匿名メッセージとして転送する共通処理。
    スラッシュコマンドとモーダルの両方から呼び出される。
    """
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


# ==============================
# モーダル（入力フォーム）
# ==============================

class AnonymousMessageModal(discord.ui.Modal, title="匿名メッセージを送る"):
    message_input = discord.ui.TextInput(
        label="メッセージ内容",
        style=discord.TextStyle.paragraph,
        placeholder="ここに送りたい内容を入力してください（1900文字以内）",
        max_length=1900,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await send_anonymous_message(interaction, str(self.message_input.value))
        except Exception as e:
            logger.exception("モーダル送信処理中にエラーが発生しました: %s", e)
            try:
                await interaction.response.send_message("エラーが発生しました。管理者に連絡してください。", ephemeral=True)
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("モーダルでエラーが発生しました: %s", error)
        try:
            await interaction.response.send_message("エラーが発生しました。管理者に連絡してください。", ephemeral=True)
        except Exception:
            pass


# ==============================
# ボタン（View）
# ==============================

class AnonymousMessageView(discord.ui.View):
    """
    timeout=None + custom_id 固定 にすることで、
    Bot再起動後もボタンが機能し続ける「永続View」にしています。
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="匿名メッセージを送る",
        style=discord.ButtonStyle.primary,
        emoji="✉️",
        custom_id="anonymous_message_button",
    )
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AnonymousMessageModal())


# ==============================
# イベント
# ==============================

@bot.event
async def on_ready():
    try:
        # 永続Viewを登録（Bot再起動後もボタンを押せるようにする）
        bot.add_view(AnonymousMessageView())

        # アプリコマンドを同期
        await bot.tree.sync()
        logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
        logger.info("App commands synced.")
    except Exception as e:
        logger.exception("Failed to sync app commands: %s", e)


# ==============================
# スラッシュコマンド
# ==============================

@bot.tree.command(name="secret-msg", description="匿名で管理者チャンネルにメッセージを送信します")
@app_commands.describe(message="送信したいメッセージ")
async def secret_msg(interaction: discord.Interaction, message: str):
    # このコマンドは実行者本人にだけ見えるレスポンスを返します（ephemeral=True）
    try:
        await send_anonymous_message(interaction, message)
    except Exception as e:
        logger.exception("予期しないエラー: %s", e)
        try:
            await interaction.response.send_message("エラーが発生しました。管理者に連絡してください。", ephemeral=True)
        except Exception:
            pass


@bot.tree.command(name="setup-anonymous", description="【管理者用】このチャンネルに匿名メッセージ送信ボタンを設置します")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_anonymous(interaction: discord.Interaction):
    """
    このコマンドを「送信用チャンネル」（例: #お便り箱）で実行すると、
    ボタン付きのメッセージがそのチャンネルに設置されます。
    """
    try:
        embed = discord.Embed(
            title="📮 匿名メッセージ受付",
            description=(
                "下のボタンを押すと入力フォームが開きます。\n"
                "送信者情報は一切記録・表示されません。安心してご利用ください。"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.channel.send(embed=embed, view=AnonymousMessageView())
        await interaction.response.send_message("このチャンネルにボタンを設置しました。", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("ボットにこのチャンネルへの送信権限がありません。", ephemeral=True)
    except Exception as e:
        logger.exception("setup-anonymous 実行中にエラーが発生しました: %s", e)
        await interaction.response.send_message("エラーが発生しました。", ephemeral=True)


@setup_anonymous.error
async def setup_anonymous_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドはサーバー管理権限を持つ人のみ実行できます。", ephemeral=True)
    else:
        logger.exception("setup-anonymous コマンドエラー: %s", error)
        try:
            await interaction.response.send_message("エラーが発生しました。", ephemeral=True)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        keep_alive()  # UptimeRobotのping用にFlaskサーバーを起動
        bot.run(BOT_TOKEN)
    except Exception as e:
        logger.exception("Bot の実行に失敗しました: %s", e)
