import telebot
from telebot import types
import os
import csv
import datetime
import logging

# --- Настройка ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "" # Замените на токен вашего бота
ADMIN_USER_IDS = [int(admin_id) for admin_id in (os.environ.get("1324", "123").split(','))] # Замените на свой ID админа
ADMIN_GROUP_ID = os.environ.get("ADMIN_GROUP_ID") # Опционально: ID группы для уведомлений админа
ENABLE_PROMOCODES = True # По умолчанию промокоды включены

# --- Хранилище данных (В памяти, для production используйте БД) ---
products = {} # product_id: {'name': ..., 'description': ..., 'price': ..., 'category': ..., 'stock': ..., 'image': ...}
categories = {} # category_id: 'category_name'
user_carts = {} # user_id: {product_id: quantity}
user_data = {} # user_id: {'name': ..., 'payment_method': ...}
sales_log = [] # Список словарей заказов
promocodes_enabled = ENABLE_PROMOCODES
user_states = {} # user_id: {'state': ..., 'data': ...} # Для управления состояниями пользователя

bot = telebot.TeleBot(BOT_TOKEN)
logging.basicConfig(level=logging.INFO) # Включаем логирование

# --- Вспомогательные функции ---
def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

def get_product_list_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for category_id, category_name in categories.items():
        markup.add(types.InlineKeyboardButton(category_name, callback_data=f'category_{category_id}'))
    markup.add(types.InlineKeyboardButton("Корзина 🛒", callback_data='show_cart'))
    return markup

def get_categories_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for category_id, category_name in categories.items():
        markup.add(types.InlineKeyboardButton(category_name, callback_data=f'category_{category_id}'))
    markup.add(types.InlineKeyboardButton("Вернуться в меню админки", callback_data='admin_menu'))
    return markup

def get_products_in_category_keyboard(category_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for prod_id, prod_data in products.items():
        if prod_data['category'] == category_id:
            markup.add(types.InlineKeyboardButton(f"{prod_data['name']} - {prod_data['price']}₽", callback_data=f'product_{prod_id}'))
    markup.add(types.InlineKeyboardButton("Вернуться в каталог", callback_data='show_catalog'))
    return markup

def get_cart_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("Оформить заказ ✅", callback_data='checkout'))
    markup.add(types.InlineKeyboardButton("Очистить корзину 🗑️", callback_data='clear_cart'))
    markup.add(types.InlineKeyboardButton("Вернуться в каталог ◀️", callback_data='show_catalog'))

    if user_carts.get(user_id):
        for product_id in list(user_carts[user_id].keys()): # list() для избежания ошибки изменения размера словаря
            prod_name = products.get(product_id, {}).get('name', 'Неизвестный товар')
            markup.row(types.InlineKeyboardButton(f"❌ Удалить {prod_name}", callback_data=f'remove_from_cart_{product_id}'))
    return markup

def get_order_confirmation_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("Подтвердить ✅", callback_data='confirm_order'),
        types.InlineKeyboardButton("Изменить ✏️", callback_data='edit_order'),
        types.InlineKeyboardButton("Отменить ❌", callback_data='cancel_order')
    )
    return markup

def get_admin_menu_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Товары 📦", callback_data='admin_products'),
        types.InlineKeyboardButton("Категории 📂", callback_data='admin_categories'),
        types.InlineKeyboardButton("Промокоды 🎫", callback_data='admin_promocodes'),
        types.InlineKeyboardButton("Склад 📊", callback_data='admin_stock'),
        types.InlineKeyboardButton("Экспорт/Импорт 📤📥", callback_data='admin_export_import'),
        types.InlineKeyboardButton("Лог Продаж 📜", callback_data='admin_sales_log'),
        types.InlineKeyboardButton("Рассылка 📢", callback_data='admin_broadcast'),
        types.InlineKeyboardButton("Выйти из админки 🚪", callback_data='admin_exit')
    )
    return markup

def get_admin_products_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Добавить товар ➕", callback_data='admin_add_product'),
        types.InlineKeyboardButton("Редактировать товар ✏️", callback_data='admin_edit_product'),
        types.InlineKeyboardButton("Вернуться в меню админки", callback_data='admin_menu'))
    return markup

def get_admin_categories_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Добавить категорию ➕", callback_data='admin_add_category'),
        types.InlineKeyboardButton("Вернуться в меню админки", callback_data='admin_menu'))
    return markup

def get_admin_stock_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Посмотреть остатки 👁️", callback_data='admin_view_stock'),
        types.InlineKeyboardButton("Списать товар ➖", callback_data='admin_adjust_stock'),
        types.InlineKeyboardButton("Вернуться в меню админки", callback_data='admin_menu'))
    return markup

