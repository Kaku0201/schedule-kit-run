import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Any

import discord
import gspread

from discord import app_commands
from discord.ext import commands
from google.oauth2.service_account import Credentials


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    ""
).strip()

PARTICIPATION_SHEET = "참여인원저장"
MEMO_SHEET = "날짜메모"

DATABASE_FILE = "database.sqlite"


JOB_NAMES = {
    "나이트": "PLD",
    "전사": "WAR",
    "암흑기사": "DRK",
    "건브레이커": "GNB",

    "백마도사": "WHM",
    "학자": "SCH",
    "점성술사": "AST",
    "현자": "SGE",

    "몽크": "MNK",
    "용기사": "DRG",
    "닌자": "NIN",
    "사무라이": "SAM",
    "리퍼": "RPR",
    "바이퍼": "VPR",

    "음유시인": "BRD",
    "기공사": "MCH",
    "무도가": "DNC",

    "흑마도사": "BLM",
    "소환사": "SMN",
    "적마도사": "RDM",
    "청마도사": "BLU",
    "픽토맨서": "PCT",
}


def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id TEXT PRIMARY KEY,
            sheet_id TEXT,
            channel_id TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_guild_setting(
    guild_id: str,
    sheet_id: str = None,
    channel_id: str = None
):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO settings (
            guild_id,
            sheet_id,
            channel_id
        )
        VALUES (?, ?, ?)
    """, (
        guild_id,
        None,
        None
    ))

    if sheet_id is not None:
        cursor.execute("""
            UPDATE settings
            SET sheet_id = ?
            WHERE guild_id = ?
        """, (
            sheet_id,
            guild_id
        ))

    if channel_id is not None:
        cursor.execute("""
            UPDATE settings
            SET channel_id = ?
            WHERE guild_id = ?
        """, (
            channel_id,
            guild_id
        ))

    conn.commit()
    conn.close()


def get_guild_setting(
    guild_id: str
):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sheet_id, channel_id
        FROM settings
        WHERE guild_id = ?
    """, (guild_id,))

    result = cursor.fetchone()

    conn.close()

    if not result:
        return None

    return {
        "sheet_id": result[0],
        "channel_id": result[1]
    }


def extract_sheet_id(
    url: str
):
    match = re.search(
        r"/spreadsheets/d/([a-zA-Z0-9-_]+)",
        url
    )

    if not match:
        return None

    return match.group(1)


def get_gspread_client():
    service_account_info = json.loads(
        GOOGLE_SERVICE_ACCOUNT_JSON
    )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes,
    )

    return gspread.authorize(credentials)


def get_sheet(
    sheet_id: str,
    worksheet_name: str
):
    client = get_gspread_client()

    spreadsheet = client.open_by_key(
        sheet_id
    )

    return spreadsheet.worksheet(
        worksheet_name
    )


def get_job_emoji(
    bot,
    job_name: str
):
    emoji_name = JOB_NAMES.get(
        job_name
    )

    if not emoji_name:
        return "❔"

    emoji = discord.utils.get(
        bot.emojis,
        name=emoji_name
    )

    if emoji:
        return str(emoji)

    return "❔"


def parse_schedule_rows(
    sheet_id: str
):
    worksheet = get_sheet(
        sheet_id,
        PARTICIPATION_SHEET
    )

    all_values = worksheet.get_all_values()

    if len(all_values) < 3:
        return []

    job_row = all_values[0]
    nickname_row = all_values[1]
    data_rows = all_values[2:]

    schedules = []

    for row in data_rows:
        padded = row + [""] * (
            len(job_row) - len(row)
        )

        date_value = padded[0].strip()

        if not date_value:
            continue

        try:
            row_date = datetime.strptime(
                date_value,
                "%Y.%m.%d"
            ).date()

        except ValueError:
        continue

        today = datetime.today().date()

        if row_date < today:
            continue

        weekday = padded[1].strip()
        time_value = padded[2].strip()

        participants = []
        non_participants = []

        for idx in range(3, len(padded)):
            mark = padded[idx].strip().upper()

            nickname = nickname_row[idx].strip()
            job = job_row[idx].strip()

            if not nickname:
                continue

            member = {
                "nickname": nickname,
                "job": job,
            }

            if mark == "O":
                participants.append(member)
            else:
                non_participants.append(member)

        schedules.append({
            "date": date_value,
            "weekday": weekday,
            "time": time_value,
            "participants": participants,
            "non_participants": non_participants,
        })

    return schedules


def parse_memo_map(
    sheet_id: str
):
    worksheet = get_sheet(
        sheet_id,
        MEMO_SHEET
    )

    all_values = worksheet.get_all_values()

    if len(all_values) < 3:
        return {}

    nickname_row = all_values[1]
    data_rows = all_values[2:]

    memo_map = {}

    for row in data_rows:
        padded = row + [""] * (
            len(nickname_row) - len(row)
        )

        date_value = padded[0].strip()

        if not date_value:
            continue

        memos = []

        for idx in range(3, len(padded)):
            memo = padded[idx].strip()

            if not memo:
                continue

            nickname = nickname_row[idx].strip()

            memos.append({
                "nickname": nickname,
                "memo": memo,
            })

        memo_map[date_value] = memos

    return memo_map


def build_member_text(
    bot,
    members
):
    result = []

    for member in members:
        emoji = get_job_emoji(
            bot,
            member["job"]
        )

        result.append(
            f"{emoji} {member['nickname']}"
        )

    return " ".join(result)


