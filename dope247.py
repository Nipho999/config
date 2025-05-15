import os
import logging
import tempfile
import yt_dlp
import subprocess
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Please set the TELEGRAM_BOT_TOKEN environment variable")

MAX_FILE_SIZE = 50 * 1024 * 1024
SUPPORTED_DOMAINS = ['vimeo.com', 'instagram.com', 'tiktok.com', 'dailymotion.com', 'facebook.com', 'xvideos.com']

class VideoDownloaderBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.active_downloads = set()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_html(
            f"👋 Hello {user.mention_html()}!\n\n"
            "Send me a video URL from supported sites and I'll download it for you.\n"
            "Supported: Vimeo, Dailymotion, Facebook, Xvids, more...\n\n"
            "📎 Max File Size: 50MB\n"
            "I'll try to deliver good quality (480p if possible)."
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "📖 <b>Help</b>\n\n"
            "1. Send me a supported video link\n"
            "2. I'll fetch and send it (re-encoded to 480p if needed)\n"
            "3. Max size: 50MB\n\n"
            "/start - Show welcome\n"
            "/limit - Show file size info"
        )

    async def limit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "📦 <b>File Size Limit</b>\n\n"
            "Telegram bot uploads are limited to 50MB per file."
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text.strip()

        if user_id in self.active_downloads:
            await update.message.reply_text("⏳ Please wait, still working on your previous download...")
            return

        if not self._is_valid_url(text):
            await update.message.reply_text("⚠️ Please send a valid URL from supported sites.")
            return

        self.active_downloads.add(user_id)
        try:
            await update.message.reply_text("⬇️ Downloading your video, please wait...")
            await self._process_video(update, text, chat_id)
        except Exception as e:
            logger.error(f"Download error: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
        finally:
            self.active_downloads.discard(user_id)

    def _is_valid_url(self, text: str) -> bool:
        return text.startswith(('http://', 'https://')) and any(domain in text for domain in SUPPORTED_DOMAINS)

    async def _process_video(self, update: Update, url: str, chat_id: int):
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                title, file_path = self._download_video(url, temp_dir)

                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    compressed_path = os.path.join(temp_dir, "compressed.mp4")
                    self._compress_video(file_path, compressed_path)
                    file_path = compressed_path
                    file_size = os.path.getsize(file_path)

                    if file_size > MAX_FILE_SIZE:
                        raise ValueError("Even after compression, the video is too large.")

                await self._send_video(chat_id, file_path, title)

            except yt_dlp.utils.DownloadError:
                raise ValueError("Failed to download. URL might be invalid.")

    def _download_video(self, url: str, temp_dir: str) -> tuple:
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            if not os.path.exists(file_path):
                # Sometimes yt-dlp outputs a merged file with ".mp4" extension
                file_path = file_path.rsplit(".", 1)[0] + ".mp4"
            return info_dict.get('title', 'video'), file_path

    def _compress_video(self, input_path: str, output_path: str):
        cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', 'scale=-2:720',
            '-c:v', 'libx264', '-preset', 'fast',
            '-crf', '28',
            '-c:a', 'aac', '-b:a', '96k',
            '-movflags', '+faststart',
            output_path
        ]
        subprocess.run(cmd, check=True)

    async def _send_video(self, chat_id: int, file_path: str, caption: str):
        try:
            with open(file_path, 'rb') as video_file:
                await self.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=caption[:1024],
                    supports_streaming=True
                )
        except Exception as e:
            logger.error(f"Send failed: {e}")

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot = VideoDownloaderBot()

    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("limit", bot.limit_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()
