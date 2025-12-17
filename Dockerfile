FROM python:3.9-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    ca-certificates \
    --no-install-recommends && \
    # Добавление репозитория Google Chrome
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/googlechrome-linux-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-linux-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    # Обновление и установка Chrome + минимальных библиотек для Selenium
    # Убран libgconf-2-4, так как он более не поддерживается в новых дистрибутивах
    apt-get update && apt-get install -y \
    google-chrome-stable \
    libnss3 \
    libfontconfig1 \
    libgbm1 \
    libasound2 \
    --no-install-recommends && \
    # Очистка кэша для уменьшения размера образа
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Настройка порта для Render
ENV PORT=8000
EXPOSE 8000

# Запуск приложения
CMD ["python", "backend.py"]

