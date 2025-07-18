# Telegram Sticker Bot

A powerful Telegram bot that allows users to easily add images to configured sticker packs by replying to images with the "sticker" command. The bot can be hosted as a standalone API service.

## Features

- ✅ **Group Chat Support**: Works in both private chats and group conversations
- ✅ **Image to Sticker Conversion**: Reply to any image with "sticker" to add it to a pack
- ✅ **Multiple Sticker Packs**: Configure multiple sticker packs via environment variables
- ✅ **Image Processing**: Automatically processes images to meet Telegram's sticker requirements
- ✅ **Interactive Selection**: Users can choose which sticker pack to add images to
- ✅ **Webhook Support**: Supports both polling and webhook modes

## Requirements

- Python 3.11+ (managed with pyenv)
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

### Project Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd telegram-sticker-bot
   ```

2. **Install the required Python version:**
   ```bash
   pyenv install 3.11.4
   pyenv local 3.11.4
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your configuration:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_BOT_USERNAME=your_bot_username
   STICKER_PACKS=my_pack,funny_memes,work_stickers
   API_HOST=0.0.0.0
   API_PORT=8000
   MODE=polling  # or 'webhook'
   ```

4. **Run the setup (automatically installs dependencies):**
   ```bash
   make setup
   ```

## Configuration

### Required Environment Variables

- `TELEGRAM_BOT_TOKEN`: Your bot token from [@BotFather](https://t.me/BotFather)
- `TELEGRAM_BOT_USERNAME`: Your bot's username (without @)
- `STICKER_PACKS`: Comma-separated list of sticker pack names

### Optional Environment Variables

- `API_HOST`: Host for the API server (default: 0.0.0.0)
- `API_PORT`: Port for the API server (default: 8000)
- `WEBHOOK_URL`: Webhook URL for webhook mode

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
make setup         # Initial setup (create venv, install deps, check config)
make install       # Install dependencies
make run           # Run bot (mode is set via MODE env variable)
make clean         # Clean up Python cache and logs
make check-config  # Validate configuration only
```

### Using the Bot

1. **Add the bot to a group or start a private chat**
2. **Send an image to the chat**
3. **Reply to the image with the command `sticker`**
4. **Select which sticker pack to add the image to**
5. **The image will be processed and added to your chosen pack**

### Bot Commands

- `/start` - Welcome message and basic instructions
- `/help` - Detailed help and available sticker packs
- `/sticker <emoji>` - Reply to an image with an emoji to add it to a sticker pack

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
