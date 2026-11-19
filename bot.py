import asyncio
from datetime import datetime, time, timedelta, timezone
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
BOT_TOKEN = "9284016318:AAHgnB6XKr0GmNN3Xjf3PcPQJzgVePX3s0g"

# Часовой пояс (смещение от UTC). 
# +5: Екатеринбург / Пермь / Челябинск / Тюмень. Поменяй на 3, если нужно время МСК.
TZ_OFFSET = 5
TZ = timezone(timedelta(hours=TZ_OFFSET))

# ==========================================
# 📚 РАСПИСАНИЕ УРОКОВ (Фотка 1)
# ==========================================
SCHEDULE = {
    0: [  # Понедельник
        "Великие люди",
        "РоВ",
        "Черчение",
        "Ин.яз",
        "Химия",
        "Литература",
        "ОБЗР",
        "Алгебра",
        "Труд / вопр. мат"
    ],
    1: [  # Вторник
        "Труд",
        "Русский",
        "Алгебра",
        "Геометрия",
        "Биология",
        "История",
        "ВУС"
    ],
    2: [  # Среда
        "География",
        "Вероятность",
        "Физика",
        "ИКТ",
        "Физ-ра",
        "Химия",
        "Черчение"
    ],
    3: [  # Четверг
        "География",
        "Русский",
        "Русский",
        "История",
        "Физика",
        "Ин.яз",
        "Алгебра",
        "РМГ"
    ],
    4: [  # Пятница
        "Физ-ра",
        "Литература",
        "Ин.яз",
        "Биология",
        "Геометрия",
        "История",
        "Музыка"
    ]
}

DAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье"
}

# ==========================================
# 🔔 РАСПИСАНИЕ ЗВОНКОВ (Фотка 2, I смена)
# ==========================================
# Понедельник (1 урок короткий 8:00 - 8:30)
BELLS_MONDAY = [
    (time(8, 0), time(8, 30)),
    (time(8, 40), time(9, 20)),
    (time(9, 35), time(10, 15)),
    (time(10, 30), time(11, 10)),
    (time(11, 25), time(12, 5)),
    (time(12, 15), time(12, 55)),
    (time(13, 10), time(13, 50)),
    (time(14, 5), time(14, 45)),
    (time(14, 55), time(15, 35)),
    (time(15, 40), time(16, 20))
]

# Вторник - Пятница (стандартные 40-минутки)
BELLS_REGULAR = [
    (time(8, 0), time(8, 40)),
    (time(8, 50), time(9, 30)),
    (time(9, 45), time(10, 25)),
    (time(10, 40), time(11, 20)),
    (time(11, 35), time(12, 15)),
    (time(12, 25), time(13, 5)),
    (time(13, 20), time(14, 0)),
    (time(14, 15), time(14, 55)),
    (time(15, 10), time(15, 50)),
    (time(15, 55), time(16, 35))
]

def get_today_bells(weekday: int):
    """Возвращает звонки для конкретного дня"""
    return BELLS_MONDAY if weekday == 0 else BELLS_REGULAR

def format_minutes(total_seconds: int) -> str:
    """Форматирует секунды в читаемый вид"""
    mins = int(total_seconds // 60)
    if mins < 1:
        return "меньше минуты ⏳"
    hours = mins // 60
    rem_mins = mins % 60
    if hours > 0:
        return f"{hours} ч. {rem_mins} мин."
    return f"{mins} мин."

def get_current_school_state():
    """Определяет статус текущего урока или перемены"""
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

        # Сейчас идёт этот урок
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

        # Сейчас перемена
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
# 🎛 КНОПКИ МЕНЮ
# ==========================================
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🕒 Какой щас урок? И сколько до перемены?")
    builder.button(text="⏳ Сколько до урока?")
    builder.button(text="➡️ Какой следующий урок?")
    builder.button(text="📅 Расписание на сегодня")
    builder.button(text="🗓 Расписание на всю неделю")
    builder.adjust(1, 2, 1, 1)
    return builder.as_markup(resize_keyboard=True)

from aiohttp import web

# ==========================================
# 🤖 ОБРАБОТЧИКИ
# ==========================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    text = (
        "Привет! Я бот **«Бабочка»** 🦋\n"
        "Я помогу следить за расписанием, уроками и переменами.\n\n"
        "Выбирай нужную кнопку в меню ниже 👇"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")

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
    else:  # after_school
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
            text = (
                f"На сегодня уроков больше нет!\n"
                f"Завтра ({DAY_NAMES[tomorrow_day]}) 1-й урок: **{first_tomorrow}** в 08:00."
            )
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

async def handle_ping(request):
    return web.Response(text="🦋 Babochka bot is alive and running!")

async def main():
    print("🦋 Бот Бабочка запущен и готов к работе!")
    
    # Запуск фонового веб-сервера для облачных хостингов (Hugging Face / Render)
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "0.0.0.0", 7860)
        await site.start()
        print("🌐 Веб-сервер запущен на порту 7860")
    except Exception as e:
        print("⚠️ Порт 7860 не открылся (не критично для локального запуска):", e)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
