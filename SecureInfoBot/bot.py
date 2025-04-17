import os
import telebot
from telebot import types
import threading
import time
from datetime import datetime
import logging
import re
from typing import Set, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = '' #Токен бота
ADMIN_ID = 123 #Твой Айди
DATABASES_DIR = 'databases'
MIN_QUERY_LENGTH = 5
STATS_FILE = 'stats.txt'
BACKUP_INTERVAL = 3600

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

class BotStats:
    def __init__(self):
        self.total_searches = 0
        self.successful_searches = 0
        self.users = set()

    def add_user(self, user_id):
        self.users.add(user_id)

    def increment_searches(self, success = False):
        self.total_searches += 1
        if success:
            self.successful_searches += 1

    def save(self):
        with open(STATS_FILE, 'w') as f:
            f.write(f"Всего поисков: {self.total_searches}\n")
            f.write(f"Успешных поисков: {self.successful_searches}\n")
            f.write(f"Уникальных пользователей: {len(self.users)}\n")

    def get_stats_text(self):
        return (
            f"📊 <b>Статистика бота:</b>\n\n"
            f"Всего поисков: {self.total_searches}\n"
            f"Успешных поисков: {self.successful_searches}\n"
            f"Уникальных пользователей: {len(self.users)}"
        )

stats = BotStats()

db_info_cache = {
    'count': 0,
    'total_lines': 0,
    'last_updated': 0
}

def update_db_cache():
    count = len(os.listdir(DATABASES_DIR))
    total_lines = count_lines_in_database()
    db_info_cache.update({
        'count': count,
        'total_lines': total_lines,
        'last_updated': time.time()
    })

def setup_directories():
    os.makedirs(DATABASES_DIR, exist_ok=True)
    update_db_cache()

def count_lines_in_database():
    total_lines = 0
    for filename in os.listdir(DATABASES_DIR):
        filepath = os.path.join(DATABASES_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                total_lines += sum(1 for _ in f)
        except Exception as e:
            logger.error(f"Ошибка при подсчете строк в {filename}: {e}")
    return total_lines

def format_result(line, label):
    clean_label = os.path.splitext(label)[0]
    replacements = {
        ';': '\n',
        '.': '',
        '[': '',
        ']': '',
        '"': '',
        'NULL': '❌ Нет данных',
        '::': ': ',
        '==': '='
    }
    for old, new in replacements.items():
        line = line.replace(old, new)
    return f"📁 {clean_label}\n{line.strip()}\n"

def create_results_file(results, query):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = "".join(c for c in query if c.isalnum() or c in (' ', '_', '-'))[:20]
    filename = f"results_{safe_query}_{timestamp}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"Результаты поиска по запросу: {query}\n\n")
        f.write(results)
    return filename

def create_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_search = types.KeyboardButton('🔍 Поиск')
    btn_help = types.KeyboardButton('ℹ️ Помощь')
    btn_stats = types.KeyboardButton('📊 Статистика')
    markup.add(btn_search, btn_help, btn_stats)
    return markup

def backup_stats():
    while True:
        time.sleep(BACKUP_INTERVAL)
        try:
            stats.save()
            update_db_cache()
            logger.info("Статистика успешно сохранена, кэш обновлен")
        except Exception as e:
            logger.error(f"Ошибка при сохранении статистики: {e}")

def is_phone_number(text):
    cleaned = re.sub(r'[^\d]', '', text)
    return len(cleaned) >= 5 and cleaned.isdigit()

def is_email(text):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, text) is not None

def normalize_phone(phone):
    return re.sub(r'[^\d]', '', phone)

def normalize_email(email):
    return email.lower().strip()

@bot.message_handler(commands=['start'])
def start(message):
    stats.add_user(message.chat.id)
    count = db_info_cache['count']
    total_lines = db_info_cache['total_lines']
    bot.send_message(
        message.chat.id,
        f"""✨ <b>Добро пожаловать в DataProbivBot!</b> ✨

📂 <i>Количество баз данных:</i> <b>{count}</b>
📊 <i>Общее количество записей:</i> <b>{total_lines:,}</b>

🔍 Поиск доступен только по:
- Номеру телефона (от 5 цифр)
- Email адресу

ℹ️ Для справки нажмите "Помощь" """,
        parse_mode='HTML',
        reply_markup=create_keyboard()
    )
    threading.Thread(target=update_db_cache).start()

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.send_message(
        message.chat.id,
        """
<b>ℹ️ Справка по использованию бота:</b>
🔍 <b>Поиск доступен только по:</b>
- Номеру телефона (от 5 цифр)
- Email адресу
📝 <b>Примеры запросов:</b>
+79161234567
example@mail.com
<b>Доступные команды:</b>
/start - Перезапустить бота
/help - Показать эту справку
/stats - Показать статистику (только для админа)
<code>Базы данных автоматически обновляются!</code>""",
        parse_mode='HTML'
    )

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.chat.id == ADMIN_ID:
        stats.save()
        bot.send_message(
            message.chat.id,
            stats.get_stats_text(),
            parse_mode='HTML'
        )
    else:
        bot.send_message(
            message.chat.id,
            "⛔ Эта функция доступна только администратору",
            parse_mode='HTML'
        )

