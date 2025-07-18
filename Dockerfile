FROM python:3.11-slim

# Install Poetry
RUN pip install --no-cache-dir poetry

# Disable Poetry virtualenvs (use system site-packages)
ENV POETRY_VIRTUALENVS_CREATE=false

# Set workdir
WORKDIR /app

# Copy only dependency files first for better caching
COPY pyproject.toml poetry.lock ./

# Install dependencies (no dev dependencies for production)
RUN poetry install --no-interaction --no-ansi --no-root --only main

# Now copy the rest of the code
COPY . .

# Run the bot (adjust as needed)
CMD ["python", "-m", "sticker_telegram_bot.main"]