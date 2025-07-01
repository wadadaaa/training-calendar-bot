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
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Workout type mappings
WORKOUT_TYPES = {
    "бег":      {"emoji": "🏃", "name": "Running",  "name_ru": "Бег"},
    "плавание": {"emoji": "🏊", "name": "Swimming", "name_ru": "Плавание"},
    "вело":     {"emoji": "🚴", "name": "Cycling",  "name_ru": "Велосипед"},
}

# Day mappings
DAY_MAPPING = {
    "понедельник": {"num": 1, "name": "Monday",    "name_ru": "Понедельник"},
    "вторник":     {"num": 2, "name": "Tuesday",   "name_ru": "Вторник"},
    "среда":       {"num": 3, "name": "Wednesday", "name_ru": "Среда"},
    "четверг":     {"num": 4, "name": "Thursday",  "name_ru": "Четверг"},
    "пятница":     {"num": 5, "name": "Friday",    "name_ru": "Пятница"},
    "суббота":     {"num": 6, "name": "Saturday",  "name_ru": "Суббота"},
    "воскресенье": {"num": 0, "name": "Sunday",    "name_ru": "Воскресенье"},
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
        wd = today.weekday()  # Monday=0 ... Sunday=6
        info = DAY_MAPPING[self.day_name]
        # Telegram uses num=0 for Sunday, Python uses 6
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

        # 1) Find day
        day_match = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day_match:
            continue

        # 2) Find time in this or next line
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm2 = re.search(r"(\d{1,2}:\d{2})", lines[i + 1])
            if tm2:
                tm = tm2
                line = f"{line} {lines[i + 1].strip()}"
        if not tm:
            continue

        time = tm.group(1)

        # 3) Determine workout_type
        low = line.lower()
        if (("плаван" in low or "море" in low) and "бег" in low) or ("🏃" in line and "🏊" in line):
            workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in low or "🏊" in line:
            workout_type = WORKOUT_TYPES["плавание"]
        elif "вело" in low or "🚴" in line:
            workout_type = WORKOUT_TYPES["вело"]
        else:
            workout_type = WORKOUT_TYPES["бег"]

        # 4) Extract location
        after = line[line.find(time) + len(time) :]
        loc_part = after.split(".", 1)[0]
        m_loc = re.search(r",\s*(.+)$", loc_part)
        location = m_loc.group(1).strip() if m_loc else "Training location"

        # 5) Extract description
        before = line[: line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout_type["name_ru"]

        # 6) Optional Waze link
        waze_link = ""
        if i + 1 < len(lines):
            m_w = re.search(r"https?://waze\.com/[^\s]+", lines[i + 1])
            if m_w:
                waze_link = m_w.group(0)

        trainings.append(
            Training(
                day_name=day_match,
                time=time,
                workout_type=workout_type,
                description=description,
                location=location,
                waze_link=waze_link,
            )
        )

    return trainings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_message = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Привет! Скопируй расписание из WhatsApp и отправь мне —\n"
        "я найду дни, время и локации и предложу .ics файлы.\n\n"
        "Для примера формата отправь /example."
    )
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "*Как пользоваться:*\n"
        "1. Скопируй расписание из WhatsApp\n"
        "2. Отправь его мне\n"
        "3. Выбери тренировки кнопками\n"
        "4. Скачай .ics и открой в календаре"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def example_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    example_text = (
        "*Пример формата:*\n"
        "🏃 Воскресенье, бег: техника, 19:30, Бат-Ям.\n"
        "Точка сбора https://waze.com/ul/...\n"
        "🚴 Суббота, вело, 06:00, Рамла."
    )
    await update.message.reply_text(example_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if text.strip().lower() in ("start", "старт"):
        return await start(update, context)

    trainings = parse_training_message(text)
    if not trainings:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок. Попробуй /example."
        )

    context.user_data["trainings"] = trainings

    keyboard = []
    for i, t in enumerate(trainings):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date_str = t.date.strftime("%d.%m")
        mark = "✅" if t.selected else "⬜"
        btn = f"{mark} {t.workout_type['emoji']} {day_ru} {date_str} — {t.time}"
        keyboard.append([InlineKeyboardButton(btn, callback_data=f"toggle_{i}")])

    keyboard.append(
        [
            InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
            InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
        ]
    )
    keyboard.append([InlineKeyboardButton("📥 Скачать", callback_data="download")])

    await update.message.reply_text(
        f"Нашёл *{len(trainings)}* тренировок!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # ... your toggle/download logic here ...


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("example", example_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
