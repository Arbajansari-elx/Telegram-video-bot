import os
import asyncio
import tempfile
import httpx
import yt_dlp
import json
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# ─── Stats ────────────────────────────────────────────────────────────────────
stats = {
    "total_users": set(),
    "total_downloads": 0,
    "failed_downloads": 0,
    "download_history": []
}

# ─── User state ───────────────────────────────────────────────────────────────
user_quality = {}
pending = {}

# ─── Telegram helpers ─────────────────────────────────────────────────────────
async def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API}/sendMessage", json=payload)
        return r.json().get("result", {}).get("message_id")

async def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{API}/editMessageText", json=payload)

async def delete_message(chat_id, message_id):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{API}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id})

async def answer_callback(callback_id, text=""):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

async def send_video(chat_id, filepath, caption):
    async with httpx.AsyncClient(timeout=300) as client:
        with open(filepath, "rb") as f:
            await client.post(f"{API}/sendVideo", data={
                "chat_id": chat_id,
                "caption": caption,
                "supports_streaming": "true"
            }, files={"video": f})

async def send_document(chat_id, filepath, caption):
    async with httpx.AsyncClient(timeout=300) as client:
        with open(filepath, "rb") as f:
            await client.post(f"{API}/sendDocument", data={
                "chat_id": chat_id,
                "caption": caption,
            }, files={"document": f})

# ─── Quality keyboard ─────────────────────────────────────────────────────────
def quality_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔵 360p (Fast)", "callback_data": "q_360p"},
                {"text": "🟡 720p (HD)", "callback_data": "q_720p"},
            ],
            [
                {"text": "🔴 1080p (Full HD)", "callback_data": "q_1080p"},
                {"text": "⚡ Best Available", "callback_data": "q_best"},
            ]
        ]
    }

# ─── Download from URL (YouTube, Instagram, Public Telegram, etc.) ────────────
def download_video(url, output_dir, quality="best"):
    quality_formats = {
        "360p": "best[height<=360][filesize<45M]/best[height<=360]/worst",
        "720p": "best[height<=720][filesize<45M]/best[height<=720]/best",
        "1080p": "best[height<=1080][filesize<45M]/best[height<=1080]/best",
        "best": "best[filesize<45M]/best[height<=720]/best",
    }
    ydl_opts = {
        "format": quality_formats.get(quality, quality_formats["best"]),
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "merge_output_format": "mp4",
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15"
        }
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
            "platform": info.get("extractor_key", "Unknown"),
        }

# ─── Download forwarded Telegram video ───────────────────────────────────────
async def download_telegram_file(file_id, output_dir):
    async with httpx.AsyncClient(timeout=30) as client:
        # Get file path
        r = await client.get(f"{API}/getFile", params={"file_id": file_id})
        result = r.json().get("result", {})
        file_path = result.get("file_path")
        if not file_path:
            return None

        file_size = result.get("file_size", 0)
        if file_size > 50 * 1024 * 1024:
            return "TOO_LARGE"

        # Download file
        download_url = f"{FILE_API}/{file_path}"
        r2 = await client.get(download_url, timeout=120)
        ext = file_path.split(".")[-1] if "." in file_path else "mp4"
        save_path = os.path.join(output_dir, f"tg_video.{ext}")
        with open(save_path, "wb") as f:
            f.write(r2.content)
        return save_path

