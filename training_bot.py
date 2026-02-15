import os
import re
import sys
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict, InvalidToken
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
    "силовые":  {"emoji": "🏋️",  "name": "Strength", "name_ru": "Силовые"},
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

RU_MONTHS = {
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
}

TIME_RE = re.compile(r"(\d{1,2}:\d{2})")
URL_RE = re.compile(r"https?://\S+", flags=re.IGNORECASE)
MORE_WORD_RE = re.compile(r"\bморе\b", flags=re.IGNORECASE)
LEADING_NOISE_RE = re.compile(r"^[^0-9A-Za-zА-Яа-яЁё]+")

APP_TIMEZONE = ZoneInfo("Asia/Jerusalem")


# ——— Trainig model ——————————————————————————————————————————————————
def now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


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
        now = now_local()
        wd = now.weekday()  # 0=Mon … 6=Sun
        info = DAY_MAPPING[self.day_name]
        # Telegram: num=0→Sunday, Python uses 6
        target = 6 if info["num"] == 0 else info["num"] - 1
        delta = (target - wd) % 7
        candidate = now + timedelta(days=delta)

        # If the training is for "today" but its time already passed, move to next week.
        try:
            hour, minute = map(int, self.time.split(":"))
            candidate_at_time = candidate.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate_at_time < now:
                candidate += timedelta(days=7)
        except (ValueError, IndexError):
            pass

        return candidate

    def _event_window(self) -> Tuple[datetime, datetime]:
        hour, minute = map(int, self.time.split(":"))
        start = self.date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(hours=1, minutes=30)
        return start, end

    @staticmethod
    def _fmt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%S")

    def _google_calendar_url(self, start: datetime, end: datetime) -> str:
        title = f"{self.workout_type['emoji']} {self.description}"
        details = f"📍 Место: {self.location}"
        if self.waze_link:
            details += f"\n🗺️ Навигация: {self.waze_link}"

        params = {
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{self._fmt(start)}/{self._fmt(end)}",
            "details": details,
            "location": self.location,
            "ctz": "Asia/Jerusalem",
        }

        url_params = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
        return f"https://calendar.google.com/calendar/render?{url_params}"

    def to_google_calendar_url(self) -> str:
        start, end = self._event_window()
        return self._google_calendar_url(start, end)

    def to_ics(self) -> str:
        start, end = self._event_window()
        desc = f"Navigation: {self.waze_link}" if self.waze_link else ""
        dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Training Calendar Bot//EN",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            f"UID:training-{self._fmt(start)}-{self.workout_type['name']}@bot",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{self._fmt(start)}",
            f"DTEND:{self._fmt(end)}",
            f"SUMMARY:{self.workout_type['emoji']} {self.description}",
            f"LOCATION:{self.location}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        return "\n".join(lines)


# ——— Text parser —————————————————————————————————————————————————————
def format_date_ru(date: datetime) -> str:
    ds = date.strftime("%d %B")
    for en, ru in RU_MONTHS.items():
        ds = ds.replace(en, ru)
    return ds


