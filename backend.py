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

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = FastAPI()

# --- CORS: Разрешаем доступ всем ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- МОДЕЛИ ---
class LoginRequest(BaseModel):
    login: str
    password: str

class ScheduleRequest(BaseModel):
    token: str
    week: int
    year: int

# --- ГЛАВНАЯ СТРАНИЦА (ИСПРАВЛЕНИЕ 404) ---
@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Сервер SevasU работает! Приложение может подключаться.",
        "time": datetime.datetime.now().isoformat()
    }

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

def add_dates_to_schedule(schedule_output, start_date):
    days_map = {"Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3, "Пятница": 4, "Суббота": 5, "Воскресенье": 6}
    for day_entry in schedule_output:
        day_index = days_map.get(day_entry["day"])
        if day_index is not None and start_date:
            current_date = start_date + datetime.timedelta(days=day_index)
            day_entry["date_string"] = current_date.strftime("%d.%m")
        else: day_entry["date_string"] = "" 
    return schedule_output

def parse_schedule_api(data, week, year):
    schedule_output = []
    days_order = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    monday_date = get_date_for_iso_week(year, week)
    if not isinstance(data, dict): return []
    for day in days_order:
        if day in data:
            day_lessons = []
            paras = sorted(data[day].keys(), key=lambda x: int(x) if x.isdigit() else 99)
            for para_num in paras:
                for lesson in data[day][para_num]:
                    teacher = lesson.get('prepod_full') or lesson.get('prep_fio') or ""
                    room = lesson.get('auditorium') or lesson.get('aud_name') or ""
                    group = lesson.get('group_name') or ""
                    day_lessons.append({
                        "time": get_time_by_para(para_num),
                        "subject": lesson.get('discipline_name', 'Предмет?'),
                        "type": lesson.get('nagruzka', ''),
                        "room": room.strip(),
                        "teacher": teacher.strip(),
                        "group": clean_group_name(group)
                    })
            if day_lessons:
                schedule_output.append({"day": day, "lessons": day_lessons})
    return add_dates_to_schedule(schedule_output, monday_date)

# --- ЛОГИКА SELENIUM ---
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
        try:
            wait.until(EC.presence_of_element_located((By.NAME, "username"))).send_keys(username)
            driver.find_element(By.NAME, "password").send_keys(password)
            driver.find_element(By.ID, "kc-login").click()
            wait.until(EC.url_contains("timetablestudent"))
            time.sleep(2)
            for c in driver.get_cookies():
                if c['name'] == 'session': return c['value']
        except Exception as e:
            logger.error(f"Ошибка формы: {e}")
            return None
    except Exception as e:
        logger.error(f"Ошибка драйвера: {e}")
        return None
    finally:
        if driver: driver.quit()

# --- API ENDPOINTS ---
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
    raise HTTPException(status_code=401, detail="Неверный логин/пароль")

@app.post("/api/schedule")
def get_schedule(req: ScheduleRequest):
    payload = {"session": req.token, "week": req.week, "year": req.year, "semestr": "24-25"}
    headers = {'Content-Type': 'application/json', 'Cookie': f'session={req.token}'}
    try:
        resp = requests.post("https://timetable.sevsu.ru/napi/StudentsRaspGet", json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return {"schedule": parse_schedule_api(resp.json(), req.week, req.year), "week": req.week}
        raise HTTPException(status_code=401)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=8000)
