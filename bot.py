import os
import logging
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
from psycopg2 import connect, Error

# ================== НАСТРОЙКИ ==================
TOKEN = os.getenv('TG_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))  # Ваш ID через @userinfobot

# Состояния регистрации
REGISTER_NAME, REGISTER_AGE, REGISTER_GENDER, REGISTER_PHOTO, REGISTER_INTERESTS = range(5)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== БАЗА ДАННЫХ ==================
def init_db():
    """Инициализация таблиц в базе данных"""
    conn = None
    try:
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            # Таблица пользователей
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    age INTEGER NOT NULL,
                    gender VARCHAR(10) NOT NULL,
                    photo TEXT NOT NULL,
                    interests TEXT[] NOT NULL,
                    banned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )""")

            # Таблица лайков
            cur.execute("""
                CREATE TABLE IF NOT EXISTS likes (
                    id SERIAL PRIMARY KEY,
                    user_from BIGINT NOT NULL,
                    user_to BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_from, user_to)
                )""")
            
            # Индекс для быстрого поиска
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_search 
                ON users (gender, age)
            """)
        conn.commit()
        logger.info("Таблицы созданы успешно")
    except Error as e:
        logger.error(f"Ошибка БД: {e}")
    finally:
        if conn:
            conn.close()

init_db()

# ================== ОСНОВНЫЕ КОМАНДЫ ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.message.from_user
    conn = None
    try:
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user.id,))
            if cur.fetchone():
                await update.message.reply_text(
                    "👋 С возвращением! Используйте команды:\n"
                    "/search - Поиск анкет\n"
                    "/edit - Редактировать профиль"
                )
                return
    except Error as e:
        logger.error(f"Ошибка: {e}")
    finally:
        if conn:
            conn.close()

    await update.message.reply_text("👋 Введите ваше имя:")
    return REGISTER_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик имени"""
    context.user_data['name'] = update.message.text
    await update.message.reply_text("📅 Сколько вам лет?")
    return REGISTER_AGE

async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик возраста"""
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Возраст должен быть числом! Повторите:")
        return REGISTER_AGE
    
    context.user_data['age'] = int(update.message.text)
    reply_keyboard = [['Мужской', 'Женский']]
    await update.message.reply_text(
        "🚻 Выберите ваш пол:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return REGISTER_GENDER

async def register_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик пола"""
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("📸 Отправьте ваше фото:")
    return REGISTER_PHOTO

async def register_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фото"""
    photo = update.message.photo[-1].file_id
    context.user_data['photo'] = photo
    await update.message.reply_text("🎮 Укажите ваши интересы через запятую:")
    return REGISTER_INTERESTS

async def register_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик интересов"""
    interests = [x.strip() for x in update.message.text.split(',')]
    user = update.message.from_user
    
    conn = None
    try:
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users 
                (user_id, name, age, gender, photo, interests)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    age = EXCLUDED.age,
                    gender = EXCLUDED.gender,
                    photo = EXCLUDED.photo,
                    interests = EXCLUDED.interests
            """, (
                user.id,
                context.user_data['name'],
                context.user_data['age'],
                context.user_data['gender'],
                context.user_data['photo'],
                interests
            ))
        conn.commit()
        await update.message.reply_text("✅ Профиль обновлен!")
    except Error as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Ошибка сохранения профиля")
    finally:
        if conn:
            conn.close()
    return ConversationHandler.END

# ================== ПОИСК И ЛАЙКИ ==================
async def search_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск анкет"""
    user = update.message.from_user
    conn = None
    try:
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM users 
                WHERE user_id != %s 
                AND banned = FALSE 
                ORDER BY RANDOM() 
                LIMIT 1
            """, (user.id,))
            profile = cur.fetchone()
            
            if not profile:
                await update.message.reply_text("😢 Анкет пока нет")
                return

            keyboard = [
                [
                    InlineKeyboardButton("❤️", callback_data=f'like_{profile[0]}'),
                    InlineKeyboardButton("👎", callback_data=f'dislike_{profile[0]}')
                ]
            ]
            await update.message.reply_photo(
                photo=profile[4],
                caption=f"👤 {profile[1]}, {profile[2]}\n🎯 Интересы: {', '.join(profile[5])}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Error as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Ошибка поиска")
    finally:
        if conn:
            conn.close()

async def like_dislike_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик лайков"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action, target_id = query.data.split('_')
    target_id = int(target_id)
    
    conn = None
    try:
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            if action == 'like':
                cur.execute("""
                    SELECT * FROM likes 
                    WHERE user_from = %s AND user_to = %s
                """, (target_id, user_id))
                
                if cur.fetchone():
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"💌 Взаимная симпатия! Пишите: @{target_id}"
                    )
                    await context.bot.send_message(
                        chat_id=target_id,
                        text=f"💌 Пользователь @{query.from_user.username} тоже вас лайкнул!"
                    )
                else:
                    cur.execute("""
                        INSERT INTO likes (user_from, user_to) 
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                    """, (user_id, target_id))
                    conn.commit()
            else:
                cur.execute("""
                    DELETE FROM likes 
                    WHERE user_from = %s AND user_to = %s
                """, (user_id, target_id))
                conn.commit()
    except Error as e:
        logger.error(f"Ошибка: {e}")
    finally:
        if conn:
            conn.close()

# ================== АДМИН-ПАНЕЛЬ ==================
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бан пользователя"""
    if update.message.from_user.id != ADMIN_ID:
        return
    
    try:
        target_id = int(context.args[0])
        conn = connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET banned = TRUE 
                WHERE user_id = %s
            """, (target_id,))
            conn.commit()
        await update.message.reply_text(f"🚫 Пользователь {target_id} забанен")
    except:
        await update.message.reply_text("❌ Используйте: /ban <user_id>")

# ================== ЗАПУСК БОТА ==================
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # Обработчик регистрации
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

    # Регистрация команд
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("search", search_profiles))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CallbackQueryHandler(like_dislike_handler))

    # Запуск
    application.run_polling()
    logger.info("Бот успешно запущен!")

if __name__ == '__main__':
    main()
