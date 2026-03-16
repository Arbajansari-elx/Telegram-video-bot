import os
import asyncio
import tempfile
import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# ─── Download function ─────────────────────────────────────────────────────────
def download_video(url: str, output_dir: str) -> dict:
    ydl_opts = {
        "format": "best[filesize<45M]/best[height<=720]/best",
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            filename = filename.rsplit(".", 1)[0] + ".mp4"
        return {
            "file": filename,
            "title": info.get("title", "Video"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
        }

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎬 *Video Downloader Bot*\n\n"
        "Koi bhi video link bhejo, main turant download karke bhej deta hoon\\!\n\n"
        "✅ *Supported Platforms:*\n"
        "• YouTube\n"
        "• Instagram \\(Reels/Posts\\)\n"
        "• Twitter / X\n"
        "• Facebook\n"
        "• TikTok\n"
        "• Vimeo, Reddit, Dailymotion\n"
        "• Twitch Clips\n"
        "• \\.\\.\\. aur bahut saare\\!\n\n"
        "📌 *Bas link paste karo — main kaam karunga\\!*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

# ─── /help ────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *How to Use:*\n\n"
        "1️⃣ Koi bhi video ka link copy karo\n"
        "2️⃣ Is bot mein paste karo\n"
        "3️⃣ Bot video download karke bhej dega\n\n"
        "⚠️ *Limits:*\n"
        "• Max file size: 45MB\n"
        "• Agar video bada ho toh quality auto reduce hogi\n\n"
        "🛠 Commands:\n"
        "/start \\- Bot start karo\n"
        "/help \\- Help dekho"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

# ─── Message handler ──────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if not (text.startswith("http://") or text.startswith("https://")):
        await update.message.reply_text(
            "❌ Bhai, valid video link bhejo!\n\nExample:\nhttps://youtube.com/watch?v=..."
        )
        return

    status_msg = await update.message.reply_text("⏳ Processing... thoda wait karo!")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            await status_msg.edit_text("📥 Downloading video...")

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, download_video, text, tmpdir)

            filepath = info["file"]

            if not os.path.exists(filepath):
                await status_msg.edit_text("❌ File nahi mili. Dobara try karo.")
                return

            file_size = os.path.getsize(filepath)
            if file_size > 50 * 1024 * 1024:
                await status_msg.edit_text(
                    "❌ File 50MB se badi hai! Telegram bots itna support nahi karte."
                )
                return

            await status_msg.edit_text("📤 Uploading to Telegram...")

            mins = int(info["duration"] // 60)
            secs = int(info["duration"] % 60)
            caption = (
                f"🎬 {info['title'][:100]}\n"
                f"👤 {info['uploader']}\n"
                f"⏱ {mins}:{secs:02d}\n\n"
                f"📥 Downloaded via Bot"
            )

            with open(filepath, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )

            await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "private" in err.lower():
            msg = "🔒 Private video hai — download nahi ho sakta."
        elif "age" in err.lower():
            msg = "🔞 Age-restricted video — supported nahi."
        elif "copyright" in err.lower():
            msg = "⚠️ Copyright restricted video."
        else:
            msg = f"❌ Download failed!\n{err[:200]}"
        await status_msg.edit_text(msg)

    except Exception as e:
        await status_msg.edit_text(f"❌ Error aa gaya:\n{str(e)[:200]}")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN set nahi hai!")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot chal raha hai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
