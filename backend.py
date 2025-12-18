import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import datetime
import uvicorn
import re
import time

# --- ВАЖНО: ВЫВОД ВЕРСИИ В ЛОГИ ---
print("------------------------------------------------")
print("ЗАПУСК НОВОЙ ВЕРСИИ КОДА (v2.0)")
print("Если вы видите это, значит код обновился!")
print("------------------------------------------------")

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

# --- ГЛАВНАЯ СТРАНИЦА ---
@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Сервер работает!",
        "time": datetime.datetime.now().isoformat()
    }

# --- ИСПРАВЛЕННЫЙ ВХОД ЧЕРЕЗ SELENIUM ---
def selenium_full_login(username, password):
    logger.info(f"==> Вход для {username}")
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
        
        wait = WebDriverWait(driver, 25)
        user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        user_field.send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.ID, "kc-login").click()
        
        wait.until(EC.url_contains("timetablestudent"))
        
        for c in driver.get_cookies():
            if c['name'] == 'session': return c['value']
        return None
    except Exception as e:
        logger.error(f"Ошибка входа: {e}")
        return None
    finally:
        if driver: driver.quit()

# --- ENDPOINTS ---
@app.post("/api/login")
def login(creds: LoginRequest):
    token = selenium_full_login(creds.login, creds.password)
    if token:
        return {
            "user": {"fio": creds.login, "group": "Студент", "avatar_initials": "ST"},
            "token": token
        }
    raise HTTPException(status_code=401, detail="Неверный логин")

@app.post("/api/schedule")
def get_schedule(req: ScheduleRequest):
    # Упрощенная логика для теста связи
    payload = {"session": req.token, "week": req.week, "year": req.year, "semestr": "24-25"}
    headers = {'Content-Type': 'application/json', 'Cookie': f'session={req.token}'}
    try:
        r = requests.post("https://timetable.sevsu.ru/napi/StudentsRaspGet", json=payload, headers=headers)
        if r.status_code == 200:
            # Возвращаем сырые данные, чтобы проверить связь
            return {"schedule": [], "raw": "Связь есть!"} 
        raise HTTPException(status_code=401)
    except: raise HTTPException(status_code=500)

@app.post("/api/chat")
def chat(req: ChatRequest):
    return {"reply": "Бот спит."}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
