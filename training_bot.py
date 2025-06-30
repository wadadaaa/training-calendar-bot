import os
import re
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
    "бег":      {"emoji": "🏃",     "name": "Running",     "name_ru": "Бег"},
    "плавание": {"emoji": "🏊",     "name": "Swimming",    "name_ru": "Плавание"},
    "вело":     {"emoji": "🚴",     "name": "Cycling",     "name_ru": "Велосипед"},
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
        today = datetime.now()
        current_weekday = today.weekday()  # Monday=0 ... Sunday=6

        info = DAY_MAPPING[self.day_name.lower()]
        target = info["num"]
        # Convert Sunday=0 to Python's Sunday=6
        target = 6 if target == 0 else target - 1

        days_ahead = (target - current_weekday) % 7 or 7
        return today + timedelta(days=days_ahead)

    def to_ics(self) -> str:
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

        return (
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


def parse_training_message(text: str) -> List[Training]:
    trainings: List[Training] = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        # 1) Find a weekday
        day = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day:
            continue

        # 2) Find time (current or next line)
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm = re.search(r"(\d{1,2}:\d{2})", lines[i + 1])
            if tm:
                line = f"{line} {lines[i + 1].strip()}"
        if not tm:
            continue

        time = tm.group(1)

        # 3) Determine workout type
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
            workout = WORKOUT_TYPES["бег"]

        # 4) Extract location
        after = line[line.find(time) + len(time):]
        loc_part = after.split(".", 1)[0]
        m_loc = re.search(r",\s*(.+)$", loc_part)
        location = m_loc.group(1).strip() if m_loc else "Training location"

        # 5) Extract description
        before = line[: line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟🏃‍♂️🏊‍♀️]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout["name_ru"]

        # 6) Waze link
        waze = ""
        if i + 1 < len(lines):
            m_waze = re.search(r"https?://waze\.com/[^\s]+", lines[i + 1])
            if m_waze:
                waze = m_waze.group(0)

        trainings.append(
            Training(
                day_name=day,
                time=time,
                workout_type=workout,
                description=description,
                location=location,
                waze_link=waze,
            )
        )

    return trainings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Main menu keyboard
    menu = ReplyKeyboardMarkup(
        [["/example", "/help"]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

    welcome = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Привет! Я помогу перенести расписание из WhatsApp в твой календарь.\n\n"
        "*Команды:*\n"
        "/start — меню\n"
        "/help  — помощь\n"
        "/example — пример формата\n"
    )
    await update.message.reply_text(
        welcome, parse_mode="Markdown", reply_markup=menu
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "*Как пользоваться:*\n"
        "1. Скопируй расписание из WhatsApp\n"
        "2. Отправь его мне\n"
        "3. Выбери тренировки\n"
        "4. Получи .ics файлы и добавь в календарь\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def example_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    example = (
        "*Пример:*\n"
        "🏃 Воскресенье, бег: техника, 19:30, Бат-Ям.\n"
        "Точка сбора https://waze.com/ul/...\n"
        "🏊 Понедельник, плавание, 19:50, Рамат-Ган.\n"
    )
    await update.message.reply_text(example, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    trainings = parse_training_message(text)

    if not trainings:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок. Отправь /example для формата."
        )

    context.user_data["trainings"] = trainings

    kb = []
    for idx, t in enumerate(trainings):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date = t.date.strftime("%d.%m")
        mark = "✅" if t.selected else "⬜"
        kb.append([
            InlineKeyboardButton(
                f"{mark} {t.workout_type['emoji']} {day_ru} {date} — {t.time}",
                callback_data=f"toggle_
