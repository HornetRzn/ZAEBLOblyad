import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext,
    ConversationHandler, CallbackQueryHandler
)
import psycopg2

# Настройки
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Состояния анкеты
NAME, AGE, ORIENTATION, ROLE, LOCATION, BIO, PHOTO = range(7)

# Подключение к базе
def get_db():
    return psycopg2.connect(DATABASE_URL)

# Создание таблиц
def create_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age INTEGER,
            orientation TEXT,
            role TEXT,
            location TEXT,
            bio TEXT,
            photos TEXT[]
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# /start
def start(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("👋 Привет! Давай создадим твою анкету. Как тебя зовут?")
    return NAME

# Имя
def name(update: Update, context: CallbackContext) -> int:
    context.user_data['name'] = update.message.text
    update.message.reply_text("📅 Сколько тебе лет?")
    return AGE

# Возраст
def age(update: Update, context: CallbackContext) -> int:
    try:
        age = int(update.message.text)
        context.user_data['age'] = age
    except:
        update.message.reply_text("❌ Введи число! Например: 25")
        return AGE

    keyboard = [
        [InlineKeyboardButton("Гей", callback_data="гей")],
        [InlineKeyboardButton("Би", callback_data="би")],
        [InlineKeyboardButton("Транс", callback_data="транс")],
        [InlineKeyboardButton("Гетеро", callback_data="гетеро")],
        [InlineKeyboardButton("Другое", callback_data="другое")],
    ]
    update.message.reply_text("🌈 Твоя ориентация:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ORIENTATION

# Ориентация
def orientation(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    context.user_data['orientation'] = query.data
    query.edit_message_text(f"Ориентация: {query.data}")
    query.message.reply_text("🔥 Твоя роль в сексе:")
    return ROLE

# Роль
def role(update: Update, context: CallbackContext) -> int:
    context.user_data['role'] = update.message.text
    update.message.reply_text("📍 В каком районе Рязани/области ты живешь?")
    return LOCATION

# Локация
def location(update: Update, context: CallbackContext) -> int:
    context.user_data['location'] = update.message.text
    update.message.reply_text("📝 Расскажи о себе и кого хочешь найти:")
    return BIO

# О себе
def bio(update: Update, context: CallbackContext) -> int:
    context.user_data['bio'] = update.message.text
    update.message.reply_text("📸 Прикрепи 1-3 фото или видео (до 15 сек). Отправь 'Готово', когда закончишь.")
    return PHOTO

# Фото/видео
def photo(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data
    if 'photos' not in user_data:
        user_data['photos'] = []

    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        user_data['photos'].append(photo_id)
    elif update.message.video:
        video_id = update.message.video.file_id
        user_data['photos'].append(video_id)
    elif update.message.text.lower() == 'готово':
        return save_data(update, context)

    if len(user_data['photos']) >= 3:
        return save_data(update, context)
    else:
        update.message.reply_text("✅ Файл сохранен. Можно отправить ещё или 'Готово'.")
        return PHOTO

# Сохранение в базу
def save_data(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    data = context.user_data

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO users (user_id, name, age, orientation, role, location, bio, photos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                name = excluded.name,
                age = excluded.age,
                orientation = excluded.orientation,
                role = excluded.role,
                location = excluded.location,
                bio = excluded.bio,
                photos = excluded.photos
        ''', (
            user.id,
            data['name'],
            data['age'],
            data['orientation'],
            data['role'],
            data['location'],
            data['bio'],
            data.get('photos', [])
        ))
        conn.commit()
        update.message.reply_text("🎉 Анкета сохранена! Скоро найдем тебе пару!")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        update.message.reply_text("😢 Что-то пошло не так. Попробуй позже.")
    finally:
        cur.close()
        conn.close()

    return ConversationHandler.END

# Запуск
def main():
    create_tables()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(Filters.text, name)],
            AGE: [MessageHandler(Filters.text, age)],
            ORIENTATION: [CallbackQueryHandler(orientation)],
            ROLE: [MessageHandler(Filters.text, role)],
            LOCATION: [MessageHandler(Filters.text, location)],
            BIO: [MessageHandler(Filters.text, bio)],
            PHOTO: [MessageHandler(Filters.photo | Filters.video | Filters.text, photo)],
        },
        fallbacks=[]
    )

    dp.add_handler(conv_handler)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
