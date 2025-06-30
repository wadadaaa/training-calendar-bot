import os
import re
import logging
from datetime import datetime, timedelta
from io import BytesIO
import asyncio
from typing import List, Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Workout type mappings
WORKOUT_TYPES = {
    'бег': {'emoji': '🏃', 'name': 'Running', 'name_ru': 'Бег'},
    'плавание': {'emoji': '🏊', 'name': 'Swimming', 'name_ru': 'Плавание'},
    'вело': {'emoji': '🚴', 'name': 'Cycling', 'name_ru': 'Велосипед'},
}

# Day mappings
DAY_MAPPING = {
    'понедельник': {'num': 1, 'name': 'Monday', 'name_ru': 'Понедельник'},
    'вторник': {'num': 2, 'name': 'Tuesday', 'name_ru': 'Вторник'},
    'среда': {'num': 3, 'name': 'Wednesday', 'name_ru': 'Среда'},
    'четверг': {'num': 4, 'name': 'Thursday', 'name_ru': 'Четверг'},
    'пятница': {'num': 5, 'name': 'Friday', 'name_ru': 'Пятница'},
    'суббота': {'num': 6, 'name': 'Saturday', 'name_ru': 'Суббота'},
    'воскресенье': {'num': 0, 'name': 'Sunday', 'name_ru': 'Воскресенье'},
}


class Training:
    def __init__(self, day_name: str, time: str, workout_type: dict, 
                 description: str, location: str, waze_link: str = ''):
        self.day_name = day_name
        self.time = time
        self.workout_type = workout_type
        self.description = description
        self.location = location
        self.waze_link = waze_link
        self.selected = True
        self.date = self._calculate_date()
    
    def _calculate_date(self) -> datetime:
        """Calculate the next occurrence of this training day"""
        today = datetime.now()
        current_day = today.weekday()  # Monday is 0, Sunday is 6
        
        # Convert our day number (Sunday=0) to Python's format (Monday=0)
        day_info = DAY_MAPPING.get(self.day_name.lower())
        if not day_info:
            return today
        
        target_day = day_info['num']
        if target_day == 0:  # Sunday
            target_day = 6
        else:
            target_day -= 1
        
        days_until = target_day - current_day
        if days_until <= 0:
            days_until += 7
        
        return today + timedelta(days=days_until)
    
    def to_ics(self) -> str:
        """Convert training to ICS format"""
        start_date = self.date.replace(hour=0, minute=0, second=0)
        hours, minutes = map(int, self.time.split(':'))
        start_date = start_date.replace(hour=hours, minute=minutes)
        
        end_date = start_date + timedelta(hours=1, minutes=30)
        
        # Format dates for ICS
        start_str = start_date.strftime('%Y%m%dT%H%M%S')
        end_str = end_date.strftime('%Y%m%dT%H%M%S')
        timestamp = datetime.now().strftime('%Y%m%dT%H%M%SZ')
        
        # Create UID
        uid = f"training-{start_str}-{self.workout_type['name']}@telegram-bot"
        
        # Build description
        description = ''
        if self.waze_link:
            description = f"Waze: {self.waze_link}"
        
        ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Training Calendar Bot//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{timestamp}
