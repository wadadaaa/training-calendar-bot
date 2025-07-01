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

# Bot token (set in environment)
# Make sure to set your BOT_TOKEN as an environment variable
# For example: export BOT_TOKEN='your_token_here'
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Workout type mappings
WORKOUT_TYPES = {
    "бег": {"emoji": "🏃", "name": "Running", "name_ru": "Бег"},
    "плавание": {"emoji": "🏊", "name": "Swimming", "name_ru": "Плавание"},
    "вело": {"emoji": "🚴", "name": "Cycling", "name_ru": "Велосипед"},
}

# Day mappings
DAY_MAPPING = {
    "понедельник": {"num": 1, "name": "Monday", "name_ru": "Понедельник"},
    "вторник": {"num": 2, "name": "Tuesday", "name_ru": "Вторник"},
    "среда": {"num": 3, "name": "Wednesday", "name_ru": "Среда"},
    "четверг": {"num": 4, "name": "Thursday", "name_ru": "Четверг"},
    "пятница": {"num": 5, "name": "Friday", "name_ru": "Пятница"},
    "суббота": {"num": 6, "name": "Saturday", "name_ru": "Суббота"},
    "воскресенье": {"num": 0, "name": "Sunday", "name_ru": "Воскресенье"},
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
        # In Python, Monday is 0 and Sunday is 6.
        # We'll adjust our mapping to align with this.
        target_weekday = {
            "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
            "пятница": 4, "суббота": 5, "воскресенье": 6
        }.get(self.day_name.lower())

        if target_weekday is None:
            return today # Fallback

        current_weekday = today.weekday()
        days_ahead = target_weekday - current_weekday
        if days_ahead <= 0: # If it's today but passed, or a previous day
            days_ahead += 7
        
        return today + timedelta(days=days_ahead)


    def to_ics(self) -> str:
        """Convert training to ICS format"""
        # Set the correct date and time for the event
        hours, minutes = map(int, self.time.split(":"))
        start_date = self.date.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        
        # Assume training duration is 1 hour and 30 minutes
        end_date = start_date + timedelta(hours=1, minutes=30)

        # Format dates for ICS
        start_str = start_date.strftime("%Y%m%dT%H%M%S")
        end_str = end_date.strftime("%Y%m%dT%H%M%S")
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")

        # Create a unique ID for the event
        uid = f"training-{start_str}-{self.workout_type['name']}@telegram-bot"

        # Build description, including Waze link if available
        description = self.description
        if self.waze_link:
            description += f"\\n\\nWaze: {self.waze_link}"

        ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Training Calendar Bot//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{timestamp}
DTSTART:{start_str}
DTEND:{end_str}
SUMMARY:{self.workout_type['emoji']} {self.workout_type['name_ru']}
LOCATION:{self.location}
DESCRIPTION:{description}
END:VEVENT
END:VCALENDAR"""

        return ics_content

# --- CORRECTED PARSER FUNCTION ---
def parse_training_message(text: str) -> List[Training]:
    """Parse WhatsApp training message and extract training sessions"""
    trainings = []
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1  # Move to the next line for the next iteration

        if not line:
            continue

        # Look for a day of the week in the current line
        day_match = None
        for day in DAY_MAPPING.keys():
            if day in line.lower():
                day_match = day
                break

        # If a day was found, proceed to find time, location, etc.
        if day_match:
            line_with_day = line
            line_with_time = line
            waze_link_line_index = i

            # Look for time on the current line
            time_match = re.search(r"(\d{1,2}:\d{2})", line_with_time)

            # If time not found, check the next line
            if not time_match and i < len(lines):
                next_line = lines[i].strip()
                time_match = re.search(r"(\d{1,2}:\d{2})", next_line)
                if time_match:
                    line_with_time = next_line
                    waze_link_line_index = i + 1
                    i += 1 # Consume the next line as it's part of this entry

            # If we still can't find a time, skip this entry
            if not time_match:
                logger.warning(f"Found day '{day_match}' but no time on the same or next line.")
                continue

            time = time_match.group(1)
            logger.info(f"Found training: {day_match} at {time}")

            # --- Extract Details ---

            # 1. Workout Type (use the line where the day was found)
            workout_type = {"emoji": "🏃", "name": "Training", "name_ru": "Тренировка"}
            line_lower = line_with_day.lower()
            if ("плаван" in line_lower or "море" in line_lower) and "бег" in line_lower:
                workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
            elif (("🏃" in line_with_day or "🏃‍♂" in line_with_day or "🏃‍♀" in line_with_day) and
                  ("🏊" in line_with_day or "🏊‍♂" in line_with_day or "🏊‍♀" in line_with_day or "🏊🏻‍♂️" in line_with_day)):
                workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
            elif "плаван" in line_lower or "🏊" in line_with_day or "🛟" in line_with_day:
                workout_type = {"emoji": "🏊", "name": "Swimming", "name_ru": "Плавание"}
            elif "вело" in line_lower or "🚴" in line_with_day:
                workout_type = {"emoji": "🚴", "name": "Cycling", "name_ru": "Велосипед"}
            elif "бег" in line_lower or "🏃" in line_with_day:
                workout_type = {"emoji": "🏃", "name": "Running", "name_ru": "Бег"}

            # 2. Location (use the line where the time was found)
            after_time = line_with_time[line_with_time.find(time) + len(time):]
            location_part = after_time.split(".")[0] if "." in after_time else after_time
            location_match = re.search(r",\s*(.+)", location_part) # Made more greedy
            location = location_match.group(1).strip() if location_match else "Training location"

            # 3. Description (use the line where the day was found)
            desc_text = line_with_day
            # If time was on the same line, only take text before it
            if line_with_time is line_with_day:
                 desc_text = line_with_day[: line_with_day.find(time)]
            
            for day_key in DAY_MAPPING.keys():
                desc_text = desc_text.replace(day_key.capitalize(), "").replace(day_key, "")
            desc_text = re.sub(r"[🏃🏊🚴🛟🏃‍♂🏊🏻‍♂️🏃‍♀]+", "", desc_text).strip(" ,:-")
            description = desc_text if desc_text else workout_type["name_ru"]

            # 4. Waze Link (check the line immediately following the time line)
            waze_link = ""
            if waze_link_line_index < len(lines):
                next_line = lines[waze_link_line_index]
                link_match = re.search(r"https://waze\.com/[^\s]+", next_line)
                if link_match:
                    waze_link = link_match.group(0)

            # Create and append the Training object
            trainings.append(Training(
                day_name=day_match,
                time=time,
                workout_type=workout_type,
                description=description,
                location=location,
                waze_link=waze_link,
            ))

    return trainings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    welcome_message = """
Привет! Я помогу перенести расписание тренировок из WhatsApp в твой календарь. 🗓️

*Как использовать:*
1. Скопируй расписание тренировок из WhatsApp
2. Отправь его мне сообщением
3. Выбери нужные тренировки
4. Получи файлы для календаря

*Команды:*
`/start` - Показать это сообщение
`/help` - Помощь
`/example` - Пример формата

Просто отправь мне расписание тренировок! 👇
"""
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = """
*Как пользоваться ботом:*

1.  *Скопируй* всё сообщение с тренировками из WhatsApp.
2.  *Вставь* и отправь его мне.
3.  Я покажу все найденные тренировки.
4.  *Выбери* нужные, нажимая на кнопки.
5.  Нажми *Скачать выбранные*.
6.  *Открой* полученные `.ics` файлы, чтобы добавить события в календарь.

*Советы:*
- Бот понимает русский текст.
- Находит дни недели, время и локации.
- Ссылки Waze включаются в описание события.
- Длительность тренировки по умолчанию 1.5 часа.

*Поддерживаемые типы тренировок:*
🏃 Бег
🏊 Плавание
🚴 Велосипед
🏃🏊 Бег + Плавание
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def example_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show an example of the expected format"""
    example_text = """
*Пример расписания тренировок:*
