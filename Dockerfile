FROM python:3.11-slim

# 1. Install System Dependencies (Poppler + Git)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy requirements first (Better caching)
COPY requirements.txt .

# 3. Install Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of the code
COPY . .

# 5. EXPOSE the port (Render uses 10000 usually, but Streamlit needs to be told)
EXPOSE 8501

# 6. START COMMAND
# We use 'sh -c' to pass the PORT variable correctly to Streamlit
# Give permission to run the script
RUN chmod +x start.sh

# The New Entry Point
CMD ["sh", "start.sh"]