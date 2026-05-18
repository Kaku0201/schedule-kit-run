import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

import discord
import gspread

from discord import app_commands
from discord.ext import commands
from google.oauth2.service_account import Credentials


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

PARTICIPATION_SHEET = "참여인원저장"
MEMO_SHEET = "날짜메모"
DATABASE_FILE = "database.sqlite"

JOB_NAMES = {
    "나이트": "PLD", "전사": "WAR", "암흑기사": "DRK", "건브레이커": "GNB",
    "백마도사": "WHM", "학자": "SCH", "점성술사": "AST", "현자": "SGE",
    "몽크": "MNK", "용기사": "DRG", "닌자": "NIN", "사무라이": "SAM",
    "리퍼": "RPR", "바이퍼": "VPR", "음유시인": "BRD", "기공사": "MCH",
    "무도가": "DNC", "흑마도사": "BLM", "소환사": "SMN", "적마도사": "RDM",
    "청마도사": "BLU", "픽토맨서": "PCT",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id   TEXT PRIMARY KEY,
            sheet_id   TEXT,
            channel_id TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_guild_setting(guild_id: str, sheet_id: str = None, channel_id: str = None):
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        INSERT OR IGNORE INTO settings (guild_id, sheet_id, channel_id)
        VALUES (?, NULL, NULL)
    """, (guild_id,))

    if sheet_id is not None:
        conn.execute("UPDATE settings SET sheet_id = ? WHERE guild_id = ?", (sheet_id, guild_id))
    if channel_id is not None:
        conn.execute("UPDATE settings SET channel_id = ? WHERE guild_id = ?", (channel_id, guild_id))

    conn.commit()
    conn.close()


def get_guild_setting(guild_id: str) -> Optional[dict]:
    conn = sqlite3.connect(DATABASE_FILE)
    row = conn.execute(
        "SELECT sheet_id, channel_id FROM settings WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"sheet_id": row[0], "channel_id": row[1]}


# ── Google Sheets ──────────────────────────────────────────────────────────────

_gspread_client: Optional[gspread.Client] = None


def get_gspread_client() -> gspread.Client:
    """클라이언트를 캐싱해서 재사용합니다."""
    global _gspread_client
    if _gspread_client is None:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(info, scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ])
        _gspread_client = gspread.authorize(creds)
    return _gspread_client


def get_worksheet(sheet_id: str, worksheet_name: str):
    client = get_gspread_client()
    return client.open_by_key(sheet_id).worksheet(worksheet_name)


def extract_sheet_id(url: str) -> Optional[str]:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None


# ── 파싱 ──────────────────────────────────────────────────────────────────────

def parse_schedule_rows(sheet_id: str) -> List[dict]:
    ws = get_worksheet(sheet_id, PARTICIPATION_SHEET)
    rows = ws.get_all_values()

    if len(rows) < 3:
        return []

    job_row, nickname_row, *data_rows = rows
    today = datetime.today().date()
    schedules = []

    for row in data_rows:
        padded = row + [""] * max(0, len(job_row) - len(row))
        date_str = padded[0].strip()

        if not date_str:
            continue

        try:
            row_date = datetime.strptime(date_str, "%Y.%m.%d").date()
        except ValueError:
            continue  # ← 버그 수정: try 블록 안으로 이동

        if row_date < today:
            continue

        participants, non_participants = [], []

        for idx in range(3, len(padded)):
            nickname = nickname_row[idx].strip() if idx < len(nickname_row) else ""
            job = job_row[idx].strip() if idx < len(job_row) else ""
            mark = padded[idx].strip().upper()

            if not nickname:
                continue

            member = {"nickname": nickname, "job": job}
            (participants if mark == "O" else non_participants).append(member)

        schedules.append({
            "date": date_str,
            "weekday": padded[1].strip(),
            "time": padded[2].strip(),
            "participants": participants,
            "non_participants": non_participants,
        })

    return schedules


def parse_memo_map(sheet_id: str) -> Dict[str, List[dict]]:
    ws = get_worksheet(sheet_id, MEMO_SHEET)
    rows = ws.get_all_values()

    if len(rows) < 3:
        return {}

    nickname_row = rows[1]
    memo_map: Dict[str, List[dict]] = {}

    for row in rows[2:]:
        padded = row + [""] * max(0, len(nickname_row) - len(row))
        date_str = padded[0].strip()

        if not date_str:
            continue

        # 날짜 형식 검증 추가
        try:
            datetime.strptime(date_str, "%Y.%m.%d")
        except ValueError:
            continue

        memos = [
            {"nickname": nickname_row[i].strip(), "memo": padded[i].strip()}
            for i in range(3, len(padded))
            if i < len(nickname_row) and padded[i].strip() and nickname_row[i].strip()
        ]
        memo_map[date_str] = memos

    return memo_map


# ── 임베드 빌드 ───────────────────────────────────────────────────────────────

def get_job_emoji(bot: commands.Bot, job_name: str) -> str:
    code = JOB_NAMES.get(job_name)
    if not code:
        return "❔"
    emoji = discord.utils.get(bot.emojis, name=code)
    return str(emoji) if emoji else "❔"


def build_member_text(bot: commands.Bot, members: List[dict]) -> str:
    return " ".join(
        f"{get_job_emoji(bot, m['job'])} {m['nickname']}" for m in members
    ) or "없음"


def build_memo_text(bot: commands.Bot, memos: List[dict], members: List[dict]) -> str:
    if not memos:
        return "특이사항 없음"

    job_map = {m["nickname"]: m["job"] for m in members}
    lines = [
        f"{get_job_emoji(bot, job_map.get(d['nickname'], ''))} {d['nickname']}: {d['memo']}"
        for d in memos
    ]
    return "\n".join(lines)


def build_schedule_embeds(
    bot: commands.Bot,
    schedules: List[dict],
    memo_map: Dict[str, List[dict]],
) -> List[discord.Embed]:
    """
    Discord embed description 4096자 제한 대응:
    일정이 많으면 embed를 여러 개로 분할합니다.
    """
    SEPARATOR = "\n\n━━━━━━━━━━━━━━\n\n"
    MAX_DESC = 3800  # 여유 있게 제한

    blocks = []
    for s in schedules:
        all_members = s["participants"] + s["non_participants"]
        block = (
            f"## {s['date']} ({s['weekday']}) {s['time']}\n\n"
            f"### ✅ 참여자\n{build_member_text(bot, s['participants'])}\n\n"
            f"### 📝 특이사항\n"
            f"{build_memo_text(bot, memo_map.get(s['date'], []), all_members)}\n\n"
            f"### ❌ 미참여자\n{build_member_text(bot, s['non_participants'])}"
        )
        blocks.append(block)

    embeds: List[discord.Embed] = []
    current_blocks: List[str] = []
    current_len = 0

    for block in blocks:
        addition = (SEPARATOR if current_blocks else "") + block
        if current_blocks and current_len + len(addition) > MAX_DESC:
            # 현재까지 모아둔 걸로 embed 생성
            embeds.append(_make_embed(current_blocks, SEPARATOR, is_first=len(embeds) == 0))
            current_blocks = [block]
            current_len = len(block)
        else:
            current_blocks.append(block)
            current_len += len(addition)

    if current_blocks:
        embeds.append(_make_embed(current_blocks, SEPARATOR, is_first=len(embeds) == 0))

    return embeds


def _make_embed(blocks: List[str], sep: str, is_first: bool) -> discord.Embed:
    embed = discord.Embed(
        title="📅 이번 주 일정" if is_first else None,
        description=sep.join(blocks),
        color=0x7289DA,
    )
    embed.set_footer(text="FF14 Schedule Bot")
    return embed


# ── Bot ───────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user}")
    init_database()
    try:
        synced = await bot.tree.sync()
        print(f"슬래시 명령어 동기화 완료: {len(synced)}개")
    except Exception as e:
        print(f"명령어 동기화 실패: {e}")


@bot.tree.command(name="시트연동", description="구글 시트를 연동합니다.")
@app_commands.default_permissions(administrator=True)
async def connect_sheet(interaction: discord.Interaction, sheet_url: str):
    await interaction.response.defer(ephemeral=True)
    sheet_id = extract_sheet_id(sheet_url)
    if not sheet_id:
        await interaction.followup.send("올바른 구글 시트 링크가 아닙니다.", ephemeral=True)
        return

    # 실제 접근 가능한지 미리 확인
    try:
        get_worksheet(sheet_id, PARTICIPATION_SHEET)
    except Exception:
        await interaction.followup.send(
            "시트에 접근할 수 없습니다. 서비스 계정에 공유 권한이 있는지 확인해주세요.",
            ephemeral=True,
        )
        return

    save_guild_setting(guild_id=str(interaction.guild_id), sheet_id=sheet_id)
    await interaction.followup.send("✅ 시트 연동 완료", ephemeral=True)


@bot.tree.command(name="출력채널설정", description="현재 채널을 일정 출력 채널로 설정합니다.")
@app_commands.default_permissions(administrator=True)
async def connect_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    save_guild_setting(
        guild_id=str(interaction.guild_id),
        channel_id=str(interaction.channel_id),
    )
    await interaction.followup.send(f"✅ <#{interaction.channel_id}> 채널 연동 완료", ephemeral=True)


@bot.tree.command(name="설정확인", description="현재 서버 설정을 확인합니다.")
@app_commands.default_permissions(administrator=True)
async def check_settings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    setting = get_guild_setting(str(interaction.guild_id))

    if not setting:
        await interaction.followup.send("설정 없음", ephemeral=True)
        return

    sheet_status = "✅ 설정됨" if setting["sheet_id"] else "❌ 없음"
    channel_status = f"<#{setting['channel_id']}>" if setting["channel_id"] else "❌ 없음"

    await interaction.followup.send(
        f"**시트 연동:** {sheet_status}\n**출력 채널:** {channel_status}",
        ephemeral=True,
    )


@bot.tree.command(name="일정출력", description="이번 주 일정을 출력합니다.")
async def send_schedule(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    setting = get_guild_setting(str(interaction.guild_id))
    if not setting or not setting["sheet_id"]:
        await interaction.followup.send("시트가 연동되지 않았습니다. `/시트연동` 을 먼저 실행해주세요.", ephemeral=True)
        return
    if not setting["channel_id"]:
        await interaction.followup.send("출력 채널이 설정되지 않았습니다. `/출력채널설정` 을 먼저 실행해주세요.", ephemeral=True)
        return

    try:
        schedules = parse_schedule_rows(setting["sheet_id"])
        memo_map = parse_memo_map(setting["sheet_id"])
    except Exception as e:
        await interaction.followup.send(f"시트 읽기 오류: {e}", ephemeral=True)
        return

    if not schedules:
        await interaction.followup.send("출력할 일정이 없습니다.", ephemeral=True)
        return

    channel = bot.get_channel(int(setting["channel_id"]))
    if not channel:
        await interaction.followup.send("채널을 찾을 수 없습니다.", ephemeral=True)
        return

    embeds = build_schedule_embeds(bot, schedules, memo_map)

    try:
        for embed in embeds:
            await channel.send(embed=embed)
        await interaction.followup.send(f"✅ 일정 출력 완료 ({len(embeds)}개 메시지)", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("채널에 메시지를 보낼 권한이 없습니다.", ephemeral=True)


bot.run(DISCORD_BOT_TOKEN)
