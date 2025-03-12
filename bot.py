import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext
)
from psycopg2 import connect, sql

# Конфигурация
TOKEN = os.getenv('TG_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Инициализация БД
def init_db():
    conn = connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE,
                name VARCHAR(50),
                age INTEGER,
                gender VARCHAR(10),
                photo TEXT,
                interests TEXT[],
                banned BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS likes (
                id SERIAL PRIMARY KEY,
                user_from INTEGER,
                user_to INTEGER,
                UNIQUE(user_from, user_to)
            );
        """)
    conn.commit()
    conn.close()

init_db()

# Состояния
REGISTER, EDIT = range(2)

def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    conn = connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user.id,))
        if not cur.fetchone():
            update.message.reply_text("👋 Добро пожаловать! Давайте создадим ваш профиль.\nВведите ваше имя:")
            return REGISTER
        else:
            show_profile(update, user.id)
    conn.close()
    return ConversationHandler.END

def register_name(update: Update, context: CallbackContext):
    context.user_data['name'] = update.message.text
    update.message.reply_text("📅 Сколько вам лет?")
    return REGISTER

def register_age(update: Update, context: CallbackContext):
    context.user_data['age'] = update.message.text
    reply_keyboard = [['Мужской', 'Женский']]
    update.message.reply_text(
        "🚻 Выберите ваш пол:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return REGISTER

def register_gender(update: Update, context: CallbackContext):
    context.user_data['gender'] = update.message.text
    update.message.reply_text("📸 Пришлите ваше фото:")
    return REGISTER

def register_photo(update: Update, context: CallbackContext):
    photo = update.message.photo[-1].file_id
    context.user_data['photo'] = photo
    update.message.reply_text("🎮 Укажите ваши интересы через запятую:")
    return REGISTER

def register_interests(update: Update, context: CallbackContext):
    interests = [x.strip() for x in update.message.text.split(',')]
    user = update.message.from_user
    conn = connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (user_id, name, age, gender, photo, interests)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user.id, context.user_data['name'], context.user_data['age'], 
             context.user_data['gender'], context.user_data['photo'], interests))
    conn.commit()
    conn.close()
    update.message.reply_text("✅ Профиль создан! Используйте /search для поиска")
    return ConversationHandler.END

def search_profiles(update: Update, context: CallbackContext):
    user = update.message.from_user
    conn = connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM users 
            WHERE user_id != %s 
            AND banned = FALSE 
            LIMIT 1
        """, (user.id,))
        profile = cur.fetchone()
        if profile:
            keyboard = [
                [InlineKeyboardButton("❤️", callback_data=f'like_{profile[1]}'),
                 InlineKeyboardButton("👎", callback_data=f'dislike_{profile[1]}')]
            ]
            update.message.reply_photo(
                photo=profile[5],
                caption=f"👤 {profile[2]}, {profile[3]}\n🎯 Интересы: {', '.join(profile[6])}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            update.message.reply_text("😢 Больше анкет нет")
    conn.close()

def like_dislike_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    action, target_id = query.data.split('_')
    user_id = query.from_user.id
    
    conn = connect(DATABASE_URL)
    with conn.cursor() as cur:
        if action == 'like':
            cur.execute("""
                INSERT INTO likes (user_from, user_to)
                VALUES (%s, %s)
                RETURNING id
            """, (user_id, target_id))
            
            cur.execute("""
                SELECT * FROM likes 
                WHERE user_from = %s AND user_to = %s
            """, (target_id, user_id))
            if cur.fetchone():
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"💌 У вас взаимная симпатия с пользователем {target_id}! Напишите сообщение:"
                )
                context.bot.send_message(
                    chat_id=target_id,
                    text=f"💌 Пользователь {user_id} тоже вас лайкнул! Напишите сообщение:"
                )
        else:
            cur.execute("""
                DELETE FROM likes 
                WHERE user_from = %s AND user_to = %s
            """, (user_id, target_id))
    conn.commit()
    conn.close()
    query.answer()

# Админ-команды
def ban_user(update: Update, context: CallbackContext):
    if update.message.from_user.id == ADMIN_ID:
        target_id = int(context.args[0])
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET banned = TRUE 
                WHERE user_id = %s
            """, (target_id,))
        conn.commit()
        conn.close()
        update.message.reply_text(f"🚫 Пользователь {target_id} забанен")

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REGISTER: [
                MessageHandler(Filters.text & ~Filters.command, register_name),
                MessageHandler(Filters.photo, register_photo),
                MessageHandler(Filters.regex('^(Мужской|Женский)$'), register_gender),
                MessageHandler(Filters.text & ~Filters.command, register_interests)
            ]
        },
        fallbacks=[]
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler("search", search_profiles))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CallbackQueryHandler(like_dislike_handler))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