def get_admin_export_import_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Экспорт товаров 📤", callback_data='admin_export_products'),
        types.InlineKeyboardButton("Импорт товаров 📥", callback_data='admin_import_products'),
        types.InlineKeyboardButton("Вернуться в меню админки", callback_data='admin_menu'))
    return markup

def format_cart(user_id):
    cart_items = user_carts.get(user_id, {})
    if not cart_items:
        return "Ваша корзина пуста."
    cart_text = "Ваша корзина:\n"
    total_price = 0
    for product_id, quantity in cart_items.items():
        product = products.get(product_id)
        if product:
            item_price = product['price'] * quantity
            cart_text += f"- {product['name']} x{quantity} - {item_price}₽\n"
            total_price += item_price
    cart_text += f"\nИтого: {total_price}₽"
    return cart_text

def format_order_confirmation(user_id, payment_method, promocode=None):
    cart_text = format_cart(user_id)
    user_info_text = ""
    if user_data.get(user_id):
        user_info_text = f"\n\nИмя: {user_data[user_id].get('name', 'Не указано')}\nСпособ оплаты: {payment_method}"
    else:
        user_info_text = f"\n\nСпособ оплаты: {payment_method}"
    if promocode:
        user_info_text += f"\nПромокод: {promocode}"

    return cart_text + user_info_text

def generate_product_id():
    return str(len(products) + 1)

def generate_category_id():
    return str(len(categories) + 1)

def export_products_to_csv():
    filename = "products_export.csv"
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['product_id', 'name', 'description', 'price', 'category', 'stock']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for prod_id, prod_data in products.items():
            writer.writerow({'product_id': prod_id, **prod_data})
    return filename

def export_products_to_txt():
    filename = "products_export.txt"
    with open(filename, 'w', encoding='utf-8') as txtfile:
        for prod_id, prod_data in products.items():
            txtfile.write(f"ID: {prod_id}\n")
            txtfile.write(f"Название: {prod_data['name']}\n")
            txtfile.write(f"Описание: {prod_data['description']}\n")
            txtfile.write(f"Цена: {prod_data['price']}\n")
            txtfile.write(f"Категория: {categories.get(prod_data['category'], 'Неизвестно')}\n")
            txtfile.write(f"Остаток: {prod_data['stock']}\n\n")
    return filename

def set_user_state(user_id, state, data=None):
    user_states[user_id] = {'state': state, 'data': data}

def get_user_state(user_id):
    return user_states.get(user_id, {}).get('state')

def get_user_state_data(user_id):
    return user_states.get(user_id, {}).get('data')

def clear_user_state(user_id):
    if user_id in user_states:
        del user_states[user_id]


# --- Обработчики команд и сообщений ---
@bot.message_handler(commands=['start'])
def start(message):
    user = message.from_user
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_catalog = types.KeyboardButton('Каталог')
    btn_cart = types.KeyboardButton('Корзина')
    btn_contact = types.KeyboardButton('Связь')
    markup.add(btn_catalog, btn_cart, btn_contact)
    bot.reply_to(message, f"Привет, {user.username or user.first_name}! Я бот для заказов. Нажмите Каталог, чтобы посмотреть товары или Корзина, чтобы посмотреть вашу корзину.", reply_markup=markup)

@bot.message_handler(regexp='^Связь$')
def contact_us_start(message):
    set_user_state(message.from_user.id, 'waiting_for_question')
    bot.reply_to(message, "Напишите ваш вопрос, и я передам его администратору.")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'waiting_for_question')
def contact_us_message(message):
    user = message.from_user
    admin_message = f"Новый вопрос от пользователя [{user.username or user.first_name}](tg://user?id={user.id}) (ID: {user.id}):\n\n{message.text}"
    for admin_id in ADMIN_USER_IDS:
        bot.send_message(chat_id=admin_id, text=admin_message, parse_mode="Markdown", disable_web_page_preview=True)
    bot.reply_to(message, "Ваш вопрос отправлен администратору. Ожидайте ответа.")
    clear_user_state(message.from_user.id)


@bot.message_handler(regexp='^Каталог$')
def show_catalog(message):
    bot.reply_to(message, "Выберите категорию:", reply_markup=get_product_list_keyboard())

@bot.message_handler(regexp='^Корзина$')
def show_cart(message):
    user_id = message.from_user.id
    cart_text = format_cart(user_id)
    bot.reply_to(message, cart_text, reply_markup=get_cart_keyboard(user_id))

