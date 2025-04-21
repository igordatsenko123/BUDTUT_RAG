import os
import subprocess
import pandas as pd
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
from qa_engine import get_answer
from openai import OpenAI

client = OpenAI(api_key=OPENAI_API_KEY)

LOG_FILE = "chat_history.csv"

# === Логгер ===
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

# === Обработка текстовых сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user = update.message.from_user

    log_message(user.id, user.username, update.message.message_id, "text", "question", user_input)

    answer = get_answer(user_input)

    log_message(user.id, user.username, update.message.message_id, "text", "answer", answer)

    await update.message.reply_text(answer)

# === Обработка голосовых сообщений ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    user = update.message.from_user

    input_ogg = "voice.ogg"
    output_wav = "voice.wav"
    await file.download_to_drive(input_ogg)

    subprocess.run(["ffmpeg", "-y", "-i", input_ogg, output_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with open(output_wav, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    recognized_text = response.text
    print(f"🎙️ Распознан текст: {recognized_text}")

    log_message(user.id, user.username, update.message.message_id, "voice", "question", recognized_text)

    answer = get_answer(recognized_text)

    log_message(user.id, user.username, update.message.message_id, "voice", "answer", answer)

    await update.message.reply_text(answer)

    os.remove(input_ogg)
    os.remove(output_wav)

# === Запуск бота ===
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))

print("🤖 Бот запущен!")
app.run_polling()
