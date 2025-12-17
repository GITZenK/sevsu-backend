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

# Настройка логирования для отладки в Render
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- SELENIUM ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- НАСТРОЙКИ ---
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "") 

TIMETABLE_API = "https://timetable.sevsu.ru/napi/StudentsRaspGet"
TIMETABLE_START = "https://timetable.sevsu.ru/timetablestudent"
IOT_START = "https://iot.sevsu.ru/"
IOT_API_PROFILE = "https://iot.sevsu.ru/api/profile?expand=cohorts.option"
LOGIN_PAGE = "https://do.sevsu.ru/login/index.php"

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

def get_time_by_para(para_num):
    times = {
        "1": "08:30 - 10:00", "2": "10:10 - 11:40", "3": "11:50 - 13:20", "4": "14:00 - 15:30",
        "5": "15:40 - 17:10", "6": "17:20 - 18:50", "7": "19:00 - 20:30", "8": "20:40 - 22:10"
    }
    return times.get(str(para_num), "??:??")

def calculate_course(group_name):
    try:
        match = re.search(r'-(\d{2})[-\s]', group_name)
        if match:
            year = int("20" + match.group(1))
            now = datetime.date.today()
            course = now.year - year + (1 if now.month >= 9 else 0)
            if 1 <= course <= 6: return f"{course} курс"
    except: pass
    return "1 курс"

def clean_group_name(text):
    if not text: return "Не найдено"
    match = re.search(r'([А-ЯA-Z]{1,6}/[а-яa-z]{1,2}-\d{2}-\d-?[а-яa-z]?)', text)
    if match: return match.group(1)
    return text.strip()

def get_date_for_iso_week(year, week):
    try:
        d = datetime.date(year, 1, 4)
        start_of_week1 = d - datetime.timedelta(days=d.isoweekday() - 1)
        target_date = start_of_week1 + datetime.timedelta(weeks=week - 1)
        return target_date
    except: return None

def add_dates_to_schedule(schedule_output, start_date):
    days_map = {"Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3, "Пятница": 4, "Суббота": 5, "Воскресенье": 6}
    for day_entry in schedule_output:
        day_name = day_entry["day"]
        day_index = days_map.get(day_name)
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
            day_schedule = data[day]
            day_lessons = []
            paras = sorted(day_schedule.keys(), key=lambda x: int(x) if x.isdigit() else 99)
            for para_num in paras:
                lessons = day_schedule[para_num]
                for lesson in lessons:
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

def selenium_full_login(username, password):
    logger.info(f"Запуск Selenium для пользователя {username}")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    if os.path.exists("/usr/bin/google-chrome"):
        chrome_options.binary_location = "/usr/bin/google-chrome"
    
    driver = None
    tokens = {"timetable": None, "iot": None}
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        logger.info("Переход на страницу логина расписания...")
        driver.get(TIMETABLE_START)
        
        try:
            # Ждем появления полей ввода
            wait = WebDriverWait(driver, 15)
            user_input = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            pass_input = driver.find_element(By.NAME, "password")
            
            user_input.send_keys(username)
            pass_input.send_keys(password)
            driver.find_element(By.ID, "kc-login").click()
            
            # Ждем перехода обратно в расписание
            wait.until(EC.url_contains("timetablestudent"))
            logger.info("Успешный вход в систему расписания!")
            
            for c in driver.get_cookies():
                if c['name'] == 'session':
                    tokens["timetable"] = c['value']
                    break
        except Exception as e:
            logger.error(f"Ошибка внутри Selenium (поля не найдены или таймаут): {e}")
            # Сохраняем скриншот ошибки для логов Render (если доступно)
            driver.save_screenshot("error_login.png")
            
        return tokens
    except Exception as e:
        logger.error(f"Критическая ошибка Selenium: {e}")
        return tokens
    finally:
        if driver: driver.quit()

def get_real_profile_moodle(username, password):
    """Парсинг профиля через requests (быстро, но может блокироваться)"""
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
    try:
        r = session.get(LOGIN_PAGE, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        sso_link = next((a['href'] for a in soup.find_all('a', href=True) if 'oauth2/login.php' in a['href']), None)
        if not sso_link: return None
        
        r_auth = session.get(sso_link, headers=headers, timeout=10)
        soup_auth = BeautifulSoup(r_auth.text, 'html.parser')
        form = soup_auth.find('form')
        if not form: return None
        
        payload = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input') if inp.get('name')}
        payload['username'] = username
        payload['password'] = password
        
        r_post = session.post(form.get('action') or r_auth.url, data=payload, headers=headers, timeout=10)
        if "do.sevsu.ru" not in r_post.url: return None
        
        soup_dash = BeautifulSoup(r_post.text, 'html.parser')
        fio = "Студент"
        user_menu = soup_dash.find('div', class_='usermenu')
        if user_menu:
            span = user_menu.find('span', class_='usertext')
            if span: fio = span.get_text().strip()
            
        return {
            "fio": fio,
            "group": "Студент",
            "course": "1 курс",
            "rating": 0,
            "avatar_initials": fio[:2].upper()
        }
    except Exception as e:
        logger.warning(f"Не удалось получить профиль из Moodle: {e}")
        return None

@app.post("/api/login")
def login(creds: LoginRequest):
    logger.info(f"Попытка входа для {creds.login}")
    
    # 1. Пробуем получить профиль (даже если не выйдет - идем дальше)
    profile = get_real_profile_moodle(creds.login, creds.password)
    
    # 2. Основной вход через Selenium для получения токена расписания
    tokens = selenium_full_login(creds.login, creds.password)
    
    if tokens['timetable']:
        # Если профиль не спарсился, создаем заглушку
        final_profile = profile if profile else {
            "fio": creds.login,
            "group": "Загрузка...",
            "course": "--",
            "rating": 0,
            "avatar_initials": creds.login[:2].upper()
        }
        return {"user": final_profile, "token": tokens['timetable']}
    
    # Если даже Selenium не смог зайти
    raise HTTPException(status_code=401, detail="Неверный логин/пароль или сервер университета заблокировал запрос. Попробуйте еще раз.")

@app.post("/api/schedule")
def get_schedule(req: ScheduleRequest):
    week, year = req.week, req.year
    payload = {"session": req.token, "week": week, "year": year, "semestr": "24-25"}
    headers = {'Content-Type': 'application/json', 'Cookie': f'session={req.token}'}
    try:
        resp = requests.post(TIMETABLE_API, json=payload, headers=headers)
        if resp.status_code == 200:
            return {"schedule": parse_schedule_api(resp.json(), week, year)}
        raise HTTPException(status_code=401)
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