@bot.callback_query_handler(func=lambda call: call.data == 'clear_cart')
def clear_cart_callback(call):
    user_id = call.from_user.id
    user_carts[user_id] = {}
    bot.answer_callback_query(call.id, "Корзина очищена.")
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Корзина очищена.", reply_markup=get_product_list_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == 'checkout')
def checkout_start_callback(call):
    user_id = call.from_user.id
    if not user_carts.get(user_id) or not user_carts[user_id]:
        bot.answer_callback_query(call.id, text="Ваша корзина пуста.")
        return

    if not user_data.get(user_id) or 'name' not in user_data[user_id]:
        set_user_state(user_id, 'waiting_for_name')
        bot.send_message(call.message.chat.id, "Укажите ваше имя для заказа:")
    else:
        set_user_state(user_id, 'waiting_for_payment_method')
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton('Наличные'), types.KeyboardButton('Карта'))
        bot.send_message(call.message.chat.id, "Выберите способ оплаты:", reply_markup=markup)

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'waiting_for_name')
def get_name_handler(message):
    user_id = message.from_user.id
    user_data[user_id] = user_data.get(user_id, {})
    user_data[user_id]['name'] = message.text
    set_user_state(user_id, 'waiting_for_payment_method')
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Наличные'), types.KeyboardButton('Карта'))
    bot.reply_to(message, "Выберите способ оплаты:", reply_markup=markup)


@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'waiting_for_payment_method', content_types=['text'])
def get_payment_method_handler(message):
    user_id = message.from_user.id
    payment_method = message.text
    user_state_data = get_user_state_data(user_id) or {}

    if payment_method.lower() == 'карта': # Обработка выбора "Карта"
        payment_method = "Карта (ожидает подтверждения админа)" # Обновляем метод оплаты для отображения
        bot.send_message(message.chat.id, "Вы выбрали оплату картой. \n\n**Важно:** Оплата картой требует ручного подтверждения от администратора. После подтверждения заказа, администратор свяжется с вами для уточнения деталей оплаты.\n\nПожалуйста, подтвердите ваш заказ.", parse_mode='Markdown') # Инструкция для пользователя

    user_state_data['payment_method'] = payment_method
    set_user_state(user_id, 'waiting_for_promocode_choice', data=user_state_data)


    if promocodes_enabled:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton('Да'), types.KeyboardButton('Нет'))
        bot.send_message(message.chat.id, "У вас есть промокод?", reply_markup=markup)
        set_user_state(user_id, 'waiting_for_promocode_choice', data={'payment_method': payment_method})

    else:
         payment_method = get_user_state_data(user_id)['payment_method']
         order_confirmation_text = format_order_confirmation(user_id, payment_method)
         markup_confirm = get_order_confirmation_keyboard()
         bot.send_message(message.chat.id, order_confirmation_text, reply_markup=markup_confirm)
         clear_user_state(user_id)
         set_user_state(user_id, 'order_confirmation_pending', data={'payment_method': payment_method})
         bot.reply_to(message, "Подтвердите или измените заказ", reply_markup=types.ReplyKeyboardRemove()) # Убираем клаву способов оплаты


@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'waiting_for_promocode_choice', content_types=['text'])
def promocode_choice_handler(message):
    user_id = message.from_user.id
    answer = message.text.lower()

    if answer == 'да':
        set_user_state(user_id, 'waiting_for_promocode_input', data=get_user_state_data(user_id))
        bot.reply_to(message, "Введите промокод:", reply_markup=types.ReplyKeyboardRemove())

    elif answer == 'нет':
        user_state_data = get_user_state_data(user_id)
        user_state_data['promocode'] = None
        set_user_state(user_id, 'order_confirmation_pending', data=user_state_data) # Переходим к подтверждению заказа
        payment_method = user_state_data['payment_method']
        order_confirmation_text = format_order_confirmation(user_id, payment_method)
        markup_confirm = get_order_confirmation_keyboard()
        bot.send_message(message.chat.id, order_confirmation_text, reply_markup=markup_confirm)
        bot.reply_to(message, "Подтвердите или измените заказ", reply_markup=types.ReplyKeyboardRemove()) # Убираем клаву выбора промокода
    else:
        bot.reply_to(message, "Пожалуйста, ответьте 'Да' или 'Нет'.")


@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'waiting_for_promocode_input', content_types=['text'])
def promocode_input_handler(message):
    user_id = message.from_user.id
    promocode = message.text
    user_state_data = get_user_state_data(user_id)
    user_state_data['promocode'] = promocode
    set_user_state(user_id, 'order_confirmation_pending', data=user_state_data) # Переходим к подтверждению заказа, сохранив промокод
    payment_method = user_state_data['payment_method']
    order_confirmation_text = format_order_confirmation(user_id, payment_method, promocode)
    markup_confirm = get_order_confirmation_keyboard()
    bot.send_message(message.chat.id, order_confirmation_text, reply_markup=markup_confirm)
    bot.reply_to(message, "Подтвердите или измените заказ", reply_markup=types.ReplyKeyboardRemove()) # Убираем клаву ввода промокода


