import os
import time
import telebot
from telebot import types
import whisper
import base64
import re
from openai import OpenAI 
from database import Database

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
db = Database()

# --- БИБЛИОТЕКИ LLAMA INDEX (RAG) ---
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings, Document
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ==========================================
# 1. НАСТРОЙКИ СИСТЕМЫ (ВАЖНО!)
# ==========================================

# 1.1. Исправляем путь, чтобы Python видел ffmpeg.exe в текущей папке
# ВАЖНО: Тут должно быть __file__ (два подчеркивания с каждой стороны)
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.environ["PATH"] += os.pathsep + current_dir
except NameError:
    # Если запускаете через интерактивную консоль, __file__ может не быть
    pass

# 1.2. Отключаем прокси (чтобы телеграм не вис)
os.environ['NO_PROXY'] = 'api.telegram.org'
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(key, None)

# 1.3. Отключаем лишние предупреждения
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

# 1.4. Папка для базы знаний
KNOWLEDGE_DIR = "./my_knowledge"
if not os.path.exists(KNOWLEDGE_DIR):
    os.makedirs(KNOWLEDGE_DIR)

# ==========================================
# 2. КОНФИГУРАЦИЯ БОТА
# ==========================================
TELEGRAM_TOKEN = '7502929605:AAEKTy1yX3FRe9dPbQ5cK14MckcjySj2diY' 
LM_STUDIO_URL = "http://localhost:1234/v1"

print("⚙️ Настраиваю нейросети...")

# Настройка "Мозга" (LLM)
Settings.llm = OpenAILike(
    model="local-model",
    api_base=LM_STUDIO_URL,
    api_key="lm-studio",
    is_chat_model=True,
    context_window=8192,
    timeout=120.0
)

# Настройка "Памяти" (Embeddings)
Settings.embed_model = HuggingFaceEmbedding(
    model_name="intfloat/multilingual-e5-small"
)

# Глобальная переменная для чат-движка
chat_engine = None

# ==========================================
# 3. ИНИЦИАЛИЗАЦИЯ
# ==========================================
print("⏳ Загружаю Whisper (Голос)...")
try:
    audio_model = whisper.load_model("base")
    print("✅ Whisper загружен!")
except Exception as e:
    audio_model = None
    print(f"⚠️ Whisper не работает: {e}")

vision_client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Настройка команд в меню (слева внизу)
bot.set_my_commands([
    telebot.types.BotCommand("/start", "🔄 Главное меню"),
    telebot.types.BotCommand("/clear", "🧹 Очистить контекст"),
    telebot.types.BotCommand("/files", "📂 Список файлов"),
    telebot.types.BotCommand("/help", "❓ Помощь")
])

# ==========================================
# 4. ЛОГИКА RAG (БАЗА ЗНАНИЙ)
# ==========================================
def rebuild_index():
    """Перечитывает папку и создает умный чат"""
    global chat_engine
    print("📚 Индексация базы знаний...")
    
    if not os.listdir(KNOWLEDGE_DIR):
        documents = []
    else:
        documents = SimpleDirectoryReader(KNOWLEDGE_DIR).load_data()
    
    # Заглушка, если папка пустая
    if not documents:
        documents = [Document(text="Инструкция: У тебя пока нет внешних файлов. Используй свои знания.")]

    index = VectorStoreIndex.from_documents(documents)
    
    # Память диалога (4000 токенов)
    memory = ChatMemoryBuffer.from_defaults(token_limit=4000)

    # Создаем движок в режиме "Context Chat"
    chat_engine = index.as_chat_engine(
        chat_mode="context",
        memory=memory,
        system_prompt=(
            "Ты полезный ИИ-ассистент. "
            "1. Используй контекст из базы знаний для ответов. "
            "2. Если в базе нет ответа, отвечай, используя свои общие знания. "
            "3. Будь вежлив."
        ),
        similarity_top_k=3
    )
    print("✅ База знаний обновлена!")

# Первичный запуск
rebuild_index()

# ==========================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def clean_think_tags(text):
    """Удаляет мысли <think>...</think>"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

def get_main_keyboard():
    """Создает кнопки меню"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🧹 Очистить контекст")
    btn2 = types.KeyboardButton("📄 Показать файлы")
    btn3 = types.KeyboardButton("❓ Помощь")
    markup.add(btn1, btn2)
    markup.add(btn3)
    return markup

def safe_send(chat_id, text, markup=None):
    """Безопасная отправка (защита от сбоев сети)"""
    if not text: return
    # Если маркап не передан, используем главное меню, чтобы кнопки не пропадали
    if markup is None: 
        markup = get_main_keyboard()
        
    for i in range(3):
        try:
            bot.send_message(chat_id, text, reply_markup=markup)
            return
        except Exception as e:
            time.sleep(2)

def split_and_send(message, text):
    """Режет длинный текст"""
    parts = []
    while len(text) > 0:
        if len(text) > 1500:
            split = text.rfind(' ', 0, 1500)
            if split == -1: split = 1500
            parts.append(text[:split])
            text = text[split:].lstrip()
        else:
            parts.append(text)
            text = ""
    for part in parts:
        safe_send(message.chat.id, part)
        time.sleep(1)

