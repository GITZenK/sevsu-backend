FROM python:3.9-slim

# Установка системных зависимостей для Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    ca-certificates \
    --no-install-recommends && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/googlechrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y \
    google-chrome-stable \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Принудительно выводим логи Python в консоль Amvera
ENV PYTHONUNBUFFERED=1

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Amvera ожидает порт 80 или 8000. Мы зафиксируем 8000.
ENV PORT=8000
EXPOSE 8000

# Запускаем через uvicorn напрямую, чтобы избежать проблем с именами файлов
CMD ["uvicorn", "backend.py:app", "--host", "0.0.0.0", "--port", "8000"]