def build_memo_text(
    bot,
    memos,
    members
):
    if not memos:
        return "특이사항 없음"

    member_job_map = {}

    for member in members:
        member_job_map[
            member["nickname"]
        ] = member["job"]

    lines = []

    for memo_data in memos:
        nickname = memo_data["nickname"]
        memo = memo_data["memo"]

        job = member_job_map.get(
            nickname,
            ""
        )

        emoji = get_job_emoji(
            bot,
            job
        )

        lines.append(
            f"{emoji} {nickname}: {memo}"
        )

    return "\n".join(lines)


def build_schedule_embed(
    bot,
    schedules,
    memo_map
):
    embed = discord.Embed(
        title="📅 이번 주 일정",
        color=0x7289DA,
    )

    sections = []

    for schedule in schedules:
        date_text = schedule["date"]
        weekday = schedule["weekday"]
        time_value = schedule["time"]

        participants = build_member_text(
            bot,
            schedule["participants"]
        )

        non_participants = build_member_text(
            bot,
            schedule["non_participants"]
        )

        memo_text = build_memo_text(
            bot,
            memo_map.get(date_text, []),
            schedule["participants"]
            + schedule["non_participants"]
        )

        block = (
            f"## {date_text} ({weekday}) {time_value}\n\n"
            f"### ✅ 참여자\n"
            f"{participants or '없음'}\n\n"
            f"### 📝 특이사항\n"
            f"{memo_text}\n\n"
            f"### ❌ 미참여자\n"
            f"{non_participants or '없음'}"
        )

        sections.append(block)

    embed.description = (
        "\n\n━━━━━━━━━━━━━━\n\n"
    ).join(sections)

    embed.set_footer(
        text="FF14 Schedule Bot"
    )

    return embed


intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


@bot.event
async def on_ready():
    print(
        f"로그인 완료: {bot.user}"
    )

    init_database()

    try:
        synced = await bot.tree.sync()

        print(
            f"슬래시 명령어 동기화 완료: {len(synced)}개"
        )

    except Exception as e:
        print(
            f"명령어 동기화 실패: {e}"
        )


@bot.tree.command(
    name="시트연동",
    description="구글 시트를 연동합니다."
)
@app_commands.default_permissions(
    administrator=True
)
async def connect_sheet(
    interaction: discord.Interaction,
    sheet_url: str
):
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        sheet_id = extract_sheet_id(
            sheet_url
        )

        if not sheet_id:
            await interaction.followup.send(
                "올바른 구글 시트 링크가 아닙니다.",
                ephemeral=True
            )
            return

        save_guild_setting(
            guild_id=str(
                interaction.guild_id
            ),
            sheet_id=sheet_id
        )

        await interaction.followup.send(
            "시트 연동 완료",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(
            f"오류 발생: {e}",
            ephemeral=True
        )


@bot.tree.command(
    name="채널연동",
    description="현재 채널을 일정 출력 채널로 설정합니다."
)
@app_commands.default_permissions(
    administrator=True
)
async def connect_channel(
    interaction: discord.Interaction
):
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        save_guild_setting(
            guild_id=str(
                interaction.guild_id
            ),
            channel_id=str(
                interaction.channel_id
            )
        )

        await interaction.followup.send(
            "채널 연동 완료",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(
            f"오류 발생: {e}",
            ephemeral=True
        )


@bot.tree.command(
    name="설정확인",
    description="현재 서버 설정을 확인합니다."
)
@app_commands.default_permissions(
    administrator=True
)
async def check_settings(
    interaction: discord.Interaction
):
    await interaction.response.defer(
        ephemeral=True
    )

    setting = get_guild_setting(
        str(interaction.guild_id)
    )

    if not setting:
        await interaction.followup.send(
            "설정 없음",
            ephemeral=True
        )
        return

    sheet_id = setting["sheet_id"]
    channel_id = setting["channel_id"]

    text = (
        f"시트 연동: "
        f"{'설정됨' if sheet_id else '없음'}\n"
        f"채널 연동: "
        f"{f'<#{channel_id}>' if channel_id else '없음'}"
    )

    await interaction.followup.send(
        text,
        ephemeral=True
    )


@bot.tree.command(
    name="일정출력",
    description="이번 주 일정을 출력합니다."
)
async def send_schedule(
    interaction: discord.Interaction
):
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        setting = get_guild_setting(
            str(interaction.guild_id)
        )

        if not setting:
            await interaction.followup.send(
                "시트가 연동되지 않았습니다.",
                ephemeral=True
            )
            return

        sheet_id = setting["sheet_id"]
        channel_id = setting["channel_id"]

        if not sheet_id:
            await interaction.followup.send(
                "시트가 연동되지 않았습니다.",
                ephemeral=True
            )
            return

        if not channel_id:
            await interaction.followup.send(
                "채널이 연동되지 않았습니다.",
                ephemeral=True
            )
            return

        schedules = parse_schedule_rows(
            sheet_id
        )

        memo_map = parse_memo_map(
            sheet_id
        )

        embed = build_schedule_embed(
            bot,
            schedules,
            memo_map
        )

        channel = bot.get_channel(
            int(channel_id)
        )

        if not channel:
            await interaction.followup.send(
                "채널을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        await channel.send(
            embed=embed
        )

        await interaction.followup.send(
            "일정 출력 완료",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(
            f"오류 발생: {e}",
            ephemeral=True
        )


bot.run(DISCORD_BOT_TOKEN)
