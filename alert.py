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

# --- Global ---
registered_pics_ids = []
last_update_id = None
last_api_state = None  # None = belum tahu, "UP" atau "DOWN"


# --- Utilitas Waktu ---
def get_jakarta_time():
    utc_now = datetime.now(timezone.utc)
    jakarta_offset = timedelta(hours=7)
    jakarta_time = utc_now + jakarta_offset
    return jakarta_time.strftime("%d/%m/%Y %H:%M:%S WIB")


# --- Escape MarkdownV2 ---
def escape_markdown_v2(text: str) -> str:
    """Escape semua karakter spesial Telegram MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + c if c in escape_chars else c for c in text])


# --- Load & Save PIC ---
async def load_registered_pics():
    global registered_pics_ids
    if os.path.exists(REGISTERED_PICS_FILE):
        try:
            with open(REGISTERED_PICS_FILE, 'r') as f:
                registered_pics_ids = list(set(json.load(f)))
            print(f"[{get_jakarta_time()}] Loaded {len(registered_pics_ids)} registered PICs.")
        except Exception as e:
            print(f"[{get_jakarta_time()}] Failed to load PIC list: {e}")
            registered_pics_ids = []
    else:
        print(f"[{get_jakarta_time()}] No {REGISTERED_PICS_FILE}, starting empty.")
        registered_pics_ids = []


async def save_registered_pics():
    with open(REGISTERED_PICS_FILE, 'w') as f:
        json.dump(list(set(registered_pics_ids)), f, indent=4)
    print(f"[{get_jakarta_time()}] Saved {len(registered_pics_ids)} registered PICs.")


# --- Kirim Pesan ---
async def send_alert_to_pics(bot: Bot, message: str):
    if not registered_pics_ids:
        print(f"[{get_jakarta_time()}] No PICs registered.")
        return

    for chat_id in registered_pics_ids[:]:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            print(f"[{get_jakarta_time()}] Alert sent to {chat_id}")
        except TelegramError as e:
            print(f"[{get_jakarta_time()}] Error sending to {chat_id}: {e}")
            if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                registered_pics_ids.remove(chat_id)
                await save_registered_pics()


# --- Cek API ---
async def check_api_status(bot: Bot):
    global last_api_state
    escaped_url = escape_markdown_v2(API_TO_MONITOR_URL)
    now = get_jakarta_time()

    print(f"[{now}] [APICheckLoop] Checking API {API_TO_MONITOR_URL}...")

    current_state = "UP"
    reason = "Service normal"

    try:
        response = requests.get(API_TO_MONITOR_URL, timeout=5)
        code = response.status_code

        if code != 200:
            current_state = "DOWN"
            if code == 503:
                reason = f"Service not running \\(status *503 Service Unavailable*\\)"
            elif code == 404:
                reason = f"VM Offline \\(status *404 Not Found*\\)"
            else:
                reason = f"Unknown: *{code}*"
    except requests.exceptions.ConnectionError:
        current_state = "DOWN"
        reason = "Can't accessed \\(Possible Offline VM\\)"
    except requests.exceptions.Timeout:
        current_state = "DOWN"
        reason = "Timeout — server is not reponded"
    except Exception as e:
        current_state = "DOWN"
        reason = f"Error tak terduga: `{escape_markdown_v2(str(e))}`"

    # --- Logika anti-spam: hanya kirim saat status BERUBAH ---
    if last_api_state is None:
        # Pertama kali bot dijalankan
        last_api_state = current_state
        message = (
            f"🟢 *AwarenixBot Active*\n\n"
            f"📡 URL: `{escaped_url}`\n\n"
            f"📅 Time: *{now}*\n\n"
            f"📈 Early Status: *{reason}*"
        )
        await send_alert_to_pics(bot, message)

    elif last_api_state == "UP" and current_state == "DOWN":
        # Service baru saja down
        message = (
            f"🚨 *ALERT: SERVICE DOWN*\n\n"
            f"📡 URL: `{escaped_url}`\n\n"
            f"📅 Time: *{now}*\n\n"
            f"💥 Condition: *{reason}*\n\n"
            f"⚠️ Please check the server or vm."
        )
        await send_alert_to_pics(bot, message)
        last_api_state = "DOWN"

    elif last_api_state == "DOWN" and current_state == "UP":
        # Service baru pulih
        message = (
            f"✅ *SERVICE RUNNING*\n\n"
            f"📡 URL: `{escaped_url}`\n\n"
            f"📅 Time: *{now}*\n\n"
            f"💚 Condition: *{reason}*\n\n"
            f"System is running well."
        )
        await send_alert_to_pics(bot, message)
        last_api_state = "UP"

    else:
        # Tidak ada perubahan status
        print(f"[{now}] No state change ({current_state}), skip alert.")
        last_api_state = current_state


# --- Handle Telegram Commands ---
async def handle_updates(bot: Bot):
    global last_update_id
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
                    user = update.message.from_user
                    first_name = getattr(user, 'first_name', '') or ""
                    last_name = getattr(user, 'last_name', '') or ""
                    username = f"@{getattr(user, 'username', '')}" if getattr(user, 'username', '') else "(tanpa username)"
                    full_name = f"{first_name} {last_name}".strip()

                    if chat_id not in registered_pics_ids:
                        registered_pics_ids.append(chat_id)
                        await save_registered_pics()
                        await bot.send_message(
                            chat_id=chat_id,
                            text="✅ *AwarenixBot aktif*\\. Anda akan menerima alert status API\\.",
                            parse_mode="MarkdownV2"
                        )

                        # Kirim notifikasi ke admin (chat_id admin = 2020661886)
                        admin_chat_id = 2020661886
                        message = (
                            f"👤 *PIC Baru Terdaftar*\n"
                            f"📅 Waktu: *{get_jakarta_time()}*\n"
                            f"🆔 Chat ID: `{chat_id}`\n"
                            f"👨 Nama: *{escape_markdown_v2(full_name)}*\n"
                            f"🔗 Username: {escape_markdown_v2(username)}"
                        )
                        await bot.send_message(
                            chat_id=admin_chat_id,
                            text=message,
                            parse_mode="MarkdownV2"
                        )

                    else:
                        await bot.send_message(
                            chat_id=chat_id,
                            text="Anda sudah terdaftar menerima alert.",
                            parse_mode="MarkdownV2"
                        )

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

                elif text == "/status":
                    now = get_jakarta_time()
                    try:
                        response = requests.get(API_TO_MONITOR_URL, timeout=5)
                        code = response.status_code
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"📊 *STATUS SAAT INI*\n📡 `{escape_markdown_v2(API_TO_MONITOR_URL)}`\n📅 *{now}*\nStatus: *{code}*",
                            parse_mode="MarkdownV2"
                        )
                    except Exception:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"🚨 Tidak dapat menjangkau `{escape_markdown_v2(API_TO_MONITOR_URL)}` saat ini\\.",
                            parse_mode="MarkdownV2"
                        )

                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="Halo\\! Kirim `/start` untuk daftar menerima alert atau `/stop` untuk berhenti\\.",
                        parse_mode="MarkdownV2"
                    )

    except TelegramError as e:
        if "terminated by other getUpdates request" in str(e):
            print(f"[{get_jakarta_time()}] ⚠️ Bot instance lain masih jalan — polling diabaikan sementara.")
            await asyncio.sleep(5)
        else:
            print(f"[{get_jakarta_time()}] Telegram error: {e}")


# --- Main Bot ---
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
