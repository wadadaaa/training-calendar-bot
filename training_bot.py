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
        current_weekday = today.weekday()  # Monday=0

        info = DAY_MAPPING[self.day_name.lower()]
        target = info["num"]
        target = 6 if target == 0 else target - 1  # convert Sunday=0→6

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

        # Day detection
        day_match = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day_match:
            continue

        # Time detection
        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm:
            continue
        time = tm.group(1)

        logger.info(f"Found training on {day_match} at {time}")

        # Workout type
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

        # Location extraction
        after = line[line.find(time) + len(time) :]
        loc_part = after.split(".", 1)[0]
        loc_match = re.search(r",\s*(.+)$", loc_part)
        location = loc_match.group(1).strip() if loc_match else "Training location"

        # Description extraction
        before = line[: line.find(time)]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING)) + r"|[🏃🏊🚴🛟🏃‍♂️🏊‍♀️]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout["name_ru"]

        # Optional Waze link on next line
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
    welcome = (
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Привет! Я помогу перенести расписание из WhatsApp в твой календарь.\n\n"
        "*Команды:*\n"
        "/start — это сообщение\n"
        "/help  — помощь\n"
        "/example — пример формата\n"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


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
    # Avoid triple-quoted string issues by concatenating
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
        kb.append(
            [
                InlineKeyboardButton(
                    f"{mark} {t.workout_type['emoji']} {day_ru} {date} — {t.time}",
                    callback_data=f"toggle_{idx}",
                )
            ]
        )

    kb.append(
        [
            InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
            InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
        ]
    )
    kb.append([InlineKeyboardButton("📥 Скачать", callback_data="download")])

    await update.message.reply_text(
        f"Нашёл *{len(trainings)}* тренировок. Выбери:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    trainings: List[Training] = context.user_data.get("trainings", [])
    if not trainings:
        return await query.edit_message_text(
            "Сессия истекла, отправь расписание заново."
        )

    cmd = query.data
    if cmd.startswith("toggle_"):
        idx = int(cmd.split("_")[1])
        trainings[idx].selected = not trainings[idx].selected
    elif cmd == "select_all":
        for t in trainings:
            t.selected = True
    elif cmd == "deselect_all":
        for t in trainings:
            t.selected = False
    elif cmd == "download":
        chosen = [t for t in trainings if t.selected]
        if not chosen:
            return await query.message.reply_text(
                "⚠️ Выберите хотя бы одну тренировку."
            )
        await query.message.reply_text(f"Создаю {len(chosen)} .ics файлов…")
        for t in chosen:
            ics_bytes = t.to_ics().encode("utf-8")
            bio = BytesIO(ics_bytes)
            bio.name = (
                f"{t.workout_type['name'].lower()}_"
                f"{DAY_MAPPING[t.day_name]['name'].lower()}.ics"
            )

            # Russian month formatting
            date_str = t.date.strftime("%d %B")
            for en, ru in {
                "January": "января",
                "February": "февраля",
                "March": "марта",
                "April": "апреля",
                "May": "мая",
                "June": "июня",
                "July": "июля",
                "August": "августа",
                "September": "сентября",
                "October": "октября",
                "November": "ноября",
                "December": "декабря",
            }.items():
                date_str = date_str.replace(en, ru)

            caption = (
                f"{t.workout_type['emoji']} *{t.workout_type['name_ru']}*\n"
                f"📅 {DAY_MAPPING[t.day_name]['name_ru']}, {date_str}\n"
                f"⏰ {t.time}\n"
                f"📍 {t.location}"
            )
            await query.message.reply_document(bio, caption=caption, parse_mode="Markdown")

        return await query.message.reply_text(
            "✅ Готово! Открой .ics файлы, чтобы добавить в календарь."
        )

    # Rebuild keyboard after any toggle
    kb = []
    for idx, t in enumerate(trainings):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date = t.date.strftime("%d.%m")
        mark = "✅" if t.selected else "⬜"
        kb.append(
            [
                InlineKeyboardButton(
                    f"{mark} {t.workout_type['emoji']} {day_ru} {date} — {t.time}",
                    callback_data=f"toggle_{idx}",
                )
            ]
        )
    kb.append(
        [
            InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
            InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
        ]
    )
    kb.append([InlineKeyboardButton("📥 Скачать", callback_data="download")])

    await query.edit_message_text(
        f"Нашёл *{len(trainings)}* тренировок. Выбрано: {sum(t.selected for t in trainings)}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


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
