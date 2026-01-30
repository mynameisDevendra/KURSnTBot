# Use a lightweight Python version
FROM python:3.11-slim

# 1. Install System Dependencies (This fixes the Image Error!)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    git \
    && rm -rf /var/lib/apt/lists/*

# 2. Set up the App
WORKDIR /app
COPY . /app

# 3. Install Python Libraries
RUN pip install --no-cache-dir -r requirements.txt

# 4. Start the Bot
CMD ["python", "bot.py"]