@bot.message_handler(func=lambda message: message.text == '🔍 Поиск')
def search_button(message):
    msg = bot.send_message(
        message.chat.id,
        "🔍 <b>Введите номер телефона или email:</b>\n\n"
        "<code>Примеры:\n+79161234567\nexample@mail.com</code>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_search)

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def help_button(message):
    help_command(message)

@bot.message_handler(func=lambda message: message.text == '📊 Статистика')
def stats_button(message):
    show_stats(message)

def process_search(message):
    query = message.text.strip()
    is_phone = is_phone_number(query)
    is_email_addr = is_email(query)
    if not (is_phone or is_email_addr):
        bot.send_message(
            message.chat.id,
            "⚠️ <b>Некорректный запрос!</b>\n\n"
            "🔍 Поиск доступен только по:\n"
            "- Номеру телефона (от 5 цифр)\n"
            "- Email адресу\n\n"
            "ℹ️ Используйте /help для справки",
            parse_mode='HTML'
        )
        return
    search_query = normalize_phone(query) if is_phone else normalize_email(query)
    query_type = "номеру телефона" if is_phone else "email адресу"
    stats.increment_searches()
    search_msg = bot.send_message(
        message.chat.id,
        f"🔎 <i>Ищем по {query_type}:</i> <code>{query}</code>",
        parse_mode='HTML'
    )
    threading.Thread(
        target=perform_search,
        args=(message.chat.id, search_msg.message_id, search_query, query, query_type, is_phone)
    ).start()

def perform_search(chat_id, msg_id, search_query, original_query, query_type, is_phone):
    results = []
    seen_lines = set()
    found = False
    try:
        for filename in os.listdir(DATABASES_DIR):
            file_path = os.path.join(DATABASES_DIR, filename)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        if is_phone:
                            line_cleaned = re.sub(r'[^\d]', '', line)
                            if search_query in line_cleaned:
                                formatted_line = format_result(line, filename)
                                if formatted_line not in seen_lines:
                                    seen_lines.add(formatted_line)
                                    results.append(formatted_line)
                                found = True
                        else:
                            line_lower = line.lower()
                            if search_query in line_lower:
                                formatted_line = format_result(line, filename)
                                if formatted_line not in seen_lines:
                                    seen_lines.add(formatted_line)
                                    results.append(formatted_line)
                                found = True
            except Exception as e:
                logger.error(f"Ошибка при чтении файла {filename}: {e}")
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
        if found:
            stats.increment_searches(success=True)
            results_text = "\n".join(results)
            filename = create_results_file(results_text, original_query)
            try:
                with open(filename, 'rb') as f:
                    bot.send_document(
                        chat_id,
                        f,
                        caption=f"✅ <b>Результаты поиска по {query_type}:</b> <code>{original_query}</code>\n\n"
                               "📄 Все результаты сохранены в файле",
                        parse_mode='HTML'
                    )
            finally:
                try:
                    os.remove(filename)
                except Exception as e:
                    logger.error(f"Ошибка при удалении временного файла: {e}")
        else:
            bot.send_message(
                chat_id,
                f"❌ <b>По {query_type}</b> <code>{original_query}</code> <b>ничего не найдено</b>\n\n"
                "Попробуйте изменить запрос или проверьте правильность ввода",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Ошибка при выполнении поиска: {e}")
        bot.send_message(
            chat_id,
            "⚠️ Произошла ошибка при поиске. Пожалуйста, попробуйте позже.",
            parse_mode='HTML'
        )

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/'):
        bot.send_message(
            message.chat.id,
            "⚠️ Неизвестная команда. Используйте /help для справки"
        )
    else:
        process_search(message)

def main():
    setup_directories()
    logger.info("DataProbiv_Bot запущен! Для остановки нажмите Ctrl+C")
    threading.Thread(target=backup_stats, daemon=True).start()
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        stats.save()
    finally:
        stats.save()

if __name__ == '__main__':
    main()
