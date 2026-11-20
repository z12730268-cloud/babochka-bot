import asyncio
import sqlite3
from datetime import datetime, time, timedelta, timezone
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
BOT_TOKEN = "9284016318:AAHgnB6XKr0GmNN3Xjf3PcPQJzgVePX3s0g"

# Администратор бота (без знака @)
ADMIN_USERNAME = "Ruikzak77"

# Часовой пояс (смещение от UTC, +5 для Екатеринбурга / Урала)
TZ_OFFSET = 5
TZ = timezone(timedelta(hours=TZ_OFFSET))

# ==========================================
# 💾 БАЗА ДАННЫХ (SQLite)
# ==========================================
DB_PATH = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user: types.User):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (user_id, username, first_name, joined_at) VALUES (?, ?, ?, ?)",
        (user.id, user.username, user.first_name, datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_setting(key: str, default=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

init_db()

def is_admin(user: types.User) -> bool:
    if not user or not user.username:
        return False
    return user.username.lower() == ADMIN_USERNAME.lower()

# ==========================================
# 📚 РАСПИСАНИЕ УРОКОВ (Фотка 1)
# ==========================================
SCHEDULE = {
    0: ["Великие люди", "РоВ", "Черчение", "Ин.яз", "Химия", "Литература", "ОБЗР", "Алгебра", "Труд / вопр. мат"],
    1: ["Труд", "Русский", "Алгебра", "Геометрия", "Биология", "История", "ВУС"],
    2: ["География", "Вероятность", "Физика", "ИКТ", "Физ-ра", "Химия", "Черчение"],
    3: ["География", "Русский", "Русский", "История", "Физика", "Ин.яз", "Алгебра", "РМГ"],
    4: ["Физ-ра", "Литература", "Ин.яз", "Биология", "Геометрия", "История", "Музыка"]
}

DAY_NAMES = {
    0: "Понедельник", 1: "Вторник", 2: "Среда",
    3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"
}

# Расписание звонков
BELLS_MONDAY = [
    (time(8, 0), time(8, 30)), (time(8, 40), time(9, 20)),
    (time(9, 35), time(10, 15)), (time(10, 30), time(11, 10)),
    (time(11, 25), time(12, 5)), (time(12, 15), time(12, 55)),
    (time(13, 10), time(13, 50)), (time(14, 5), time(14, 45)),
    (time(14, 55), time(15, 35)), (time(15, 40), time(16, 20))
]

BELLS_REGULAR = [
    (time(8, 0), time(8, 40)), (time(8, 50), time(9, 30)),
    (time(9, 45), time(10, 25)), (time(10, 40), time(11, 20)),
    (time(11, 35), time(12, 15)), (time(12, 25), time(13, 5)),
    (time(13, 20), time(14, 0)), (time(14, 15), time(14, 55)),
    (time(15, 10), time(15, 50)), (time(15, 55), time(16, 35))
]

def get_today_bells(weekday: int):
    return BELLS_MONDAY if weekday == 0 else BELLS_REGULAR

def format_minutes(total_seconds: int) -> str:
    mins = int(total_seconds // 60)
    if mins < 1:
        return "меньше минуты ⏳"
    hours = mins // 60
    rem_mins = mins % 60
    if hours > 0:
        return f"{hours} ч. {rem_mins} мин."
    return f"{mins} мин."

def get_current_school_state():
    now = datetime.now(TZ)
    weekday = now.weekday()
    if weekday not in SCHEDULE:
        return {"status": "weekend"}

    lessons = SCHEDULE[weekday]
    all_bells = get_today_bells(weekday)
    today_bells = all_bells[:len(lessons)]
    now_dt = now

    first_start = datetime.combine(now.date(), today_bells[0][0], tzinfo=TZ)
    last_end = datetime.combine(now.date(), today_bells[-1][1], tzinfo=TZ)

    if now_dt < first_start:
        delta = (first_start - now_dt).total_seconds()
        return {
            "status": "before_school",
            "time_left": format_minutes(delta),
            "first_lesson": lessons[0],
            "start_time": today_bells[0][0].strftime("%H:%M")
        }

    if now_dt >= last_end:
        return {"status": "after_school"}

    for idx, (b_start, b_end) in enumerate(today_bells):
        lesson_start = datetime.combine(now.date(), b_start, tzinfo=TZ)
        lesson_end = datetime.combine(now.date(), b_end, tzinfo=TZ)

        if lesson_start <= now_dt < lesson_end:
            delta_break = (lesson_end - now_dt).total_seconds()
            next_lesson = lessons[idx + 1] if idx + 1 < len(lessons) else None
            return {
                "status": "in_lesson",
                "lesson_num": idx + 1,
                "lesson_name": lessons[idx],
                "time_to_break": format_minutes(delta_break),
                "end_time": b_end.strftime("%H:%M"),
                "next_lesson": next_lesson
            }

        if idx + 1 < len(today_bells):
            next_start = datetime.combine(now.date(), today_bells[idx + 1][0], tzinfo=TZ)
            if lesson_end <= now_dt < next_start:
                delta_lesson = (next_start - now_dt).total_seconds()
                return {
                    "status": "in_break",
                    "next_num": idx + 2,
                    "next_lesson": lessons[idx + 1],
                    "time_to_lesson": format_minutes(delta_lesson),
                    "start_time": today_bells[idx + 1][0].strftime("%H:%M")
                }

    return {"status": "after_school"}

# ==========================================
# 🎛 КЛАВИАТУРЫ
# ==========================================
def main_keyboard(user_is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.button(text="🕒 Какой щас урок? И сколько до перемены?")
    builder.button(text="⏳ Сколько до урока?")
    builder.button(text="➡️ Какой следующий урок?")
    builder.button(text="📅 Расписание на сегодня")
    builder.button(text="🗓 Расписание на всю неделю")
    
    # Эту кнопку видит ТОЛЬКО @Ruikzak77
    if user_is_admin:
        builder.button(text="👑 Админ-панель")
        builder.adjust(1, 2, 1, 1, 1)
    else:
        builder.adjust(1, 2, 1, 1)
        
    return builder.as_markup(resize_keyboard=True)

def admin_inline_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Рассылка всем", callback_data="admin_broadcast")
    builder.button(text="📊 Создать опрос", callback_data="admin_poll")
    builder.button(text="📣 Настройка рекламы", callback_data="admin_ad")
    builder.button(text="👥 Сколько людей в боте", callback_data="admin_stats")
    builder.button(text="❌ Закрыть", callback_data="admin_close")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()

# ==========================================
# 🕵️ ШПИОН-MIDDLEWARE (Логирование сообщений админу)
# ==========================================
class SpyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message) and event.from_user:
            user = event.from_user
            save_user(user)

            # Если пишет не админ — пересылаем админу сообщение и то, что он нажал
            if not is_admin(user):
                admin_id = get_setting("admin_id")
                if admin_id:
                    bot: Bot = data["bot"]
                    user_tag = f"@{user.username}" if user.username else f"ID: {user.id}"
                    name = user.first_name or "Без имени"
                    content = event.text or event.caption or "[Медиа/Файл]"
                    try:
                        await bot.send_message(
                            chat_id=int(admin_id),
                            text=f"👁 **Сообщение от {name}** ({user_tag}):\n\n💬 `{content}`",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
        return await handler(event, data)

# ==========================================
# 🧠 FSM СОСТОЯНИЯ ДЛЯ АДМИНКИ
# ==========================================
class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_poll_question = State()
    waiting_for_poll_options = State()
    waiting_for_ad_text = State()
    waiting_for_ad_interval = State()

# ==========================================
# 🤖 БОТ И ОБРАБОТЧИКИ
# ==========================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.message.middleware(SpyMiddleware())

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_admin = is_admin(message.from_user)
    
    # Запоминаем ID админа в базу, чтобы слать ему логи и уведомления
    if user_admin:
        set_setting("admin_id", str(message.chat.id))
        extra_text = "\n\n👑 **Вы авторизованы как Администратор!** У вас появилась кнопка «👑 Админ-панель»."
    else:
        extra_text = ""

    text = (
        "Привет! Я бот **«Бабочка»** 🦋\n"
        "Я помогу следить за расписанием, уроками и переменами.\n\n"
        "Выбирай нужную кнопку в меню ниже 👇"
        f"{extra_text}"
    )
    await message.answer(text, reply_markup=main_keyboard(user_admin), parse_mode="Markdown")

# 1. Какой щас урок? И сколько до перемены?
@dp.message(F.text == "🕒 Какой щас урок? И сколько до перемены?")
async def handle_current_lesson(message: types.Message):
    state = get_current_school_state()
    st = state["status"]
    if st == "weekend":
        text = "🦋 **Сегодня выходной!** Уроков нет, отдыхай! 🎉"
    elif st == "before_school":
        text = (
            f"☀️ **Уроки ещё не начались.**\n\n"
            f"Первый урок: **{state['first_lesson']}** в {state['start_time']}.\n"
            f"До начала: **{state['time_left']}** ⏳"
        )
    elif st == "in_lesson":
        text = (
            f"📚 Сейчас идёт **{state['lesson_num']}-й урок**: **{state['lesson_name']}**\n"
            f"🔔 Звонок на перемену в: **{state['end_time']}**\n"
            f"⏳ До перемены осталось: **{state['time_to_break']}**"
        )
    elif st == "in_break":
        text = (
            f"☕ **Сейчас перемена!**\n\n"
            f"Следующий урок ({state['next_num']}-й): **{state['next_lesson']}**\n"
            f"🔔 Звонок в {state['start_time']} (через **{state['time_to_lesson']}**)"
        )
    else:
        text = "🎉 **Все уроки на сегодня закончились!** Свобода! 🦋"
    await message.answer(text, parse_mode="Markdown")

# 2. Сколько до урока?
@dp.message(F.text == "⏳ Сколько до урока?")
async def handle_time_to_lesson(message: types.Message):
    state = get_current_school_state()
    st = state["status"]
    if st == "weekend":
        text = "🦋 Сегодня выходной! До уроков ещё далеко."
    elif st == "before_school":
        text = (
            f"⏳ До 1-го урока (**{state['first_lesson']}**) осталось: **{state['time_left']}**\n"
            f"Начало в {state['start_time']}."
        )
    elif st == "in_break":
        text = (
            f"⏳ До начала {state['next_num']}-го урока (**{state['next_lesson']}**) осталось: "
            f"**{state['time_to_lesson']}** (звонок в {state['start_time']})."
        )
    elif st == "in_lesson":
        if state["next_lesson"]:
            text = (
                f"Сейчас ещё идёт {state['lesson_num']}-й урок ({state['lesson_name']}).\n"
                f"До перемены: **{state['time_to_break']}**.\n"
                f"Следующий урок — **{state['next_lesson']}**."
            )
        else:
            text = f"Сейчас идёт последний урок на сегодня! До его конца: **{state['time_to_break']}**."
    else:
        text = "На сегодня все уроки уже закончились! До завтра отдыхай 🦋"
    await message.answer(text, parse_mode="Markdown")

# 3. Какой следующий урок?
@dp.message(F.text == "➡️ Какой следующий урок?")
async def handle_next_lesson(message: types.Message):
    state = get_current_school_state()
    st = state["status"]
    if st == "weekend":
        text = "🦋 Сегодня выходной! Следующие уроки в понедельник."
    elif st == "before_school":
        text = f"Следующий (первый) урок: **1. {state['first_lesson']}** в {state['start_time']}."
    elif st == "in_break":
        text = (
            f"Следующий урок: **{state['next_num']}. {state['next_lesson']}**\n"
            f"Начнётся в **{state['start_time']}** (через {state['time_to_lesson']})."
        )
    elif st == "in_lesson":
        if state["next_lesson"]:
            text = (
                f"Следующий урок: **{state['lesson_num'] + 1}. {state['next_lesson']}**.\n"
                f"Текущий урок ({state['lesson_name']}) кончится через {state['time_to_break']}."
            )
        else:
            text = "Этот урок последний на сегодня! Дальше уроков нет, можно домой 🎉"
    else:
        now = datetime.now(TZ)
        tomorrow_day = (now.weekday() + 1) % 7
        if tomorrow_day in SCHEDULE:
            first_tomorrow = SCHEDULE[tomorrow_day][0]
            text = f"На сегодня уроков больше нет!\nЗавтра ({DAY_NAMES[tomorrow_day]}) 1-й урок: **{first_tomorrow}** в 08:00."
        else:
            text = "На сегодня уроки окончены! Впереди выходные 🎉"
    await message.answer(text, parse_mode="Markdown")

# 4. Расписание на сегодня
@dp.message(F.text == "📅 Расписание на сегодня")
async def handle_today_schedule(message: types.Message):
    now = datetime.now(TZ)
    weekday = now.weekday()
    if weekday not in SCHEDULE:
        await message.answer("🦋 Сегодня выходной! Уроков нет.", parse_mode="Markdown")
        return

    lessons = SCHEDULE[weekday]
    bells = get_today_bells(weekday)
    day_title = DAY_NAMES[weekday]
    lines = [f"📅 **Расписание на сегодня ({day_title}):**\n"]

    state = get_current_school_state()
    current_num = state.get("lesson_num", -1) if state["status"] == "in_lesson" else -1

    for i, name in enumerate(lessons):
        start_t = bells[i][0].strftime("%H:%M")
        end_t = bells[i][1].strftime("%H:%M")
        marker = "👉 " if (i + 1) == current_num else "▫️ "
        lines.append(f"{marker}**{i + 1}. {name}** `({start_t} - {end_t})`")

    lines.append("\n_👉 — текущий урок_")
    await message.answer("\n".join(lines), parse_mode="Markdown")

# 5. Расписание на всю неделю
@dp.message(F.text == "🗓 Расписание на всю неделю")
async def handle_all_week(message: types.Message):
    res = ["🦋 **Расписание на неделю:**\n"]
    for day_idx in range(5):
        day_title = DAY_NAMES[day_idx]
        lessons = SCHEDULE[day_idx]
        bells = get_today_bells(day_idx)
        res.append(f"📌 **{day_title}:**")
        for i, name in enumerate(lessons):
            start_t = bells[i][0].strftime("%H:%M")
            end_t = bells[i][1].strftime("%H:%M")
            res.append(f"  {i + 1}. {name} ({start_t} - {end_t})")
        res.append("")
    await message.answer("\n".join(res), parse_mode="Markdown")

# ==========================================
# 👑 АДМИН-ПАНЕЛЬ (ТОЛЬКО ДЛЯ @Ruikzak77)
# ==========================================
@dp.message(F.text == "👑 Админ-панель")
async def handle_admin_button(message: types.Message):
    if not is_admin(message.from_user):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return
    set_setting("admin_id", str(message.chat.id))
    await message.answer("👑 **Панель управления администратора**\nВыберите действие:", reply_markup=admin_inline_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_stats")
async def cb_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user):
        return await call.answer("Нет прав!", show_alert=True)
    users = get_all_users()
    await call.message.edit_text(f"📊 **Статистика бота:**\n\n👥 Всего пользователей в базе: **{len(users)}** чел.", reply_markup=admin_inline_keyboard(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_close")
async def cb_close(call: types.CallbackQuery):
    await call.message.delete()
    await call.answer()

# --- РАССЫЛКА ---
@dp.callback_query(F.data == "admin_broadcast")
async def cb_broadcast(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user):
        return await call.answer("Нет прав!", show_alert=True)
    await state.set_state(AdminStates.waiting_for_broadcast)
    await call.message.answer("✍️ Отправьте текст сообщения для рассылки всем пользователям бота (или напишите `отмена`):")
    await call.answer()

@dp.message(StateFilter(AdminStates.waiting_for_broadcast))
async def process_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        return await message.answer("❌ Рассылка отменена.", reply_markup=main_keyboard(True))

    users = get_all_users()
    sent_count = 0
    status_msg = await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")

    for u_id in users:
        try:
            # Отправляем сообщение вместе с обычными кнопками бота
            await message.copy_to(chat_id=u_id, reply_markup=main_keyboard(False))
            sent_count += 1
            await asyncio.sleep(0.05)  # Защита от спам-лимитов Telegram
        except Exception:
            pass

    await status_msg.edit_text(f"✅ Рассылка завершена!\nУспешно доставлено: **{sent_count}** из **{len(users)}** пользователей.")
    await state.clear()

# --- ОПРОСЫ ---
@dp.callback_query(F.data == "admin_poll")
async def cb_poll(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user):
        return await call.answer("Нет прав!", show_alert=True)
    await state.set_state(AdminStates.waiting_for_poll_question)
    await call.message.answer("❓ Введите **вопрос** для опроса (или `отмена`):")
    await call.answer()

@dp.message(StateFilter(AdminStates.waiting_for_poll_question))
async def process_poll_question(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        return await message.answer("❌ Создание опроса отменено.", reply_markup=main_keyboard(True))

    await state.update_data(poll_question=message.text)
    await state.set_state(AdminStates.waiting_for_poll_options)
    await message.answer("📝 Теперь введите варианты ответов через запятую.\n*Пример:* `Да, Нет, Не знаю`")

@dp.message(StateFilter(AdminStates.waiting_for_poll_options))
async def process_poll_options(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    if message.text and message.text.lower() == "отмена":
        await state.clear()
        return await message.answer("❌ Создание опроса отменено.", reply_markup=main_keyboard(True))

    options = [opt.strip() for opt in message.text.split(",") if opt.strip()]
    if len(options) < 2:
        return await message.answer("⚠️ Нужно указать как минимум 2 варианта ответа через запятую!")

    data = await state.get_data()
    question = data["poll_question"]

    users = get_all_users()
    sent_count = 0
    status_msg = await message.answer(f"⏳ Отправляю опрос {len(users)} пользователям...")

    for u_id in users:
        try:
            await bot.send_poll(chat_id=u_id, question=question, options=options, is_anonymous=True)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await status_msg.edit_text(f"✅ Опрос успешно разослан {sent_count} пользователям!")
    await state.clear()

# --- РЕКЛАМА И ВРЕМЯ ЕЕ ПОЯВЛЕНИЯ ---
@dp.callback_query(F.data == "admin_ad")
async def cb_ad(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user):
        return await call.answer("Нет прав!", show_alert=True)
    
    current_ad = get_setting("ad_text", "Не задана")
    current_interval = get_setting("ad_interval_hours", "0")
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить текст рекламы", callback_data="admin_set_ad_text")
    builder.button(text="⏱ Изменить интервал показа", callback_data="admin_set_ad_interval")
    builder.button(text="🚀 Запустить показ рекламы сейчас", callback_data="admin_send_ad_now")
    builder.button(text="🛑 Отключить рекламу", callback_data="admin_disable_ad")
    builder.button(text="⬅️ Назад", callback_data="admin_stats")
    builder.adjust(1)

    text = (
        f"📢 **Настройка рекламы:**\n\n"
        f"📌 Текущий текст: _{current_ad}_\n"
        f"⏱ Интервал автопоказа: каждые **{current_interval}** ч. (0 = отключено)"
    )
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_set_ad_text")
async def cb_set_ad_text(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user):
        return
    await state.set_state(AdminStates.waiting_for_ad_text)
    await call.message.answer("📝 Введите рекламный текст/сообщение:")
    await call.answer()

@dp.message(StateFilter(AdminStates.waiting_for_ad_text))
async def process_ad_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    set_setting("ad_text", message.text)
    await state.clear()
    await message.answer("✅ Рекламный текст успешно сохранён!", reply_markup=main_keyboard(True))

@dp.callback_query(F.data == "admin_set_ad_interval")
async def cb_set_ad_interval(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user):
        return
    await state.set_state(AdminStates.waiting_for_ad_interval)
    await call.message.answer("⏱ Введите интервал автопоказа в **часах** (например, `4` для показа каждые 4 часа, или `0` чтобы отключить):")
    await call.answer()

@dp.message(StateFilter(AdminStates.waiting_for_ad_interval))
async def process_ad_interval(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    try:
        hours = float(message.text.replace(",", "."))
        set_setting("ad_interval_hours", str(hours))
        set_setting("ad_last_sent", str(datetime.now(TZ).timestamp()))
        await state.clear()
        await message.answer(f"✅ Интервал установлен: каждые **{hours}** ч.!", reply_markup=main_keyboard(True))
    except ValueError:
        await message.answer("⚠️ Введите число (например `2`, `4` или `0.5`)!")

@dp.callback_query(F.data == "admin_disable_ad")
async def cb_disable_ad(call: types.CallbackQuery):
    if not is_admin(call.from_user):
        return
    set_setting("ad_interval_hours", "0")
    await call.answer("Реклама отключена!", show_alert=True)
    await cb_ad(call, None)

@dp.callback_query(F.data == "admin_send_ad_now")
async def cb_send_ad_now(call: types.CallbackQuery):
    if not is_admin(call.from_user):
        return
    ad_text = get_setting("ad_text")
    if not ad_text:
        return await call.answer("Сначала задайте текст рекламы!", show_alert=True)
    
    users = get_all_users()
    count = 0
    for u_id in users:
        try:
            await bot.send_message(chat_id=u_id, text=f"📢 **Реклама:**\n\n{ad_text}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await call.answer(f"Реклама разослана {count} пользователям!", show_alert=True)

# --- ФОНОВЫЙ ЦИКЛ АВТОПОКАЗА РЕКЛАМЫ ---
async def ad_background_loop():
    while True:
        await asyncio.sleep(60)  # Проверяем каждую минуту
        try:
            interval = float(get_setting("ad_interval_hours", "0"))
            if interval <= 0:
                continue
            
            ad_text = get_setting("ad_text")
            if not ad_text:
                continue

            last_sent = float(get_setting("ad_last_sent", "0"))
            now_ts = datetime.now(TZ).timestamp()
            interval_sec = interval * 3600

            if now_ts - last_sent >= interval_sec:
                set_setting("ad_last_sent", str(now_ts))
                users = get_all_users()
                for u_id in users:
                    try:
                        await bot.send_message(chat_id=u_id, text=f"📢 **Реклама:**\n\n{ad_text}", parse_mode="Markdown")
                        await asyncio.sleep(0.05)
                    except Exception:
                        pass
        except Exception as e:
            print("Ошибка в ad_background_loop:", e)

# ==========================================
# 🌐 ВЕБ-СЕРВЕР И СТАРТ
# ==========================================
async def handle_ping(request):
    return web.Response(text="🦋 Babochka bot is alive and running!")

async def main():
    print("🦋 Бот Бабочка с админкой запущен и готов к работе!")
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "0.0.0.0", 7860)
        await site.start()
        print("🌐 Веб-сервер запущен на порту 7860")
    except Exception as e:
        print("⚠️ Порт 7860 не открылся:", e)

    # Запуск авто-рекламы
    asyncio.create_task(ad_background_loop())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
