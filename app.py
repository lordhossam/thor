import os
import logging
import sqlite3
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, CallbackQueryHandler
)
import yt_dlp
from flask import Flask, jsonify
from pydub import AudioSegment
from datetime import datetime

# تهيئة السجل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تهيئة التطبيق
app = Flask(__name__)

# فئة THOR الأساسية
class ThorDownloader:
    def __init__(self):
        self.platforms = {
            'youtube': {'name': 'YouTube', 'icon': '🎬', 'max_quality': '4k'},
            'tiktok': {'name': 'TikTok', 'icon': '🕺', 'max_quality': '1080p'},
            'instagram': {'name': 'Instagram', 'icon': '📸', 'max_quality': '1080p'},
            'twitter': {'name': 'Twitter', 'icon': '🐦', 'max_quality': '720p'}
        }
        
        self.quality_options = {
            '480p': {'label': 'جودة متوسطة', 'emoji': '🟢', 'vip': False},
            '720p': {'label': 'جودة عالية', 'emoji': '🔵', 'vip': False},
            '1080p': {'label': 'جودة فائقة', 'emoji': '🟣', 'vip': True},
            '4k': {'label': 'جودة خارقة', 'emoji': '⚡', 'vip': True},
            'mp3': {'label': 'تحويل لـ MP3', 'emoji': '🎵', 'vip': False}
        }
        
        # إنشاء مجلد التحميلات إذا لم يكن موجوداً
        if not os.path.exists('downloads'):
            os.makedirs('downloads')
        
        # تهيئة قاعدة البيانات
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect('thor.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                    (user_id INTEGER PRIMARY KEY, 
                     username TEXT, 
                     join_date TEXT, 
                     is_vip BOOLEAN DEFAULT FALSE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS downloads
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     user_id INTEGER,
                     url TEXT,
                     platform TEXT,
                     quality TEXT,
                     download_date TEXT)''')
        conn.commit()
        conn.close()

    def detect_platform(self, url):
        for platform, data in self.platforms.items():
            if platform in url.lower():
                return platform, data
        return None, None

    def get_buttons(self, platform_data, url, user_id):
        is_vip = self.check_vip(user_id)
        buttons = []
        
        # أزرار الجودة
        for qual, data in self.quality_options.items():
            if not data['vip'] or is_vip:
                if qual == '4k' and platform_data['max_quality'] != '4k':
                    continue
                buttons.append([InlineKeyboardButton(
                    f"{data['emoji']} {data['label']}",
                    callback_data=f"dl:{platform_data['name']}:{qual}:{url}"
                )])
        
        # زر الترقية
        if not is_vip:
            buttons.append([InlineKeyboardButton("💎 ترقية إلى VIP", callback_data="upgrade")])
        
        return InlineKeyboardMarkup(buttons)

    def check_vip(self, user_id):
        conn = sqlite3.connect('thor.db')
        c = conn.cursor()
        c.execute("SELECT is_vip FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else False

    def download_content(self, url, quality, user_id):
        try:
            conn = sqlite3.connect('thor.db')
            c = conn.cursor()
            
            # التحقق من عدد التحميلات للمستخدم العادي
            if not self.check_vip(user_id):
                today = datetime.now().strftime("%Y-%m-%d")
                c.execute('''SELECT COUNT(*) FROM downloads 
                            WHERE user_id=? AND date(download_date)=?''', 
                         (user_id, today))
                count = c.fetchone()[0]
                
                max_free = int(os.getenv('MAX_FREE_DOWNLOADS', 3))
                if count >= max_free:
                    return None, f"لقد تجاوزت حد التحميلات المجانية ({max_free} يومياً). ترقى إلى VIP لتحميل المزيد!"

            platform, _ = self.detect_platform(url)
            download_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # إعداد خيارات yt-dlp
            ydl_opts = {
                'format': self._get_format(quality),
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
            }
            
            # عملية التحميل
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # تحويل إلى MP3 إذا طلب المستخدم
                if quality == 'mp3':
                    filename = self._convert_to_mp3(filename)
                
                # تسجيل التحميل في قاعدة البيانات
                c.execute('''INSERT INTO downloads 
                            (user_id, url, platform, quality, download_date)
                            VALUES (?, ?, ?, ?, ?)''',
                         (user_id, url, platform, quality, download_date))
                conn.commit()
                
                return filename, None
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None, str(e)
        finally:
            conn.close()

    def _get_format(self, quality):
        formats = {
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            '4k': 'bestvideo[height<=2160]+bestaudio/best[height<=2160]',
            'mp3': 'bestaudio/best'
        }
        return formats.get(quality, 'best')

    def _convert_to_mp3(self, filename):
        mp3_file = os.path.splitext(filename)[0] + '.mp3'
        audio = AudioSegment.from_file(filename)
        audio.export(mp3_file, format="mp3", bitrate="320k")
        os.remove(filename)
        return mp3_file

# إنشاء مثيل THOR
thor = ThorDownloader()

# أوامر البوت
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = sqlite3.connect('thor.db')
    c = conn.cursor()
    
    # تسجيل/تحديث المستخدم
    c.execute("INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)",
              (user.id, user.username, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    update.message.reply_text(
        f"⚡ *مرحباً {user.first_name} في THOR DOWNLOADER!*\n\n"
        "أرسل رابط أي فيديو من:\n"
        "- يوتيوب\n- تيك توك\n- إنستجرام\n- تويتر\n\n"
        "وسأحوله لك بأعلى جودة!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 ترقية إلى VIP", callback_data="upgrade")],
            [InlineKeyboardButton("🛠 المساعدة", callback_data="help")]
        ])
    )

def handle_message(update: Update, context: CallbackContext):
    url = update.message.text
    platform, platform_data = thor.detect_platform(url)
    
    if platform:
        update.message.reply_text(
            f"🔍 تم التعرف على الرابط: {platform_data['icon']} {platform_data['name']}\n"
            "اختر جودة التحميل:",
            reply_markup=thor.get_buttons(platform_data, url, update.effective_user.id)
        )
    else:
        update.message.reply_text(
            "⚠️ لم نتعرف على المنصة! الرجاء إرسال رابط من:\n"
            "- يوتيوب\n- تيك توك\n- إنستجرام\n- تويتر"
        )

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data.startswith('dl:'):
        _, platform, quality, url = query.data.split(':', 3)
        
        query.edit_message_text(f"⚡ جاري التحميل بجودة {quality}...")
        filename, error = thor.download_content(url, quality, query.from_user.id)
        
        if filename:
            try:
                if quality == 'mp3':
                    with open(filename, 'rb') as f:
                        query.message.reply_audio(
                            audio=f,
                            title=os.path.basename(filename),
                            caption=f"🎵 تم التحويل إلى MP3 بنجاح!"
                        )
                else:
                    with open(filename, 'rb') as f:
                        query.message.reply_video(
                            video=f,
                            caption=f"🎬 تم التحميل بنجاح بجودة {quality}!"
                        )
                
                os.remove(filename)
            except Exception as e:
                logger.error(f"Error sending file: {e}")
                query.message.reply_text("❌ حدث خطأ أثناء إرسال الملف!")
        else:
            query.message.reply_text(f"❌ {error}")
    
    elif query.data == 'upgrade':
        vodafone_num = os.getenv('VODAFONE_CASH_NUMBER', '01012345678')
        price = os.getenv('VIP_PRICE', '100')
        
        query.edit_message_text(
            f"💎 *ترقية إلى حساب VIP*\n\n"
            f"السعر: {price} جنيهاً\n"
            f"طريقة الدفع: فودافون كاش\n\n"
            f"1. أرسل المبلغ إلى الرقم: {vodafone_num}\n"
            f"2. أرسل صورة الإيصال\n"
            f"3. سيتم التفعيل خلال 24 ساعة\n\n"
            "مميزات VIP:\n"
            "- جودة 4K\n- تحميل غير محدود\n- سرعات خارقة",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 أرسل إيصال الدفع", callback_data="send_payment")],
                [InlineKeyboardButton("🛑 إلغاء", callback_data="cancel")]
            ])
        )
    
    elif query.data == 'help':
        help_command(update, context)

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🛠 *كيفية الاستخدام:*\n\n"
        "1. أرسل رابط فيديو من:\n"
        "- يوتيوب\n- تيك توك\n- إنستجرام\n- تويتر\n\n"
        "2. اختر جودة التحميل\n\n"
        "3. انتظر حتى يتم إرسال الملف\n\n"
        "💎 *مميزات VIP:*\n"
        "- جودة 4K\n- تحميل غير محدود\n- سرعات خارقة",
        parse_mode='Markdown'
    )

@app.route('/')
def home():
    return "THOR DOWNLOADER is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

def main():
    TOKEN = os.getenv('TELEGRAM_TOKEN')
    if not TOKEN:
        logger.error("يجب تعيين متغير البيئة TELEGRAM_TOKEN!")
        return
    
    # بدء Flask في خيط منفصل
    Thread(target=run_flask).start()
    
    # تهيئة البوت
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('help', help_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    updater.start_polling()
    logger.info("تم تشغيل البوت بنجاح!")
    updater.idle()

if __name__ == '__main__':
    main()