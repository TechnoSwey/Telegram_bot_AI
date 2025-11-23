import logging
import telebot
from telebot import types
from openai import OpenAI
from database import DatabaseManager
from config import Config, BOT_TOKEN, OPENAI_API_KEY, ADMIN_ID

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Инициализация бота и клиента OpenAI
bot = telebot.TeleBot(BOT_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)
db = DatabaseManager()

# Временные хранилища для многошаговых команд
waiting_for_user_id = {}
waiting_for_promo_data = {}

@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    user = message.from_user
    db_user = db.get_or_create_user(
        tg_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    welcome_text = f"""
🤖 Добро пожаловать, {user.first_name}!

Я - AI-ассистент на базе OpenAI. Вы можете задавать мне любые вопросы!

💫 Ваш баланс: {db_user['balance']} запросов

Доступные команды:
/balance - Проверить баланс
/buy - Купить запросы
/promo - Активировать промокод
/help - Помощь

Для начала просто напишите ваш вопрос!
    """
    
    bot.send_message(message.chat.id, welcome_text)

@bot.message_handler(commands=['help'])
def help_command(message):
    """Обработчик команды /help"""
    help_text = """
📖 Справка по боту:

💬 Просто напишите ваш вопрос - и я постараюсь на него ответить!

💰 Каждый запрос расходует 1 единицу баланса

Доступные команды:
/start - Начать работу
/balance - Проверить баланс
/buy - Купить дополнительные запросы
/promo - Активировать промокод
/help - Эта справка

Для администраторов:
/stat - Статистика
/createpromo - Создать промокод
/give - Начислить запросы
    """
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['balance'])
def balance_command(message):
    """Проверка баланса"""
    user_id = message.from_user.id
    balance = db.get_user_balance(user_id)
    stats = db.get_user_stats(user_id)
    
    balance_text = f"""
💫 Ваш баланс: {balance} запросов

📊 Статистика:
Всего запросов: {stats['total_requests']}
Доступно сейчас: {balance}

💡 Пополнить баланс: /buy
🎁 Активировать промокод: /promo
    """
    bot.send_message(message.chat.id, balance_text)

@bot.message_handler(commands=['buy'])
def buy_command(message):
    """Покупка запросов"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    prices = [
        ("10 запросов", 10),
        ("25 запросов", 25),
        ("50 запросов", 50),
        ("100 запросов", 100)
    ]
    
    for label, amount in prices:
        callback_data = f"buy_{amount}"
        markup.add(types.InlineKeyboardButton(label, callback_data=callback_data))
    
    bot.send_message(
        message.chat.id,
        "💰 Выберите пакет запросов для покупки:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy_callback(call):
    """Обработка выбора пакета запросов"""
    amount = int(call.data.split('_')[1])
    create_invoice(call.message.chat.id, call.from_user.id, amount)

def create_invoice(chat_id, user_id, amount):
    """Создание инвойса для оплаты"""
    prices = [types.LabeledPrice(label=f"{amount} запросов", amount=amount)]
    
    bot.send_invoice(
        chat_id=chat_id,
        title=f"Покупка {amount} запросов",
        description=f"Пополнение баланса на {amount} запросов к AI-ассистенту",
        invoice_payload=f"requests_{amount}_{user_id}",
        provider_token="",  # Для Stars оставляем пустым
        currency="XTR",
        prices=prices
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    """Обработка предварительной проверки платежа"""
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    """Обработка успешного платежа"""
    payment_info = message.successful_payment
    
    # Парсим payload для получения данных
    payload_parts = payment_info.invoice_payload.split('_')
    amount = int(payload_parts[1])
    user_id = int(payload_parts[2])
    
    # Добавляем запись о платеже
    db.add_payment(
        tg_id=user_id,
        amount=amount,
        stars_paid=amount,
        payment_id=payment_info.telegram_payment_charge_id
    )
    
    bot.send_message(
        message.chat.id,
        f"✅ Оплата прошла успешно! Ваш баланс пополнен на {amount} запросов."
    )

@bot.message_handler(commands=['promo'])
def promo_command(message):
    """Активация промокода"""
    bot.send_message(message.chat.id, "🎁 Введите промокод:")
    bot.register_next_step_handler(message, process_promo_code)

def process_promo_code(message):
    """Обработка введенного промокода"""
    promo_code = message.text.strip().upper()
    user_id = message.from_user.id
    
    success, requests_added = db.use_promo_code(promo_code, user_id)
    
    if success:
        bot.send_message(
            message.chat.id,
            f"✅ Промокод активирован! Вам начислено {requests_added} запросов."
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Неверный промокод, либо он уже был использован."
        )

# Админские команды
@bot.message_handler(commands=['stat'])
def stat_command(message):
    """Статистика (только для админа)"""
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ У вас нет прав для этой команды.")
        return
    
    users = db.get_all_users_stats()
    total_users = len(users)
    total_requests = sum(user['total_requests'] for user in users)
    active_users = len([user for user in users if user['total_requests'] > 0])
    
    stat_text = f"""
📊 Статистика бота:

👥 Пользователи: {total_users}
📈 Активные: {active_users}
💬 Всего запросов: {total_requests}

