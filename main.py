# インストール:
# pip install -U "discord.py>=2.0" python-dotenv
#
# .env の例:
# BOT_TOKEN=your_bot_token_here
#
# 注意:
# - Bot は「applications.commands」スコープで招待し、メッセージ送信権限を付与してください。
# - メンバーの状態を取得するために "Server Members Intent" を Discord 開発者ポータルで有効にしてください（intents.members = True を使用しています）。

import os
import logging
import sys
import asyncio
from typing import Optional, Dict, Any

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

if not BOT_TOKEN:
    logger.error("BOT_TOKEN が .env に設定されていません。")
    sys.exit("BOT_TOKEN is required in .env")

# Intents: VC の人数やメンバー情報を監視するため members/voice_states を有効にしています。
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ---------------------------------------------------------------------
# VC 募集機能（/vc）
# ---------------------------------------------------------------------

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

# VC -> 募集メッセージのマッピング（ランタイムのみ）
# key: vc_channel_id -> { "text_channel_id": int, "message_id": int, "guild_id": int }
vc_message_map: Dict[int, Dict[str, Any]] = {}
vc_map_lock = asyncio.Lock()


@bot.event
async def on_ready():
    try:
        # アプリコマンドを同期
        await bot.tree.sync()
        logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
        logger.info("App commands synced.")
    except Exception as e:
        logger.exception("Failed to sync app commands: %s", e)

    # VC 監視タスクを一度だけ開始
    if not getattr(bot, "_vc_watcher_started", False):
        bot.loop.create_task(_vc_empty_watcher())
        bot._vc_watcher_started = True


def quoted_block(text: str) -> str:
    # メッセージの各行を引用ブロックとして整形（必要なら再利用）
    lines = text.splitlines() or [text]
    return "\n".join(["> " + line for line in lines])


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
        view: "RecruitView" = self.view  # type: ignore
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
        view: "RecruitView" = self.view  # type: ignore
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


class RecruitCommentModal(discord.ui.Modal, title="一言を入力（任意）"):
    """④一言（任意）入力用モーダル"""

    comment_input = discord.ui.TextInput(
        label="一言（任意）",
        placeholder="例: 初心者歓迎です！ など（空欄でもOK）",
        max_length=200,
        required=False,
    )

    def __init__(self, view: "RecruitView"):
        super().__init__()
        self.recruit_view = view
        # 既に入力済みの内容があれば初期値としてセット
        if view.selected_comment:
            self.comment_input.default = view.selected_comment

    async def on_submit(self, interaction: discord.Interaction):
        value = str(self.comment_input.value).strip()
        self.recruit_view.selected_comment = value or None
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
        view: "RecruitView" = self.view  # type: ignore
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
        self.selected_comment: Optional[str] = None  # ④一言（任意）

        self.message: Optional[discord.Message] = None  # on_timeout でパネルを編集するために保持

        # セレクト類
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
        embed.add_field(name="④ 一言（任意）", value=self.selected_comment or "（未入力）", inline=False)
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
        label="一言（任意）を入力",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit_comment_button",
    )
    async def comment_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # モーダルを表示（任意入力）
        await interaction.response.send_modal(RecruitCommentModal(self))

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
        embed.add_field(name="一言（任意）", value=self.selected_comment or "（なし）", inline=False)
        embed.set_footer(text=f"募集者: {interaction.user.display_name}")
        if interaction.user.display_avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # ロールメンションは embed 内だけでは通知が飛ばないため、
        # 実際に通知させたい場合は message の content 側に含める必要がある
        content_text = role_mention or ""

        target_channel = interaction.channel
        try:
            sent_message = await target_channel.send(content=content_text, embed=embed)
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

        # VC -> メッセージ紐付け（監視対象に追加）
        if self.selected_vc_id:
            async with vc_map_lock:
                vc_message_map[self.selected_vc_id] = {
                    "text_channel_id": target_channel.id,
                    "message_id": sent_message.id,
                    "guild_id": interaction.guild.id if interaction.guild else None,
                }

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


# ---------------------------------------------------------------------
# VC 空チェックのバックグラウンドタスク
# ---------------------------------------------------------------------
async def _vc_empty_watcher():
    """vc_message_map を定期的にチェックして、VC が空になったら該当メッセージを「終了済み」に編集する"""
    await bot.wait_until_ready()
    logger.info("VC empty watcher started.")
    CHECK_INTERVAL = 20  # 秒ごとにチェック
    while not bot.is_closed():
        try:
            async with vc_map_lock:
                keys = list(vc_message_map.keys())
            for vc_id in keys:
                try:
                    vc_channel = bot.get_channel(vc_id)
                    if vc_channel is None:
                        # チャンネルが見つからない場合は監視対象から外す
                        async with vc_map_lock:
                            vc_message_map.pop(vc_id, None)
                        continue

                    # 非ボットの参加者がいるかを確認
                    non_bot_members = [m for m in getattr(vc_channel, "members", []) if not m.bot]
                    if len(non_bot_members) == 0:
                        # 空になった -> 対応するメッセージを編集
                        async with vc_map_lock:
                            info = vc_message_map.pop(vc_id, None)
                        if info:
                            text_ch_id = info.get("text_channel_id")
                            msg_id = info.get("message_id")
                            try:
                                text_ch = bot.get_channel(text_ch_id)
                                if text_ch is None:
                                    # 取得できないなら飛ばす
                                    continue
                                # fetch message to get current embed/content
                                message = await text_ch.fetch_message(msg_id)
                                # 編集: embed のタイトルに「（終了済み）」を付与して色をグレーに変更
                                if message.embeds:
                                    embed = message.embeds[0]
                                    new_embed = embed.copy()
                                    if "終了済み" not in (new_embed.title or ""):
                                        new_embed.title = (new_embed.title or "") + " — 終了済み"
                                    new_embed.colour = discord.Color.dark_gray()
                                    try:
                                        await message.edit(embed=new_embed)
                                    except Exception:
                                        # 編集できない場合はログだけ残す
                                        logger.exception("募集メッセージの編集に失敗しました")
                                else:
                                    # embed が無ければ content に追記
                                    new_content = (message.content or "") + "\n\n（終了済み）"
                                    try:
                                        await message.edit(content=new_content)
                                    except Exception:
                                        logger.exception("募集メッセージの編集に失敗しました")
                            except discord.NotFound:
                                # メッセージが既に削除されている場合は無視
                                pass
                            except Exception:
                                logger.exception
