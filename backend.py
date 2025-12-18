import os
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import datetime
import uvicorn
import re
import time
import json
import logging

# Настройка логов для панели Amvera
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = FastAPI()

# Настройка CORS, чтобы мобильное приложение могло подключаться
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- МОДЕЛИ ДАННЫХ ---
class LoginRequest(BaseModel):
    login: str
    password: str

class ScheduleRequest(BaseModel):
    token: str
    week: int
    year: int

# --- ГЛАВНАЯ СТРАНИЦА (Чтобы не было Page Not Found) ---
@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Сервер СевГУ успешно запущен в Amvera!",
        "time": datetime.datetime.now().isoformat()
    }

# --- ЛОГИКА SELENIUM ---
def selenium_full_login(username, password):
    logger.info(f"==> Попытка входа для {username}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    if os.path.exists("/usr/bin/google-chrome"):
        options.binary_location = "/usr/bin/google-chrome"
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.get("https://timetable.sevsu.ru/timetablestudent")
        
        wait = WebDriverWait(driver, 20)
        user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_field = driver.find_element(By.NAME, "password")
        
        user_field.send_keys(username)
        pass_field.send_keys(password)
        driver.find_element(By.ID, "kc-login").click()
        
        wait.until(EC.url_contains("timetablestudent"))
        time.sleep(2)
        
        for c in driver.get_cookies():
            if c['name'] == 'session':
                logger.info("✅ Сессия получена!")
                return c['value']
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка входа: {str(e)}")
        return None
    finally:
        if driver: driver.quit()

# --- ЭНДПОИНТЫ API ---
@app.post("/api/login")
def login(creds: LoginRequest):
    token = selenium_full_login(creds.login, creds.password)
    if token:
        user_data = {
            "fio": creds.login,
            "group": "Студент СевГУ",
            "avatar_initials": creds.login[:2].upper()
        }
        return {"user": user_data, "token": token}
    
    raise HTTPException(status_code=401, detail="Неверный логин или пароль")

@app.post("/api/schedule")
def get_schedule(req: ScheduleRequest):
    # Здесь должна быть ваша логика парсинга расписания (timetable.html)
    # Для теста возвращаем пустой массив
    return {"schedule": []}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
