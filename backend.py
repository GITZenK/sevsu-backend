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

# --- SELENIUM ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- НАСТРОЙКИ ---
# Рекомендуется использовать переменные окружения для безопасности ключей
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "ВСТАВЬ_НОВЫЙ_КЛЮЧ_СЮДА") 

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

def get_iso_week():
    """Возвращает текущий номер недели и год."""
    today = datetime.date.today()
    return today.isocalendar()[1], today.year

def get_time_by_para(para_num):
    """Возвращает время начала и конца пары по ее номеру."""
    times = {
        "1": "08:30 - 10:00", "2": "10:10 - 11:40", "3": "11:50 - 13:20", "4": "14:00 - 15:30",
        "5": "15:40 - 17:10", "6": "17:20 - 18:50", "7": "19:00 - 20:30", "8": "20:40 - 22:10"
    }
    return times.get(str(para_num), "??:??")

def calculate_course(group_name):
    """Определяет курс по названию группы."""
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
    """Извлекает короткое название группы из текста."""
    if not text: return "Не найдено"
    match = re.search(r'([А-ЯA-Z]{1,6}/[а-яa-z]{1,2}-\d{2}-\d-?[а-яa-z]?)', text)
    if match: return match.group(1)
    return text.strip()

def get_date_for_iso_week(year, week):
    """Возвращает дату понедельника для заданной ISO недели и года."""
    try:
        d = datetime.date(year, 1, 4)
        start_of_week1 = d - datetime.timedelta(days=d.isoweekday() - 1)
        target_date = start_of_week1 + datetime.timedelta(weeks=week - 1)
        return target_date
    except:
        return None

def add_dates_to_schedule(schedule_output, start_date):
    """Добавляет конкретную дату DD.MM для каждого дня в расписании."""
    days_map = {"Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3, "Пятница": 4, "Суббота": 5, "Воскресенье": 6}
    for day_entry in schedule_output:
        day_name = day_entry["day"]
        day_index = days_map.get(day_name)
        if day_index is not None and start_date:
            current_date = start_date + datetime.timedelta(days=day_index)
            day_entry["date_string"] = current_date.strftime("%d.%m")
        else:
            day_entry["date_string"] = "" 
    return schedule_output

def parse_schedule_api(data, week, year):
    """Парсит сырые данные расписания, добавляя ФИО, кабинет, ГРУППУ и ДАТУ."""
    schedule_output = []
    days_order = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    if not isinstance(data, dict): return []

    monday_date = get_date_for_iso_week(year, week)

    for day in days_order:
        if day in data:
            day_schedule = data[day]
            day_lessons = []
            paras = sorted(day_schedule.keys(), key=lambda x: int(x) if x.isdigit() else 99)
            for para_num in paras:
                lessons = day_schedule[para_num]
                if not lessons: continue
                for lesson in lessons:
                    teacher = (
                        lesson.get('prepod_full') or 
                        lesson.get('prep_fio') or 
                        lesson.get('prep_short_name') or 
                        lesson.get('prepodName') or 
                        lesson.get('teacher_name') or 
                        lesson.get('fio') or
                        lesson.get('prepod') or
                        lesson.get('teacher') or
                        ""
                    )
                    room = (
                        lesson.get('auditorium') or 
                        lesson.get('aud_name') or 
                        lesson.get('auditory') or 
                        lesson.get('aud') or
                        lesson.get('cabinet') or
                        lesson.get('room_name') or
                        lesson.get('num_aud') or
                        ""
                    )
                    group = (lesson.get('group_name') or lesson.get('group_fio') or lesson.get('group') or "")

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

def clean_ai_text(text):
    text = re.sub(r'[*_`]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def get_ai_response(message, bot_type):
    if not DEEPSEEK_API_KEY or "sk-or" not in DEEPSEEK_API_KEY:
        return "Модуль ИИ не подключен. Введите API ключ DeepSeek в backend.py."
        
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        system_prompt = ""
        if bot_type == 'tech':
            system_prompt = "Ты ассистент-технарь для студента СевГУ. Отвечай кратко, используй технические термины, приводи формулы или код, если уместно. Стиль: сухой, точный. Не используй Markdown."
        else:
            system_prompt = "Ты ассистент-гуманитарий для студента СевГУ. Отвечай развернуто, красиво, используй метафоры. Стиль: литературный, мягкий, поддерживающий. Не используй Markdown."
            
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": 0.7
        }
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            if data['choices'] and data['choices'][0]['message']['content']:
                 return data['choices'][0]['message']['content']
            return "ИИ не смог сгенерировать ответ. Попробуйте другой вопрос."
        else:
            return f"Ошибка DeepSeek API: {response.status_code}"
    except Exception as e:
        return f"Сбой сети ИИ: {e}"

def selenium_full_login(username, password):
    print("🚀 Запуск Selenium (Ускоренный режим)...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    # Путь к Chrome для Docker (Render)
    if os.path.exists("/usr/bin/google-chrome"):
        chrome_options.binary_location = "/usr/bin/google-chrome"
    
    driver = None
    tokens = {"timetable": None, "iot": None}
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print("🌍 [1/2] Вход в Расписание...")
        driver.get(TIMETABLE_START)
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username")))
            driver.find_element(By.NAME, "username").send_keys(username)
            driver.find_element(By.NAME, "password").send_keys(password)
            driver.find_element(By.ID, "kc-login").click()
        except: pass

        print("⏳ Ждем загрузки...")
        try:
            WebDriverWait(driver, 15).until(EC.url_contains("timetablestudent")) 
            time.sleep(1) 
            for c in driver.get_cookies():
                if c['name'] == 'session':
                    tokens["timetable"] = c['value']
                    print("✅ Токен расписания получен!")
                    break
        except: print("❌ Расписание не открылось.")

        print("🌍 [2/2] Вход в ИОТ...")
        driver.get(IOT_START)
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "app")))
            time.sleep(2) 
            logs = driver.get_log('performance')
            for entry in logs:
                try:
                    message = json.loads(entry['message'])['message']
                    if message['method'] == 'Network.requestWillBeSent':
                        params = message['params']
                        url = params['request']['url']
                        if "sevsu.ru" in url and "api" in url:
                            headers = params['request']['headers']
                            auth = headers.get('Authorization') or headers.get('authorization')
                            if auth and "Bearer" in auth:
                                tokens["iot"] = auth.replace("Bearer ", "")
                                print("✅ Токен ИОТ перехвачен!")
                                break
                except: continue
        except Exception as e: print(f"❌ Ошибка перехвата ИОТ: {e}")
        return tokens

    except Exception as e:
        print(f"❌ Критическая ошибка Selenium: {e}")
        return tokens
    finally:
        if driver: driver.quit()