DTSTART:{start_str}
DTEND:{end_str}
SUMMARY:{self.workout_type['emoji']} {self.workout_type['name']}: {self.description}
LOCATION:{self.location}
DESCRIPTION:{description}
END:VEVENT
END:VCALENDAR"""
        
        return ics_content


def parse_training_message(text: str) -> List[Training]:
    """Parse WhatsApp training message and extract training sessions"""
    trainings = []
    lines = text.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Look for lines that contain a day of the week
        day_match = None
        for day in DAY_MAPPING.keys():
            if day in line.lower():
                day_match = day
                break
        
        # If we found a day, look for a time
        if day_match:
            time_match = re.search(r'(\d{1,2}:\d{2})', line)
            if not time_match:
                continue
            
            time = time_match.group(1)
            
            # Log for debugging
            logger.info(f"Found training: {day_match} at {time}")
            
            # Determine workout type based on text content
            workout_type = {'emoji': '🏃', 'name': 'Training', 'name_ru': 'Тренировка'}
            
            # Check text content for workout type
            line_lower = line.lower()
            
            # Check for combined training first (both swimming and running keywords)
            if ('плаван' in line_lower or 'море' in line_lower) and 'бег' in line_lower:
                workout_type = {'emoji': '🏃🏊', 'name': 'Run+Swim', 'name_ru': 'Бег+Плавание'}
            # Check if line has both running and swimming emojis
            elif ('🏃' in line and '🏊' in line) or ('🏃‍♂' in line and '🏊' in line):
                workout_type = {'emoji': '🏃🏊', 'name': 'Run+Swim', 'name_ru': 'Бег+Плавание'}
            elif 'плаван' in line_lower or '🏊' in line or '🛟' in line:
                workout_type = {'emoji': '🏊', 'name': 'Swimming', 'name_ru': 'Плавание'}
            elif 'вело' in line_lower or '🚴' in line:
                workout_type = {'emoji': '🚴', 'name': 'Cycling', 'name_ru': 'Велосипед'}
            elif 'бег' in line_lower or '🏃' in line:
                workout_type = {'emoji': '🏃', 'name': 'Running', 'name_ru': 'Бег'}
            
            # Extract location (after time)
            after_time = line[line.find(time) + len(time):]
            # Remove everything after the period to get clean location
            location_part = after_time.split('.')[0] if '.' in after_time else after_time
            location_match = re.search(r',\s*(.+?)$', location_part)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    welcome_message = """
🏃‍♂️ *Календарь тренировок* 🏊‍♀️

Привет! Я помогу перенести расписание тренировок из WhatsApp в твой календарь.

*Как использовать:*
1. Скопируй расписание тренировок из WhatsApp
2. Отправь его мне сообщением
3. Выбери нужные тренировки
4. Получи файлы для календаря

*Команды:*
/start - Показать это сообщение
/help - Помощь
/example - Пример формата

