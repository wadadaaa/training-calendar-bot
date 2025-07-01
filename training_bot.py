import os
import re
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import List
from urllib.parse import quote

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ——— Logging —————————————————————————————————————————————————————
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ——— Config ————————————————————————————————————————————————————————
BOT_TOKEN = os.environ["BOT_TOKEN"]

WORKOUT_TYPES = {
    "бег":      {"emoji": "🏃",   "name": "Running",  "name_ru": "Бег"},
    "плавание": {"emoji": "🏊",   "name": "Swimming", "name_ru": "Плавание"},
    "вело":     {"emoji": "🚴",   "name": "Cycling",  "name_ru": "Велосипед"},
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


# ——— Trainig model ——————————————————————————————————————————————————
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
        self.date = self._calc_date()

    def _calc_date(self) -> datetime:
        today = datetime.now()
        wd = today.weekday()  # 0=Mon … 6=Sun
        info = DAY_MAPPING[self.day_name]
        # Telegram: num=0→Sunday, Python uses 6
        target = 6 if info["num"] == 0 else info["num"] - 1
        delta = (target - wd) % 7 or 7
        return today + timedelta(days=delta)

    def to_ics(self) -> str:
        start = self.date.replace(
            hour=int(self.time.split(":")[0]),
            minute=int(self.time.split(":")[1]),
            second=0,
        )
        end = start + timedelta(hours=1, minutes=30)
        fmt = lambda d: d.strftime("%Y%m%dT%H%M%S")
        uid = f"training-{fmt(start)}-{self.workout_type['name']}@bot"
        desc = f"Waze: {self.waze_link}" if self.waze_link else ""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Training Calendar Bot//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{fmt(start)}",
            f"DTEND:{fmt(end)}",
            f"SUMMARY:{self.workout_type['emoji']} {self.description}",
            f"LOCATION:{self.location}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        return "\n".join(lines)

    def to_google_calendar_url(self) -> str:
        """Создает ссылку для добавления в Google Calendar"""
        start = self.date.replace(
            hour=int(self.time.split(":")[0]),
            minute=int(self.time.split(":")[1]),
            second=0,
        )
        end = start + timedelta(hours=1, minutes=30)
        
        # Форматирование для Google Calendar (UTC)
        fmt = lambda d: d.strftime("%Y%m%dT%H%M%S")
        
        title = f"{self.workout_type['emoji']} {self.description}"
        details = f"📍 Место: {self.location}"
        if self.waze_link:
            details += f"\n🗺️ Навигация: {self.waze_link}"
        
        # URL encoding
        params = {
            'action': 'TEMPLATE',
            'text': title,
            'dates': f"{fmt(start)}/{fmt(end)}",
            'details': details,
            'location': self.location
        }
        
        url_params = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
        return f"https://calendar.google.com/calendar/render?{url_params}"


# ——— Text parser —————————————————————————————————————————————————————
def parse_training_message(text: str) -> List[Training]:
    trainings: List[Training] = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        line = re.sub(
            r'^(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]+\uFE0F?)+\s*',
            "",
            raw,
        ).strip()
        if not line:
            continue

        day = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day:
            continue

        tm = re.search(r"(\d{1,2}:\d{2})", line)
        if not tm and i + 1 < len(lines):
            tm2 = re.search(r"(\d{1,2}:\d{2})", lines[i + 1])
            if tm2:
                tm = tm2
                line = f"{line} {lines[i + 1].strip()}"
        if not tm:
            continue
        time = tm.group(1)

        low = line.lower()
        if (("плаван" in low or "море" in low) and "бег" in low) or ("🏃" in raw and "🏊" in raw):
            wt = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in low or "🏊" in line:
            wt = WORKOUT_TYPES["плавание"]
        elif "вело" in low or "🚴" in line:
            wt = WORKOUT_TYPES["вело"]
        else:
            wt = WORKOUT_TYPES["бег"]

        after = line.split(time, 1)[1]
        loc = after.split(".", 1)[0]
        m_loc = re.search(r",\s*(.+)$", loc)
        location = m_loc.group(1).strip() if m_loc else "Training location"

        before = line.split(time, 1)[0]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING.keys())) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or wt["name_ru"]

        wlink = ""
        if i + 1 < len(lines):
            m = re.search(r"https?://waze\.com/\S+", lines[i + 1])
            if m:
                wlink = m.group(0)

        trainings.append(Training(day, time, wt, description, location, wlink))

    return trainings


# ——— Handlers —————————————————————————————————————————————————————————————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Скопируйте расписание из WhatsApp и отправьте мне — я верну файлы для календаря.\n"
        "Пример формата: /example",
        parse_mode="Markdown",
    )


