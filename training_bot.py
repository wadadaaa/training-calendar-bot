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

# Bot token (set in environment)
BOT_TOKEN = os.environ["BOT_TOKEN"]

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
        wd = today.weekday()  # 0=Mon, 6=Sun
        info = DAY_MAPPING[self.day_name]
        # Telegram uses 0=Sunday → convert to Python 6
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
        start_str = fmt(start_dt)
        end_str = fmt(end_dt)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        uid = f"training-{start_str}-{self.workout_type['name']}@bot"
        desc = f"Waze: {self.waze_link}" if self.waze_link else ""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Training Calendar Bot//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
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
    """Extract Training objects from a WhatsApp‐style schedule."""
    trainings: List[Training] = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        # 1) Find day
        day = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day:
            continue

        # 2) Find time in this or next line
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm = re.search(r"(\d{1,2}:\d{2})", lines[i + 1])
            if tm:
                line = f"{line} {lines[i+1].strip()}"
        if not tm:
            continue
        time = tm.group(1)

        # 3) Workout type
        low = line.lower()
        if (("плаван" in low or "море" in low) and "бег" in low) or ("🏃" in line and "🏊" in line):
            wt = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in low or "🏊" in line:
            wt = WORKOUT_TYPES["плавание"]
        elif "вело" in low or "🚴" in line:
            wt = WORKOUT_TYPES["вело"]
        else:
            wt = WORKOUT_TYPES["бег"]

        # 4) Location
        after = line[line.find(time) + len(time) :]
        loc_part = after.split(".", 1)[0]
        m_loc = re.search(r",\s*(.+)$", loc_part)
        loc = m_loc.group(1).strip() if m_loc else "Training location"

        # 5) Description
        before = line[: line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        desc = desc or wt["name_ru"]

        # 6) Waze link
        wlink = ""
        if i + 1 < len(lines):
            m_w = re.search(r"https?://waze\.com/[^\s]+", lines[i + 1])
            if m_w:
                wlink = m_w.group(0)

        trainings.append(Training(day, time, wt, desc, loc, wlink))

    return trainings


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Скопируйте расписание из WhatsApp и отправьте мне в сообщении, "
        "я разберу дни, время и локации и предложу .ics файл.\n\n"
        "Для примера формата используйте /example"
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
    # allow “start” without slash
    if text.strip().lower() in ("start", "старт"):
        return await start_cmd(update, context)

    sessions = parse_training_message(text)
    if not sessions:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок. Попробуйте /example"
        )

    # Store and show inline-keyboard … (your existing selection logic here)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    # … your toggle & download handling here …


async def main() -> None:
    # 1) Build app
    app = Application.builder().token(BOT_TOKEN).build()

    # 2) Remove any webhook + drop pending updates
    await app.bot.delete_webhook(drop_pending_updates=True)

    # 3) Register handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("example", example_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))

    # 4) Start bot: initialize → start → poll → idle
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()


if __name__ == "__main__":
    asyncio.run(main())