@bot.callback_query_handler(func=lambda call: call.data == 'confirm_order')
def confirm_order_callback(call):
    user_id = call.from_user.id
    user_state_data = get_user_state_data(user_id)
    payment_method = user_state_data.get('payment_method', 'Не указан')
    promocode = user_state_data.get('promocode')

    order_text_admin = f"Новый заказ!\n\nОт пользователя: [{call.from_user.username or call.from_user.first_name}](tg://user?id={user_id}) (ID: {user_id})\n{format_order_confirmation(user_id, payment_method, promocode)}\n\n[Ссылка на диалог](tg://user?id={user_id})"

    if payment_method == "Карта (ожидает подтверждения админа)":
        order_text_admin = f"⚠️ **Новый заказ - ОПЛАТА КАРТОЙ (ОЖИДАЕТ ПОДТВЕРЖДЕНИЯ ОПЛАТЫ ВРУЧНУЮ)!** ⚠️\n\nОт пользователя: [{call.from_user.username or call.from_user.first_name}](tg://user?id={user_id}) (ID: {user_id})\n{format_order_confirmation(user_id, payment_method, promocode)}\n\n[Ссылка на диалог](tg://user?id={user_id})"


    for admin_id in ADMIN_USER_IDS:
        bot.send_message(chat_id=admin_id, text=order_text_admin, parse_mode="Markdown", disable_web_page_preview=True)
    if ADMIN_GROUP_ID:
        bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"Новый заказ! от пользователя ID {user_id}")

    sales_log.append({
        'user_id': user_id,
        'order_time': datetime.datetime.now().isoformat(),
        'cart_items': user_carts[user_id],
        'payment_method': payment_method,
        'promocode': promocode
    })

    user_carts[user_id] = {}
    bot.answer_callback_query(call.id, "Заказ подтвержден!")
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Спасибо за заказ! Мы свяжемся с вами в ближайшее время.", reply_markup=types.ReplyKeyboardRemove())
    clear_user_state(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'cancel_order')
def cancel_order_callback(call):
    bot.answer_callback_query(call.id, "Заказ отменен.")
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Заказ отменен.", reply_markup=get_product_list_keyboard())
    clear_user_state(call.from_user.id)

@bot.callback_query_handler(func=lambda call: call.data == 'edit_order')
def edit_order_callback(call):
    bot.answer_callback_query(call.id, "Функция редактирования заказа пока не реализована.")
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Изменение заказа пока нельзя. Пожалуйста, отмените и сформируйте новый заказ.", reply_markup=get_product_list_keyboard())
    clear_user_state(call.from_user.id)

@bot.callback_query_handler(func=lambda call: call.data == 'show_catalog')
def show_catalog_callback(call):
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Выберите категорию:", reply_markup=get_product_list_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == 'show_cart')
def show_cart_callback(call):
    user_id = call.from_user.id
    cart_text = format_cart(user_id)
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=cart_text, reply_markup=get_cart_keyboard(user_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith('category_'))
def category_callback(call):
    category_id = call.data.split('_')[1]
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Товары в категории: {categories.get(category_id, 'Неизвестно')}", reply_markup=get_products_in_category_keyboard(category_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith('product_'))
def product_callback(call):
    user_id = call.from_user.id
    product_id = call.data.split('_')[1]
    product = products.get(product_id)
    if product:
        if product['stock'] > 0:
            if user_id not in user_carts:
                user_carts[user_id] = {}
            if product_id in user_carts[user_id]:
                user_carts[user_id][product_id] += 1
            else:
                user_carts[user_id][product_id] = 1
            bot.answer_callback_query(call.id, f"{product['name']} добавлено в корзину!")
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{product['name']} добавлен в корзину.", reply_markup=get_product_list_keyboard())
        else:
            bot.answer_callback_query(call.id, "Товара нет в наличии.")
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Товара '{product['name']}' нет в наличии.", reply_markup=get_product_list_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_from_cart_'))
def remove_from_cart_callback(call):
    user_id = call.from_user.id
    product_id = call.data.split('_')[3]
    if user_carts.get(user_id) and product_id in user_carts[user_id]:
        del user_carts[user_id][product_id]
    cart_text = format_cart(user_id)
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=cart_text, reply_markup=get_cart_keyboard(user_id))
    bot.answer_callback_query(call.id, "Товар удален из корзины.")


