import asyncio
import json
import os
import requests
from telegram import Bot
from telegram.error import TelegramError
from datetime import datetime, timedelta, timezone
import traceback

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = '7956809240:AAFiHa-y6Gi-aIVKGa3wm92X-DZpI4Bdlxg'
API_TO_MONITOR_URL = 'https://dashboard.kliktrap.com'
API_CHECK_INTERVAL_SECONDS = 60
REGISTERED_PICS_FILE = 'registered_pics.json'
LAST_STATE_FILE = 'last_api_status.json'
ADMIN_CHAT_ID = 2020661886  

# --- Global ---
registered_pics_ids = []
last_update_id = None
last_api_state = None  # "UP" atau "DOWN"


# --- Utilitas Waktu ---
def get_jakarta_time():
    utc_now = datetime.now(timezone.utc)
    jakarta_offset = timedelta(hours=7)
    jakarta_time = utc_now + jakarta_offset
    return jakarta_time.strftime("%d/%m/%Y %H:%M:%S WIB")


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


# --- Load & Save Last State ---
def load_last_state():
    global last_api_state
    if os.path.exists(LAST_STATE_FILE):
        try:
            with open(LAST_STATE_FILE, 'r') as f:
                data = json.load(f)
                last_api_state = "DOWN" if data.get("is_down") else "UP"
            print(f"[{get_jakarta_time()}] Loaded last_api_state = {last_api_state}")
        except Exception as e:
            print(f"[{get_jakarta_time()}] Failed to load last state: {e}")
            last_api_state = None
    else:
        last_api_state = None


def save_last_state():
    data = {"is_down": True if last_api_state == "DOWN" else False}
    with open(LAST_STATE_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"[{get_jakarta_time()}] Saved last_api_state = {last_api_state}")


# --- Kirim Pesan ---
async def send_alert_to_pics(bot: Bot, message: str):
    if not registered_pics_ids:
        print(f"[{get_jakarta_time()}] No PICs registered.")
        return

    for chat_id in registered_pics_ids[:]:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML')
            print(f"[{get_jakarta_time()}] Alert sent to {chat_id}")
        except TelegramError as e:
            print(f"[{get_jakarta_time()}] Error sending to {chat_id}: {e}")
            try:
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"⚠️ Gagal kirim pesan ke <code>{chat_id}</code>: <code>{str(e)}</code>",
                    parse_mode="HTML"
                )
            except Exception as e2:
                print(f"[{get_jakarta_time()}] Failed to notify admin: {e2}")
            if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                registered_pics_ids.remove(chat_id)
                await save_registered_pics()


