import io
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import discord
import gspread
import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

matplotlib.use("Agg")

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


def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id      TEXT PRIMARY KEY,
            sheet_id      TEXT,
            channel_id    TEXT,
            message_ids   TEXT,
            ping_role_id  TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_guild_setting(
    guild_id: str,
    sheet_id: str = None,
    channel_id: str = None,
    message_ids: list = None,
    ping_role_id: str = None,
):
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute("""
        INSERT OR IGNORE INTO settings (guild_id, sheet_id, channel_id, message_ids, ping_role_id)
        VALUES (?, NULL, NULL, NULL, NULL)
    """, (guild_id,))
    if sheet_id is not None:
        conn.execute("UPDATE settings SET sheet_id = ? WHERE guild_id = ?", (sheet_id, guild_id))
    if channel_id is not None:
        conn.execute(
            "UPDATE settings SET channel_id = ?, message_ids = NULL WHERE guild_id = ?",
            (channel_id, guild_id),
        )
    if message_ids is not None:
        conn.execute(
            "UPDATE settings SET message_ids = ? WHERE guild_id = ?",
            (json.dumps(message_ids), guild_id),
        )
    if ping_role_id is not None:
        conn.execute(
            "UPDATE settings SET ping_role_id = ? WHERE guild_id = ?",
            (ping_role_id, guild_id),
        )
    conn.commit()
    conn.close()


def get_guild_setting(guild_id: str) -> Optional[dict]:
    conn = sqlite3.connect(DATABASE_FILE)
    row = conn.execute(
        "SELECT sheet_id, channel_id, message_ids, ping_role_id FROM settings WHERE guild_id = ?",
        (guild_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "sheet_id": row[0],
        "channel_id": row[1],
        "message_ids": json.loads(row[2]) if row[2] else [],
        "ping_role_id": row[3],
    }


_gspread_client: Optional[gspread.Client] = None


def get_gspread_client() -> gspread.Client:
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
    global _gspread_client
    try:
        client = get_gspread_client()
        return client.open_by_key(sheet_id).worksheet(worksheet_name)
    except Exception:
        _gspread_client = None
        client = get_gspread_client()
        return client.open_by_key(sheet_id).worksheet(worksheet_name)


def extract_sheet_id(url: str) -> Optional[str]:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None


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
            continue
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


def parse_all_schedule_rows(sheet_id: str) -> List[dict]:
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
            continue
        if row_date >= today:
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
            "row_date": row_date,
            "participants": participants,
            "non_participants": non_participants,
        })

    return schedules


def period_to_start_date(period: str):
    today = datetime.today().date()
    mapping = {
        "지난 1주일": timedelta(days=7),
        "지난 1개월": timedelta(days=30),
        "지난 3개월": timedelta(days=90),
        "지난 6개월": timedelta(days=180),
        "지난 1년":   timedelta(days=365),
    }
    delta = mapping.get(period)
    return today - delta if delta else None


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


def get_job_emoji(bot: commands.Bot, job_name: str) -> str:
    code = JOB_NAMES.get(job_name)
    if not code:
        return "❔"
    emoji = discord.utils.get(bot.emojis, name=code)
    return str(emoji) if emoji else "❔"


def build_member_text(bot: commands.Bot, members: List[dict]) -> str:
    if not members:
        return "없음"
    formatted = [f"{get_job_emoji(bot, m['job'])}\u00A0{m['nickname']}" for m in members]
    n = len(formatted)
    if n <= 4:
        return "  ".join(formatted)
    split = n // 2
    top = "  ".join(formatted[:split])
    bottom = "  ".join(formatted[split:])
    return f"{top}\n{bottom}"


def build_memo_text(bot: commands.Bot, memos: List[dict], members: List[dict]) -> str:
    if not memos:
        return "특이사항 없음"
    job_map = {m["nickname"]: m["job"] for m in members}
    lines = [
        f"{get_job_emoji(bot, job_map.get(d['nickname'], ''))}\u00A0{d['nickname']}: {d['memo']}"
        for d in memos
    ]
    return "\n".join(lines)


