import importlib
import os
import sys
import types


SAMPLE_WEEKLY_TEXT = """Групповые тренировки на новую неделю:

🏃‍♀ Воскресенье, 19:30, бег: техника, сила, скорость.
Бат-Ям.
Точка сбора 👉🏻 https://waze.com/ul/hsv8wn6rz1

🏃‍♀ Воскресенье, 19:30, бег: техника, сила, скорость.
Парк «Зимняя Лужа», Нетания
Точка сбора 👉🏻 https://waze.com/ul/hsv8z8y7bd

🛟 Понедельник, 20:00, плавание.
Кантри Рамат Ган.
Точка сбора 👉🏻 https://waze.com/ul/hsv8y2tvht

🏃 Вторник, 19:30, интервальный бег.
Каньона Аялон, Рамат-Ган, парковка возле футбольного поля.
Точка сбора 👉🏻 https://waze.com/ul/hsv8y87zn9

🆕🏃‍♂️ Вторник, 19:30, групповой бег, Модиин, парк Морешет (Гиват Ашон), подземная парковка, встречаемся на площади в парке, прямо у выхода из парковки.
*Тренировка состоится при наличии участников
Место встречи 👉🏻 https://waze.com/ul/hsv8vkpux9

🏃 Среда, 19:30, интервальный бег на стадионе.
Легкоатлетический стадион Ришен ле Цион.
Точка сбора 👉🏻 https://waze.com/ul/hsv8tzjs6u

🆕🏃‍♂️ Среда, 19:30, развивающий бег.
Спортек Нешер
*Тренировка состоится при наличии участников
Точка сбора 👉🏻 https://waze.com/ul/hsvbfmqeg7

🏃‍♀ Четверг, 19:30, развивающий бег.
Парк «Зимняя Лужа», Нетания
Точка сбора 👉🏻 https://waze.com/ul/hsv8z8y7bd

🆕 🏃‍♂️ Суббота, 6:30, трейловый бег.
Данные о тренировке напишем чуть позже в группе DAVAY Modiin

🆕 🏃‍♀ Суббота, 8:00, длительный бег по набережной.
Площадь Данмарк, возле кафе Camel.
Точка сбора 👉🏻  https://maps.app.goo.gl/LRYdRUD2ewN6ucvW6?g_st=ic

🚴  Суббота, вело, 7:00, возле центра продаж, аэропорт сити.
Длительное вело + темповая работа
Точка сбора 👉🏻  https://waze.com/ul/hsv8vfwcwe

🏋️‍♀️ Суббота, 19:00, Силовые тренировки в спортзале.
Каньон Бат Ям, Йосефталь 92, спортзал icon.
Точка сбора 👉🏻  https://waze.com/ul/hsv8wnu5uv

Тренируемся вместе!
Тренируемся продуктивно!
Добиваемся целей!
"""


def load_training_bot_module():
    os.environ.setdefault("BOT_TOKEN", "test-token")

    telegram = types.ModuleType("telegram")
    telegram.Update = object
    telegram.InlineKeyboardButton = object
    telegram.InlineKeyboardMarkup = object
    sys.modules["telegram"] = telegram
    telegram_error = types.ModuleType("telegram.error")
    telegram_error.Conflict = type("Conflict", (Exception,), {})
    sys.modules["telegram.error"] = telegram_error

    telegram_ext = types.ModuleType("telegram.ext")
    telegram_ext.Application = object
    telegram_ext.CommandHandler = object
    telegram_ext.MessageHandler = object
    telegram_ext.CallbackQueryHandler = object
    telegram_ext.filters = object

    class DummyContextTypes:
        DEFAULT_TYPE = object

    telegram_ext.ContextTypes = DummyContextTypes
    sys.modules["telegram.ext"] = telegram_ext

    if "training_bot" in sys.modules:
        del sys.modules["training_bot"]
    return importlib.import_module("training_bot")


def test_parse_training_message_weekly_schedule_regression():
    training_bot = load_training_bot_module()
    trainings = training_bot.parse_training_message(SAMPLE_WEEKLY_TEXT)

    assert len(trainings) == 12

    parsed = [
        (
            t.day_name,
            t.time,
            t.workout_type["name_ru"],
            t.description,
            t.location,
            t.waze_link,
        )
        for t in trainings
    ]

    assert parsed == [
        (
            "воскресенье",
            "19:30",
            "Бег",
            "бег: техника, сила, скорость",
            "Бат-Ям",
            "https://waze.com/ul/hsv8wn6rz1",
        ),
        (
            "воскресенье",
            "19:30",
            "Бег",
            "бег: техника, сила, скорость",
            "Парк «Зимняя Лужа», Нетания",
            "https://waze.com/ul/hsv8z8y7bd",
        ),
        (
            "понедельник",
            "20:00",
            "Плавание",
            "плавание",
            "Кантри Рамат Ган",
            "https://waze.com/ul/hsv8y2tvht",
        ),
        (
            "вторник",
            "19:30",
            "Бег",
            "интервальный бег",
            "Каньона Аялон, Рамат-Ган, парковка возле футбольного поля",
            "https://waze.com/ul/hsv8y87zn9",
        ),
        (
            "вторник",
            "19:30",
            "Бег",
            "групповой бег",
            "Модиин, парк Морешет (Гиват Ашон), подземная парковка, встречаемся на площади в парке, прямо у выхода из парковки",
            "https://waze.com/ul/hsv8vkpux9",
        ),
        (
            "среда",
            "19:30",
            "Бег",
            "интервальный бег на стадионе",
            "Легкоатлетический стадион Ришен ле Цион",
            "https://waze.com/ul/hsv8tzjs6u",
        ),
        (
            "среда",
            "19:30",
            "Бег",
            "развивающий бег",
            "Спортек Нешер",
            "https://waze.com/ul/hsvbfmqeg7",
        ),
        (
            "четверг",
            "19:30",
            "Бег",
            "развивающий бег",
            "Парк «Зимняя Лужа», Нетания",
            "https://waze.com/ul/hsv8z8y7bd",
        ),
        (
            "суббота",
            "6:30",
            "Бег",
            "трейловый бег",
            "Training location",
            "",
        ),
        (
            "суббота",
            "8:00",
            "Бег",
            "длительный бег по набережной",
            "Площадь Данмарк, возле кафе Camel",
            "https://maps.app.goo.gl/LRYdRUD2ewN6ucvW6?g_st=ic",
        ),
        (
            "суббота",
            "7:00",
            "Велосипед",
            "вело",
            "возле центра продаж, аэропорт сити",
            "https://waze.com/ul/hsv8vfwcwe",
        ),
        (
            "суббота",
            "19:00",
            "Силовые",
            "Силовые тренировки в спортзале",
            "Каньон Бат Ям, Йосефталь 92, спортзал icon",
            "https://waze.com/ul/hsv8wnu5uv",
        ),
    ]
