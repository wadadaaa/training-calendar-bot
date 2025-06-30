import os
import re
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import List
import urllib.parse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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

BOT_TOKEN = os.environ.get("BOT_TOKEN")

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
    def __init__(self, day_name: str, time: str, workout_type: dict,
                 description: str, location: str, waze_link: str = ""):
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
        wd = today.weekday()  # Monday=0
        info = DAY_MAPPING[self.day_name]
        target = 6 if info["num"] == 0 else info["num"] - 1
        days_ahead = (target - wd) % 7 or 7
        return today + timedelta(days=days_ahead)

    def to_ics(self) -> str:
        start = self.date.replace(
            hour=int(self.time.split(":")[0]),
            minute=int(self.time.split(":")[1]),
            second=0
        )
        end = start + timedelta(hours=1, minutes=30)
        fmt = lambda dt: dt.strftime("%Y%m%dT%H%M%S")
        uid = f"training-{fmt(start)}-{self.workout_type['name']}@bot"
        desc = f"Waze: {self.waze_link}" if self.waze_link else ""
        return (
            "BEGIN:VCALENDAR
"
            "VERSION:2.0
"
            "PRODID:-//Training Bot//EN
"
            "BEGIN:VEVENT
"
            f"UID:{uid}
"
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}
"
            f"DTSTART:{fmt(start)}
"
            f"DTEND:{fmt(end)}
"
            f"SUMMARY:{self.workout_type['emoji']} {self.description}
"
            f"LOCATION:{self.location}
"
            f"DESCRIPTION:{desc}
"
            "END:VEVENT
"
            "END:VCALENDAR"
        )

# Parsing logic omitted for brevity; same as before

def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️

"
        "Чтобы начать, просто скопируйте расписание тренировок из WhatsApp и отправьте мне в сообщение.
"
        "Я сам разберу дни, время и локации и предложу скачать .ics для вашего календаря.

"
        "Для примера формата отправьте /example."
    )
    update.message.reply_text(text, parse_mode="Markdown")

async def example_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Пример формата:*
"
        "🏃 Воскресенье, бег: техника, 19:30, Бат-Ям.
"
        "Точка сбора https://waze.com/ul/...
"
        "🚴 Суббота, вело, 06:00, Рамла.
"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    trainings = parse_training_message(text)
    if not trainings:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок. Попробуйте формат из примера: /example"
        )
    # proceed with selection and download as before
    # ...

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # handle toggles, download etc. as before
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
