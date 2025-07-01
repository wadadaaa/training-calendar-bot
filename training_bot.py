import os
import re
import logging
import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

WORKOUT_TYPES = {
    "бег":      {"emoji": "🏃", "name": "Running",  "name_ru": "Бег"},
    "плавание": {"emoji": "🏊", "name": "Swimming", "name_ru": "Плавание"},
    "вело":     {"emoji": "🚴", "name": "Cycling",  "name_ru": "Велосипед"},
}

DAY_MAPPING = {
    "понедельник": {"num": 1, "name_ru": "Понедельник"},
    "вторник":     {"num": 2, "name_ru": "Вторник"},
    "среда":       {"num": 3, "name_ru": "Среда"},
    "четверг":     {"num": 4, "name_ru": "Четверг"},
    "пятница":     {"num": 5, "name_ru": "Пятница"},
    "суббота":     {"num": 6, "name_ru": "Суббота"},
    "воскресенье": {"num": 0, "name_ru": "Воскресенье"},
}


class Training:
    def __init__(
        self,
        day_name: str,
        time: str,
        workout_type: dict,
        description: str,
        location: str,
        waze_link: str = "",
    ):
        self.day_name = day_name
        self.time = time
        self.workout_type = workout_type
        self.description = description
        self.location = location
        self.waze_link = waze_link
        self.selected = True
        self.date = self._calculate_date()

    def _calculate_date(self) -> datetime:
        today = datetime.now()
        wd = today.weekday()  # 0=Mon ... 6=Sun
        info = DAY_MAPPING[self.day_name]
        # Telegram num=0 for Sunday → Python=6
        target = 6 if info["num"] == 0 else info["num"] - 1
        delta = (target - wd) % 7 or 7
        return today + timedelta(days=delta)

    def to_ics(self) -> str:
        start_dt = self.date.replace(
            hour=int(self.time.split(":")[0]),
            minute=int(self.time.split(":")[1]),
            second=0,
        )
        end_dt = start_dt + timedelta(hours=1, minutes=30)
        fmt = lambda d: d.strftime("%Y%m%dT%H%M%S")
        uid = f"training-{fmt(start_dt)}-{self.workout_type['name']}@bot"
        desc = f"Waze: {self.waze_link}" if self.waze_link else ""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Training Calendar Bot//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{fmt(start_dt)}",
            f"DTEND:{fmt(end_dt)}",
            f"SUMMARY:{self.workout_type['emoji']} {self.description}",
            f"LOCATION:{self.location}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        return "\n".join(lines)


def parse_training_message(text: str) -> List[Training]:
    trainings: List[Training] = []
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        # 1) detect day
        day = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day:
            continue

        # 2) detect time
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm2 = re.search(r"(\d{1,2}:\d{2})", lines[i+1])
            if tm2:
                tm = tm2
                line = f"{line} {lines[i+1].strip()}"
        if not tm:
            continue
        time = tm.group(1)

        # 3) determine workout_type
        low = line.lower()
        if (("плаван" in low or "море" in low) and "бег" in low) or ("🏃" in line and "🏊" in line):
            workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in low or "🏊" in line:
            workout_type = WORKOUT_TYPES["плавание"]
        elif "вело" in low or "🚴" in line:
            workout_type = WORKOUT_TYPES["вело"]
        else:
            workout_type = WORKOUT_TYPES["бег"]

        # 4) extract location
        after = line[line.find(time) + len(time):]
        loc_part = after.split(".", 1)[0]
        m_loc = re.search(r",\s*(.+)$", loc_part)
        location = m_loc.group(1).strip() if m_loc else "Training location"

        # 5) extract description
        before = line[:line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout_type["name_ru"]

        # 6) optional Waze link
        wlink = ""
        if i + 1 < len(lines):
            m_w = re.search(r"https?://waze\.com/[^\s]+", lines[i+1])
            if m_w:
                wlink = m_w.group(0)

        trainings.append(Training(day, time, workout_type, description, location, wlink))
    return trainings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Скопируйте расписание из WhatsApp и отправьте мне, "
        "я его распаршу и верну .ics файлы.\n\n"
        "Пример формата: /example"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def example(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Пример формата:*\n"
        "🏃 Воскресенье, бег: техника, 19:30, Бат-Ям.\n"
        "Точка сбора https://waze.com/ul/...\n"
        "🚴 Суббота, вело, 06:00, Рамла."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if text.strip().lower() in ("start", "старт"):
        return await start(update, context)

    sessions = parse_training_message(text)
    if not sessions:
        return await update.message.reply_text("❌ Не нашёл тренировок. Попробуйте /example.")

    context.user_data["trainings"] = sessions
    # … now build inline keyboard for selection/download …


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    # … handle toggle/select_all/download …


async def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # remove webhook to avoid getUpdates conflicts
    await app.bot.delete_webhook(drop_pending_updates=True)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("example", example))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()


if __name__ == "__main__":
    asyncio.run(main())
