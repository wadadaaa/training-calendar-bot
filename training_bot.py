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


# ——— Training model ——————————————————————————————————————————————————
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


# ——— Improved Text parser —————————————————————————————————————————————————————
def parse_training_message(text: str) -> List[Training]:
    trainings: List[Training] = []
    lines = text.splitlines()

    for i, raw_line in enumerate(lines):
        # 1) Более агрессивная очистка эмоджи в начале строки
        line = re.sub(
            r'^[\u{1F000}-\u{1F9FF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]+\s*',
            "",
            raw_line,
            flags=re.UNICODE
        ).strip()
        
        if not line:
            continue

        # 2) Поиск дня недели (более гибкий)
        day = None
        for day_key in DAY_MAPPING.keys():
            if day_key in line.lower():
                day = day_key
                break
        
        if not day:
            continue

        # 3) Поиск времени в текущей или следующей строке
        time_match = re.search(r"(\d{1,2}:\d{2})", line)
        time = None
        combined_line = line
        
        if time_match:
            time = time_match.group(1)
        elif i + 1 < len(lines):
            next_line = lines[i + 1]
            time_match_next = re.search(r"(\d{1,2}:\d{2})", next_line)
            if time_match_next:
                time = time_match_next.group(1)
                # Объединяем строки для правильного парсинга локации
                combined_line = f"{line} {next_line.strip()}"
        
        if not time:
            continue

        # 4) Определение типа тренировки (улучшенная логика)
        line_lower = combined_line.lower()
        raw_lower = raw_line.lower()
        
        # Проверяем комбинированные тренировки
        if (("плаван" in line_lower or "море" in line_lower) and "бег" in line_lower) or \
           ("🏃" in raw_line and ("🏊" in raw_line or "🛟" in raw_line)):
            workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in line_lower or "🏊" in raw_line or "🛟" in raw_line:
            workout_type = WORKOUT_TYPES["плавание"]
        elif "вело" in line_lower or "🚴" in raw_line:
            workout_type = WORKOUT_TYPES["вело"]
        else:
            workout_type = WORKOUT_TYPES["бег"]

        # 5) Извлечение локации (улучшенная логика)
        location = "Training location"
        
        # Разделяем по времени
        parts_after_time = combined_line.split(time, 1)
        if len(parts_after_time) > 1:
            after_time = parts_after_time[1].strip()
            
            # Убираем начальную запятую и ищем локацию
            after_time = after_time.lstrip(", ")
            
            # Ищем текст до точки или до конца строки
            location_match = re.match(r"([^.]+)", after_time)
            if location_match:
                location_text = location_match.group(1).strip()
                # Убираем лишние символы в начале
                location_text = re.sub(r"^[,\s]+", "", location_text)
                if location_text and not location_text.startswith("*"):
                    location = location_text

        # 6) Извлечение описания (улучшенная логика)
        before_time = combined_line.split(time, 1)[0]
        
        # Убираем день недели
        desc_text = before_time
        for day_key in DAY_MAPPING.keys():
            desc_text = re.sub(day_key, "", desc_text, flags=re.IGNORECASE)
        
        # Убираем эмоджи и лишние символы
        desc_text = re.sub(r"[🏃🏊🚴🛟‍♀‍♂️]+", "", desc_text)
        desc_text = re.sub(r"^[,\s:-]+|[,\s:-]+$", "", desc_text)
        
        description = desc_text.strip() if desc_text.strip() else workout_type["name_ru"]

        # 7) Поиск Waze ссылки в следующих строках
        waze_link = ""
        # Ищем в следующих 3 строках
        for j in range(i + 1, min(i + 4, len(lines))):
            waze_match = re.search(r"https?://waze\.com/\S+", lines[j])
            if waze_match:
                waze_link = waze_match.group(0)
                break
            # Также ищем Google Maps ссылки
            google_match = re.search(r"https?://maps\.app\.goo\.gl/\S+", lines[j])
            if google_match:
                waze_link = google_match.group(0)
                break

        # 8) Создаем объект тренировки
        training = Training(day, time, workout_type, description, location, waze_link)
        trainings.append(training)
        
        logger.info(f"Найдена тренировка: {day} {time} - {description} в {location}")

    return trainings


# ——— Handlers —————————————————————————————————————————————————————————————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🏃‍♂️ *Календарь тренировок* 🏊‍♀️\n\n"
        "Скопируйте расписание из WhatsApp и отправьте мне — я верну файлы для календаря.\n"
        "Поддерживаю: 📥 .ics файлы, 📅 Google Calendar, 🏆 TrainingPeaks\n\n"
        "Пример формата: /example",
        parse_mode="Markdown",
    )


async def example(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Пример:*\n"
        "🏃 Воскресенье, бег: техника, 19:30, Бат-Ям.\n"
        "Точка сбора https://waze.com/ul/...\n"
        "🚴 Суббота, вело, 06:00, Рамла.\n"
        "🏃🏊 Пятница, бег + плавание, 6:00, пляж.",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if text.strip().lower() in ("start", "старт"):
        return await start(update, context)

    sessions = parse_training_message(text)
    if not sessions:
        return await update.message.reply_text(
            "❌ Не нашёл тренировок в сообщении.\n\n"
            "Попробуйте формат: /example\n"
            "Или проверьте, что указаны день недели и время."
        )

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
        f"Нашёл *{len(sessions)}* тренировок! Выберите нужные:",
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

    # Обновляем клавиатуру
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
        f"Нашёл *{len(trainings)}* тренировок! Выберите нужные:",
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

    logger.info("🚀 Training Calendar Bot запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