# --- Админ панель ---
@bot.message_handler(commands=['admin'])
def admin_command(message):
    user_id = message.from_user.id
    if is_admin(user_id):
        bot.reply_to(message, "Админ панель:", reply_markup=get_admin_menu_keyboard())
        set_user_state(user_id, 'admin_menu')
    else:
        bot.reply_to(message, "Вы не админ.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_menu' and get_user_state(call.from_user.id) == 'admin_menu')
@bot.callback_query_handler(func=lambda call: call.data == 'admin_exit' and get_user_state(call.from_user.id) == 'admin_menu') # Выход из админки
def admin_menu_callback(call):
      user_id = call.from_user.id
      if call.data == 'admin_menu': # Обработка повторного нажатия "Админ меню"
          pass # Ничего не делаем, меню уже показано
      elif call.data == 'admin_exit':
          bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Вы вышли из админ панели.", reply_markup=get_product_list_keyboard())
          clear_user_state(user_id)
          return

      if is_admin(user_id):
          bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Админ панель:", reply_markup=get_admin_menu_keyboard())
          set_user_state(user_id, 'admin_menu')
      else:
          bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_products' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_products_callback(call):
    if is_admin(call.from_user.id):
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Управление товарами:", reply_markup=get_admin_products_keyboard())
        set_user_state(call.from_user.id, 'admin_products_menu')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_categories' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_categories_callback(call):
    if is_admin(call.from_user.id):
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Управление категориями:", reply_markup=get_admin_categories_keyboard())
        set_user_state(call.from_user.id, 'admin_categories_menu')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_promocodes' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_promocodes_callback(call):
    if is_admin(call.from_user.id):
        global promocodes_enabled
        promocodes_enabled = not promocodes_enabled
        status = "Включены" if promocodes_enabled else "Выключены"
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Промокоды {status}.", reply_markup=get_admin_menu_keyboard())
        set_user_state(call.from_user.id, 'admin_menu') # Возвращаемся в админ меню
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_stock' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_stock_callback(call):
     if is_admin(call.from_user.id):
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Управление складом:", reply_markup=get_admin_stock_keyboard())
        set_user_state(call.from_user.id, 'admin_stock_menu')
     else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_export_import' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_export_import_callback(call):
    if is_admin(call.from_user.id):
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Экспорт/Импорт:", reply_markup=get_admin_export_import_keyboard())
        set_user_state(call.from_user.id, 'admin_export_import_menu')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_sales_log' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_sales_log_callback(call):
    if is_admin(call.from_user.id):
        log_text = "Лог Продаж:\n"
        for order in sales_log:
            log_text += f"\nЗаказ от пользователя ID: {order['user_id']} ({order['order_time']})\nСпособ оплаты: {order['payment_method']}\nСостав заказа: {order['cart_items']}\n"
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=log_text if sales_log else "Лог продаж пуст.", reply_markup=get_admin_menu_keyboard())
        set_user_state(call.from_user.id, 'admin_sales_log_view')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_broadcast' and get_user_state(call.from_user.id) == 'admin_menu')
def admin_broadcast_callback(call):
    if is_admin(call.from_user.id):
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Введите сообщение для рассылки:", reply_markup=types.ReplyKeyboardRemove())
        set_user_state(call.from_user.id, 'admin_broadcast_start')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")


@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_broadcast_start' and is_admin(message.from_user.id))
def broadcast_message_handler(message):
    broadcast_text = message.text
    user_ids_to_broadcast = set()

    for order_data in sales_log:
        user_ids_to_broadcast.add(order_data['user_id'])

    broadcast_count = 0
    for user_id in user_ids_to_broadcast:
        try:
            bot.send_message(chat_id=user_id, text=broadcast_text)
            broadcast_count += 1
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    bot.reply_to(message, f"Сообщение отправлено {broadcast_count} пользователям.", reply_markup=get_admin_menu_keyboard())
    set_user_state(message.from_user.id, 'admin_menu') # Вернуться в админ меню


@bot.callback_query_handler(func=lambda call: call.data == 'admin_add_product' and get_user_state(call.from_user.id) == 'admin_products_menu')
def admin_add_product_callback(call):
    if is_admin(call.from_user.id):
        set_user_state(call.from_user.id, 'admin_add_product_name', data={}) # Инициализация данных для нового товара
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Введите название товара:", reply_markup=types.ReplyKeyboardRemove())
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_name' and is_admin(message.from_user.id))
def admin_add_product_name_handler(message):
    user_state_data = get_user_state_data(message.from_user.id)
    user_state_data['name'] = message.text
    set_user_state(message.from_user.id, 'admin_add_product_description', data=user_state_data)
    bot.reply_to(message, "Введите описание товара:")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_description' and is_admin(message.from_user.id))
def admin_add_product_description_handler(message):
    user_state_data = get_user_state_data(message.from_user.id)
    user_state_data['description'] = message.text
    set_user_state(message.from_user.id, 'admin_add_product_price', data=user_state_data)
    bot.reply_to(message, "Введите цену товара:")


