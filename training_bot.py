import os
import re
import logging
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

# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Workout type mappings
WORKOUT_TYPES = {
    "бег":    {"emoji": "🏃",     "name": "Running",     "name_ru": "Бег"},
    "плавание": {"emoji": "🏊",     "name": "Swimming",    "name_ru": "Плавание"},
    "вело":   {"emoji": "🚴",     "name": "Cycling",     "name_ru": "Велосипед"},
}

# Day mappings
DAY_MAPPING = {
    "понедельник":  {"num": 1, "name": "Monday",    "name_ru": "Понедельник"},
    "вторник":      {"num": 2, "name": "Tuesday",   "name_ru": "Вторник"},
    "среда":        {"num": 3, "name": "Wednesday", "name_ru": "Среда"},
    "четверг":      {"num": 4, "name": "Thursday",  "name_ru": "Четверг"},
    "пятница":      {"num": 5, "name": "Friday",    "name_ru": "Пятница"},
    "суббота":      {"num": 6, "name": "Saturday",  "name_ru": "Суббота"},
    "воскресенье":  {"num": 0, "name": "Sunday",    "name_ru": "Воскресенье"},
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
        """Calculate the next occurrence of this training day"""
        today = datetime.now()
        current_weekday = today.weekday()  # Monday is 0, Sunday is 6

        day_info = DAY_MAPPING[self.day_name.lower()]
        target = day_info["num"]
        # Convert Sunday=0 to Python's Sunday=6
        target = 6 if target == 0 else target - 1

        delta = (target - current_weekday) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)

    def to_ics(self) -> str:
        """Convert training to ICS format"""
        start_dt = self.date.replace(
            hour=int(self.time.split(":")[0]),
            minute=int(self.time.split(":")[1]),
            second=0,
        )
        end_dt = start_dt + timedelta(hours=1, minutes=30)

        start_str = start_dt.strftime("%Y%m%dT%H%M%S")
        end_str = end_dt.strftime("%Y%m%dT%H%M%S")
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        uid = f"training-{start_str}-{self.workout_type['name']}@telegram-bot"

        desc = f"Waze: {self.waze_link}" if self.waze_link else ""
        ics = (
            "BEGIN:VCALENDAR\n"
            "VERSION:2.0\n"
            "PRODID:-//Training Calendar Bot//EN\n"
            "BEGIN:VEVENT\n"
            f"UID:{uid}\n"
            f"DTSTAMP:{timestamp}\n"
            f"DTSTART:{start_str}\n"
            f"DTEND:{end_str}\n"
            f"SUMMARY:{self.workout_type['emoji']} {self.workout_type['name']}: {self.description}\n"
            f"LOCATION:{self.location}\n"
            f"DESCRIPTION:{desc}\n"
            "END:VEVENT\n"
            "END:VCALENDAR"
        )
        return ics


def parse_training_message(text: str) -> List[Training]:
    """Parse WhatsApp-style training text into a list of Training objects."""
    trainings: List[Training] = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        # detect day
        day_match = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day_match:
            continue

        # detect time
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm:
            continue
        time = tm.group(1)

        logger.info(f"Found training on {day_match} at {time}")

        # determine workout_type
        lower = line.lower()
        if (("плаван" in lower or "море" in lower) and "бег" in lower) or (
            "🏃" in line and "🏊" in line
        ):
            workout = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in lower or "🏊" in line or "🛟" in line:
            workout = WORKOUT_TYPES["плавание"]
        elif "вело" in lower or "🚴" in line:
            workout = WORKOUT_TYPES["вело"]
        else:
            workout = WORKOUT_TYPES.get("бег")

        # extract location (after time, before any period)
        after = line[line.find(time) + len(time) :]
        loc_part = after.split(".", 1)[0]
        loc_match = re.search(r",\s*(.+)$", loc_part)
        location = loc_match.group(1).strip() if loc_match else "Training location"

        # extract description (before time, minus day and emoji)
        before = line[: line.find(time)]
        desc = re.sub(
            r"|".join(re.escape(e) for e in DAY_MAPPING) + r"|[🏃🏊🚴🛟🏃‍♂️🏊‍♀️]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout["name_ru"]

        # check next line for Waze link
        waze = ""
        if i + 1 < len(lines):
            link = re.search(r"https?://waze\.com/[^\s]+", lines[i + 1])
            if link:
                waze = link.group(0)

        trainings.append(
            Training(
                day_name=day_match,
                time=time,
                workout_type=workout,
                description=description,
                location=location,
                waze_link=waze,
            )
        )

    return trainings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome = """
🏃‍♂️ *Календарь тренировок* 🏊‍♀️

Привет! Я помогу перенести расписание из WhatsApp в твой календарь.

*Команды:*
/start — Это сообщение
/help  — Помощь
/example — Пример
"""
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = """
*Как пользоваться:*
1. Скопируй расписание из WhatsApp
2. Отправь его мне
3. Выбери тренировки
4. Получи .ics файлы и добавь в календарь
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def example_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    example = """
*Пример:*
