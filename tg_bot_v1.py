import os
import time
import telebot
from telebot import types
import whisper
import base64
import re
from openai import OpenAI 

# --- БИБЛИОТЕКИ RAG ---
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings, Document
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ==========================================
# 1. НАСТРОЙКИ СИСТЕМЫ
# ==========================================
# Исправляем путь для FFmpeg (голос)
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.environ["PATH"] += os.pathsep + current_dir
except:
    pass

# Отключаем прокси и лишние предупреждения
os.environ['NO_PROXY'] = 'api.telegram.org'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(key, None)

# Папка базы знаний
KNOWLEDGE_DIR = "./my_knowledge"
if not os.path.exists(KNOWLEDGE_DIR):
    os.makedirs(KNOWLEDGE_DIR)

# ==========================================
# 2. КОНФИГУРАЦИЯ (ИСПРАВЛЕНО СОЕДИНЕНИЕ)
# ==========================================
TELEGRAM_TOKEN = '7502929605:AAEKTy1yX3FRe9dPbQ5cK14MckcjySj2diY' 

# ВАЖНО: Используем 127.0.0.1 вместо localhost, чтобы не было ошибки ConnectionError
LM_STUDIO_URL = "http://26.127.170.20:1234/v1"

print("⚙️ Настраиваю нейросети...")

# Настройка LLM
Settings.llm = OpenAILike(
    model="local-model",
    api_base=LM_STUDIO_URL,
    api_key="lm-studio",
    is_chat_model=True,
    context_window=8192,
    timeout=120.0
)

# Настройка Embeddings
Settings.embed_model = HuggingFaceEmbedding(
    model_name="intfloat/multilingual-e5-small"
)

chat_engine = None

# ==========================================
# 3. ИНИЦИАЛИЗАЦИЯ
# ==========================================
print("⏳ Загружаю Whisper...")
try:
    audio_model = whisper.load_model("base")
    print("✅ Whisper загружен!")
except:
    audio_model = None
    print("⚠️ Whisper отключен.")

vision_client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ==========================================
# 4. МЕНЮ И КЛАВИАТУРА
# ==========================================
def get_main_keyboard():
    """Создает кнопки под строкой ввода"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # Первый ряд кнопок
    btn1 = types.KeyboardButton("🧹 Очистить контекст")
    btn2 = types.KeyboardButton("📄 Показать файлы")
    # Второй ряд
    btn3 = types.KeyboardButton("❓ Помощь")
    
    markup.row(btn1, btn2)
    markup.row(btn3)
    return markup

# ==========================================
# 5. ЛОГИКА RAG
# ==========================================
def rebuild_index():
    global chat_engine
    print("📚 Обновляю базу знаний...")
    
    if not os.listdir(KNOWLEDGE_DIR):
        documents = []
    else:
        documents = SimpleDirectoryReader(KNOWLEDGE_DIR).load_data()
    
    if not documents:
        documents = [Document(text="База знаний пуста. Используй общие знания.")]

    index = VectorStoreIndex.from_documents(documents)
    memory = ChatMemoryBuffer.from_defaults(token_limit=4000)

    chat_engine = index.as_chat_engine(
        chat_mode="context",
        memory=memory,
        system_prompt=(
            "Ты умный помощник. "
            "1. Используй информацию из контекста (файлов) для ответа. "
            "2. Если информации нет в файлах, используй свои знания. "
            "3. Будь краток и точен."
        ),
        similarity_top_k=3
    )
    print("✅ Готово!")

rebuild_index()

# ==========================================
# 6. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def clean_think_tags(text):
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

def safe_send(chat_id, text, markup=None):
    if not text: return
    # Если клавиатура не передана, добавляем её принудительно, чтобы не пропадала
    if markup is None:
        markup = get_main_keyboard()
        
    for i in range(3):
        try:
            bot.send_message(chat_id, text, reply_markup=markup)
            return
        except Exception as e:
            time.sleep(2)

def split_and_send(message, text):
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
# 7. ОБРАБОТЧИКИ
# ==========================================

# --- КОМАНДА START ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    safe_send(message.chat.id, 
              "👋 Привет! Я готов.\nКнопки управления внизу 👇", 
              markup=get_main_keyboard())

# --- КНОПКИ (Обработка текста кнопок) ---
@bot.message_handler(func=lambda message: message.text == "🧹 Очистить контекст")
def clear_memory(message):
    chat_engine.reset()
    safe_send(message.chat.id, "🧠 Память очищена! Я забыл прошлый разговор.")

@bot.message_handler(func=lambda message: message.text == "📄 Показать файлы")
def show_files(message):
    files = os.listdir(KNOWLEDGE_DIR)
    if not files:
        msg = "📂 Папка пуста."
    else:
        msg = "📂 **Файлы в базе:**\n" + "\n".join([f"- {f}" for f in files])
    safe_send(message.chat.id, msg)

@bot.message_handler(func=lambda message: message.text == "❓ Помощь")
def help_msg(message):
    msg = (
        "🤖 **Как пользоваться:**\n"
        "1. **Файлы:** Пришли PDF/DOCX/TXT — я их выучу.\n"
        "2. **Вопросы:** Спрашивай что угодно.\n"
        "3. **Фото:** Пришли картинку — я опишу.\n"
        "4. **Голос:** Можешь говорить голосом."
    )
    safe_send(message.chat.id, msg)

# --- ЗАГРУЗКА ФАЙЛОВ ---
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        f_name = message.document.file_name
        safe_send(message.chat.id, f"📥 Скачиваю {f_name}...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        with open(os.path.join(KNOWLEDGE_DIR, f_name), 'wb') as f:
            f.write(downloaded)
            
        rebuild_index()
        safe_send(message.chat.id, "✅ Файл добавлен в базу знаний!")
    except Exception as e:
        safe_send(message.chat.id, f"Ошибка: {e}")

# --- ФОТО ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        caption = message.caption if message.caption else "Что здесь?"
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        b64 = base64.b64encode(downloaded).decode('utf-8')
        
        response = vision_client.chat.completions.create(
            model="local-model",
            messages=[{"role": "user", "content": [{"type": "text", "text": caption}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
            max_tokens=800
        )
        split_and_send(message, clean_think_tags(response.choices[0].message.content))
    except:
        safe_send(message.chat.id, "❌ Ошибка Vision.")

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
        handle_text(message)
    except Exception as e:
        safe_send(message.chat.id, f"Ошибка голоса: {e}")

# --- ТЕКСТ (ОБЫЧНЫЙ ЧАТ) ---
@bot.message_handler(content_types=['text'])
def handle_text(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        response = chat_engine.chat(message.text)
        split_and_send(message, clean_think_tags(str(response)))
    except Exception as e:
        print(f"Ошибка чата: {e}")
        safe_send(message.chat.id, "⚠️ Ошибка связи с нейросетью. Проверьте LM Studio.")

# ==========================================
# 8. ЗАПУСК
# ==========================================
if __name__ == '__main__':
    print("🚀 Бот с КНОПКАМИ запущен!")
    bot.remove_webhook()
    while True:
        try:
            bot.polling(non_stop=True, interval=2, timeout=60)
        except Exception as e:
            print(f"🔄 Рестарт... {e}")
            time.sleep(5)