def workout_type_for_text(raw_text: str, normalized_text: str) -> dict:
    has_run = "бег" in normalized_text or "🏃" in raw_text
    has_swim = (
        "плаван" in normalized_text
        or bool(MORE_WORD_RE.search(normalized_text))
        or "🏊" in raw_text
        or "🛟" in raw_text
    )

    if has_run and has_swim:
        return {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
    if has_swim:
        return WORKOUT_TYPES["плавание"]
    if "вело" in normalized_text or "🚴" in raw_text:
        return WORKOUT_TYPES["вело"]
    if "силов" in normalized_text or "🏋" in raw_text:
        return WORKOUT_TYPES["силовые"]
    return WORKOUT_TYPES["бег"]


def preview_place(location: str) -> str:
    if not location or location == "Training location":
        return "Место уточняется"

    low = location.lower().replace("ё", "е")
    city_map = {
        "бат-ям": "Бат-Ям",
        "бат ям": "Бат-Ям",
        "нетания": "Нетания",
        "рамат-ган": "Рамат-Ган",
        "рамат ган": "Рамат-Ган",
        "модиин": "Модиин",
        "ришен ле цион": "Ришен ле Цион",
        "нешер": "Нешер",
        "рамла": "Рамла",
        "аэропорт сити": "Аэропорт Сити",
    }
    for token, city in city_map.items():
        if token in low:
            return city

    ignore_tokens = (
        "парк",
        "стадион",
        "парковк",
        "площадь",
        "кафе",
        "центр",
        "каньон",
        "кантри",
        "спортзал",
        "возле",
    )
    parts = [part.strip(" .") for part in location.split(",") if part.strip()]
    for part in reversed(parts):
        part_low = part.lower()
        if any(token in part_low for token in ignore_tokens):
            continue
        if any(ch.isdigit() for ch in part):
            continue
        return part

    return parts[-1] if parts else location


def shorten_preview(text: str, max_len: int = 18) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def build_selection_text(trainings: List[Training]) -> str:
    return f"Нашёл *{len(trainings)}* тренировок! Выберите:"


def build_training_keyboard(trainings: List[Training]) -> InlineKeyboardMarkup:
    kb = []
    for idx, t in enumerate(trainings):
        day_ru = DAY_MAPPING[t.day_name]["name_ru"]
        date = t.date.strftime("%d.%m")
        mark = "✅" if t.selected else "⬜"
        place = shorten_preview(preview_place(t.location))
        btn = f"{mark} {t.workout_type['emoji']} {day_ru} {date} — {t.time} · {place}"
        kb.append([InlineKeyboardButton(btn, callback_data=f"toggle_{idx}")])

    kb.append(
        [
            InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
            InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all"),
        ]
    )
    kb.append(
        [
            InlineKeyboardButton("📥 Скачать .ics", callback_data="download"),
            InlineKeyboardButton("📅 Google Calendar", callback_data="google_calendar"),
        ]
    )
    return InlineKeyboardMarkup(kb)


def training_caption(t: Training, google_url: Optional[str] = None) -> str:
    cap = (
        f"{t.workout_type['emoji']} *{t.workout_type['name_ru']}*\n"
        f"📅 {DAY_MAPPING[t.day_name]['name_ru']}, {format_date_ru(t.date)}\n"
        f"⏰ {t.time}\n"
        f"📍 {t.location}"
    )
    if google_url:
        cap += f"\n\n[➕ Добавить в Google Calendar]({google_url})"
    return cap


def strip_leading_noise(line: str) -> str:
    return LEADING_NOISE_RE.sub("", line).strip()


def extract_day_name(line: str) -> Optional[str]:
    cleaned = strip_leading_noise(line).lower()
    for day in DAY_MAPPING:
        if cleaned.startswith(day):
            return day
    return None


def split_training_blocks(text: str) -> List[List[str]]:
    blocks: List[List[str]] = []
    current: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if extract_day_name(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)

    if current:
        blocks.append(current)

    return blocks


def extract_time(block: List[str]) -> str:
    for line in block:
        m = TIME_RE.search(line)
        if m:
            return m.group(1)
    return ""


def extract_header_core(header_line: str, day_name: str, time: str) -> str:
    cleaned = strip_leading_noise(header_line)
    low = cleaned.lower()

    if low.startswith(day_name):
        core = cleaned[len(day_name):]
    else:
        idx = low.find(day_name)
        core = cleaned[idx + len(day_name):] if idx >= 0 else cleaned

    core = core.replace(time, "", 1)
    core = re.sub(r"(,\s*){2,}", ", ", core)
    return core.strip(" ,:-—–.")


def split_description_and_inline_location(header_core: str) -> Tuple[str, str]:
    text = header_core.strip(" .")
    if not text:
        return "", ""

    if ":" in text:
        return text, ""

    if "," in text:
        desc, rest = text.split(",", 1)
        return desc.strip(" ."), rest.strip(" .")

    return text, ""


def extract_navigation_link(block: List[str]) -> str:
    for line in block:
        m = URL_RE.search(line)
        if m:
            return m.group(0).rstrip(").,")
    return ""


def extract_location(block: List[str], inline_location: str) -> str:
    if inline_location:
        return inline_location

    for line in block:
        candidate = line.strip(" .")
        if not candidate:
            continue

        low = candidate.lower()
        if URL_RE.search(candidate):
            continue
        if candidate.startswith("*"):
            continue
        if "точка сбора" in low or "место встречи" in low:
            continue
        if "тренировка состоится" in low:
            continue
        if "данные о тренировке" in low:
            continue

        return candidate

    return "Training location"


def parse_training_message(text: str) -> List[Training]:
    trainings: List[Training] = []
    for block in split_training_blocks(text):
        header = block[0]
        day = extract_day_name(header)
        if not day:
            continue

        time = extract_time(block)
        if not time:
            continue

        block_text = " ".join(block)
        wt = workout_type_for_text(block_text, block_text.lower())

        header_core = extract_header_core(header, day, time)
        description, inline_location = split_description_and_inline_location(header_core)
        location = extract_location(block[1:], inline_location)
        link = extract_navigation_link(block)

        trainings.append(
            Training(
                day,
                time,
                wt,
                description or wt["name_ru"],
                location,
                link,
            )
        )

    return trainings


def parse_callback_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def apply_telegram_py314_compat_patch() -> None:
    """
    python-telegram-bot 20.7 misses a private slot used by Updater.__init__.
    Python 3.14 enforces this and raises AttributeError during app build.
    """
    if sys.version_info < (3, 14):
        return

    try:
        import telegram
        from telegram.ext import _applicationbuilder, _updater
    except Exception:
        return

    if getattr(telegram, "__version__", "") != "20.7":
        return

    if "_Updater__polling_cleanup_cb" in _updater.Updater.__slots__:
        return

    class _UpdaterPy314Compat(_updater.Updater):
        __slots__ = ("_Updater__polling_cleanup_cb",)

    _updater.Updater = _UpdaterPy314Compat
    _applicationbuilder.Updater = _UpdaterPy314Compat
    logger.warning(
        "Applied python-telegram-bot 20.7 compatibility patch for Python 3.14."
    )


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, Conflict):
        if not context.application.bot_data.get("conflict_reported"):
            logger.warning(
                "Telegram Conflict: another bot instance is currently polling with this token. "
                "Waiting and retrying (common during rolling deployments)."
            )
            context.application.bot_data["conflict_reported"] = True
        return

    logger.error("Unhandled exception in update handler", exc_info=err)


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

    await update.message.reply_text(
        build_selection_text(sessions),
        reply_markup=build_training_keyboard(sessions),
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
        i = parse_callback_int(cmd.split("_", 1)[1])
        if i is None or not (0 <= i < len(trainings)):
            return await query.message.reply_text("❌ Не удалось изменить выбор. Обновите список.")
        trainings[i].selected = not trainings[i].selected

    elif cmd in ("select_all", "deselect_all"):
        selected = cmd == "select_all"
        for t in trainings:
            t.selected = selected

    elif cmd == "download":
        chosen = [t for t in trainings if t.selected]
        if not chosen:
            return await query.message.reply_text("⚠️ Выберите хотя бы одну тренировку!")

        await query.message.reply_text(f"📥 Создаю {len(chosen)} .ics файла…")
        for t in chosen:
            data = t.to_ics().encode("utf-8")
            bio = BytesIO(data)
            bio.name = f"{t.workout_type['name'].lower()}_{t.day_name}.ics"
            await query.message.reply_document(
                bio,
                caption=training_caption(t),
                parse_mode="Markdown",
            )

        return await query.message.reply_text("✅ Готово!")

    elif cmd == "google_calendar":
        chosen = [t for t in trainings if t.selected]
        if not chosen:
            return await query.message.reply_text("⚠️ Выберите хотя бы одну тренировку!")

        await query.message.reply_text(f"📅 Создаю ссылки для {len(chosen)} тренировок…")
        for t in chosen:
            google_url = t.to_google_calendar_url()
            await query.message.reply_text(
                training_caption(t, google_url),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

        return await query.message.reply_text("✅ Ссылки готовы! Нажмите на любую, чтобы добавить в календарь.")

    await query.edit_message_text(
        build_selection_text(trainings),
        reply_markup=build_training_keyboard(trainings),
        parse_mode="Markdown",
    )


# ——— Entry point ——————————————————————————————————————————————————————————————
def main() -> None:
    apply_telegram_py314_compat_patch()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("example", example))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(handle_error)

    try:
        app.run_polling(drop_pending_updates=True)
    except InvalidToken:
        logger.error(
            "BOT_TOKEN отклонен Telegram API. Обновите переменную BOT_TOKEN в Railway Variables."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