@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_price' and is_admin(message.from_user.id))
def admin_add_product_price_handler(message):
    try:
        price = float(message.text)
        user_state_data = get_user_state_data(message.from_user.id)
        user_state_data['price'] = price
        set_user_state(message.from_user.id, 'admin_add_product_category', data=user_state_data)
        bot.reply_to(message, "Введите категорию товара (название):")
    except ValueError:
        bot.reply_to(message, "Пожалуйста, введите цену в виде числа.")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_category' and is_admin(message.from_user.id))
def admin_add_product_category_handler(message):
    category_name = message.text
    category_id_to_use = None
    for cat_id, cat_name in categories.items():
        if cat_name.lower() == category_name.lower():
            category_id_to_use = cat_id
            break
    if not category_id_to_use:
        category_id_to_use = generate_category_id()
        categories[category_id_to_use] = category_name

    user_state_data = get_user_state_data(message.from_user.id)
    user_state_data['category'] = category_id_to_use
    set_user_state(message.from_user.id, 'admin_add_product_stock', data=user_state_data)
    bot.reply_to(message, "Введите количество товара на складе:")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_stock' and is_admin(message.from_user.id))
def admin_add_product_stock_handler(message):
    try:
        stock = int(message.text)
        user_state_data = get_user_state_data(message.from_user.id)
        user_state_data['stock'] = stock
        set_user_state(message.from_user.id, 'admin_add_product_image', data=user_state_data)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton('/skip')) # Кнопка для пропуска фото
        bot.reply_to(message, "Отправьте изображение товара (или /skip чтобы пропустить):", reply_markup=markup)
    except ValueError:
        bot.reply_to(message, "Пожалуйста, введите количество в виде целого числа.")

@bot.message_handler(commands=['skip'], func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_image' and is_admin(message.from_user.id))
def skip_photo_handler(message):
    user_state_data = get_user_state_data(message.from_user.id)
    user_state_data['image'] = None
    new_product_data = user_state_data
    product_id = generate_product_id()
    products[product_id] = new_product_data
    bot.reply_to(message, f"Товар '{new_product_data['name']}' (ID: {product_id}) добавлен без изображения.", reply_markup=get_admin_products_keyboard())
    clear_user_state(message.from_user.id)
    set_user_state(message.from_user.id, 'admin_products_menu')

@bot.message_handler(content_types=['photo'], func=lambda message: get_user_state(message.from_user.id) == 'admin_add_product_image' and is_admin(message.from_user.id))
def admin_add_product_image_handler(message):
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    image_url = f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}' # Сохраняем URL, можно и локально
    user_state_data = get_user_state_data(message.from_user.id)
    user_state_data['image'] = image_url
    new_product_data = user_state_data
    product_id = generate_product_id()
    products[product_id] = new_product_data
    bot.reply_to(message, f"Товар '{new_product_data['name']}' (ID: {product_id}) добавлен успешно.", reply_markup=get_admin_products_keyboard())
    clear_user_state(message.from_user.id)
    set_user_state(message.from_user.id, 'admin_products_menu')


@bot.callback_query_handler(func=lambda call: call.data == 'admin_edit_product' and get_user_state(call.from_user.id) == 'admin_products_menu')
def admin_edit_product_callback(call):
    if is_admin(call.from_user.id):
        markup = types.InlineKeyboardMarkup(row_width=1)
        for prod_id, prod_data in products.items():
            markup.add(types.InlineKeyboardButton(f"{prod_data['name']} (ID: {prod_id})", callback_data=f'admin_edit_product_select_{prod_id}'))
        markup.add(types.InlineKeyboardButton("Вернуться в меню товаров", callback_data='admin_products'))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Выберите товар для редактирования:", reply_markup=markup)
        set_user_state(call.from_user.id, 'admin_edit_product_select_menu') # Состояние выбора товара для редактирования

    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_edit_product_select_') and get_user_state(call.from_user.id) == 'admin_edit_product_select_menu')
def admin_edit_product_select_callback(call):
    if is_admin(call.from_user.id):
        product_id = call.data.split('_')[-1]
        set_user_state(call.from_user.id, 'admin_edit_product_field_select', data={'product_id': product_id}) # Состояние выбора поля для редактирования
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("Название", callback_data='edit_field_name'),
            types.InlineKeyboardButton("Описание", callback_data='edit_field_description'),
            types.InlineKeyboardButton("Цена", callback_data='edit_field_price'),
            types.InlineKeyboardButton("Категория", callback_data='edit_field_category'),
            types.InlineKeyboardButton("Остаток", callback_data='edit_field_stock'),
            types.InlineKeyboardButton("Изображение", callback_data='edit_field_image'),
            types.InlineKeyboardButton("Вернуться к списку товаров", callback_data='admin_edit_product')
        )
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Редактирование товара ID: {product_id}. Выберите поле для редактирования:", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_field_') and get_user_state(call.from_user.id) == 'admin_edit_product_field_select')
def admin_edit_product_field_callback(call):
    if is_admin(call.from_user.id):
        field = call.data.split('_')[-1]
        user_state_data = get_user_state_data(call.from_user.id)
        user_state_data['edit_field'] = field
        set_user_state(call.from_user.id, 'admin_edit_product_value_input', data=user_state_data) # Запрос нового значения
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Введите новое значение для поля '{field}':", reply_markup=types.ReplyKeyboardRemove())
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")