def build_schedule_embeds(
    bot: commands.Bot,
    schedules: List[dict],
    memo_map: Dict[str, List[dict]],
) -> List[discord.Embed]:
    MAX_DESC = 3800
    SEPARATOR = "\n\n━━━━━━━━━━━━━━\n\n"

    blocks = []
    for s in schedules:
        all_members = s["participants"] + s["non_participants"]
        p_count = len(s["participants"])
        np_count = len(s["non_participants"])
        participant_text = build_member_text(bot, s["participants"])
        non_participant_text = build_member_text(bot, s["non_participants"])
        memo_text = build_memo_text(bot, memo_map.get(s["date"], []), all_members)

        block = (
            f"## {s['date']} ({s['weekday']}) {s['time']}\n"
            f"**✅ 참여 {p_count}명**\n{participant_text}\n\n"
            f"**❌ 미참여 {np_count}명**\n{non_participant_text}\n\n"
            f"**📝 특이사항**\n{memo_text}"
        )
        blocks.append(block)

    embeds: List[discord.Embed] = []
    current_blocks: List[str] = []
    current_len = 0

    for block in blocks:
        addition = (SEPARATOR if current_blocks else "") + block
        if current_blocks and current_len + len(addition) > MAX_DESC:
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
        color=0x5865F2,
    )
    embed.set_footer(text="FF14 Schedule Bot")
    return embed


def build_attendance_image(schedules: List[dict], period: str) -> discord.File:
    fonts = [f.name for f in fm.fontManager.ttflist]
    if "NanumGothic" in fonts:
        plt.rcParams["font.family"] = "NanumGothic"
    else:
        plt.rcParams["font.family"] = "DejaVu Sans"

    member_set: dict = {}
    dates = []
    for s in schedules:
        dates.append(s["date"])
        for m in s["participants"] + s["non_participants"]:
            if m["nickname"] not in member_set:
                member_set[m["nickname"]] = m["job"]

    members = list(member_set.keys())
    n_members = len(members)
    n_dates = len(dates)

    matrix = []
    for nickname in members:
        row = []
        for s in schedules:
            participated = any(p["nickname"] == nickname for p in s["participants"])
            in_roster = any(
                p["nickname"] == nickname
                for p in s["participants"] + s["non_participants"]
            )
            row.append(1 if participated else (0 if in_roster else -1))
        matrix.append(row)

    rates = []
    for row in matrix:
        valid = [v for v in row if v != -1]
        rates.append(round(len([v for v in valid if v == 1]) / len(valid) * 100) if valid else 0)

    fig_h = max(4, n_members * 0.55 + 2.5)
    fig_w = max(8, n_dates * 0.7 + 3)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor("#1e1f22")
    ax.set_facecolor("#1e1f22")

    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            color = "#57f287" if val == 1 else ("#ed4245" if val == 0 else "#3a3b3e")
            ax.add_patch(plt.Rectangle((c, r), 0.9, 0.9, color=color, linewidth=0))

    for r, rate in enumerate(rates):
        color = "#57f287" if rate >= 75 else ("#fee75c" if rate >= 50 else "#ed4245")
        ax.text(n_dates + 0.1, r + 0.45, f"{rate}%", va="center", ha="left",
                fontsize=9, color=color, fontweight="bold")

    ax.set_xlim(0, n_dates + 1.2)
    ax.set_ylim(0, n_members)
    ax.set_yticks([i + 0.45 for i in range(n_members)])
    ax.set_yticklabels(members, color="#dcddde", fontsize=10)
    ax.set_xticks([i + 0.45 for i in range(n_dates)])
    short_dates = [d[5:] for d in dates]
    ax.set_xticklabels(short_dates, color="#b5bac1", fontsize=8, rotation=45, ha="right")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title(f"출석 통계 ({period})", color="#fff", fontsize=13, pad=12)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return discord.File(buf, filename="attendance.png")


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
    ping_status = f"<@&{setting['ping_role_id']}>" if setting["ping_role_id"] else "❌ 없음"

    await interaction.followup.send(
        f"**시트 연동:** {sheet_status}\n**출력 채널:** {channel_status}\n**핑 역할:** {ping_status}",
        ephemeral=True,
    )


