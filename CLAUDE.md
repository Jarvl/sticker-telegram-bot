# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Telegram bot that allows group chats to curate sticker packs by replying to media with the `/sticker` command. The bot supports both polling and webhook modes.

## Development Commands

### Setup and Installation
```bash
poetry install              # Install dependencies
make setup                  # Initial setup with pyenv check
make check-config           # Validate configuration only
make migrate                # Run database migrations
```

### Running the Bot
```bash
make run                    # Run bot in mode specified by MODE env variable
poetry run python -m sticker_telegram_bot.main --config-check  # Config check only
```

### Code Quality
```bash
make format                 # Format code with black (line-length 88)
make lint                   # Run flake8 linter
poetry run black .          # Format code directly
poetry run flake8 .         # Lint directly
```

### Docker
```bash
make docker-build           # Build Docker image
make docker-run             # Run with Docker Compose
make docker-stop            # Stop containers
make logs                   # View Docker logs
```

### Cleanup
```bash
make clean                  # Clean Python cache and logs
```

## Architecture

### Core Components

**sticker_telegram_bot/config.py**
- Centralized configuration using environment variables
- Uses pydantic-like validation with `Config.validate()` class method
- All config is loaded from `.env` file via python-dotenv
- Requires `DATABASE_URL` for Postgres-backed group sticker pack records

**sticker_telegram_bot/bot.py**
- Main `StickerBot` class containing all bot logic
- Uses python-telegram-bot v22.7 with async/await patterns
- Global singleton instance: `bot = StickerBot()`
- `/manage` and `/sticker` are registered through a `ConversationHandler` with `concurrent_updates(False)`

**sticker_telegram_bot/db/**
- SQLAlchemy 2.x async ORM models, session setup, and repository methods
- `sticker_packs` stores bot-created group packs with denormalized `chat_id` and `is_visible`
- Sticker pack records are unique per `(telegram_name, chat_id)` so the same bot-managed pack can be imported into multiple groups

**sticker_telegram_bot/main.py**
- Entry point that validates config and starts bot in appropriate mode
- Supports `--config-check` flag for configuration validation
- Mode selection based on `Config.MODE` environment variable

### Bot Workflow

1. **Media Submission Flow** (Images, animations, and Telegram stickers):
   - User replies to an image/GIF/Telegram sticker with `/sticker` in a group chat. Telegram sticker messages use `message.sticker` (static WEBP or video WEBM); animated TGS stickers are rejected with a clear message.
   - Bot extracts `file_id` (and duration for GIF animations; video stickers use duration `0` unless extended later) and stores transient flow data in `context.user_data` scoped by chat
   - Optional `suggested_emoji` from the source sticker is stored for UX hints
   - Bot prompts user for emoji (📸 for images, 🎬 for animations)
   - User sends emoji response (validated with `emoji.is_emoji()`)
   - Bot presents inline keyboard with visible group sticker packs plus a create-pack option
   - User selects pack via callback query, or creates a new pack using the pending sticker as the first sticker
   - Bot processes media:
     - **Images**: resize to 512x512, RGBA, centered on transparent canvas
     - **Animations**: convert to WEBM VP9 (see Video Processing below)
   - Bot adds sticker to the selected bot-created group pack with appropriate sticker format ("static" or "video")

2. **State Management**:
   - `ConversationHandler(per_chat=True, per_user=True)` manages `/manage` and `/sticker`
   - Transient state is stored in `context.user_data["chat_flows"][chat_id]`
   - Use `/cancel` command to clear pending state and end the conversation

3. **Animation Detection**:
   - Telegram auto-converts GIFs to MP4 animations (`message.animation`)
   - `filters.ANIMATION` catches GIF uploads
   - Animations handled separately from images with dedicated handler
   - Duration extracted from animation metadata for processing

4. **Group Pack Management**:
   - `/manage` shows inline buttons for listing packs, creating a new empty pack, and importing an existing bot-managed pack from one of its stickers
   - Pack detail views include Show/Hide toggle and Back navigation
   - Empty pack creation uses a generated white placeholder sticker, records the pack after Telegram claims the name, then removes the placeholder best-effort
   - Imported pack names are read from `message.sticker.set_name`, must end with `_by_<bot username>`, and are stored as visible for the importing group

5. **Callback Data Format**:
   - Manage callbacks use compact forms like `mg:home`, `mg:list`, `mg:pack:{id}`, `mg:toggle:{id}`, `mg:create`, `mg:import`
   - Sticker callbacks use compact forms like `st:add:{id}` and `st:create`

### Media Processing

**Images** are processed in `process_image_for_sticker()`:
- Convert to RGBA mode
- Resize maintaining aspect ratio (max 512px on any side)
- Center on 512x512 transparent canvas using PIL
- Output as PNG bytes

**Animations** are processed in `process_video_for_sticker()`:
- Uses ffmpeg directly via subprocess; seekable input via a short-lived temp file, WEBM output on stdout
- Conversion specs:
  - Codec: VP9 (libvpx-vp9)
  - Resolution: 512px on longest side with even dimensions via scale filter
  - FPS: 30 constant via fps filter
  - Audio: stripped with `-an`
  - Duration: if >3s, speeds up video using setpts filter
  - Quality: CRF 30 with constant quality mode
- Filter chain: `setpts` (optional), `scale`, `pad`, `fps` combined with `,`.join()
- File size validation: rejects if >256KB
- Error handling via process.returncode and stderr

### Sticker Pack Naming

Sticker set names generated by `_make_group_sticker_set_name()`:
- Sanitizes title (removes special chars, collapses spaces to underscores)
- Format: `{cleaned_title}_{abs_chat_id}_by_{bot_username}`
- Must start with a letter per Telegram requirements

## Configuration

Required environment variables:
- `TELEGRAM_BOT_TOKEN`: Bot token from @BotFather
- `TELEGRAM_BOT_USERNAME`: Bot username (without @)
- `DATABASE_URL`: Postgres connection string using `postgresql+psycopg://`

Optional environment variables:
- `MODE`: "polling" or "webhook" (default: polling)
- `API_HOST`: Host for API server (default: 0.0.0.0)
- `API_PORT`: Port for API server (default: 8000)
- `WEBHOOK_URL`: Required if MODE=webhook

**Important**: Run Alembic migrations before starting the bot in a fresh database.

## Python Version

- Requires Python 3.11+ (specified in pyproject.toml)
- Project uses pyenv with version in `.python-version` file
- Managed with Poetry for dependencies

## Key Dependencies
- System `ffmpeg`: Video processing via subprocess pipes (no Python wrapper)
- PostgreSQL plus SQLAlchemy/psycopg/Alembic for persistence

## Notes for Development

- All bot message handlers are async functions using `async def`
- The bot uses a global singleton pattern: modifications to `StickerBot` affect the global `bot` instance
- Error messages use emojis and friendly language (e.g., "🗿 Hey that's a nice sticker suggestion...")
- HTML formatting is used in success messages with fallback to plain text if parsing fails
- Logging is configured at INFO level with timestamp, name, level, and message format
- FFmpeg must be installed on the system for animated sticker support (installed in Dockerfile)
- Video processing uses ffmpeg subprocess with a temp input file and stdout for WEBM output
