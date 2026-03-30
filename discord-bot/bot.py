import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
import gspread
from discord import app_commands
from discord.ext import commands
from google.oauth2.service_account import Credentials

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "참여인원저장").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "bot_config.json"
SENT_RECORDS_FILE = BASE_DIR / "sent_records.json"


def validate_env() -> None:
    missing = []

    if not DISCORD_BOT_TOKEN:
        missing.append("DISCORD_BOT_TOKEN")
    if not GOOGLE_SHEET_ID:
        missing.append("GOOGLE_SHEET_ID")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")

    if missing:
        raise RuntimeError(f"필수 환경변수가 비어 있음: {', '.join(missing)}")


def load_json_file(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default

    if not isinstance(data, dict):
        return default

    return data


def save_json_file(path: Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_bot_config() -> Dict[str, Any]:
    data = load_json_file(CONFIG_FILE, {"guild_channels": {}})
    if "guild_channels" not in data or not isinstance(data["guild_channels"], dict):
        data["guild_channels"] = {}
    return data


def save_bot_config(config: Dict[str, Any]) -> None:
    save_json_file(CONFIG_FILE, config)


def get_configured_channel_id(guild_id: int) -> Optional[int]:
    config = load_bot_config()
    raw = config.get("guild_channels", {}).get(str(guild_id))

    if not raw:
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_configured_channel_id(guild_id: int, channel_id: int) -> None:
    config = load_bot_config()
    config.setdefault("guild_channels", {})
    config["guild_channels"][str(guild_id)] = str(channel_id)
    save_bot_config(config)


def clear_configured_channel_id(guild_id: int) -> None:
    config = load_bot_config()
    guild_channels = config.setdefault("guild_channels", {})
    guild_channels.pop(str(guild_id), None)
    save_bot_config(config)


def load_sent_records() -> Dict[str, Any]:
    data = load_json_file(SENT_RECORDS_FILE, {"guild_records": {}})
    if "guild_records" not in data or not isinstance(data["guild_records"], dict):
        data["guild_records"] = {}
    return data


def save_sent_records(data: Dict[str, Any]) -> None:
    save_json_file(SENT_RECORDS_FILE, data)


def get_guild_sent_keys(guild_id: int) -> set[str]:
    data = load_sent_records()
    records = data.get("guild_records", {}).get(str(guild_id), [])
    if not isinstance(records, list):
        return set()
    return set(str(x) for x in records)


def add_guild_sent_keys(guild_id: int, keys: List[str]) -> None:
    data = load_sent_records()
    guild_records = data.setdefault("guild_records", {})
    current = guild_records.get(str(guild_id), [])

    if not isinstance(current, list):
        current = []

    merged = sorted(set(str(x) for x in current).union(set(keys)))
    guild_records[str(guild_id)] = merged
    save_sent_records(data)


def clear_guild_sent_keys(guild_id: int) -> None:
    data = load_sent_records()
    guild_records = data.setdefault("guild_records", {})
    guild_records[str(guild_id)] = []
    save_sent_records(data)


def get_gspread_client() -> gspread.Client:
    service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes,
    )
    return gspread.authorize(credentials)


def make_schedule_key(
    date_value: str,
    weekday: str,
    time_value: str,
    participant_codes: List[str],
) -> str:
    normalized_codes = ",".join(sorted(code.strip() for code in participant_codes if code.strip()))
    return f"{date_value}|{weekday}|{time_value}|{normalized_codes}"


def read_participation_rows() -> List[Dict[str, Any]]:
    client = get_gspread_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    worksheet = spreadsheet.worksheet(GOOGLE_WORKSHEET_NAME)

    # 1행: 닉네임 / 2행: 코드 / 3행부터 데이터
    all_values = worksheet.get_all_values()
    if len(all_values) < 3:
        return []

    nickname_row = all_values[0]
    code_row = all_values[1]
    data_rows = all_values[2:]

    # A: 날짜 / B: 요일 / C: 시간 / D~K: 참여 여부
    nicknames = nickname_row[3:11]
    codes = code_row[3:11]

    rows: List[Dict[str, Any]] = []

    for row in data_rows:
        padded = row + [""] * max(0, 11 - len(row))

        date_value = padded[0].strip()
        weekday = padded[1].strip()
        time_value = padded[2].strip()
        marks = padded[3:11]

        if not date_value:
            continue

        participants: List[str] = []
        participant_codes: List[str] = []

        for idx, mark in enumerate(marks):
            if mark.strip().upper() == "O":
                nickname = nicknames[idx].strip() if idx < len(nicknames) else ""
                code = codes[idx].strip() if idx < len(codes) else ""

                participants.append(nickname or code or f"참여자{idx + 1}")
                participant_codes.append(code or f"P{idx + 1}")

        schedule_key = make_schedule_key(
            date_value=date_value,
            weekday=weekday,
            time_value=time_value,
            participant_codes=participant_codes,
        )

        rows.append(
            {
                "date": date_value,
                "weekday": weekday,
                "time": time_value,
                "participants": participants,
                "participant_codes": participant_codes,
                "schedule_key": schedule_key,
            }
        )

    return rows


def sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda x: (
            x["date"],
            x["time"],
            ",".join(x["participant_codes"]),
        ),
    )


