import json
import os
from pathlib import Path
from typing import List, Dict, Any

import discord
import gspread
from google.oauth2.service_account import Credentials


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "참여인원저장").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

STATE_FILE = Path("sent_records.json")


def load_sent_records() -> List[str]:
    if not STATE_FILE.exists():
        return []

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return [str(x) for x in data]

        return []
    except Exception:
        return []


def save_sent_records(records: List[str]) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def validate_env() -> None:
    missing = []

    if not DISCORD_BOT_TOKEN:
        missing.append("DISCORD_BOT_TOKEN")
    if not DISCORD_CHANNEL_ID:
        missing.append("DISCORD_CHANNEL_ID")
    if not GOOGLE_SHEET_ID:
        missing.append("GOOGLE_SHEET_ID")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")

    if missing:
        raise RuntimeError(f"필수 환경변수가 비어 있음: {', '.join(missing)}")


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

        participants = []
        participant_codes = []

        for idx, mark in enumerate(marks):
            if mark.strip().upper() == "O":
                nickname = nicknames[idx].strip() if idx < len(nicknames) else ""
                code = codes[idx].strip() if idx < len(codes) else ""

                participants.append(nickname or code or f"참여자{idx + 1}")
                participant_codes.append(code or f"P{idx + 1}")

        record_key = make_record_key(
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
                "record_key": record_key,
            }
        )

    return rows


def make_record_key(
    date_value: str,
    weekday: str,
    time_value: str,
    participant_codes: List[str],
) -> str:
    codes = ",".join(participant_codes)
    return f"{date_value}|{weekday}|{time_value}|{codes}"


def build_embed(new_rows: List[Dict[str, Any]]) -> discord.Embed:
    lines = []

    for row in new_rows:
        date_text = row["date"]
        weekday = row["weekday"]
        time_value = row["time"]
        participants = row["participants"]

        header = date_text
        if weekday:
            header += f" ({weekday})"
        if time_value:
            header += f" {time_value}"

        participant_text = ", ".join(participants) if participants else "없음"

        lines.append(f"**• {header}**")
        lines.append(participant_text)
        lines.append("")

    description = "\n".join(lines).strip()

    return discord.Embed(
        title="🔔 이번 주 공대 일정",
        description=description,
    )


intents = discord.Intents.default()
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    try:
        print(f"로그인 완료: {client.user}")

        rows = read_participation_rows()
        sent_records = set(load_sent_records())

        new_rows = [row for row in rows if row["record_key"] not in sent_records]

        if not new_rows:
            print("새로 보낼 일정 없음")
            await client.close()
            return

        new_rows.sort(key=lambda x: (x["date"], x["time"]))

        channel = client.get_channel(int(DISCORD_CHANNEL_ID))
        if channel is None:
            channel = await client.fetch_channel(int(DISCORD_CHANNEL_ID))

        embed = build_embed(new_rows)
        await channel.send(embed=embed)

        for row in new_rows:
            sent_records.add(row["record_key"])

        save_sent_records(sorted(sent_records))
        print(f"{len(new_rows)}개의 새 일정 전송 완료")

    except Exception as e:
        print(f"오류 발생: {e}")
        raise
    finally:
        await client.close()


def main() -> None:
    validate_env()
    client.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
