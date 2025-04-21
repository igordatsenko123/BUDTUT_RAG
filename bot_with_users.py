import os
import json
import subprocess
import pandas as pd
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, ContextTypes,
    CommandHandler, ConversationHandler
)
from telegram.ext import filters
from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
from qa_engine import get_answer
from openai import OpenAI

client = OpenAI(api_key=OPENAI_API_KEY)

# === Файлы ===
USER_FILE = "user_info.json"
LOG_FILE = "chat_history.csv"

# === Состояния анкеты ===
NAME, SURNAME, PHONE, SPECIALTY = range(4)

# === Кнопки меню ===
menu_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("📋 Профиль")], [KeyboardButton("✏️ Обновить анкету")]],
    resize_keyboard=True
)

# === Логирование ===
def log_message(user_id, username, msg_id, msg_type, role, content):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_entry = {
        "user_id": user_id,
        "username": username,
        "datetime": timestamp,
        "message_id": msg_id,
        "message_type": msg_type,
        "role": role,
        "content": content
    }
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE)
        df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
    else:
        df = pd.DataFrame([new_entry])
    df.to_csv(LOG_FILE, index=False)

# === Проверка регистрации ===
def is_registered(user_id):
    if not os.path.exists(USER_FILE):
        return False
    with open(USER_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return str(user_id) in data

# === Анкета ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_registered(user_id):
        name = json.load(open(USER_FILE, encoding="utf-8"))[str(user_id)]["name"]
        await update.message.reply_text(
            f"С возвращением, {name}!\nВыбери, что хочешь сделать:",
            reply_markup=menu_keyboard
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Привет! Давай сначала заполним анкету. Как тебя зовут?",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
        )
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Фамилия?")
    return SURNAME

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["surname"] = update.message.text
    await update.message.reply_text("Телефон?")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Специальность?")
    return SPECIALTY

async def get_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["specialty"] = update.message.text
    user_id = str(update.effective_user.id)

    user_info = {
        "name": context.user_data["name"],
        "surname": context.user_data["surname"],
        "phone": context.user_data["phone"],
        "specialty": context.user_data["specialty"]
    }

    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    data[user_id] = user_info

    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    await update.message.reply_text("Спасибо! Теперь давай продолжим общение 😊", reply_markup=menu_keyboard)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Анкета отменена.")
    return ConversationHandler.END

# === Показ профиля ===
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_registered(user_id):
        await update.message.reply_text("Ты ещё не зарегистрирован. Напиши /start.")
        return
    with open(USER_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    user = data[user_id]
    profile_text = (
        f"👤 *Твоя анкета:*\n"
        f"Имя: {user['name']}\n"
        f"Фамилия: {user['surname']}\n"
        f"Телефон: {user['phone']}\n"
        f"Специальность: {user['specialty']}"
    )
    await update.message.reply_text(profile_text, parse_mode="Markdown")

# === Повторная анкета ===
async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Обновим анкету. Как тебя зовут?")
    return NAME

# === Ответ на текст ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text == "📋 Профиль":
        return await show_profile(update, context)
    elif text == "✏️ Обновить анкету":
        return await update_profile(update, context)

    if not is_registered(user_id):
        await update.message.reply_text("Сначала нужно заполнить анкету. Напиши /start.")
        return

    user = update.effective_user
    log_message(user.id, user.username, update.message.message_id, "text", "question", text)

    answer = get_answer(text)

    log_message(user.id, user.username, update.message.message_id, "text", "answer", answer)
    await update.message.reply_text(answer)

# === Ответ на голос ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("Сначала нужно заполнить анкету. Напиши /start.")
        return

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    user = update.message.from_user

    input_ogg = "voice.ogg"
    output_wav = "voice.wav"
    await file.download_to_drive(input_ogg)

    subprocess.run(["ffmpeg", "-y", "-i", input_ogg, output_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with open(output_wav, "rb") as f:
        response = client.audio.transcriptions.create(model="whisper-1", file=f)
    recognized_text = response.text

    log_message(user.id, user.username, update.message.message_id, "voice", "question", recognized_text)

    answer = get_answer(recognized_text)

    log_message(user.id, user.username, update.message.message_id, "voice", "answer", answer)
    await update.message.reply_text(answer)

    os.remove(input_ogg)
    os.remove(output_wav)

# === Запуск ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            SPECIALTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_specialty)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("profile", show_profile))
    app.add_handler(CommandHandler("update_profile", update_profile))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))



    print("🤖 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
