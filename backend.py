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

# Настройка логов для панели Render
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    login: str
    password: str

class ScheduleRequest(BaseModel):
    token: str
    week: int
    year: int

class ChatRequest(BaseModel):
    message: str
    bot_type: str

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_time_by_para(para_num):
    times = {"1": "08:30 - 10:00", "2": "10:10 - 11:40", "3": "11:50 - 13:20", "4": "14:00 - 15:30",
             "5": "15:40 - 17:10", "6": "17:20 - 18:50", "7": "19:00 - 20:30", "8": "20:40 - 22:10"}
    return times.get(str(para_num), "??:??")

def clean_group_name(text):
    if not text: return "Студент"
    match = re.search(r'([А-ЯA-Z]{1,6}/[а-яa-z]{1,2}-\d{2}-\d-?[а-яa-z]?)', text)
    return match.group(1) if match else text.strip()

def get_date_for_iso_week(year, week):
    try:
        d = datetime.date(year, 1, 4)
        start_of_week1 = d - datetime.timedelta(days=d.isoweekday() - 1)
        return start_of_week1 + datetime.timedelta(weeks=week - 1)
    except: return None

# --- ЛОГИКА ВХОДА ---

def selenium_full_login(username, password):
    logger.info(f"==> Запуск Selenium для {username}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    if os.path.exists("/usr/bin/google-chrome"):
        options.binary_location = "/usr/bin/google-chrome"
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        logger.info("==> Открываю страницу расписания...")
        driver.get("https://timetable.sevsu.ru/timetablestudent")
        
        # Ожидание загрузки формы (критический момент для облака)
        wait = WebDriverWait(driver, 20)
        try:
            user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            pass_field = driver.find_element(By.NAME, "password")
            logger.info("==> Форма найдена, ввожу данные...")
            
            user_field.send_keys(username)
            pass_field.send_keys(password)
            driver.find_element(By.ID, "kc-login").click()
            
            # Ждем появления куки или перехода
            wait.until(EC.url_contains("timetablestudent"))
            time.sleep(2)
            
            for c in driver.get_cookies():
                if c['name'] == 'session':
                    logger.info("✅ Сессия получена успешно!")
                    return c['value']
        except Exception as e:
            logger.error(f"❌ Ошибка на этапе ввода/ожидания: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка драйвера: {str(e)}")
        return None
    finally:
        if driver: driver.quit()

@app.post("/api/login")
def login(creds: LoginRequest):
    token = selenium_full_login(creds.login, creds.password)
    
    if token:
        # Возвращаем заглушку профиля, так как главное - токен расписания
        user_data = {
            "fio": creds.login,
            "group": "Студент СевГУ",
            "course": "-",
            "rating": 0,
            "avatar_initials": creds.login[:2].upper()
        }
        return {"user": user_data, "token": token}
    
    # ВАЖНО: Теперь возвращаем 401 ошибку, чтобы фронтенд ее видел
    raise HTTPException(
        status_code=401, 
        detail="Университет отклонил вход. Проверьте логин/пароль или попробуйте позже (возможно блокировка сервера)."
    )

@app.post("/api/schedule")
def get_schedule(req: ScheduleRequest):
    payload = {"session": req.token, "week": req.week, "year": req.year, "semestr": "24-25"}
    headers = {'Content-Type': 'application/json', 'Cookie': f'session={req.token}'}
    try:
        resp = requests.post(TIMETABLE_API, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            # Тут вызываем ваш парсер (упрощенно для примера)
            data = resp.json()
            return {"schedule": []} # Сюда нужно вставить вашу функцию parse_schedule_api
        raise HTTPException(status_code=401)
    except: raise HTTPException(status_code=500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
