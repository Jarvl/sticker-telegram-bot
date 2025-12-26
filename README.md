# Telegram Sticker Bot

A powerful Telegram bot that allows users to easily add images to configured sticker packs by replying to images with the "sticker" command. The bot can be hosted as a standalone API service.

## Features

- ✅ **Group Chat Support**: Works in both private chats and group conversations
- ✅ **Image to Sticker Conversion**: Reply to any image with "sticker" to add it to a pack
- ✅ **Animated Sticker Support**: Convert GIFs to animated stickers (WEBM VP9 format)
- ✅ **Multiple Sticker Packs**: Configure multiple sticker packs via environment variables
- ✅ **Media Processing**: Automatically processes images and animations to meet Telegram's sticker requirements
- ✅ **Interactive Selection**: Users can choose which sticker pack to add images to
- ✅ **Webhook Support**: Supports both polling and webhook modes

## Requirements

- Python 3.11+ (managed with pyenv)
- [Poetry](https://python-poetry.org/) for dependency management
- [FFmpeg](https://ffmpeg.org/) for animated sticker conversion
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- At least one sticker pack configured

## Installation

### Prerequisites

1. **Install pyenv** (if not already installed):
   ```bash
   # On macOS
   brew install pyenv
   
   # On Ubuntu/Debian
   curl https://pyenv.run | bash
   
   # On Windows (using WSL or Git Bash)
   curl https://pyenv.run | bash
   ```

2. **Add pyenv to your shell** (add to `~/.bashrc`, `~/.zshrc`, etc.):
   ```bash
   export PYENV_ROOT="$HOME/.pyenv"
   export PATH="$PYENV_ROOT/bin:$PATH"
   eval "$(pyenv init --path)"
   eval "$(pyenv init -)"
   ```

3. **Install Poetry** (if not already installed):
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   # Or see https://python-poetry.org/docs/#installation for details
   ```

### Project Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd sticker-telegram-bot
   ```

2. **Install the required Python version:**
   ```bash
   pyenv install 3.11.4
   pyenv local 3.11.4
   ```

3. **Install FFmpeg:**
   ```bash
   # On macOS
   brew install ffmpeg

   # On Ubuntu/Debian
   sudo apt-get install ffmpeg

   # On Windows (using Chocolatey)
   choco install ffmpeg
   ```

4. **Install dependencies with Poetry:**
   ```bash
   poetry install
   ```

5. **Set up environment variables:**
   - Copy and edit your `.env` file as needed (see below for required variables).

## Configuration

### Required Environment Variables

- `TELEGRAM_BOT_TOKEN`: Your bot token from [@BotFather](https://t.me/BotFather)
- `TELEGRAM_BOT_USERNAME`: Your bot's username (without @)
- `STICKER_PACKS`: Comma-separated list of sticker pack names
- `STICKER_PACK_OWNER_USER_ID`: The Telegram user ID (integer) that owns the sticker packs

### Optional Environment Variables

- `API_HOST`: Host for the API server (default: 0.0.0.0)
- `API_PORT`: Port for the API server (default: 8000)
- `WEBHOOK_URL`: Webhook URL for webhook mode
- `MODE`: `polling` or `webhook` (default: polling)

**Note:**
- When using Kubernetes secrets or other orchestrators, ensure that environment variables are set as plain strings with no extra whitespace or newlines. If you encounter `ValueError: invalid literal for int() with base 10`, check your secret formatting and consider using `.strip()` in your config code.

## Usage

### Running the Bot

The bot can be run in either polling or webhook mode, as defined by the `MODE` environment variable in your `.env` file.

#### 1. Set the mode in your .env file
Add or update the following line in your `.env`:
```env
MODE=polling  # or 'webhook'
```

#### 2. Start the bot
```bash
make run
```
This will start the bot in the mode specified by `MODE` in your environment.

### Available Make Commands

```bash
make help          # Show all available commands
make setup         # Initial setup (install deps, check config)
make install       # Install dependencies
make run           # Run bot (mode is set via MODE env variable)
make clean         # Clean up Python cache and logs
make check-config  # Validate configuration only
make format        # Format code with black
make lint          # Run flake8 linter
```

### Using the Bot

1. **Add the bot to a group or start a private chat**
2. **Send an image or GIF to the chat**
3. **Reply to the image/GIF with the command `sticker`** (or send directly in allowed chats)
4. **Send an emoji for the sticker** (e.g., 🗿, 🔫, 💩)
5. **Select which sticker pack to add it to**
6. **The media will be processed and added to your chosen pack**

### Bot Commands

- `/start` - Welcome message and basic instructions
- `/help` - Detailed help and available sticker packs
- `/sticker` - Reply to an image or GIF to add it to a sticker pack
- `/cancel` - Cancel any pending sticker request

### Animated Sticker Notes

- GIFs are automatically converted to WEBM VP9 format
- If a GIF is longer than 3 seconds, it will be sped up to fit the requirement
- Maximum file size after conversion: 256 KB
- If a GIF cannot be compressed enough, it will be rejected

## Docker Support

You can also run the bot using Docker with the Makefile:

```bash
# Build the image
make docker-build

# Run with Docker Compose
make docker-run

# Stop containers
make docker-stop

# View logs
make logs
```

Or manually:
```bash
# Build the image
docker build -t telegram-sticker-bot .

# Run the container
docker run -d \
  --name sticker-bot \
  -p 8000:8000 \
  --env-file .env \
  telegram-sticker-bot
```