def get_real_profile_moodle(username, password):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'})
    try:
        r = session.get(LOGIN_PAGE)
        soup = BeautifulSoup(r.text, 'html.parser')
        sso_link = next((a['href'] for a in soup.find_all('a', href=True) if 'oauth2/login.php' in a['href']), None)
        if not sso_link: return None
        r_auth = session.get(sso_link)
        soup_auth = BeautifulSoup(r_auth.text, 'html.parser')
        form = soup_auth.find('form')
        if not form: return None
        payload = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input') if inp.get('name')}
        payload['username'] = username
        payload['password'] = password
        action = form.get('action') or r_auth.url
        r_post = session.post(action, data=payload)
        if "do.sevsu.ru" not in r_post.url: return None
        soup_dash = BeautifulSoup(r_post.text, 'html.parser')
        user_menu = soup_dash.find('div', class_='usermenu')
        fio = "Студент"
        if user_menu:
            span = user_menu.find('span', class_='usertext')
            if span: fio = re.sub(r'\s+', ' ', span.get_text()).strip()
        group = "Не найдено"
        prof_link = next((a['href'] for a in soup_dash.find_all('a', href=True) if 'user/profile.php' in a['href']), None)
        if prof_link:
            r_prof = session.get(prof_link)
            soup_p = BeautifulSoup(r_prof.text, 'html.parser')
            raw_text = soup_p.get_text()
            for dt in soup_p.find_all(['dt', 'th']):
                if "Групп" in dt.get_text():
                    dd = dt.find_next_sibling(['dd', 'td'])
                    if dd:
                        raw_text = dd.get_text(strip=True) + " " + raw_text
                        break
            group = clean_group_name(raw_text)
        return {
            "fio": fio,
            "group": group,
            "course": calculate_course(group),
            "rating": 0,
            "avatar_initials": fio[:2].upper()
        }
    except: return None

@app.post("/api/login")
def login(creds: LoginRequest):
    profile = get_real_profile_moodle(creds.login, creds.password)
    if not profile:
        return {"manual_token_required": True, "message": "Неверный логин или пароль"}
    
    tokens = selenium_full_login(creds.login, creds.password)
    if tokens.get("iot"):
        try:
            headers = {"Authorization": f"Bearer {tokens['iot']}"}
            r_iot = requests.get(IOT_API_PROFILE, headers=headers)
            if r_iot.status_code == 200:
                data = r_iot.json()
                def find_rating(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k in ["rating", "score", "balls", "total"] and isinstance(v, (int, float)):
                                return v
                        for v in obj.values():
                            res = find_rating(v)
                            if res: return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_rating(item)
                            if res: return res
                    return 0
                profile["rating"] = find_rating(data)
        except: pass

    combined_token = f"{tokens['timetable'] or ''}|{tokens['iot'] or ''}"
    if tokens['timetable']:
        return {"user": profile, "token": combined_token}
    else:
        return {"manual_token_required": True, "message": "Авто-вход не удался.", "partial_user": profile}

@app.post("/api/schedule")
def get_schedule(req: ScheduleRequest):
    timetable_token = req.token.split("|")[0] if "|" in req.token else req.token
    week, year = req.week, req.year
    payload = {"session": timetable_token, "week": week, "year": year, "semestr": "25-26"}
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0.0.0 Safari/537.36',
        'Origin': 'https://timetable.sevsu.ru',
        'Referer': 'https://timetable.sevsu.ru/timetablestudent',
        'Cookie': f'session={timetable_token}'
    }
    try:
        resp = requests.post(TIMETABLE_API, json=payload, headers=headers)
        if resp.status_code == 200:
            schedule_data = parse_schedule_api(resp.json(), week, year)
            return {"schedule": schedule_data, "week": week}
        else:
            raise HTTPException(status_code=401, detail="Токен истек")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
def chat_with_bot(req: ChatRequest):
    response = get_ai_response(req.message, req.bot_type)
    return {"reply": clean_ai_text(response)}

if __name__ == "__main__":
    # Динамический порт для Render
    port = int(os.environ.get("PORT", 8000))
    print(f"Запуск сервера СевГУ на порту {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)