def build_row_block(row: Dict[str, Any]) -> str:
    header = row["date"]

    if row["weekday"]:
        header += f" ({row['weekday']})"

    if row["time"]:
        header += f" {row['time']}"

    participant_text = ", ".join(row["participants"]) if row["participants"] else "없음"

    return f"**• {header}**\n{participant_text}"


def build_embeds(rows: List[Dict[str, Any]], title: str) -> List[discord.Embed]:
    max_description_len = 3800
    blocks = [build_row_block(row) for row in rows]

    pages: List[List[str]] = []
    current_page: List[str] = []
    current_len = 0

    for block in blocks:
        add_len = len(block) + (2 if current_page else 0)

        if current_page and current_len + add_len > max_description_len:
            pages.append(current_page)
            current_page = [block]
            current_len = len(block)
        else:
            current_page.append(block)
            current_len += add_len

    if current_page:
        pages.append(current_page)

    embeds: List[discord.Embed] = []

    for idx, page_blocks in enumerate(pages, start=1):
        embed = discord.Embed(
            title=title,
            description="\n\n".join(page_blocks),
        )

        if len(pages) == 1:
            embed.set_footer(text=f"총 {len(rows)}건")
        else:
            embed.set_footer(text=f"{idx}/{len(pages)} 페이지 · 총 {len(rows)}건")

        embeds.append(embed)

    return embeds