@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_edit_product_value_input' and is_admin(message.from_user.id))
def admin_edit_product_value_handler(message):
    user_state_data = get_user_state_data(message.from_user.id)
    product_id = user_state_data['product_id']
    field = user_state_data['edit_field']
    new_value = message.text

    if field == 'price':
        try:
            new_value = float(new_value)
        except ValueError:
            bot.reply_to(message, "Пожалуйста, введите цену в виде числа.")
            return
    elif field == 'stock':
        try:
            new_value = int(new_value)
        except ValueError:
            bot.reply_to(message, "Пожалуйста, введите количество в виде целого числа.")
            return
    elif field == 'category': # Базовое обновление категории
         category_name = new_value
         category_id_to_use = None
         for cat_id, cat_name in categories.items():
             if cat_name.lower() == category_name.lower():
                 category_id_to_use = cat_id
                 break
         if not category_id_to_use:
             category_id_to_use = generate_category_id()
             categories[category_id_to_use] = category_name
         new_value = category_id_to_use

    products[product_id][field] = new_value
    bot.reply_to(message, f"Поле '{field}' товара ID {product_id} обновлено.", reply_markup=get_admin_products_keyboard())
    clear_user_state(message.from_user.id)
    set_user_state(message.from_user.id, 'admin_products_menu')


@bot.callback_query_handler(func=lambda call: call.data == 'admin_add_category' and get_user_state(call.from_user.id) == 'admin_categories_menu')
def admin_add_category_callback(call):
    if is_admin(call.from_user.id):
        set_user_state(call.from_user.id, 'admin_add_category_name')
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Введите название новой категории:", reply_markup=types.ReplyKeyboardRemove())
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_add_category_name' and is_admin(message.from_user.id))
def admin_add_category_name_handler(message):
    category_name = message.text
    category_id = generate_category_id()
    categories[category_id] = category_name
    bot.reply_to(message, f"Категория '{category_name}' добавлена (ID: {category_id}).", reply_markup=get_admin_categories_keyboard())
    clear_user_state(message.from_user.id)
    set_user_state(message.from_user.id, 'admin_categories_menu')

@bot.callback_query_handler(func=lambda call: call.data == 'admin_view_stock' and get_user_state(call.from_user.id) == 'admin_stock_menu')
def admin_view_stock_callback(call):
    if is_admin(call.from_user.id):
        stock_text = "Остатки товаров:\n"
        for prod_id, prod_data in products.items():
            stock_text += f"- {prod_data['name']} (ID: {prod_id}): {prod_data['stock']} шт.\n"
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=stock_text if products else "Список товаров пуст.", reply_markup=get_admin_stock_keyboard())
        set_user_state(call.from_user.id, 'admin_stock_view')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_adjust_stock' and get_user_state(call.from_user.id) == 'admin_stock_menu')
def admin_adjust_stock_callback(call):
    if is_admin(call.from_user.id):
        markup = types.InlineKeyboardMarkup(row_width=1)
        for prod_id, prod_data in products.items():
            markup.add(types.InlineKeyboardButton(f"{prod_data['name']} (ID: {prod_id})", callback_data=f'admin_adjust_stock_select_{prod_id}'))
        markup.add(types.InlineKeyboardButton("Вернуться в меню склада", callback_data='admin_stock'))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Выберите товар для списания:", reply_markup=markup)
        set_user_state(call.from_user.id, 'admin_adjust_stock_select_menu')

    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_adjust_stock_select_') and get_user_state(call.from_user.id) == 'admin_adjust_stock_select_menu')
def admin_adjust_stock_select_callback(call):
     if is_admin(call.from_user.id):
        product_id = call.data.split('_')[-1]
        set_user_state(call.from_user.id, 'admin_adjust_stock_quantity_input', data={'product_id': product_id})
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Введите количество для списания для товара ID {product_id} (укажите число):", reply_markup=types.ReplyKeyboardRemove())
     else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'admin_adjust_stock_quantity_input' and is_admin(message.from_user.id))
