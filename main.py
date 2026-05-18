import os
import re
import sys
import time
import requests
from threading import Thread
from flask import Flask
import telebot
from pypdf import PdfReader  # مكتبة قراءة ملفات الـ PDF

# --- إعداد خادم الويب لإبقاء السيرفر مستيقظاً 24/7 ---
app = Flask('')

@app.route('/')
def home():
    return "🚀 بوت ترجمة الـ PDF يعمل بنجاح 24/7!"

def run_web_server():
    app.run(host='0.0.0.0', port=8080)

# --- جلب المفاتيح السرية بأمان من إعدادات Render ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# نموذج Llama 3.1 8B السريع والممتاز للترجمة النصية صفحة بصفحة
TRANSLATION_MODEL = "llama-3.1-8b-instant" 

TEMP_PDF_PATH = "temp_process.pdf"
OUTPUT_TXT_PATH = "translated_document.txt"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# --- 1. دالة استخراج النص والترجمة عبر Groq Llama ---
def translate_text_with_groq(text):
    if not text.strip(): return "[صفحة فارغة]"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    prompt = f"Translate the following text into professional Arabic. Preserve the original meaning and return ONLY the translated text without commentary:\n\n{text}"
    payload = {"model": TRANSLATION_MODEL, "messages": [{"role": "user", "content": prompt}]}
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content']
            elif response.status_code == 429:
                time.sleep(15)  # الانتظار في حال الوصول لحد السرعة
                continue
        except:
            time.sleep(5)
    return "[فشلت ترجمة هذه الفقرة بسبب قيود السيرفر]"

# --- 2. دالة تحميل الملف من روابط جوجل درايف إذا أرسلها المستخدم كـ نص ---
def download_pdf_from_drive(drive_url):
    file_id = None
    if "/file/d/" in drive_url:
        file_id = drive_url.split("/file/d/")[1].split("/")[0]
    elif "id=" in drive_url:
        file_id = drive_url.split("id=")[1].split("&")[0]
        
    if not file_id: return False
    
    download_url = f"https://docs.google.com/uc?export=download&id={file_id}"
    session = requests.Session()
    response = session.get(download_url, stream=True)
    
    token = None
    for key, value in response.cookies.items():
        if "download_warning" in key:
            token = value
            break
    if token:
        response = session.get(download_url + f"&confirm={token}", stream=True)
        
    if response.status_code == 200:
        with open(TEMP_PDF_PATH, "wb") as f:
            for chunk in response.iter_content(chunk_size=32768):
                if chunk: f.write(chunk)
        return True
    return False

# --- 3. معالجة ملف الـ PDF وترجمته صفحة بصفحة ---
def process_and_translate_pdf(chat_id, status_msg):
    try:
        reader = PdfReader(TEMP_PDF_PATH)
        total_pages = len(reader.pages)
        translated_document = ""
        
        for index, page in enumerate(reader.pages):
            bot.edit_message_text(f"⏳ جاري قراءة وترجمة الصفحة [{index + 1}/{total_pages}]...", chat_id=chat_id, message_id=status_msg.message_id)
            page_text = page.extract_text()
            
            if page_text.strip():
                translated_page = translate_text_with_groq(page_text)
                translated_document += f"\n\n--- الصفحة {index + 1} ---\n\n" + translated_page
            else:
                translated_document += f"\n\n--- الصفحة {index + 1} ---\n\n[صفحة فارغة أو تحتوي على صورة]"
                
        with open(OUTPUT_TXT_PATH, "w", encoding="utf-8") as f:
            f.write(translated_document.strip())
            
        bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        with open(OUTPUT_TXT_PATH, "rb") as f:
            bot.send_document(chat_id, f, caption="🎯 مبروك! انتهت ترجمة ملف الـ PDF الخاص بك بنجاح.")
            
    except Exception as e:
        bot.edit_message_text(f"💥 حدث خطأ أثناء معالجة الملف: {e}", chat_id=chat_id, message_id=status_msg.message_id)
        
    # تنظيف الملفات مؤقتاً
    if os.path.exists(TEMP_PDF_PATH): os.remove(TEMP_PDF_PATH)
    if os.path.exists(OUTPUT_TXT_PATH): os.remove(OUTPUT_TXT_PATH)

# --- إدارة أوامر ورسائل البوت ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "📚 **مرحباً بك في بوت ترجمة ملفات PDF!**\n\nقم بـ:\nورفع ملف الـ PDF مباشرة هنا في الشات.\n📥 أو أرسل رابط ملف PDF من Google Drive.\n\nسأقوم بترجمته صفحة بصفحة وإرسال النتيجة النصية لك فوراً! 🤖✨")

# أولاً: استقبال ملف الـ PDF المرفوع مباشرة
@bot.message_handler(content_types=['document'])
def handle_pdf_document(message):
    if message.document.mime_type == 'application/pdf' or message.document.file_name.endswith('.pdf'):
        status_msg = bot.reply_to(message, "⏳ جاري تحميل ملف الـ PDF من سيرفرات تليجرام وتجهيزه...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open(TEMP_PDF_PATH, 'wb') as f:
            f.write(downloaded_file)
            
        process_and_translate_pdf(message.chat.id, status_msg)
    else:
        bot.reply_to(message, "⚠️ عذراً، هذا الملف ليس بصيغة PDF. من فضلك أرسل ملف PDF صحيح.")

# ثانياً: استقبال الروابط النصية (جوجل درايف)
@bot.message_handler(func=lambda message: True)
def handle_text_links(message):
    text = message.text.strip()
    if "drive.google.com" in text:
        status_msg = bot.reply_to(message, "⏳ تم رصد رابط جوجل درايف! جاري تحميل الملف سحابياً...")
        if download_pdf_from_drive(text):
            process_and_translate_pdf(message.chat.id, status_msg)
        else:
            bot.edit_message_text("❌ فشل تحميل الملف من جوجل درايف. تأكد أن خيار 'أي شخص لديه الرابط يمكنه العرض' مفعّل.", chat_id=message.chat.id, message_id=status_msg.message_id)
    else:
        bot.reply_to(message, "ℹ️ من فضلك قم برفع ملف PDF مباشرة، أو أرسل رابط جوجل درايف صالح.")

if __name__ == "__main__":
    server_thread = Thread(target=run_web_server)
    server_thread.start()
    print("🚀 بوت ملفات الـ PDF نشط الآن...")
    bot.infinity_polling()