def is_guild_manager(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False

    user = interaction.user
    if not isinstance(user, discord.Member):
        return False

    return user.guild_permissions.manage_guild or user.guild_permissions.administrator


def is_allowed_channel(guild_id: Optional[int], channel_id: Optional[int]) -> bool:
    if guild_id is None or channel_id is None:
        return False

    configured_channel_id = get_configured_channel_id(guild_id)

    # 채널 지정 안 했으면 어디서든 사용 가능
    if configured_channel_id is None:
        return True

    return int(configured_channel_id) == int(channel_id)


class ScheduleBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        if DISCORD_GUILD_ID:
            guild = discord.Object(id=int(DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"길드 명령어 동기화 완료: {len(synced)}개")
        else:
            synced = await self.tree.sync()
            print(f"전역 명령어 동기화 완료: {len(synced)}개")

    async def on_ready(self) -> None:
        print(f"로그인 완료: {self.user}")


bot = ScheduleBot()


async def send_embed_pages(
    interaction: discord.Interaction,
    embeds: List[discord.Embed],
    empty_message: str,
) -> None:
    if not embeds:
        await interaction.edit_original_response(content=empty_message)
        return

    await interaction.edit_original_response(content=None, embed=embeds[0])

    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="일정", description="아직 보내지 않은 신규 일정만 불러옵니다.")
@app_commands.guild_only()
async def schedule_command(interaction: discord.Interaction) -> None:
    guild_id = interaction.guild_id
    channel_id = interaction.channel_id

    configured_channel_id = get_configured_channel_id(guild_id) if guild_id else None

    if not is_allowed_channel(guild_id, channel_id):
        if configured_channel_id:
            await interaction.response.send_message(
                f"이 서버에서는 <#{configured_channel_id}> 채널에서만 사용할 수 있어요.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "이 명령어를 사용할 수 없는 채널이에요.",
                ephemeral=True,
            )
        return

    if guild_id is None:
        await interaction.response.send_message(
            "서버에서만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        rows = sort_rows(read_participation_rows())
        sent_keys = get_guild_sent_keys(guild_id)

        new_rows = [row for row in rows if row["schedule_key"] not in sent_keys]

        if not new_rows:
            await interaction.edit_original_response(content="새로 보낼 일정이 없어요.")
            return

        embeds = build_embeds(new_rows, "신규 공대 일정")
        await send_embed_pages(interaction, embeds, "새로 보낼 일정이 없어요.")

        new_keys = [row["schedule_key"] for row in new_rows]
        add_guild_sent_keys(guild_id, new_keys)

    except Exception as e:
        await interaction.edit_original_response(
            content=f"일정을 불러오는 중 오류가 났어요.\n`{type(e).__name__}: {e}`"
        )


@bot.tree.command(name="전체일정", description="현재 시트에 있는 전체 일정을 불러옵니다.")
@app_commands.guild_only()
async def all_schedule_command(interaction: discord.Interaction) -> None:
    guild_id = interaction.guild_id
    channel_id = interaction.channel_id

    configured_channel_id = get_configured_channel_id(guild_id) if guild_id else None

    if not is_allowed_channel(guild_id, channel_id):
        if configured_channel_id:
            await interaction.response.send_message(
                f"이 서버에서는 <#{configured_channel_id}> 채널에서만 사용할 수 있어요.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "이 명령어를 사용할 수 없는 채널이에요.",
                ephemeral=True,
            )
        return

    await interaction.response.defer(thinking=True)

    try:
        rows = sort_rows(read_participation_rows())

        if not rows:
            await interaction.edit_original_response(content="현재 등록된 일정이 없어요.")
            return

        embeds = build_embeds(rows, "전체 공대 일정")
        await send_embed_pages(interaction, embeds, "현재 등록된 일정이 없어요.")

    except Exception as e:
        await interaction.edit_original_response(
            content=f"전체 일정을 불러오는 중 오류가 났어요.\n`{type(e).__name__}: {e}`"
        )


@bot.tree.command(name="기록초기화", description="이 서버의 보낸 일정 기록을 초기화합니다.")
@app_commands.guild_only()
async def reset_sent_records_command(interaction: discord.Interaction) -> None:
    if not is_guild_manager(interaction):
        await interaction.response.send_message(
            "이 명령어는 서버 관리 권한이 있는 사람만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    if interaction.guild_id is None:
        await interaction.response.send_message(
            "서버에서만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    clear_guild_sent_keys(interaction.guild_id)

    await interaction.response.send_message(
        "이 서버의 보낸 일정 기록을 초기화했어요.\n이제 `/일정`을 실행하면 현재 시트의 일정이 다시 신규로 전송돼요.",
        ephemeral=True,
    )


@bot.tree.command(name="채널지정", description="이 서버에서 /일정을 사용할 채널을 지정합니다.")
@app_commands.guild_only()
@app_commands.describe(channel="지정할 텍스트 채널. 비워두면 현재 채널로 설정")
async def set_channel_command(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
) -> None:
    if not is_guild_manager(interaction):
        await interaction.response.send_message(
            "이 명령어는 서버 관리 권한이 있는 사람만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    if interaction.guild_id is None:
        await interaction.response.send_message(
            "서버에서만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    target_channel: Optional[discord.TextChannel] = channel

    if target_channel is None:
        if isinstance(interaction.channel, discord.TextChannel):
            target_channel = interaction.channel
        else:
            await interaction.response.send_message(
                "현재 채널을 텍스트 채널로 확인할 수 없어요. 채널을 직접 선택해 주세요.",
                ephemeral=True,
            )
            return

    set_configured_channel_id(interaction.guild_id, target_channel.id)

    await interaction.response.send_message(
        f"이 서버의 일정 채널을 {target_channel.mention} 으로 설정했어요.\n"
        f"이제 `/일정`, `/전체일정`은 해당 채널에서만 사용할 수 있어요.",
        ephemeral=True,
    )


@bot.tree.command(name="채널확인", description="현재 이 서버에 지정된 일정 채널을 확인합니다.")
@app_commands.guild_only()
async def check_channel_command(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "서버에서만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    channel_id = get_configured_channel_id(interaction.guild_id)

    if channel_id is None:
        await interaction.response.send_message(
            "아직 지정된 일정 채널이 없어요.\n지금은 아무 채널에서나 `/일정`, `/전체일정`을 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"현재 일정 채널은 <#{channel_id}> 이에요.",
        ephemeral=True,
    )


@bot.tree.command(name="채널해제", description="이 서버의 일정 채널 제한을 해제합니다.")
@app_commands.guild_only()
async def clear_channel_command(interaction: discord.Interaction) -> None:
    if not is_guild_manager(interaction):
        await interaction.response.send_message(
            "이 명령어는 서버 관리 권한이 있는 사람만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    if interaction.guild_id is None:
        await interaction.response.send_message(
            "서버에서만 사용할 수 있어요.",
            ephemeral=True,
        )
        return

    clear_configured_channel_id(interaction.guild_id)

    await interaction.response.send_message(
        "일정 채널 제한을 해제했어요.\n이제 아무 채널에서나 `/일정`, `/전체일정`을 사용할 수 있어요.",
        ephemeral=True,
    )


@bot.tree.command(name="핑", description="봇이 살아있는지 확인합니다.")
async def ping_command(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("퐁!", ephemeral=True)


def main() -> None:
    validate_env()
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
