# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

A Telegram bot that parses Russian-language workout schedules (typically from WhatsApp) and converts them to:
- ICS calendar files for download
- Google Calendar direct-add links

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot locally (requires BOT_TOKEN env var)
export BOT_TOKEN="your_telegram_bot_token"
python training_bot.py

# Run tests (if requirements-dev.txt exists)
pip install -r requirements-dev.txt
pytest

# Linting and formatting
black .
isort .
mypy training_bot.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram Bot API token from @BotFather |
| `LOG_LEVEL` | No | Logging level (INFO, DEBUG) |

## Architecture

Single-file application (`training_bot.py`) with these core components:

### Data Model
- `Training` class (line ~47): Represents a parsed workout session
  - Stores day, time, workout type, description, location, waze link
  - `_calc_date()`: Calculates the next occurrence of the specified weekday
  - `to_ics()`: Generates ICS calendar format
  - `to_google_calendar_url()`: Generates Google Calendar add-event URL

### Parser
- `parse_training_message()` (line ~133): Regex-based text parser
  - Strips leading emojis and identifies Russian day names
  - Extracts time (HH:MM format), looks on next line if not found
  - Detects workout type from keywords (`бег`, `плавание`, `вело`) or emojis
  - Parses location and Waze links from subsequent lines

### Telegram Handlers
- `start()`, `example()`: Command handlers for /start and /example
- `handle_message()`: Main message handler, parses text and shows selection UI
- `button_callback()`: Handles inline keyboard interactions (toggle, select/deselect all, download, google_calendar)

### Supported Workout Types
```python
WORKOUT_TYPES = {
    "бег":      {"emoji": "🏃", "name": "Running"},
    "плавание": {"emoji": "🏊", "name": "Swimming"},
    "вело":     {"emoji": "🚴", "name": "Cycling"},
}
```
Also supports combination: `бег + море` → "Run+Swim"

## Deployment

Configured for Railway (`railway.json`):
- Uses Nixpacks builder
- Start command: `python training_bot.py`

## Key Implementation Details

- **Timezone**: Uses server's local time; all dates calculated relative to `datetime.now()`
- **Date calculation**: Workouts always scheduled for next occurrence of that weekday
- **ICS duration**: Hardcoded to 1.5 hours
- **Russian month names**: Manually mapped in English-to-Russian dictionary within handlers
- **Session state**: Training selections stored in `context.user_data["trainings"]`