# ─── Process URL download ─────────────────────────────────────────────────────
async def process_download(chat_id, url, quality, username):
    status_id = await send_message(chat_id, "⏳ Processing... thoda wait karo!")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            await edit_message(chat_id, status_id, f"📥 Downloading in {quality}...")

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, download_video, url, tmpdir, quality)
            filepath = info["file"]

            if not os.path.exists(filepath):
                await edit_message(chat_id, status_id, "❌ File nahi mili. Dobara try karo.")
                stats["failed_downloads"] += 1
                return

            file_size = os.path.getsize(filepath)
            if file_size > 50 * 1024 * 1024:
                await edit_message(chat_id, status_id, "❌ File 50MB se badi hai!\n360p ya 720p try karo.")
                stats["failed_downloads"] += 1
                return

            await edit_message(chat_id, status_id, "📤 Uploading to Telegram...")

            mins = int(info["duration"] // 60)
            secs = int(info["duration"] % 60)
            size_mb = round(file_size / (1024 * 1024), 1)
            caption = (
                f"🎬 {info['title'][:80]}\n"
                f"👤 {info['uploader']}\n"
                f"⏱ {mins}:{secs:02d} | 📦 {size_mb}MB | 🎯 {quality}\n"
                f"🌐 {info['platform']}"
            )

            await send_video(chat_id, filepath, caption)
            await delete_message(chat_id, status_id)

            stats["total_downloads"] += 1
            stats["total_users"].add(chat_id)
            stats["download_history"].append({
                "user": username,
                "platform": info["platform"],
                "quality": quality,
                "size": f"{size_mb}MB",
                "time": datetime.now().strftime("%H:%M %d/%m")
            })
            if len(stats["download_history"]) > 20:
                stats["download_history"].pop(0)

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "private" in err.lower():
            msg = "🔒 Private content — public link use karo."
        elif "age" in err.lower():
            msg = "🔞 Age-restricted content."
        elif "instagram" in err.lower():
            msg = "📱 Instagram public posts hi support hote hain."
        else:
            msg = f"❌ Download failed!\n{err[:150]}"
        await edit_message(chat_id, status_id, msg)
        stats["failed_downloads"] += 1
    except Exception as e:
        await edit_message(chat_id, status_id, f"❌ Error: {str(e)[:150]}")
        stats["failed_downloads"] += 1

# ─── Process forwarded Telegram video ────────────────────────────────────────
async def process_forwarded_video(chat_id, file_id, username, file_name="video"):
    status_id = await send_message(chat_id, "⏳ Forwarded video save ho rahi hai...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            await edit_message(chat_id, status_id, "📥 Downloading from Telegram...")
            result = await download_telegram_file(file_id, tmpdir)

            if result is None:
                await edit_message(chat_id, status_id, "❌ File download nahi hui.")
                return
            if result == "TOO_LARGE":
                await edit_message(chat_id, status_id, "❌ File 50MB se badi hai!")
                return

            filepath = result
            file_size = os.path.getsize(filepath)
            size_mb = round(file_size / (1024 * 1024), 1)

            await edit_message(chat_id, status_id, "📤 Sending back to you...")

            caption = (
                f"📹 Forwarded Video Saved!\n"
                f"📦 Size: {size_mb}MB\n"
                f"👤 Saved by: @{username}"
            )

            await send_video(chat_id, filepath, caption)
            await delete_message(chat_id, status_id)

            stats["total_downloads"] += 1
            stats["total_users"].add(chat_id)
            stats["download_history"].append({
                "user": username,
                "platform": "Telegram Forward",
                "quality": "original",
                "size": f"{size_mb}MB",
                "time": datetime.now().strftime("%H:%M %d/%m")
            })

    except Exception as e:
        await edit_message(chat_id, status_id, f"❌ Error: {str(e)[:150]}")
        stats["failed_downloads"] += 1

# ─── Admin panel ──────────────────────────────────────────────────────────────
async def send_admin_panel(chat_id):
    if ADMIN_ID == 0 or chat_id != ADMIN_ID:
        await send_message(chat_id, "❌ Tum admin nahi ho!")
        return

    history_text = ""
    for h in stats["download_history"][-5:]:
        history_text += f"\n• {h['user']} | {h['platform']} | {h['quality']} | {h['size']} | {h['time']}"

    text = (
        "👑 ADMIN PANEL\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: {len(stats['total_users'])}\n"
        f"✅ Total Downloads: {stats['total_downloads']}\n"
        f"❌ Failed: {stats['failed_downloads']}\n"
        f"📊 Success Rate: {round(stats['total_downloads'] / max(stats['total_downloads'] + stats['failed_downloads'], 1) * 100)}%\n\n"
        f"📜 Recent Downloads:{history_text if history_text else ' None yet'}\n\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
    )
    await send_message(chat_id, text)

# ─── Handle text messages ─────────────────────────────────────────────────────
async def handle_message(chat_id, text, username):
    stats["total_users"].add(chat_id)

    if text == "/start":
        await send_message(chat_id,
            "🎬 Video Downloader Bot\n\n"
            "Kya bhej sakte ho:\n"
            "🔗 YouTube, Instagram, Twitter, TikTok link\n"
            "📢 Telegram public channel link\n"
            "↩️ Kisi ka bhi video forward karo\n\n"
            "Commands:\n"
            "/quality - Default quality set karo\n"
            "/help - Help\n"
            "/admin - Admin panel"
        )
        return

    if text == "/help":
        await send_message(chat_id,
            "📖 How to Use:\n\n"
            "1️⃣ YouTube/Instagram/Twitter link bhejo\n"
            "2️⃣ Telegram public channel link bhejo\n"
            "3️⃣ Koi bhi video is bot pe forward karo\n\n"
            "Quality choose karne ka option milega!\n\n"
            "⚠️ Max 50MB file size"
        )
        return

    if text == "/admin":
        await send_admin_panel(chat_id)
        return

    if text == "/quality":
        await send_message(chat_id, "🎯 Default quality choose karo:", reply_markup=quality_keyboard())
        return

    if text.startswith("http://") or text.startswith("https://"):
        pending[chat_id] = {"url": text}
        await send_message(chat_id, "🎯 Quality choose karo:", reply_markup=quality_keyboard())
        return

    await send_message(chat_id,
        "❌ Samajh nahi aaya!\n\n"
        "Yeh bhejo:\n"
        "• Video ka link (YouTube, Instagram, etc.)\n"
        "• Telegram public channel link\n"
        "• Koi bhi video forward karo"
    )

# ─── Handle video/document messages (forwarded) ───────────────────────────────
async def handle_video_message(chat_id, message, username):
    stats["total_users"].add(chat_id)

    # Check if forwarded
    is_forwarded = "forward_origin" in message or "forward_from" in message or "forward_from_chat" in message

    video = message.get("video") or message.get("document")
    if not video:
        return

    file_id = video.get("file_id")
    if not file_id:
        return

    if is_forwarded:
        source = "forwarded message"
        if "forward_from_chat" in message:
            chat_name = message["forward_from_chat"].get("title", "channel")
            source = f"@{message['forward_from_chat'].get('username', chat_name)}"
        await send_message(chat_id, f"↩️ Forwarded video mila ({source})!\nSave kar raha hoon...")
    else:
        await send_message(chat_id, "📹 Video mila! Save kar raha hoon...")

    await process_forwarded_video(chat_id, file_id, username)

# ─── Main polling ─────────────────────────────────────────────────────────────
async def handle_callback(callback):
    chat_id = callback["from"]["id"]
    username = callback["from"].get("username", str(chat_id))
    data = callback.get("data", "")
    message_id = callback["message"]["message_id"]
    callback_id = callback["id"]

    await answer_callback(callback_id)

    if data.startswith("q_"):
        quality = data.replace("q_", "")
        user_quality[chat_id] = quality

        if chat_id in pending:
            url = pending[chat_id]["url"]
            del pending[chat_id]
            await delete_message(chat_id, message_id)
            await process_download(chat_id, url, quality, username)
        else:
            await edit_message(chat_id, message_id, f"✅ Default quality set: {quality}")

async def poll():
    offset = 0
    print("🤖 Bot chal raha hai...")
    while True:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"{API}/getUpdates", params={
                    "offset": offset,
                    "timeout": 30
                })
                data = r.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1

                    if "message" in update:
                        msg = update["message"]
                        chat_id = msg.get("chat", {}).get("id")
                        username = msg.get("from", {}).get("username", str(chat_id))

                        # Video or document (forwarded or direct)
                        if "video" in msg or "document" in msg:
                            asyncio.create_task(handle_video_message(chat_id, msg, username))

                        # Text message
                        elif "text" in msg:
                            text = msg["text"].strip()
                            asyncio.create_task(handle_message(chat_id, text, username))

                    elif "callback_query" in update:
                        asyncio.create_task(handle_callback(update["callback_query"]))

        except Exception as e:
            print(f"Polling error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN set nahi hai!")
    asyncio.run(poll())
