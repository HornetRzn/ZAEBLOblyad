import os
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
)
from psycopg2 import connect

app = Flask(__name__)

# Конфигурация
TOKEN = os.getenv('TG_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# Состояния регистрации
REGISTER_NAME, REGISTER_AGE, REGISTER_GENDER, REGISTER_PHOTO, REGISTER_INTERESTS = range(5)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_db():
    try:
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name VARCHAR(100),
                    age INTEGER,
                    gender VARCHAR(10),
                    photo TEXT,
                    interests TEXT[],
                    banned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS likes (
                    id SERIAL PRIMARY KEY,
                    user_from BIGINT,
                    user_to BIGINT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_from, user_to)
                )""")
        conn.commit()
    except Exception as e:
        logger.error(f"Database error: {e}")
    finally:
        if conn:
            conn.close()

init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user.id,))
            if cur.fetchone():
                await update.message.reply_text("🔍 Используйте /search для поиска")
                return
    finally:
        conn.close()

    await update.message.reply_text("👋 Введите ваше имя:")
    return REGISTER_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("📅 Сколько вам лет?")
    return REGISTER_AGE

async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Введите число!")
        return REGISTER_AGE
    context.user_data['age'] = int(update.message.text)
    reply_keyboard = [['Мужской', 'Женский']]
    await update.message.reply_text(
        "🚻 Выберите пол:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return REGISTER_GENDER

async def register_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("📸 Отправьте фото:")
    return REGISTER_PHOTO

async def register_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1].file_id
    context.user_data['photo'] = photo
    await update.message.reply_text("🎮 Укажите интересы через запятую:")
    return REGISTER_INTERESTS

async def register_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    interests = [x.strip() for x in update.message.text.split(',')]
    user = update.message.from_user
    
    conn = connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users 
                (user_id, name, age, gender, photo, interests)
                VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    user.id,
                    context.user_data['name'],
                    context.user_data['age'],
                    context.user_data['gender'],
                    context.user_data['photo'],
                    interests
                ))
        conn.commit()
    except Exception as e:
        logger.error(f"DB error: {e}")
    finally:
        conn.close()
    
    await update.message.reply_text("✅ Профиль создан!")
    return ConversationHandler.END

async def search_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM users 
                WHERE user_id != %s 
                AND banned = FALSE 
                LIMIT 1""", (user.id,))
            profile = cur.fetchone()
            
            if not profile:
                await update.message.reply_text("😢 Анкет нет")
                return

            keyboard = [
                [InlineKeyboardButton("❤️", callback_data=f'like_{profile[0]}'),
                 InlineKeyboardButton("👎", callback_data=f'dislike_{profile[0]}')]
            ]
            await update.message.reply_photo(
                photo=profile[4],
                caption=f"👤 {profile[1]}, {profile[2]}\n🎯 Интересы: {', '.join(profile[5])}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    finally:
        conn.close()

async def like_dislike_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action, target_id = query.data.split('_')
    target_id = int(target_id)
    
    conn = connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            if action == 'like':
                cur.execute("""
                    SELECT * FROM likes 
                    WHERE user_from = %s AND user_to = %s""", (target_id, user_id))
                if cur.fetchone():
                    await context.bot.send_message(user_id, "💌 Взаимный лайк!")
                else:
                    cur.execute("""
                        INSERT INTO likes (user_from, user_to) 
                        VALUES (%s, %s)""", (user_id, target_id))
                    conn.commit()
    finally:
        conn.close()

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        target_id = int(context.args[0])
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET banned = TRUE 
                WHERE user_id = %s""", (target_id,))
            conn.commit()
        await update.message.reply_text(f"🚫 Пользователь {target_id} забанен")
    except:
        await update.message.reply_text("❌ Используйте /ban <user_id>")

def run_flask():
    app.run(host='0.0.0.0', port=10000)

def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_age)],
            REGISTER_GENDER: [MessageHandler(filters.Regex('^(Мужской|Женский)$'), register_gender)],
            REGISTER_PHOTO: [MessageHandler(filters.PHOTO, register_photo)],
            REGISTER_INTERESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_interests)],
        },
        fallbacks=[]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("search", search_profiles))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CallbackQueryHandler(like_dislike_handler))
    
    application.run_polling()

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    bot_thread = threading.Thread(target=run_bot)
    flask_thread.start()
    bot_thread.start()
    flask_thread.join()
    bot_thread.join()