📋 Последние пользователи:
"""
    
    for user in users[:10]:  # Показываем последних 10 пользователей
        username = user['username'] or f"{user['first_name']} {user['last_name'] or ''}"
        stat_text += f"\n👤 {username} | 💰 {user['balance']} | 📞 {user['total_requests']}"
    
    bot.send_message(message.chat.id, stat_text)

@bot.message_handler(commands=['give'])
def give_requests_command(message):
    """Начисление запросов пользователю (админ)"""
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ У вас нет прав для этой команды.")
        return
    
    bot.send_message(message.chat.id, "👤 Введите Telegram ID пользователя:")
    bot.register_next_step_handler(message, process_give_user_id)

def process_give_user_id(message):
    """Обработка ID пользователя для начисления"""
    try:
        user_id = int(message.text.strip())
        waiting_for_user_id[message.from_user.id] = user_id
        
        bot.send_message(message.chat.id, "💰 Введите количество запросов:")
        bot.register_next_step_handler(message, process_give_amount)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат ID")

def process_give_amount(message):
    """Обработка количества запросов для начисления"""
    try:
        amount = int(message.text.strip())
        admin_id = message.from_user.id
        user_id = waiting_for_user_id.get(admin_id)
        
        if user_id:
            success = db.update_user_balance(user_id, amount)
            if success:
                bot.send_message(
                    message.chat.id,
                    f"✅ Пользователю {user_id} начислено {amount} запросов."
                )
                # Уведомляем пользователя
                try:
                    bot.send_message(
                        user_id,
                        f"🎁 Вам начислено {amount} запросов администратором!"
                    )
                except:
                    pass  # Пользователь может не начать диалог с ботом
            else:
                bot.send_message(message.chat.id, "❌ Ошибка начисления запросов.")
            
            # Очищаем временные данные
            waiting_for_user_id.pop(admin_id, None)
        else:
            bot.send_message(message.chat.id, "❌ Ошибка: данные не найдены.")
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат количества")

@bot.message_handler(commands=['createpromo'])
def create_promo_command(message):
    """Создание промокода (админ)"""
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ У вас нет прав для этой команды.")
        return
    
    waiting_for_promo_data[message.from_user.id] = {}
    bot.send_message(message.chat.id, "🏷️ Введите код промокода:")
    bot.register_next_step_handler(message, process_promo_code_input)

def process_promo_code_input(message):
    """Обработка ввода кода промокода"""
    code = message.text.strip().upper()
    admin_id = message.from_user.id
    
    if admin_id in waiting_for_promo_data:
        waiting_for_promo_data[admin_id]['code'] = code
        bot.send_message(message.chat.id, "💰 Введите количество запросов для промокода:")
        bot.register_next_step_handler(message, process_promo_requests)

def process_promo_requests(message):
    """Обработка количества запросов для промокода"""
    try:
        requests = int(message.text.strip())
        admin_id = message.from_user.id
        
        if admin_id in waiting_for_promo_data:
            waiting_for_promo_data[admin_id]['requests'] = requests
            bot.send_message(
                message.chat.id,
                "🔢 Введите максимальное количество использований (0 - без лимита):"
            )
            bot.register_next_step_handler(message, process_promo_max_uses)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат количества")

def process_promo_max_uses(message):
    """Обработка максимального количества использований промокода"""
    try:
        max_uses = int(message.text.strip())
        admin_id = message.from_user.id
        
        if admin_id in waiting_for_promo_data:
            promo_data = waiting_for_promo_data[admin_id]
            
            result = db.create_promo_code(
                code=promo_data['code'],
                requests=promo_data['requests'],
                max_uses=max_uses if max_uses > 0 else None
            )
            
            if result:
                uses_text = "без лимита" if max_uses <= 0 else f"{max_uses} использований"
                bot.send_message(
                    message.chat.id,
                    f"✅ Промокод создан!\n"
                    f"Код: {promo_data['code']}\n"
                    f"Запросов: {promo_data['requests']}\n"
                    f"Лимит: {uses_text}"
                )
            else:
                bot.send_message(message.chat.id, "❌ Ошибка создания промокода.")
            
            # Очищаем временные данные
            waiting_for_promo_data.pop(admin_id, None)
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат количества")

# Обработка текстовых сообщений (запросов к AI)
@bot.message_handler(content_types=['text'])
def handle_text_message(message):
    """Обработка текстовых сообщений (запросов к AI)"""
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    # Проверяем баланс
    balance = db.get_user_balance(user_id)
    if balance <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Недостаточно запросов. Пополните баланс: /buy\n"
            "🎁 Или используйте промокод: /promo"
        )
        return
    
    # Отправляем сообщение о обработке
    processing_msg = bot.send_message(message.chat.id, "⏳ Обрабатываю запрос...")
    
    try:
        # Отправляем запрос к OpenAI
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты полезный AI-ассистент. Отвечай понятно и подробно."},
                {"role": "user", "content": user_text}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        ai_response = response.choices[0].message.content
        tokens_used = response.usage.total_tokens
        
        # Сохраняем запрос в базу и уменьшаем баланс
        db.add_request(user_id, user_text, ai_response, tokens_used)
        
        # Отправляем ответ пользователю
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=processing_msg.message_id,
            text=f"{ai_response}\n\n💫 Осталось запросов: {balance - 1}"
        )
        
    except Exception as e:
        logging.error(f"Ошибка OpenAI: {e}")
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=processing_msg.message_id,
            text="❌ Произошла ошибка при обработке запроса. Попробуйте позже."
        )

if __name__ == "__main__":
    # Проверяем конфигурацию
    try:
        Config.validate()
        logging.info("Бот запускается...")
        bot.infinity_polling()
    except Exception as e:
        logging.error(f"Ошибка запуска бота: {e}")