@bot.tree.command(name="핑설정", description="일정 출력 시 멘션할 역할을 설정합니다.")
@app_commands.default_permissions(administrator=True)
async def set_ping_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    save_guild_setting(guild_id=str(interaction.guild_id), ping_role_id=str(role.id))
    await interaction.followup.send(f"✅ {role.mention} 역할로 핑 설정 완료", ephemeral=True)


@bot.tree.command(name="일정출력", description="이번 주 일정을 출력합니다.")
@app_commands.default_permissions(administrator=True)
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
        try:
            channel = await bot.fetch_channel(int(setting["channel_id"]))
        except discord.NotFound:
            await interaction.followup.send("채널을 찾을 수 없습니다.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send("채널에 접근할 권한이 없습니다.", ephemeral=True)
            return

    for mid in setting.get("message_ids", []):
        try:
            old_msg = await channel.fetch_message(int(mid))
            await old_msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    embeds = build_schedule_embeds(bot, schedules, memo_map)

    ping_content = None
    if setting.get("ping_role_id"):
        ping_content = f"<@&{setting['ping_role_id']}>"

    try:
        new_ids = []
        for i, embed in enumerate(embeds):
            content = ping_content if i == 0 else None
            msg = await channel.send(content=content, embed=embed)
            new_ids.append(str(msg.id))
        save_guild_setting(guild_id=str(interaction.guild_id), message_ids=new_ids)
        await interaction.followup.send(f"✅ 일정 출력 완료 ({len(embeds)}개 메시지)", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("채널에 메시지를 보낼 권한이 없습니다.", ephemeral=True)


@bot.tree.command(name="일정통계", description="멤버별 출석 통계를 DM으로 전송합니다.")
@app_commands.default_permissions(administrator=True)
@app_commands.choices(기간=[
    app_commands.Choice(name="지난 1주일", value="지난 1주일"),
    app_commands.Choice(name="지난 1개월", value="지난 1개월"),
    app_commands.Choice(name="지난 3개월", value="지난 3개월"),
    app_commands.Choice(name="지난 6개월", value="지난 6개월"),
    app_commands.Choice(name="지난 1년",   value="지난 1년"),
])
async def send_statistics(interaction: discord.Interaction, 기간: str):
    await interaction.response.defer(ephemeral=True)

    setting = get_guild_setting(str(interaction.guild_id))
    if not setting or not setting["sheet_id"]:
        await interaction.followup.send("시트가 연동되지 않았습니다.", ephemeral=True)
        return

    try:
        all_schedules = parse_all_schedule_rows(setting["sheet_id"])
    except Exception as e:
        await interaction.followup.send(f"시트 읽기 오류: {e}", ephemeral=True)
        return

    start_date = period_to_start_date(기간)
    filtered = [s for s in all_schedules if s["row_date"] >= start_date] if start_date else all_schedules

    if not filtered:
        await interaction.followup.send("해당 기간에 데이터가 없습니다.", ephemeral=True)
        return

    try:
        file = build_attendance_image(filtered, 기간)
    except Exception as e:
        await interaction.followup.send(f"이미지 생성 오류: {e}", ephemeral=True)
        return

    try:
        await interaction.user.send(file=file)
        await interaction.followup.send("✅ DM으로 통계를 전송했습니다.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("DM을 보낼 수 없습니다. DM 설정을 확인해주세요.", ephemeral=True)


bot.run(DISCORD_BOT_TOKEN)
