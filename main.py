import os
import logging
import sys
from typing import Optional

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
    sys.exit("CHANNEL_ID must be an integer in .env")

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


# =====================================================================
# ここから「募集パネル」機能
# =====================================================================

# メンション対象として選択できるロールID一覧（「なし」は別途選択肢として追加されます）
RECRUIT_ROLE_IDS = [
    1533825506124763177,
    1533824492810272889,
    1533824191839735828,
    1481108235673927730,
    1533823603672613006,
]

# 選択できるVCチャンネルID一覧
RECRUIT_VC_IDS = [
    1430828208277946432,
    1430828208277946433,
    1529408955594440704,
]

# 「やっている内容」のプリセット選択肢（「その他」を選ぶと自由入力用のモーダルが開きます）
RECRUIT_CONTENT_OTHER_VALUE = "__recruit_content_other__"
RECRUIT_CONTENT_OPTIONS = ["雑談", "ゲーム", "作業・勉強", "イベント"]


class RecruitRoleSelect(discord.ui.Select):
    """①メンションするロールを選ぶドロップダウン"""

    def __init__(self, guild: Optional[discord.Guild]):
        options = [
            discord.SelectOption(label="なし", value="none", description="ロールをメンションしません")
        ]
        for role_id in RECRUIT_ROLE_IDS:
            role = guild.get_role(role_id) if guild else None
            label = role.name if role else f"ロール ({role_id})"
            options.append(discord.SelectOption(label=label[:100], value=str(role_id)))

        super().__init__(
            placeholder="① メンションするロールを選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="recruit_role_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "RecruitView" = self.view
        value = self.values[0]
        view.selected_role_id = None if value == "none" else int(value)
        view.role_chosen = True
        await view.refresh(interaction)


class RecruitContentSelect(discord.ui.Select):
    """②やっている内容を選ぶドロップダウン"""

    def __init__(self):
        options = [discord.SelectOption(label=name, value=name) for name in RECRUIT_CONTENT_OPTIONS]
        options.append(
            discord.SelectOption(label="その他（自由入力）", value=RECRUIT_CONTENT_OTHER_VALUE)
        )
        super().__init__(
            placeholder="② やっている内容を選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="recruit_content_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "RecruitView" = self.view
        if self.values[0] == RECRUIT_CONTENT_OTHER_VALUE:
            await interaction.response.send_modal(RecruitContentModal(view))
        else:
            view.selected_content = self.values[0]
            await view.refresh(interaction)


class RecruitContentModal(discord.ui.Modal, title="内容を入力"):
    """「その他」選択時に表示する自由入力用モーダル"""

    content_input = discord.ui.TextInput(
        label="やっている内容",
        placeholder="例: 〇〇について雑談 など",
        max_length=100,
        required=True,
    )

    def __init__(self, view: "RecruitView"):
        super().__init__()
        self.recruit_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.recruit_view.selected_content = str(self.content_input.value).strip()
        await self.recruit_view.refresh(interaction)


class RecruitVCSelect(discord.ui.Select):
    """③使用するVCチャンネルを選ぶドロップダウン"""

    def __init__(self, guild: Optional[discord.Guild]):
        options = []
        for vc_id in RECRUIT_VC_IDS:
            channel = guild.get_channel(vc_id) if guild else None
            label = channel.name if channel else f"VC ({vc_id})"
            options.append(discord.SelectOption(label=label[:100], value=str(vc_id)))

        super().__init__(
            placeholder="③ 使用するVCを選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="recruit_vc_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "RecruitView" = self.view
        view.selected_vc_id = int(self.values[0])
        await view.refresh(interaction)


class RecruitView(discord.ui.View):
    """募集パネル本体（実行者本人にのみ ephemeral で表示される）"""

    def __init__(self, guild: Optional[discord.Guild], author: discord.abc.User):
        super().__init__(timeout=300)  # 5分操作が無ければタイムアウト
        self.guild = guild
        self.author = author

        self.role_chosen = False
        self.selected_role_id: Optional[int] = None
        self.selected_content: Optional[str] = None
        self.selected_vc_id: Optional[int] = None

        self.message: Optional[discord.Message] = None  # on_timeout でパネルを編集するために保持

        self.add_item(RecruitRoleSelect(guild))
        self.add_item(RecruitContentSelect())
        self.add_item(RecruitVCSelect(guild))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # パネルを操作できるのはコマンド実行者本人のみ
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "この操作はコマンドを実行した本人のみ行えます。", ephemeral=True
            )
            return False
        return True

    def is_ready(self) -> bool:
        return self.role_chosen and self.selected_content is not None and self.selected_vc_id is not None

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📋 募集パネル",
            description="下のメニューから①〜③をすべて選択すると「募集を送信する」が押せるようになります。",
            color=discord.Color.blurple(),
        )
        if self.role_chosen:
            role_value = f"<@&{self.selected_role_id}>" if self.selected_role_id else "なし"
        else:
            role_value = "未選択"
        embed.add_field(name="① メンションするロール", value=role_value, inline=False)
        embed.add_field(name="② やっている内容", value=self.selected_content or "未選択", inline=False)
        vc_value = f"<#{self.selected_vc_id}>" if self.selected_vc_id else "未選択"
        embed.add_field(name="③ 使用するVC", value=vc_value, inline=False)
        return embed

    def _update_submit_button_state(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "recruit_submit":
                item.disabled = not self.is_ready()

    async def refresh(self, interaction: discord.Interaction):
        """選択が変わるたびに、ephemeralパネルの内容を更新する"""
        self._update_submit_button_state()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="⌛ タイムアウトしました。もう一度 `/vc` を実行してください。",
                    embed=None,
                    view=self,
                )
            except Exception:
                # メッセージが既に削除されている場合などは無視
                pass

    @discord.ui.button(
        label="募集を送信する",
        style=discord.ButtonStyle.success,
        disabled=True,
        custom_id="recruit_submit",
    )
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_ready():
            await interaction.response.send_message("すべての項目を選択してください。", ephemeral=True)
            return

        role_mention = f"<@&{self.selected_role_id}>" if self.selected_role_id else None
        vc_mention = f"<#{self.selected_vc_id}>"

        embed = discord.Embed(
            title="📢 VC募集中！",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        if role_mention:
            embed.add_field(name="対象ロール", value=role_mention, inline=False)
        embed.add_field(name="内容", value=self.selected_content, inline=False)
        embed.add_field(name="VC", value=vc_mention, inline=False)
        embed.set_footer(text=f"募集者: {interaction.user.display_name}")
        if interaction.user.display_avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # ロールメンションは embed 内だけでは通知が飛ばないため、
        # 実際に通知させたい場合は message の content 側に含める必要がある
        content_text = role_mention or ""

        target_channel = interaction.channel
        try:
            await target_channel.send(content=content_text, embed=embed)
        except discord.Forbidden:
            logger.exception("募集メッセージの送信権限がありません。")
            await interaction.response.send_message(
                "ボットにこのチャンネルへの送信権限がありません。管理者に連絡してください。", ephemeral=True
            )
            return
        except Exception as e:
            logger.exception("募集メッセージ送信中にエラーが発生しました: %s", e)
            await interaction.response.send_message("送信中にエラーが発生しました。あとでもう一度試してください。", ephemeral=True)
            return

        # パネルを無効化して完了表示に更新
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ 募集メッセージを送信しました！", embed=None, view=self)
        self.stop()


@bot.tree.command(name="vc", description="VC募集パネルを表示します（ロール・内容・VCを選んで送信）")
async def vc(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    view = RecruitView(interaction.guild, interaction.user)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
    view.message = await interaction.original_response()

# =====================================================================
# 「募集パネル」機能ここまで
# =====================================================================


if __name__ == "__main__":
    try:
        keep_alive()  # UptimeRobotのping用にFlaskサーバーを起動
        bot.run(BOT_TOKEN)
    except Exception as e:
        logger.exception("Bot の実行に失敗しました: %s", e)
