import re
from typing import List
from datetime import datetime

def parse_training_message(text: str) -> List[Training]:
    trainings: List[Training] = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        # 1) Убираем лишние эмоджи в начале строки (в том числе сложные последовательности)
        #    Заодно сдвинем текст к началу.
        line = re.sub(r'^(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]+\uFE0F?)+\s*', '', raw).strip()
        if not line:
            continue

        # 2) Ищем день недели
        day_match = next((d for d in DAY_MAPPING if d in line.lower()), None)
        if not day_match:
            continue

        # 3) Ищем время в этой строке
        tm = re.search(r'(\d{1,2}:\d{2})', line)
        # если не нашли — сливаем со следующей
        if not tm and i + 1 < len(lines):
            nxt = lines[i+1].strip()
            tm2 = re.search(r'(\d{1,2}:\d{2})', nxt)
            if tm2:
                tm = tm2
                line = f"{line} {nxt}"
        if not tm:
            continue
        time = tm.group(1)

        # 4) Определяем тип тренировки (workout_type)
        low = line.lower()
        if (("плаван" in low or "море" in low) and "бег" in low):
            workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "🏃" in raw and "🏊" in raw:
            workout_type = {"emoji": "🏃🏊", "name": "Run+Swim", "name_ru": "Бег+Плавание"}
        elif "плаван" in low or "🏊" in line:
            workout_type = WORKOUT_TYPES["плавание"]
        elif "вело" in low or "🚴" in line:
            workout_type = WORKOUT_TYPES["вело"]
        else:
            workout_type = WORKOUT_TYPES["бег"]

        # 5) Локация
        after = line.split(time, 1)[1]
        loc_part = after.split(".", 1)[0]
        m_loc = re.search(r',\s*(.+)$', loc_part)
        location = m_loc[1].strip() if m_loc else "Training location"

        # 6) Описание
        before = line.split(time, 1)[0]
        desc = re.sub(
            r"|".join(map(re.escape, DAY_MAPPING.keys())) + r"|[🏃🏊🚴🛟]+",
            "",
            before,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        description = desc or workout_type["name_ru"]

        # 7) Ссылка Waze из следующей строки
        waze = ""
        if i + 1 < len(lines):
            m_w = re.search(r'https?://waze\.com/\S+', lines[i+1])
            if m_w:
                waze = m_w.group(0)

        trainings.append(
            Training(
                day_name=day_match,
                time=time,
                workout_type=workout_type,
                description=description,
                location=location,
                waze_link=waze,
            )
        )

    return trainings
