#!/bin/bash

# Force-install the cpu version of faiss to prevent memory crashes
pip install faiss-cpu --no-cache-dir

# Start the Bot
echo "🚀 Starting Bot (Dedicated Mode)..."
python bot.py