# --- Cek API ---
async def check_api_status(bot: Bot):
    global last_api_state
    now = get_jakarta_time()

    print(f"[{now}] [APICheckLoop] Checking API {API_TO_MONITOR_URL}...")

    current_state = "UP"
    reason = "Service normal"

    try:
        response = requests.get(API_TO_MONITOR_URL, timeout=5)
        code = response.status_code
        text = response.text.lower().strip()

        if code != 200 or any(err in text for err in ["error", "502", "503", "bad gateway", "not found"]):
            current_state = "DOWN"
            reason = f"Status code {code} or bad content detected"
    except requests.exceptions.ConnectionError:
        current_state = "DOWN"
        reason = "Can't access (Possible Offline VM)"
    except requests.exceptions.Timeout:
        current_state = "DOWN"
        reason = "Timeout — server not responding"
    except Exception as e:
        current_state = "DOWN"
        reason = f"Unexpected error: {e}"

    print(f"[{now}] DEBUG: last_api_state={last_api_state}, current_state={current_state}")

    # === Logika pengiriman notifikasi ===
    if last_api_state is None:
        last_api_state = current_state
        msg = (
            f"🟢 <b>AwarenixBot Active</b>\n\n\n"
            f"📡 URL: <code>{API_TO_MONITOR_URL}</code>\n\n"
            f"📅 Time: <b>{now}</b>\n\n"
            f"📈 Initial status: <b>{reason}</b>"
        )
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="HTML")

    elif last_api_state == "UP" and current_state == "DOWN":
        msg = (
            f"🚨 <b>ALERT: SERVICE DOWN</b>\n\n\n"
            f"📡 URL: <code>{API_TO_MONITOR_URL}</code>\n\n"
            f"📅 Time: <b>{now}</b>\n\n"
            f"💥 Condition: <b>{reason}</b>\n\n"
            f"⚠️ Please check the server or VM."
        )
        await send_alert_to_pics(bot, msg)
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📣 <b>Status berubah: UP → DOWN</b>\n\n{msg}",
            parse_mode="HTML"
        )
        last_api_state = "DOWN"

    elif last_api_state == "DOWN" and current_state == "UP":
        msg = (
            f"✅ <b>SERVICE RUNNING</b>\n\n\n"
            f"📡 URL: <code>{API_TO_MONITOR_URL}</code>\n\n"
            f"📅 Time: <b>{now}</b>\n\n"
            f"💚 Condition: <b>{reason}</b>\n\n"
            f"System is running well."
        )
        await send_alert_to_pics(bot, msg)
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📣 <b>Status berubah: DOWN → UP</b>\n\n{msg}",
            parse_mode="HTML"
        )
        last_api_state = "UP"

    else:
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
                    username = f"@{getattr(user, 'username', '')}" if getattr(user, 'username', '') else "(no username)"
                    full_name = f"{first_name} {last_name}".strip()

                    if chat_id not in registered_pics_ids:
                        registered_pics_ids.append(chat_id)
                        await save_registered_pics()
                        await bot.send_message(
                            chat_id=chat_id,
                            text="✅ <b>AwarenixBot aktif</b>. Anda akan menerima alert status API.",
                            parse_mode="HTML"
                        )
                        msg = (
                            f"👤 <b>PIC Baru Terdaftar</b>\n"
                            f"📅 Waktu: <b>{get_jakarta_time()}</b>\n"
                            f"🆔 Chat ID: <code>{chat_id}</code>\n"
                            f"👨 Nama: <b>{full_name}</b>\n"
                            f"🔗 Username: {username}"
                        )
                        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="HTML")

                elif text == "/stop":
                    if chat_id in registered_pics_ids:
                        registered_pics_ids.remove(chat_id)
                        await save_registered_pics()
                        await bot.send_message(
                            chat_id=chat_id,
                            text="🛑 Anda telah berhenti menerima alert dari <b>AwarenixBot</b>.",
                            parse_mode="HTML"
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
                            text=f"📊 <b>STATUS SAAT INI</b>\n📡 <code>{API_TO_MONITOR_URL}</code>\n📅 <b>{now}</b>\nStatus: <b>{code}</b>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"🚨 Tidak dapat menjangkau <code>{API_TO_MONITOR_URL}</code> saat ini.",
                            parse_mode="HTML"
                        )

    except TelegramError as e:
        if "terminated by other getUpdates request" in str(e):
            print(f"[{get_jakarta_time()}] ⚠️ Bot instance lain masih jalan — polling diabaikan sementara.")
            await asyncio.sleep(5)
        else:
            print(f"[{get_jakarta_time()}] Telegram error: {e}")
    except Exception as e:
        print(f"[{get_jakarta_time()}] Unexpected error in handle_updates: {traceback.format_exc()}")


# --- Main Bot ---
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await load_registered_pics()
    load_last_state()

    async def loop_updates():
        while True:
            await handle_updates(bot)
            await asyncio.sleep(1)

    async def loop_api():
        while True:
            try:
                await check_api_status(bot)
            except Exception:
                print(f"[{get_jakarta_time()}] Error in check_api_status: {traceback.format_exc()}")
            print(f"[{get_jakarta_time()}] Loop alive — next check in {API_CHECK_INTERVAL_SECONDS}s")
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