async def example(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Пример:*\n"
        "🏃 Воскресенье, бег: техника, 19:30, Бат-Ям.\n"
        "Точка сбора https://waze.com/ul/...\n"
        "🚴 Суббота, вело, 06:00, Рамла.",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if text.strip().lower() in ("start", "старт"):
        return await start(update, context)

    sessions = parse_training_message(text)
    if not sessions:
        return await update.message.reply_text("❌ Не нашёл тренировок. Попробуйте /example.")

    context.user_data["trainings"] = sessions

    kb = []
    for idx, t in enumerate(sessions):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date = t.date.strftime("%d.%m")
        mark = "✅" if t.selected else "⬜"
        btn = f"{mark} {t.workout_type['emoji']} {day_ru} {date} — {t.time}"
        kb.append([InlineKeyboardButton(btn, callback_data=f"toggle_{idx}")])

    kb.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
    ])
    kb.append([
        InlineKeyboardButton("📥 Скачать .ics", callback_data="download"),
        InlineKeyboardButton("📅 Google Calendar", callback_data="google_calendar"),
    ])

    await update.message.reply_text(
        f"Нашёл *{len(sessions)}* тренировок! Выберите:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    trainings: List[Training] = context.user_data.get("trainings", [])
    if not trainings:
        return await query.edit_message_text("❌ Сессия устарела. Пришлите расписание снова.")

    cmd = query.data

    if cmd.startswith("toggle_"):
        i = int(cmd.split("_", 1)[1])
        trainings[i].selected = not trainings[i].selected

    elif cmd == "select_all":
        for t in trainings:
            t.selected = True

    elif cmd == "deselect_all":
        for t in trainings:
            t.selected = False

    elif cmd == "download":
        chosen = [t for t in trainings if t.selected]
        if not chosen:
            return await query.message.reply_text("⚠️ Выберите хотя бы одну тренировку!")

        await query.message.reply_text(f"📥 Создаю {len(chosen)} .ics файла…")
        for t in chosen:
            data = t.to_ics().encode("utf-8")
            bio = BytesIO(data)
            bio.name = f"{t.workout_type['name'].lower()}_{t.day_name}.ics"

            # русская дата
            ds = t.date.strftime("%d %B")
            ru_m = {
                "January":"января","February":"февраля","March":"марта",
                "April":"апреля","May":"мая","June":"июня","July":"июля",
                "August":"августа","September":"сентября",
                "October":"октября","November":"ноября","December":"декабря"
            }
            for en, ru in ru_m.items():
                ds = ds.replace(en, ru)

            cap = (
                f"{t.workout_type['emoji']} *{t.workout_type['name_ru']}*\n"
                f"📅 {DAY_MAPPING[t.day_name]['name_ru']}, {ds}\n"
                f"⏰ {t.time}\n"
                f"📍 {t.location}"
            )
            await query.message.reply_document(bio, caption=cap, parse_mode="Markdown")

        return await query.message.reply_text("✅ Готово!")

    elif cmd == "google_calendar":
        chosen = [t for t in trainings if t.selected]
        if not chosen:
            return await query.message.reply_text("⚠️ Выберите хотя бы одну тренировку!")

        await query.message.reply_text(f"📅 Создаю ссылки для {len(chosen)} тренировок…")
        for t in chosen:
            # русская дата
            ds = t.date.strftime("%d %B")
            ru_m = {
                "January":"января","February":"февраля","March":"марта",
                "April":"апреля","May":"мая","June":"июня","July":"июля",
                "August":"августа","September":"сентября",
                "October":"октября","November":"ноября","December":"декабря"
            }
            for en, ru in ru_m.items():
                ds = ds.replace(en, ru)

            google_url = t.to_google_calendar_url()
            
            cap = (
                f"{t.workout_type['emoji']} *{t.workout_type['name_ru']}*\n"
                f"📅 {DAY_MAPPING[t.day_name]['name_ru']}, {ds}\n"
                f"⏰ {t.time}\n"
                f"📍 {t.location}\n\n"
                f"[➕ Добавить в Google Calendar]({google_url})"
            )
            await query.message.reply_text(cap, parse_mode="Markdown", disable_web_page_preview=True)

        return await query.message.reply_text("✅ Ссылки готовы! Нажмите на любую, чтобы добавить в календарь.")

    kb = []
    for idx, t in enumerate(trainings):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date = t.date.strftime("%d.%m")
        mark = "✅" if t.selected else "⬜"
        btn = f"{mark} {t.workout_type['emoji']} {day_ru} {date} — {t.time}"
        kb.append([InlineKeyboardButton(btn, callback_data=f"toggle_{idx}")])

    kb.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
    ])
    kb.append([
        InlineKeyboardButton("📥 Скачать .ics", callback_data="download"),
        InlineKeyboardButton("📅 Google Calendar", callback_data="google_calendar"),
    ])

    await query.edit_message_text(
        f"Нашёл *{len(trainings)}* тренировок! Выберите:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


# ——— Entry point ——————————————————————————————————————————————————————————————
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("example", example))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