Просто отправь мне расписание тренировок! 🚴‍♂️
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = """
*Как пользоваться ботом:*

1. *Скопируй* всё сообщение с тренировками из WhatsApp
2. *Вставь* и отправь его мне
3. Я покажу все найденные тренировки
4. *Выбери* нужные (используй кнопки)
5. *Скачай* файлы .ics
6. *Открой* их на устройстве для добавления в календарь

*Советы:*
• Бот понимает русский текст
• Находит дни, время и локации
• Ссылки Waze включаются в события
• Длительность по умолчанию 1.5 часа

*Поддерживаемые типы тренировок:*
🏃 Бег
🏊 Плавание  
🚴 Велосипед
🏃🏊 Бег + Плавание

Вопросы? Напиши @your_username
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def example_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show an example of the expected format"""
    example_text = """
*Пример расписания тренировок:*

```
Групповые тренировки на новую неделе:
🏃‍♀ Воскресенье, бег: техника, сила, скорость, 19:30, Бат-Ям.
Точка сбора 👉🏻 https://waze.com/ul/hsv8wn6rz1
🏊 Понедельник, плавание, 19:50 Кантри Рамат Ган.
Точка сбора 👉🏻 https://waze.com/ul/hsv8y2tvht
🏃 Вторник, интервальный бег, 19:30, парк Яркон.
```

Просто скопируй и отправь мне такое сообщение!
"""
    await update.message.reply_text(example_text, parse_mode='Markdown')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages with training schedules"""
    text = update.message.text
    
    # Parse the training message
    trainings = parse_training_message(text)
    
    if not trainings:
        await update.message.reply_text(
            "❌ Не нашёл тренировки в твоём сообщении.\n\n"
            "Убедись, что есть:\n"
            "• Дни недели (на русском)\n"
            "• Время (например 19:30)\n\n"
            "Отправь /example чтобы увидеть правильный формат."
        )
        return
    
    # Store trainings in context for later use
    context.user_data['trainings'] = trainings
    context.user_data['message_id'] = update.message.message_id
    
    # Create inline keyboard for training selection
    keyboard = []
    for i, training in enumerate(trainings):
        day_info = DAY_MAPPING.get(training.day_name.lower(), {})
        day_display = day_info.get('name_ru', training.day_name.capitalize())
        
        date_str = training.date.strftime('%d.%m')
        button_text = f"{'✅' if training.selected else '⬜'} {training.workout_type['emoji']} {day_display} {date_str} - {training.time}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{i}")])
    
    # Add action buttons
    keyboard.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all")
    ])
    keyboard.append([InlineKeyboardButton("📥 Скачать выбранные", callback_data="download")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    selected_count = sum(1 for t in trainings if t.selected)
    message_text = f"Нашёл *{len(trainings)} тренировок*! (выбрано: {selected_count})\n\nНажми для выбора:"
    
    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses"""
    query = update.callback_query
    await query.answer()
    
    trainings = context.user_data.get('trainings', [])
    if not trainings:
        await query.edit_message_text("❌ Сессия истекла. Пожалуйста, отправь расписание снова.")
        return
    
    data = query.data
    
    if data.startswith('toggle_'):
        # Toggle individual training
        index = int(data.split('_')[1])
        if 0 <= index < len(trainings):
            trainings[index].selected = not trainings[index].selected
    
    elif data == 'select_all':
        for training in trainings:
            training.selected = True
    
    elif data == 'deselect_all':
        for training in trainings:
            training.selected = False
    
    elif data == 'download':
        # Generate and send ICS files
        selected_trainings = [t for t in trainings if t.selected]
        if not selected_trainings:
            await query.message.reply_text("⚠️ Выбери хотя бы одну тренировку!")
            return
        
        await query.message.reply_text(f"📥 Создаю {len(selected_trainings)} файлов для календаря...")
        
        for training in selected_trainings:
            # Generate ICS content
            ics_content = training.to_ics()
            
            # Create file
            day_info = DAY_MAPPING.get(training.day_name.lower(), {})
            day_english = day_info.get('name', 'Training').lower()
            filename = f"{training.workout_type['name'].lower()}_{day_english}.ics"
            
            # Send as document
            file_bytes = BytesIO(ics_content.encode('utf-8'))
            file_bytes.name = filename
            
            date_str = training.date.strftime('%d %B')
            # Format month names in Russian
            months_ru = {
                'January': 'января', 'February': 'февраля', 'March': 'марта',
                'April': 'апреля', 'May': 'мая', 'June': 'июня',
                'July': 'июля', 'August': 'августа', 'September': 'сентября',
                'October': 'октября', 'November': 'ноября', 'December': 'декабря'
            }
            for en, ru in months_ru.items():
                date_str = date_str.replace(en, ru)
            
            caption = (f"{training.workout_type['emoji']} *{training.workout_type['name_ru']}*\n"
                      f"📅 {day_info.get('name_ru', 'День')}, {date_str}\n"
                      f"⏰ {training.time}\n"
                      f"📍 {training.location}")
            
            await query.message.reply_document(
                document=file_bytes,
                caption=caption,
                parse_mode='Markdown'
            )
        
        await query.message.reply_text(
            "✅ *Готово!* Открой эти файлы на устройстве для добавления в календарь.\n\n"
            "_Совет: На iPhone нажми на файл и выбери 'Добавить в Календарь'_",
            parse_mode='Markdown'
        )
        return
    
    # Update the message with new selection state
    keyboard = []
    for i, training in enumerate(trainings):
        day_info = DAY_MAPPING.get(training.day_name.lower(), {})
        day_display = day_info.get('name_ru', training.day_name.capitalize())
        
        date_str = training.date.strftime('%d.%m')
        button_text = f"{'✅' if training.selected else '⬜'} {training.workout_type['emoji']} {day_display} {date_str} - {training.time}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{i}")])
    
    keyboard.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all")
    ])
    keyboard.append([InlineKeyboardButton("📥 Скачать выбранные", callback_data="download")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    selected_count = sum(1 for t in trainings if t.selected)
    message_text = f"Нашёл *{len(trainings)} тренировок*! (выбрано: {selected_count})\n\nНажми для выбора:"
    
    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')


def main() -> None:
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("example", example_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Run the bot
    application.run_polling()


if __name__ == '__main__':
    main()
            location = location_match.group(1).strip() if location_match else 'Training location'
            
            # Extract description - everything between day/workout type and time
            before_time = line[:line.find(time)]
            # Remove day name and clean up
            desc_text = before_time
            for day_key in DAY_MAPPING.keys():
                desc_text = desc_text.replace(day_key.capitalize(), '').replace(day_key, '')
            desc_text = re.sub(r'[🏃🏊🚴🛟🏃‍♂🏊🏻‍♂️🏃‍♀]+', '', desc_text)
            desc_text = desc_text.strip(' ,:-')
            
            description = desc_text if desc_text else workout_type['name_ru']
            
            # Look for Waze link in the next line
            waze_link = ''
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                link_match = re.search(r'https://waze\.com/[^\s]+', next_line)
                if link_match:
                    waze_link = link_match.group(0)
            
            training = Training(
                day_name=day_match,
                time=time,
                workout_type=workout_type,
                description=description,
                location=location,
                waze_link=waze_link
            )
            trainings.append(training)
    
    return trainings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    welcome_message = """
🏃‍♂️ *Календарь тренировок* 🏊‍♀️

Привет! Я помогу перенести расписание тренировок из WhatsApp в твой календарь.

*Как использовать:*
1. Скопируй расписание тренировок из WhatsApp
2. Отправь его мне сообщением
3. Выбери нужные тренировки
4. Получи файлы для календаря

*Команды:*
/start - Показать это сообщение
/help - Помощь
/example - Пример формата

Просто отправь мне расписание тренировок! 🚴‍♂️
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = """
*Как пользоваться ботом:*

1. *Скопируй* всё сообщение с тренировками из WhatsApp
2. *Вставь* и отправь его мне
3. Я покажу все найденные тренировки
4. *Выбери* нужные (используй кнопки)
5. *Скачай* файлы .ics
6. *Открой* их на устройстве для добавления в календарь

*Советы:*
• Бот понимает русский текст
• Находит дни, время и локации
• Ссылки Waze включаются в события
• Длительность по умолчанию 1.5 часа

*Поддерживаемые типы тренировок:*
🏃 Бег
🏊 Плавание  
🚴 Велосипед
🏃🏊 Бег + Плавание

Вопросы? Напиши @your_username
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def example_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show an example of the expected format"""
    example_text = """
*Пример расписания тренировок:*

```
Групповые тренировки на новую неделе:
🏃‍♀ Воскресенье, бег: техника, сила, скорость, 19:30, Бат-Ям.
Точка сбора 👉🏻 https://waze.com/ul/hsv8wn6rz1
🏊 Понедельник, плавание, 19:50 Кантри Рамат Ган.
Точка сбора 👉🏻 https://waze.com/ul/hsv8y2tvht
🏃 Вторник, интервальный бег, 19:30, парк Яркон.
```

Просто скопируй и отправь мне такое сообщение!
"""
    await update.message.reply_text(example_text, parse_mode='Markdown')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages with training schedules"""
    text = update.message.text
    
    # Parse the training message
    trainings = parse_training_message(text)
    
    if not trainings:
        await update.message.reply_text(
            "❌ Не нашёл тренировки в твоём сообщении.\n\n"
            "Убедись, что есть:\n"
            "• Дни недели (на русском)\n"
            "• Время (например 19:30)\n\n"
            "Отправь /example чтобы увидеть правильный формат."
        )
        return
    
    # Store trainings in context for later use
    context.user_data['trainings'] = trainings
    context.user_data['message_id'] = update.message.message_id
    
    # Create inline keyboard for training selection
    keyboard = []
    for i, training in enumerate(trainings):
        day_info = DAY_MAPPING.get(training.day_name.lower(), {})
        day_display = day_info.get('name_ru', training.day_name.capitalize())
        
        date_str = training.date.strftime('%d.%m')
        button_text = f"{'✅' if training.selected else '⬜'} {training.workout_type['emoji']} {day_display} {date_str} - {training.time}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{i}")])
    
    # Add action buttons
    keyboard.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all")
    ])
    keyboard.append([InlineKeyboardButton("📥 Скачать выбранные", callback_data="download")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    selected_count = sum(1 for t in trainings if t.selected)
    message_text = f"Нашёл *{len(trainings)} тренировок*! (выбрано: {selected_count})\n\nНажми для выбора:"
    
    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses"""
    query = update.callback_query
    await query.answer()
    
    trainings = context.user_data.get('trainings', [])
    if not trainings:
        await query.edit_message_text("❌ Сессия истекла. Пожалуйста, отправь расписание снова.")
        return
    
    data = query.data
    
    if data.startswith('toggle_'):
        # Toggle individual training
        index = int(data.split('_')[1])
        if 0 <= index < len(trainings):
            trainings[index].selected = not trainings[index].selected
    
    elif data == 'select_all':
        for training in trainings:
            training.selected = True
    
    elif data == 'deselect_all':
        for training in trainings:
            training.selected = False
    
    elif data == 'download':
        # Generate and send ICS files
        selected_trainings = [t for t in trainings if t.selected]
        if not selected_trainings:
            await query.message.reply_text("⚠️ Выбери хотя бы одну тренировку!")
            return
        
        await query.message.reply_text(f"📥 Создаю {len(selected_trainings)} файлов для календаря...")
        
        for training in selected_trainings:
            # Generate ICS content
            ics_content = training.to_ics()
            
            # Create file
            day_info = DAY_MAPPING.get(training.day_name.lower(), {})
            day_english = day_info.get('name', 'Training').lower()
            filename = f"{training.workout_type['name'].lower()}_{day_english}.ics"
            
            # Send as document
            file_bytes = BytesIO(ics_content.encode('utf-8'))
            file_bytes.name = filename
            
            date_str = training.date.strftime('%d %B')
            # Format month names in Russian
            months_ru = {
                'January': 'января', 'February': 'февраля', 'March': 'марта',
                'April': 'апреля', 'May': 'мая', 'June': 'июня',
                'July': 'июля', 'August': 'августа', 'September': 'сентября',
                'October': 'октября', 'November': 'ноября', 'December': 'декабря'
            }
            for en, ru in months_ru.items():
                date_str = date_str.replace(en, ru)
            
            caption = (f"{training.workout_type['emoji']} *{training.workout_type['name_ru']}*\n"
                      f"📅 {day_info.get('name_ru', 'День')}, {date_str}\n"
                      f"⏰ {training.time}\n"
                      f"📍 {training.location}")
            
            await query.message.reply_document(
                document=file_bytes,
                caption=caption,
                parse_mode='Markdown'
            )
        
        await query.message.reply_text(
            "✅ *Готово!* Открой эти файлы на устройстве для добавления в календарь.\n\n"
            "_Совет: На iPhone нажми на файл и выбери 'Добавить в Календарь'_",
            parse_mode='Markdown'
        )
        return
    
    # Update the message with new selection state
    keyboard = []
    for i, training in enumerate(trainings):
        day_info = DAY_MAPPING.get(training.day_name.lower(), {})
        day_display = day_info.get('name_ru', training.day_name.capitalize())
        
        date_str = training.date.strftime('%d.%m')
        button_text = f"{'✅' if training.selected else '⬜'} {training.workout_type['emoji']} {day_display} {date_str} - {training.time}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{i}")])
    
    keyboard.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="select_all"),
        InlineKeyboardButton("❌ Убрать всё", callback_data="deselect_all")
    ])
    keyboard.append([InlineKeyboardButton("📥 Скачать выбранные", callback_data="download")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    selected_count = sum(1 for t in trainings if t.selected)
    message_text = f"Нашёл *{len(trainings)} тренировок*! (выбрано: {selected_count})\n\nНажми для выбора:"
    
    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')


def main() -> None:
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("example", example_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Run the bot
    application.run_polling()


if __name__ == '__main__':
    main()
