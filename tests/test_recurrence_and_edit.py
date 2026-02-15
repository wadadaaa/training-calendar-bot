from datetime import datetime

from tests.test_parser_regression import load_training_bot_module


def test_to_ics_single_event():
    training_bot = load_training_bot_module()
    training = training_bot.Training(
        "среда",
        "19:30",
        training_bot.WORKOUT_TYPES["бег"],
        "Интервалы",
        "Нетания",
    )

    ics = training.to_ics()
    assert ics.count("BEGIN:VEVENT") == 1
    assert ics.count("END:VEVENT") == 1
    assert "CALSCALE:GREGORIAN" in ics


def test_to_google_calendar_url_has_ctz():
    training_bot = load_training_bot_module()
    training = training_bot.Training(
        "четверг",
        "19:30",
        training_bot.WORKOUT_TYPES["бег"],
        "Развивающий бег",
        "Рамат-Ган",
    )

    url = training.to_google_calendar_url()
    assert "calendar.google.com/calendar/render" in url
    assert "ctz=Asia/Jerusalem" in url or "ctz=Asia%2FJerusalem" in url


def test_same_day_future_time_stays_today_in_jerusalem_tz():
    training_bot = load_training_bot_module()
    original_now_local = training_bot.now_local
    try:
        training_bot.now_local = lambda: datetime(
            2026, 2, 15, 13, 0, tzinfo=training_bot.APP_TIMEZONE
        )
        future_same_day = training_bot.Training(
            "воскресенье",
            "23:59",
            training_bot.WORKOUT_TYPES["бег"],
            "Тест",
            "Бат-Ям",
        )
        past_same_day = training_bot.Training(
            "воскресенье",
            "10:00",
            training_bot.WORKOUT_TYPES["бег"],
            "Тест",
            "Бат-Ям",
        )
    finally:
        training_bot.now_local = original_now_local

    assert future_same_day.date.date() == datetime(2026, 2, 15).date()
    assert past_same_day.date.date() == datetime(2026, 2, 22).date()