# ==========================================
# 6. ОБРАБОТЧИКИ СООБЩЕНИЙ
# ==========================================

# --- КОМАНДА /START ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Сохраняем пользователя в БД
    db.add_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    
    safe_send(message.chat.id, 
              "👋 Привет! Я готов к работе.\n"
              "📄 Кидай файлы для базы знаний.\n"
              "📷 Кидай фото для анализа.\n"
              "🎤 Говори голосом или пиши текст.",
              markup=get_main_keyboard())

# --- КНОПКА: ОЧИСТИТЬ ---
@bot.message_handler(func=lambda message: message.text == "🧹 Очистить контекст" or message.text == "/clear")
def clear_memory(message):
    chat_engine.reset()
    db.clear_history(message.chat.id) # Очищаем историю в БД
    safe_send(message.chat.id, "🧠 Память диалога очищена! Начинаем с чистого листа.")

# --- КНОПКА: ФАЙЛЫ ---
@bot.message_handler(func=lambda message: message.text == "📄 Показать файлы" or message.text == "/files")
def show_files(message):
    files = os.listdir(KNOWLEDGE_DIR)
    if not files:
        msg = "📂 Папка пуста."
    else:
        msg = "📂 **Файлы в базе:**\n" + "\n".join([f"- {f}" for f in files])
    safe_send(message.chat.id, msg)

# --- КНОПКА: ПОМОЩЬ ---
@bot.message_handler(func=lambda message: message.text == "❓ Помощь" or message.text == "/help")
def help_message(message):
    msg = (
        "🤖 **Инструкция:**\n"
        "• Отправь **PDF/DOCX/TXT**, чтобы я выучил их содержимое.\n"
        "• Отправь **Голосовое**, я переведу его в текст и отвечу.\n"
        "• Отправь **Фото**, и я опишу, что на нем.\n"
        "• Нажми **Очистить контекст**, если я запутался."
    )
    safe_send(message.chat.id, msg)

# --- ЗАГРУЗКА ДОКУМЕНТОВ ---
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        f_name = message.document.file_name
        safe_send(message.chat.id, f"📥 Скачиваю {f_name}...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        save_path = os.path.join(KNOWLEDGE_DIR, f_name)
        with open(save_path, 'wb') as f:
            f.write(downloaded)
            
        rebuild_index() # Пересобираем базу
        safe_send(message.chat.id, "✅ Файл изучен! Можете задавать вопросы.")
    except Exception as e:
        safe_send(message.chat.id, f"❌ Ошибка: {e}")

# --- ФОТО (VISION) ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        caption = message.caption if message.caption else "Что на изображении?"
        
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        b64 = base64.b64encode(downloaded).decode('utf-8')
        
        response = vision_client.chat.completions.create(
            model="local-model",
            messages=[{
                "role": "user", 
                "content": [
                    {"type": "text", "text": caption},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            max_tokens=800
        )
        ans = clean_think_tags(response.choices[0].message.content)
        split_and_send(message, ans)
    except:
        safe_send(message.chat.id, "❌ Ошибка Vision. Убедитесь, что модель поддерживает зрение.")

# --- ГОЛОС ---
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if not audio_model: return
    try:
        fname = f"voice_{message.chat.id}.ogg"
        with open(fname, 'wb') as f:
            f.write(bot.download_file(bot.get_file(message.voice.file_id).file_path))
        
        text = audio_model.transcribe(fname, fp16=False)['text']
        os.remove(fname)
        
        safe_send(message.chat.id, f"🗣: {text}")
        message.text = text
        handle_text(message) # Передаем в текстовый обработчик
    except Exception as e:
        safe_send(message.chat.id, f"Ошибка голоса: {e}")

# --- ТЕКСТ (ОСНОВНОЙ ЧАТ) ---
@bot.message_handler(content_types=['text'])
def handle_text(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # 1. Сохраняем сообщение пользователя в БД
        db.add_message(message.chat.id, "user", message.text)
        
        # 2. Запрос к гибридному движку
        response = chat_engine.chat(message.text)
        ans = clean_think_tags(str(response))
        
        # 3. Сохраняем ответ ассистента в БД
        db.add_message(message.chat.id, "assistant", ans)
        
        split_and_send(message, ans)
    except Exception as e:
        print(f"Ошибка: {e}")
        safe_send(message.chat.id, "⚠️ Ошибка. Попробуйте очистить контекст.")

# ==========================================
# 7. ЗАПУСК
# ==========================================
if __name__ == '__main__':
    print("🚀 БОТ ЗАПУЩЕН! Нажмите Ctrl+C для выхода.")
    bot.remove_webhook()
    while True:
        try:
            bot.polling(non_stop=True, interval=2, timeout=60)
        except Exception as e:
            print(f"🔄 Рестарт через 5 сек... Ошибка: {e}")
            time.sleep(5)