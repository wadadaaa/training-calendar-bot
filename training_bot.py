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
        # Telegram mapping: Sunday num=0 → Python Sunday=6
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
            "BEGIN:VCALENDAR\n"
            "VERSION:2.0\n"
            "PRODID:-//Training Bot//EN\n"
            "BEGIN:VEVENT\n"
            f"UID:{uid}\n"
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}\n"
            f"DTSTART:{fmt(start)}\n"
            f"DTEND:{fmt(end)}\n"
            f"SUMMARY:{self.workout_type['emoji']} {self.description}\n"
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

        # 1) find a weekday
        day = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day:
            continue

        # 2) find time on this or next line
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm = re.search(r"(\d{1,2}:\d{2})", lines[i+1])
            if tm:
                line = f"{line} {lines[i+1].strip()}"
        if not tm:
            continue
        time = tm.group(1)

        # 3) determine workout type
        lower = line.lower()
        if (("плаван" in lower or "море" in lower) and "бег" in lower) or ("🏃" in line and "🏊" in line):
            workout = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in lower or "🏊" in line:
            workout = WORKOUT_TYPES["плавание"]
        elif "вело" in lower or "🚴" in line:
            workout = WORKOUT_TYPES["вело"]
        else:
            workout = WORKOUT_TYPES["бег"]

        # 4) extract location
        after = line[line.find(time)+len(time):]
        loc_part = after.split(".",1)[0]
        m_loc = re.search(r",\s*(.+)$", loc_part)
        location = m_loc.group(1).strip() if m_loc else "Training location"

        # 5) extract description
        before = line[:line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE
        ).strip(" ,:-")
        description = desc or workout["name_ru"]

        # 6) optional Waze link
        waze = ""
        if i+1 < len(lines):
            m_w = re.search(r"https?://waze\.com/[^\s]+", lines[i+1])
            if m_w:
                waze = m_w.group(0)

        trainings.append(Training(day, time, workout, description, location, waze))

    return trainings

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Начать", callback_data="start")]
    ])
    text = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Нажми «Начать», чтобы импортировать расписание из WhatsApp.\n"
        "Или /example для примера формата."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

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
    text_clean = text.strip().lower()
    # support users typing "start" without slash
    if text_clean in ("start", "старт"):
        return await start_cmd(update, context)

    trainings = parse_training_message(text)
    if not trainings:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок. Попробуй отправить /example."
        )
    context.user_data["trainings"] = trainings

    kb = []
    for idx, t in enumerate(trainings):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date_str = t.date.strftime("%d %B")
        for en, ru in {
            "January":"января","February":"февраля","March":"марта","April":"апреля",
            "May":"мая","June":"июня","July":"июля","August":"августа",
            "September":"сентября","October":"октября","November":"ноября","December":"декабря"
        }.items():
            date_str = date_str.replace(en, ru)
        label = f"{t.workout_type['emoji']} {day_ru}, {date_str} — {t.time}"
        mark = "✅" if t.selected else "⬜"
        kb.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"toggle_{idx}")])

    kb.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
    ])
    kb.append([InlineKeyboardButton("📥 Скачать", callback_data="choose_calendar")])

    await update.message.reply_text(
        f"Нашёл *{len(trainings)}* тренировок. Выбери:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    trainings: List[Training] = context.user_data.get("trainings", [])

    if data == "start":
        # re-display the start screen
        await query.message.reply_text(
            "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
            "Нажми «Начать», чтобы импортировать расписание из WhatsApp.\n"
            "Или /example для примера формата.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Начать", callback_data="start")]
            ])
        )
        return

    # ... here you would handle toggle_x, select_all, download, etc. ...
    # Toggle selection example:
    if data.startswith("toggle_"):
        idx = int(data.split("_")[1])
        trainings[idx].selected = not trainings[idx].selected
        # (rebuild keyboard, edit message, etc.)

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("example", example_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