def admin_adjust_stock_quantity_handler(message):
    product_id = get_user_state_data(message.from_user.id)['product_id']
    try:
        quantity_to_reduce = int(message.text)
        if product_id in products:
            products[product_id]['stock'] -= quantity_to_reduce
            if products[product_id]['stock'] < 0:
                products[product_id]['stock'] = 0
            bot.reply_to(message, f"Остаток товара ID {product_id} уменьшен на {quantity_to_reduce}. Текущий остаток: {products[product_id]['stock']}.", reply_markup=get_admin_stock_keyboard())

        else:
            bot.reply_to(message, "Товар не найден.")
        clear_user_state(message.from_user.id)
        set_user_state(message.from_user.id, 'admin_stock_menu') # Вернуться в меню склада
    except ValueError:
        bot.reply_to(message, "Пожалуйста, укажите количество для списания числом.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_export_products' and get_user_state(call.from_user.id) == 'admin_export_import_menu')
def admin_export_products_callback(call):
    if is_admin(call.from_user.id):
         markup = types.InlineKeyboardMarkup()
         markup.add(types.InlineKeyboardButton("CSV", callback_data='export_csv'), types.InlineKeyboardButton("TXT", callback_data='export_txt'))
         bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Выберите формат экспорта:", reply_markup=markup)
         set_user_state(call.from_user.id, 'admin_export_select_format_menu')
    else:
         bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'export_csv' and get_user_state(call.from_user.id) == 'admin_export_select_format_menu')
def export_csv_callback(call):
    if is_admin(call.from_user.id):
        filename = export_products_to_csv()
        with open(filename, 'rb') as file:
            bot.send_document(call.message.chat.id, file)
        clear_user_state(call.from_user.id)
        set_user_state(call.from_user.id, 'admin_export_import_menu') # Вернемся в меню экспорта/импорта
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'export_txt' and get_user_state(call.from_user.id) == 'admin_export_select_format_menu')
def export_txt_callback(call):
    if is_admin(call.from_user.id):
        filename = export_products_to_txt()
        with open(filename, 'rb') as file:
            bot.send_document(call.message.chat.id, file)
        clear_user_state(call.from_user.id)
        set_user_state(call.from_user.id, 'admin_export_import_menu') # Вернемся в меню экспорта/импорта
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_import_products' and get_user_state(call.from_user.id) == 'admin_export_import_menu')
def admin_import_products_callback(call):
    if is_admin(call.from_user.id):
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Отправьте CSV файл с товарами. Поля в CSV должны быть: product_id, name, description, price, category, stock (заголовок обязателен).", reply_markup=types.ReplyKeyboardRemove())
        set_user_state(call.from_user.id, 'admin_import_products_waiting_file')
    else:
        bot.answer_callback_query(call.id, "Нет доступа.")

@bot.message_handler(content_types=['document'], func=lambda message: get_user_state(message.from_user.id) == 'admin_import_products_waiting_file' and is_admin(message.from_user.id))
def import_products_document_handler(message):
    try:
        if message.document.file_name.endswith('.csv'):
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            text_file = downloaded_file.decode('utf-8') # Предполагаем UTF-8. Может потребоваться определение кодировки
            reader = csv.DictReader(text_file.splitlines())
            imported_count = 0
            for row in reader:
                product_id = row.get('product_id') or generate_product_id()
                products[product_id] = {
                    'name': row.get('name', 'Без названия'),
                    'description': row.get('description', ''),
                    'price': float(row.get('price', 0)),
                    'category': row.get('category', 'default_category'), # Или создаем 'default_category' если нет
                    'stock': int(row.get('stock', 0)),
                    'image': row.get('image', None)
                }
                imported_count += 1
            bot.reply_to(message, f"Импортировано {imported_count} товаров из CSV файла.", reply_markup=get_admin_menu_keyboard())

        else:
            bot.reply_to(message, "Пожалуйста, отправьте CSV файл.")

    except Exception as e:
        bot.reply_to(message, f"Ошибка импорта CSV файла: {e}. Проверьте формат файла.", reply_markup=get_admin_menu_keyboard())

    clear_user_state(message.from_user.id)
    set_user_state(message.from_user.id, 'admin_export_import_menu') # Вернемся в меню экспорта


# --- Запуск бота ---
if __name__ == '__main__':
    # Загрузка начальных данных (замените на загрузку из БД или файла)
    categories['1'] = 'Фрукты'
    categories['2'] = 'Овощи'
    products['1'] = {'name': 'Яблоко', 'description': 'Сочное красное яблоко', 'price': 50, 'category': '1', 'stock': 100, 'image': None}
    products['2'] = {'name': 'Банан', 'description': 'Спелый желтый банан', 'price': 30, 'category': '1', 'stock': 50, 'image': None}
    products['3'] = {'name': 'Помидор', 'description': 'Красный спелый помидор', 'price': 60, 'category': '2', 'stock': 75, 'image': None}

    bot.polling(none_stop=True)
