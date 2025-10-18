import asyncio
import json
import os
import requests
from telegram import Bot
from telegram.error import TelegramError
from datetime import datetime, timedelta, timezone

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = '7956809240:AAFiHa-y6Gi-aIVKGa3wm92X-DZpI4Bdlxg'
API_TO_MONITOR_URL = 'https://dashboard.kliktrap.com'
API_CHECK_INTERVAL_SECONDS = 60
REGISTERED_PICS_FILE = 'registered_pics.json'

# --- Inisialisasi Global ---
registered_pics_ids = []
last_update_id = None


# --- Utilitas ---
def get_jakarta_time():
    utc_now = datetime.now(timezone.utc)
    jakarta_offset = timedelta(hours=7)
    jakarta_time = utc_now + jakarta_offset
    return jakarta_time.strftime("%d/%m/%Y %H:%M:%S WIB")


def escape_markdown_v2(text: str) -> str:
    """Escape semua karakter spesial Telegram MarkdownV2 agar aman dikirim."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'  # karakter yang wajib di-escape
    # Pastikan juga tanda kurung ( ) ikut di-escape
    return ''.join(['\\' + c if c in escape_chars + '()' else c for c in text])


# --- Simpan / Muat daftar PIC ---
async def load_registered_pics():
    global registered_pics_ids
    if os.path.exists(REGISTERED_PICS_FILE):
        with open(REGISTERED_PICS_FILE, 'r') as f:
            try:
                data = json.load(f)
                registered_pics_ids = list(set(data))
                print(f"[{get_jakarta_time()}] Loaded {len(registered_pics_ids)} registered PICs.")
            except json.JSONDecodeError:
                print(f"[{get_jakarta_time()}] JSON decode error, start empty.")
                registered_pics_ids = []
    else:
        print(f"[{get_jakarta_time()}] No {REGISTERED_PICS_FILE}, starting empty.")
        registered_pics_ids = []


async def save_registered_pics():
    with open(REGISTERED_PICS_FILE, 'w') as f:
        json.dump(list(set(registered_pics_ids)), f, indent=4)
    print(f"[{get_jakarta_time()}] Saved {len(registered_pics_ids)} registered PICs.")


# --- Fungsi kirim pesan ke semua PIC ---
async def send_alert_to_pics(bot: Bot, message: str):
    if not registered_pics_ids:
        print(f"[{get_jakarta_time()}] No PICs registered.")
        return
    for chat_id in registered_pics_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            print(f"[{get_jakarta_time()}] Alert sent to {chat_id}")
        except TelegramError as e:
            print(f"[{get_jakarta_time()}] Error sending to {chat_id}: {e}")
            if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                registered_pics_ids.remove(chat_id)
                await save_registered_pics()


# --- Fungsi utama cek API ---
async def check_api_status(bot: Bot):
    task = asyncio.current_task()
    task_name = task.get_name() if task and hasattr(task, "get_name") else "UnknownTask"
    escaped_url = escape_markdown_v2(API_TO_MONITOR_URL)
    print(f"[{get_jakarta_time()}] [{task_name}] Checking API {API_TO_MONITOR_URL}...")

    try:
        response = requests.get(API_TO_MONITOR_URL, timeout=5)
        code = response.status_code

        # --- Penentuan pesan berdasarkan status ---
        if code == 200:
            print(f"[{get_jakarta_time()}] ✅ API OK (200).")
            return

        elif code == 503:
            message = (
                f"🚨 *ALERT:* Service di `{escaped_url}` *berhenti atau tidak merespons dengan benar* "
                f"(status *503 Service Unavailable*)\\. Mohon periksa proses backend\\."
            )

        elif code == 404:
            message = (
                f"🔴 *ALERT:* API di `{escaped_url}` *tidak ditemukan* "
                f"(status *404 Not Found*)\\. Kemungkinan besar *VM mati atau domain tidak resolve*\\."
            )

        else:
            message = (
                f"⚠️ *ALERT:* API di `{escaped_url}` mengembalikan *status code {code}*\\. "
                f"Perlu pengecekan manual\\."
            )

        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] Alert sent for status {code}")

    except requests.exceptions.ConnectionError:
        message = (
            f"🔴 *ALERT:* `{escaped_url}` *tidak bisa diakses*\\. "
            f"Ini bisa berarti *VM mati* atau *koneksi jaringan terputus*\\."
        )
        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] Connection error alert sent.")

    except requests.exceptions.Timeout:
        message = (
            f"⚠️ *ALERT:* `{escaped_url}` *timeout*\\. "
            f"Server hidup tapi *tidak merespons dalam waktu normal*\\."
        )
        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] Timeout alert sent.")

    except Exception as e:
        escaped_error = escape_markdown_v2(str(e))
        message = (
            f"🚨 *ALERT:* Terjadi error tidak terduga saat cek `{escaped_url}`: "
            f"`{escaped_error}`"
        )
        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] Unexpected error: {e}")


# --- Fungsi handle update Telegram ---
async def handle_updates(bot: Bot):
    global last_update_id
    task = asyncio.current_task()
    task_name = task.get_name() if task and hasattr(task, "get_name") else "UnknownTask"

    print(f"[{get_jakarta_time()}] [{task_name}] Checking Telegram updates (offset={last_update_id})...")
    try:
        updates = await bot.get_updates(offset=last_update_id + 1 if last_update_id else None, timeout=10)
        if not updates:
            return

        for update in updates:
            if update.update_id >= (last_update_id or 0):
                last_update_id = update.update_id

            if update.message and update.message.text:
                text = update.message.text.strip()
                chat_id = update.message.chat.id

                if text == "/start":
                    if chat_id not in registered_pics_ids:
                        registered_pics_ids.append(chat_id)
                        await save_registered_pics()
                        await bot.send_message(
                            chat_id=chat_id,
                            text="✅ *AwarenixBot aktif*\\. Anda akan menerima alert status API\\.",
                            parse_mode="MarkdownV2"
                        )
                    else:
                        await bot.send_message(chat_id=chat_id, text="Anda sudah terdaftar menerima alert.")

                elif text == "/stop":
                    if chat_id in registered_pics_ids:
                        registered_pics_ids.remove(chat_id)
                        await save_registered_pics()
                        await bot.send_message(
                            chat_id=chat_id,
                            text="🛑 Anda telah berhenti menerima alert dari *AwarenixBot*\\.",
                            parse_mode="MarkdownV2"
                        )
                    else:
                        await bot.send_message(chat_id=chat_id, text="Anda belum terdaftar untuk alert.")

                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="Halo\\! Kirim `/start` untuk daftar menerima alert atau `/stop` untuk berhenti\\.",
                        parse_mode="MarkdownV2"
                    )

    except Exception as e:
        print(f"[{get_jakarta_time()}] Telegram error: {e}")


# --- Main Bot Loop ---
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await load_registered_pics()

    async def loop_updates():
        while True:
            await handle_updates(bot)
            await asyncio.sleep(1)

    async def loop_api():
        while True:
            await check_api_status(bot)
            await asyncio.sleep(API_CHECK_INTERVAL_SECONDS)

    await asyncio.gather(
        asyncio.create_task(loop_updates(), name="TelegramUpdateLoop"),
        asyncio.create_task(loop_api(), name="APICheckLoop")
    )


if __name__ == "__main__":
    print(f"[{get_jakarta_time()}] Starting AwarenixBot...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"[{get_jakarta_time()}] Stopped by user.")
    except Exception as e:
        print(f"[{get_jakarta_time()}] Fatal error: {e}")
