import os
import re
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import List
import urllib.parse

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

# Bot token (set in environment)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Workout type mappings
WORKOUT_TYPES = {
    "бег":      {"emoji": "🏃", "name": "Running",  "name_ru": "Бег"},
    "плавание": {"emoji": "🏊", "name": "Swimming", "name_ru": "Плавание"},
    "вело":     {"emoji": "🚴", "name": "Cycling",  "name_ru": "Велосипед"},
}

# Day mappings
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
    def __init__(self,
                 day_name: str,
                 time: str,
                 workout_type: dict,
                 description: str,
                 location: str,
                 waze_link: str = ""):
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
        wd = today.weekday()  # Monday=0 ... Sunday=6
        info = DAY_MAPPING[self.day_name]
        # Convert Telegram Sunday=0 to Python Sunday=6
        target = 6 if info["num"] == 0 else info["num"] - 1
        days_ahead = (target - wd) % 7 or 7
        return today + timedelta(days=days_ahead)

    def to_ics(self) -> str:
        start_dt = self.date.replace(
            hour=int(self.time.split(":")[0]),
            minute=int(self.time.split(":")[1]),
            second=0
        )
        end_dt = start_dt + timedelta(hours=1, minutes=30)
        start_str = start_dt.strftime("%Y%m%dT%H%M%S")
        end_str = end_dt.strftime("%Y%m%dT%H%M%S")
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        uid = f"training-{start_str}-{self.workout_type['name']}@bot"
        desc = f"Waze: {self.waze_link}" if self.waze_link else ""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Training Calendar Bot//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{timestamp}",
            f"DTSTART:{start_str}",
            f"DTEND:{end_str}",
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
        day = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day:
            continue
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm = re.search(r"(\d{1,2}:\d{2})", lines[i+1])
            if tm:
                line = f"{line} {lines[i+1].strip()}"
        if not tm:
            continue
        time = tm.group(1)
        low = line.lower()
        if (("плаван" in low or "море" in low) and "бег" in low) or ("🏃" in line and "🏊" in line):
            workout = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in low or "🏊" in line:
            workout = WORKOUT_TYPES["плавание"]
        elif "вело" in low or "🚴" in line:
            workout = WORKOUT_TYPES["вело"]
        else:
            workout = WORKOUT_TYPES["бег"]
        after = line[line.find(time)+len(time):]
        loc_part = after.split(".",1)[0]
        m_loc = re.search(r",\s*(.+)$", loc_part)
        location = m_loc.group(1).strip() if m_loc else "Training location"
        before = line[:line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout["name_ru"]
        waze = ""
        if i + 1 < len(lines):
            m_w = re.search(r"https?://waze\.com/[^\s]+", lines[i+1])
            if m_w:
                waze = m_w.group(0)
        trainings.append(Training(day, time, workout, description, location, waze))
    return trainings


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Чтобы начать, скопируйте расписание из WhatsApp и отправьте его в сообщении.\n"
        "Я сам разберу дни, время и локации и предложу скачать .ics файл для вашего календаря.\n\n"
        "Для примера формата отправьте /example."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def example_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        return await start_cmd(update, context)
    trainings = parse_training_message(text)
    if not trainings:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок. Попробуйте /example."
        )
    # далее логика выбора и скачивания


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # тут handle toggle, select_all, download
    # ...


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("example", example_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
