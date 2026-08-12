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
# - /vc 機能を使うには、Botに「Server Members Intent」および「Voice State Intent」を
#   Discord Developer Portal で有効にしてください（intents.voice_states を使用します）。

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

intents = discord.Intents.default()
intents.voice_states = True  # /vc のVC監視（全員退出検知）に必要
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


# =====================================================================
# /vc 募集機能
# =====================================================================

# 送信先（募集告知）チャンネルID
VC_RECRUIT_TARGET_CHANNEL_ID = 1535644078660780153

# メンション対象として選択できるロールID一覧
VC_MENTION_ROLE_IDS = [
    1533825506124763177,
    1533824492810272889,
    1533824191839735828,
    1481108235673927730,
    1533823603672613006,
]

# 選択できるVCチャンネルID一覧
VC_TARGET_CHANNEL_IDS = [
    1430828208277946432,
    1430828208277946433,
    1529408955594440704,
]

# 「やっている内容」の選択肢
VC_CONTENT_OPTIONS = [
    "雑談",
    "ゲーム",
    "作業・勉強",
    "映画・動画視聴",
    "その他",
]

# VCチャンネルID -> 送信した募集Embedメッセージ（全員退出検知用）
active_vc_recruitments: dict[int, discord.Message] = {}


class VCRoleSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild | None):
        options = [discord.SelectOption(label="なし", value="none", default=True)]
        for role_id in VC_MENTION_ROLE_IDS:
            role = guild.get_role(role_id) if guild else None
            label = role.name if role else f"ロール({role_id})"
            options.append(discord.SelectOption(label=label[:100], value=str(role_id)))
        super().__init__(
            placeholder="① メンションするロールを選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vc_role_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "VCRecruitView" = self.view
        view.selected_role_id = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == self.values[0])
        await interaction.response.edit_message(view=view)


class VCContentSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=content, value=content)
            for content in VC_CONTENT_OPTIONS
        ]
        super().__init__(
            placeholder="② やっている内容を選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vc_content_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "VCRecruitView" = self.view
        view.selected_content = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == self.values[0])
        await interaction.response.edit_message(view=view)


class VCChannelSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild | None):
        options = []
        for ch_id in VC_TARGET_CHANNEL_IDS:
            channel = guild.get_channel(ch_id) if guild else None
            label = channel.name if channel else f"VC({ch_id})"
            options.append(discord.SelectOption(label=label[:100], value=str(ch_id)))
        super().__init__(
            placeholder="③ 使用するVCチャンネルを選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vc_channel_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "VCRecruitView" = self.view
        view.selected_vc_id = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == self.values[0])
        await interaction.response.edit_message(view=view)


class VCMessageModal(discord.ui.Modal, title="一言（任意）"):
    def __init__(self, parent_view: "VCRecruitView"):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.message_input = discord.ui.TextInput(
            label="一言メッセージ（任意）",
            placeholder="例: 初心者歓迎です！途中参加OK",
            required=False,
            max_length=200,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.parent_view

        if view.selected_content is None or view.selected_vc_id is None:
            await interaction.response.send_message(
                "「やっている内容」と「使用するVCチャンネル」は必須です。選択し直してください。",
                ephemeral=True,
            )
            return

        target_channel = bot.get_channel(VC_RECRUIT_TARGET_CHANNEL_ID)
        if target_channel is None:
            try:
                target_channel = await bot.fetch_channel(VC_RECRUIT_TARGET_CHANNEL_ID)
            except Exception as e:
                logger.exception("募集告知チャンネルの取得に失敗: %s", e)
                await interaction.response.send_message(
                    "募集の送信に失敗しました（告知チャンネルが見つかりません）。管理者に連絡してください。",
                    ephemeral=True,
                )
                return

        vc_channel_id = int(view.selected_vc_id)
        one_liner = self.message_input.value.strip()

        embed = discord.Embed(
            title="🎤 VC募集",
            color=discord.Color.green(),
        )
        embed.add_field(name="内容", value=view.selected_content, inline=False)
        embed.add_field(name="VC", value=f"<#{vc_channel_id}>", inline=False)
        if one_liner:
            embed.add_field(name="一言", value=one_liner, inline=False)
        embed.set_footer(text=f"募集者: {interaction.user.display_name}")

        mention_content = ""
        if view.selected_role_id and view.selected_role_id != "none":
            mention_content = f"<@&{int(view.selected_role_id)}>"

        allowed_mentions = discord.AllowedMentions(roles=True)

        try:
            sent_message = await target_channel.send(
                content=mention_content if mention_content else None,
                embed=embed,
                allowed_mentions=allowed_mentions,
            )
        except discord.Forbidden:
            logger.exception("募集告知チャンネルへの送信権限がありません。")
            await interaction.response.send_message(
                "ボットに告知チャンネルへの送信権限がありません。管理者に連絡してください。",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.exception("募集メッセージ送信中にエラーが発生しました: %s", e)
            await interaction.response.send_message(
                "送信中にエラーが発生しました。あとでもう一度試してください。",
                ephemeral=True,
            )
            return

        # 全員退出検知用に記録（同じVCで新しい募集が出たら上書き）
        active_vc_recruitments[vc_channel_id] = sent_message

        await interaction.response.send_message("募集を送信しました！", ephemeral=True)
        view.stop()


class VCRecruitView(discord.ui.View):
    def __init__(self, guild: discord.Guild | None):
        super().__init__(timeout=600)
        self.selected_role_id: str | None = "none"
        self.selected_content: str | None = None
        self.selected_vc_id: str | None = None

        self.add_item(VCRoleSelect(guild))
        self.add_item(VCContentSelect())
        self.add_item(VCChannelSelect(guild))

    @discord.ui.button(label="募集を送信する", style=discord.ButtonStyle.primary, row=4)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_content is None or self.selected_vc_id is None:
            await interaction.response.send_message(
                "「やっている内容」と「使用するVCチャンネル」を選択してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(VCMessageModal(self))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.tree.command(name="vc", description="VC募集を作成します")
async def vc_recruit(interaction: discord.Interaction):
    view = VCRecruitView(interaction.guild)
    await interaction.response.send_message(
        "以下から募集内容を選択してください（あなたにのみ表示されています）。",
        view=view,
        ephemeral=True,
    )


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    # 誰かがVCから抜けた／移動した場合のみチェック
    if before.channel is None or before.channel == after.channel:
        return

    left_channel = before.channel
    if left_channel.id not in active_vc_recruitments:
        return

    # まだ誰か残っている場合は何もしない
    if len(left_channel.members) > 0:
        return

    message = active_vc_recruitments.pop(left_channel.id, None)
    if message is None:
        return

    try:
        if message.embeds:
            ended_embed = message.embeds[0].copy()
            ended_embed.title = "🎤 VC募集（募集終了）"
            ended_embed.color = discord.Color.greyple()
            ended_embed.add_field(name="ステータス", value="✅ 終了しました（全員退出）", inline=False)
            await message.edit(embed=ended_embed)
        else:
            await message.edit(content=(message.content or "") + "\n\n✅ **募集終了（全員退出）**")
    except Exception as e:
        logger.exception("募集終了メッセージの編集に失敗しました: %s", e)


if __name__ == "__main__":
    try:
        keep_alive()  # UptimeRobotのping用にFlaskサーバーを起動
        bot.run(BOT_TOKEN)
    except Exception as e:
        logger.exception("Bot の実行に失敗しました: %s", e)
