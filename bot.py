import os
import asyncio
import tempfile
import httpx
import yt_dlp

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def send_message(chat_id, text):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        })

async def send_video(chat_id, filepath, caption):
    async with httpx.AsyncClient(timeout=300) as client:
        with open(filepath, "rb") as f:
            await client.post(f"{API}/sendVideo", data={
                "chat_id": chat_id,
                "caption": caption,
                "supports_streaming": "true"
            }, files={"video": f})

async def edit_message(chat_id, message_id, text):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{API}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text
        })

async def send_and_get_id(chat_id, text):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        })
        return r.json()["result"]["message_id"]

def download_video(url, output_dir):
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

async def handle_update(update):
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return

    if text == "/start":
        await send_message(chat_id,
            "🎬 Video Downloader Bot\n\n"
            "Koi bhi video link bhejo, main turant download karke bhej deta hoon!\n\n"
            "✅ Supported: YouTube, Instagram, Twitter, TikTok, Facebook, Vimeo aur 500+ sites!\n\n"
            "Bas link paste karo!"
        )
        return

    if text == "/help":
        await send_message(chat_id,
            "📖 How to Use:\n\n"
            "1. Koi bhi video ka link copy karo\n"
            "2. Is bot mein paste karo\n"
            "3. Bot video download karke bhej dega\n\n"
            "⚠️ Max file size: 45MB"
        )
        return

    if not (text.startswith("http://") or text.startswith("https://")):
        await send_message(chat_id, "❌ Valid video link bhejo!\n\nExample:\nhttps://youtube.com/watch?v=...")
        return

    status_id = await send_and_get_id(chat_id, "⏳ Processing... thoda wait karo!")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            await edit_message(chat_id, status_id, "📥 Downloading video...")

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, download_video, text, tmpdir)
            filepath = info["file"]

            if not os.path.exists(filepath):
                await edit_message(chat_id, status_id, "❌ File nahi mili. Dobara try karo.")
                return

            file_size = os.path.getsize(filepath)
            if file_size > 50 * 1024 * 1024:
                await edit_message(chat_id, status_id, "❌ File 50MB se badi hai! Telegram support nahi karta.")
                return

            await edit_message(chat_id, status_id, "📤 Uploading to Telegram...")

            mins = int(info["duration"] // 60)
            secs = int(info["duration"] % 60)
            caption = f"🎬 {info['title'][:100]}\n👤 {info['uploader']}\n⏱ {mins}:{secs:02d}"

            await send_video(chat_id, filepath, caption)

            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(f"{API}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": status_id
                })

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "private" in err.lower():
            msg = "🔒 Private video — download nahi ho sakta."
        elif "age" in err.lower():
            msg = "🔞 Age-restricted video."
        else:
            msg = f"❌ Download failed!\n{err[:200]}"
        await edit_message(chat_id, status_id, msg)
    except Exception as e:
        await edit_message(chat_id, status_id, f"❌ Error: {str(e)[:200]}")

async def poll():
    offset = 0
    print("🤖 Bot chal raha hai...")
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            try:
                r = await client.get(f"{API}/getUpdates", params={
                    "offset": offset,
                    "timeout": 30
                })
                data = r.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    asyncio.create_task(handle_update(update))
            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN set nahi hai!")
    asyncio.run(poll())
