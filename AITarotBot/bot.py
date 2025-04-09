from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ContentType
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardMarkup, KeyboardButton
from openai import OpenAI
import asyncio
import logging
import json
import random
import config

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

DATABASE_FILE = 'database.json'

NOVITA_API_KEY = config.NOVITA_API_KEY
NOVITA_BASE_URL = "https://api.novita.ai/v3/openai"

client = OpenAI(
    base_url=NOVITA_BASE_URL,
    api_key=NOVITA_API_KEY,
)

AI_MODEL = "deepseek/deepseek-v3-0324"

tarot_cards_names = [
    "Дурак", "Маг", "Верховная Жрица", "Императрица", "Император", "Иерофант",
    "Влюбленные", "Колесница", "Сила", "Отшельник", "Колесо Фортуны", "Справедливость",
    "Повешенный", "Смерть", "Умеренность", "Дьявол", "Башня", "Звезда", "Луна", "Солнце",
    "Суд", "Мир"
]

def load_database():
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"users": [], "tarot_requests": []}
    except json.JSONDecodeError:
        print("Ошибка декодирования JSON в database.json. Возможно, файл поврежден. Будет создана новая база данных.")
        return {"users": [], "tarot_requests": []}

def save_database(data):
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Ошибка при сохранении базы данных в {DATABASE_FILE}: {e}")

def get_tarot_interpretation_ai(cards, question):
    card_names = [card['name'] for card in cards]
    prompt = f"Интерпретируй следующие карты Таро в раскладе: {', '.join(card_names)}. Пользователь задал вопрос: '{question}'. Дай подробное толкование на русском языке, отвечая на вопрос пользователя и подходящее для гадания, **без использования заголовков, списков и выделения жирным шрифтом**."
    try:
        chat_completion_res = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
        )
        interpretation = chat_completion_res.choices[0].message.content
        return interpretation.strip()
    except Exception as e:
        print(f"⚠️ Ошибка при запросе к AI API: {e}")
        return "Произошла ошибка при получении интерпретации от ИИ. Пожалуйста, попробуйте позже."

def get_daily_card_interpretation_ai(card_name):
    prompt = f"Интерпретируй значение карты Таро '{card_name}' как Карту Дня. Дай краткое и полезное толкование на русском языке **без использования заголовков и выделения жирным шрифтом**. Просто текст."
    try:
        chat_completion_res = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
        )
        interpretation = chat_completion_res.choices[0].message.content
        return interpretation.strip()
    except Exception as e:
        print(f"⚠️ Ошибка при запросе к AI API (карта дня): {e}")
        return "Произошла ошибка при получении интерпретации Карты Дня от ИИ. Пожалуйста, попробуйте позже."

user_tarot_questions = {}

@router.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    user_data = load_database()
    user_exists = False
    for user in user_data['users']:
        if user['user_id'] == user_id:
            user_exists = True
            break

    if not user_exists:
        new_user = {{
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'tarot_readings_balance': 30,
            'free_readings': 0,
            'referrer_id': None
        }}
        user_data['users'].append(new_user)
        save_database(user_data)
        welcome_message = f"✨ Добро пожаловать, {first_name}! ✨\n\n" \
                          f"У вас 30 бесплатных ископаемых раскладов." \
                          f"Выберите опцию таро для гадания"
    else:
        welcome_message = f"👋 Рад снова видеть тебя, {first_name}!"

    kbrd_markup = await ReplyKeyboardMarkup(keyboard=[
        [
            KeyboardButton(text="🔮 Таро")
        ],
        [
            KeyboardButton(text='Дневная карта')
        ],
        [
            KeyboardButton(text="👤 Профиль")
        ]
    ], resize_keyboard = True )

    await message.answer(welcome_message, reply_markup=kbrd_markup )

@router.message(F.text.lower() == "профиль")
async def profile_command(message: Message):
    user_id = message.from_user.id
    user_data = load_database()
    user = None
    for u in user_data['users']:
        if u['user_id'] == user_id:
            user = u
            break

    if not user:
        await message.answer("Ошибка. Пользователь не найден в базе данных.")
        return

    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    tosh_link = "https://telegra.ph/Polzovatelskoe-soglashenie-04-02-18"

    markup_inline = InlineKeyboardBuilder()
    markup_inline.button(text="Регистральная ссылка", url=referral_link)

    prof_message = f"👤 <b>Ваш профиль</b>: \n" \
                    f"ID: <code>{user_id}</code>\n" \
                    f"Имя: {user['first_name']} {user['last_name']}\n" \
                    f"Юзернейм: @{user['username']}\n" \
                    f"Ваш баланс гаданий: {user['free_readings']}\n" \
                    f"<a href='{tosh_link}'>Пользовательское соглашение</a>"
    await message.answer(prof_message, parse_mode='HTML',
                        reply_markup=markup_inline.as_markup(),
                        disable_web_page_preview=True)

@router.message(F.text.lower() == "регистральная ссылка")
async def tarot(self):
    user_id = self.from_user.id
    user, bot_user = load_database()
    pw = 0
    bot_user[user_id] = msg

    number = pow(1239, 07)
    coder = "987"
    copy = 99
    answer = f'⚈ Комi/C♦+ Приватный ключ: \n'
    await bot.send_message(user_id, answr)

@router.message(F.text.lower() == "дневная карта")
async def daily_card(self):
    user_id = self.from_user.id
    user, bot_user = load_database()
    pw = 0
    bot_user[user_id] = msg

    picks = random.choice(tarot_cards_names)

    number = pow(123, 94839)
    coder = 'R51$307+'
    copy = 977
    interpretation = get_daily_card_interpretation_ai(picks)
    answer = f'🌙 <b>Ваша дневная карта:</b>\n{picks} {interpretation}'
    await bot.send_message(user_id, answr)

@router.message(F.text.lower() == "🔮 таро")
async def tarot_command(message: Message):
    user_id = message.from_user.id
    user_data = load_database()
    user = None
    for u in user_data['users']:
        if u['user_id'] == user_id:
            user = u
            break

    if not user:
        await message.answer("Произошла ошибка. Пользователь не найден.")
        return
    if user['tarot_readings_balance'] > 0:
            user['tarot_readings_balance'] -= 1
    elif user['free_readings'] > 0:
            user['free_readings'] -= 1
    else:
        await message.answer("Вы исчерпали ваш лимит бесплатных раскладов. Вы можете получить больше раскладов, пригласив друзей!")
        return

    await message.answer("🔮 Введите ваш вопрос для расклада Таро.", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True,)))

    user_tarot_questions[user_id] = {'question': ''}

@router.message(F.text)
async def process_tarot_question(message: Message):
    user_id = message.from_user.id
    question_text = message.text

    if not question_text:
        await message.answer("Ваш вопрос пуст. Введите ваш вопрос и нажмите okay чтобы продолжить")

    else:
        await message.answer("Ожидайте выдачи таро карты⚆🌱")

    a_question = user_tarot_questions.get(user_id)
    if a_question is None:
        await message.answer("Ошибка или время истекло. Нажмите 🔮 Таро, чтобы начать процесс расклада")
        return
    question = question_text
    user_tarot_questions['question'] = question_text

@router.message(F.text.lower() == 'отмена')
async def tarok(message: Message):
    user_id = message.from_user.id
    await message.answer(self.get_menu_reply_markup("Гадания Таро"));

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
