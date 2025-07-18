# Telegram Sticker Bot Makefile
# Cross-platform commands for managing the bot

.PHONY: help install setup run clean docker-build docker-run docker-stop logs check-config format

# Default target
help:
	@echo "Telegram Sticker Bot - Available Commands:"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make setup      - Initial setup (create venv, install deps, check config)"
	@echo "  make install    - Install dependencies"
	@echo "  make check-config- Validate configuration only"
	@echo ""
	@echo "Running the Bot:"
	@echo "  make run        - Run bot (mode is set via MODE env variable)"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-run   - Run with Docker Compose"
	@echo "  make docker-stop  - Stop Docker containers"
	@echo "  make logs        - View logs (if using Docker)"
	@echo ""
	@echo "Development Commands:"
	@echo "  make dev-install - Install development dependencies"
	@echo "  make format      - Format code with black"
	@echo "  make lint        - Run linter (flake8)"
	@echo ""
	@echo "Utility Commands:"
	@echo "  make clean       - Clean up Python cache and logs"
	@echo ""
	@echo "Examples:"
	@echo "  make setup       # First time setup"
	@echo "  make run         # Start the bot"
	@echo "  make docker-run  # Run with Docker"

# Check if .env file exists
check-env:
	@if [ ! -f .env ]; then \
		echo "Error: .env file not found!"; \
		echo "Please copy .env.example to .env and configure your settings:"; \
		echo "  cp .env.example .env"; \
		echo "  # Edit .env with your bot token and settings"; \
		exit 1; \
	fi

# Check if pyenv is available
check-pyenv:
	@if ! command -v pyenv > /dev/null 2>&1; then \
		echo "Error: pyenv is not installed!"; \
		echo "Please install pyenv first:"; \
		echo "  curl https://pyenv.run | bash"; \
		echo "  # Then add to your shell profile and restart your terminal"; \
		exit 1; \
	fi

# Check if Python is available
check-python:
	@python3 --version > /dev/null 2>&1 || python --version > /dev/null 2>&1 || (echo "Error: Python is not installed!" && exit 1)

# Check if correct Python version is installed via pyenv
check-python-version:
	@if [ -f .python-version ]; then \
		REQUIRED_VERSION=$$(cat .python-version); \
		if ! pyenv versions | grep -q "$$REQUIRED_VERSION"; then \
			echo "Error: Python version $$REQUIRED_VERSION is not installed via pyenv!"; \
			echo "Please install it with: pyenv install $$REQUIRED_VERSION"; \
			exit 1; \
		fi; \
	fi

# Setup virtual environment
setup-venv:
	@if [ ! -d venv ]; then \
		echo "Creating virtual environment..."; \
		python3 -m venv venv 2>/dev/null || python -m venv venv; \
	fi

# Activate virtual environment (cross-platform)
activate-venv:
	@if [ -f venv/bin/activate ]; then \
		. venv/bin/activate; \
	elif [ -f venv/Scripts/activate ]; then \
		. venv/Scripts/activate; \
	fi

# Initial setup
setup: check-env pyenv-setup check-python-version check-python install
	@echo "✅ Setup completed successfully!"
	@echo "You can now run the bot with: make run"

# Install dependencies
install:
	@echo "Installing dependencies..."
	@poetry install

# Check configuration only
check-config: check-env
	@echo "Validating configuration..."
	@poetry run python -m sticker_telegram_bot.main --config-check

# Run bot in API mode (default)
run: check-env install
	@echo "Starting Telegram Sticker Bot..."
	@echo "Mode: $$MODE (set in your .env file)"
	@echo "Press Ctrl+C to stop the bot"
	@echo ""
	@poetry run python -m sticker_telegram_bot.main

# Docker commands
docker-build:
	@echo "Building Docker image..."
	docker build -t telegram-sticker-bot .

docker-run: check-env
	@echo "Starting Telegram Sticker Bot with Docker Compose..."
	@echo "The bot will be available at http://localhost:8000"
	@echo "Press Ctrl+C to stop the containers"
	@echo ""
	docker-compose up

docker-stop:
	@echo "Stopping Docker containers..."
	docker-compose down

# View logs (Docker)
logs:
	@echo "Viewing Docker logs..."
	docker-compose logs -f

# Clean up
clean:
	@echo "Cleaning up..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@find . -name "*.pyo" -delete 2>/dev/null || true
	@find . -name "*.pyd" -delete 2>/dev/null || true
	@find . -name ".coverage" -delete 2>/dev/null || true
	@find . -name "*.log" -delete 2>/dev/null || true
	@rm -rf logs/ 2>/dev/null || true
	@echo "✅ Cleanup completed"

# Development helpers
dev-install: install
	@echo "Installing development dependencies..."
	@poetry add black flake8 pytest

format:
	poetry run black .

lint:
	@echo "Running linter..."
	@poetry run flake8 .

# Pyenv setup
pyenv-setup: check-pyenv
	@echo "Setting up Python version via pyenv..."
	@if [ -f .python-version ]; then \
		REQUIRED_VERSION=$$(cat .python-version); \
		echo "Installing Python $$REQUIRED_VERSION..."; \
		pyenv install $$REQUIRED_VERSION; \
		echo "Setting local Python version to $$REQUIRED_VERSION..."; \
		pyenv local $$REQUIRED_VERSION; \
		echo "✅ Python $$REQUIRED_VERSION is now active for this project"; \
	else \
		echo "Error: .python-version file not found!"; \
		exit 1; \
	fi 