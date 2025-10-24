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
API_CHECK_INTERVAL_SECONDS = 30
REGISTERED_PICS_FILE = 'registered_pics.json'
LAST_STATE_FILE = 'last_api_status.json'
HISTORY_LOG_FILE = 'status_history.log.json'
HISTORY_MAX_ENTRIES = 100
ADMIN_CHAT_ID = 2020661886

# --- Konfigurasi Anti-Flapping (Solusi Poin 1) ---
DOWN_THRESHOLD = 3
UP_THRESHOLD = 3

# --- Global ---
registered_pics_ids = []
last_update_id = None
last_api_state = None

# --- State Anti-Flapping ---
consecutive_failures = 0
consecutive_successes = 0


# --- Command Helper Text ---
def get_command_list():
    return (
        "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Available Commands:</b>\n\n"
        "🟢 /start - Subscribe to alerts\n"
        "🔴 /stop - Unsubscribe from alerts\n"
        "📊 /status - View last 5 status history\n"
        "🔍 /checknow - Check API status now\n"
    )


# --- Utilitas Waktu ---
def get_jakarta_time():
    utc_now = datetime.now(timezone.utc)
    jakarta_offset = timedelta(hours=7)
    jakarta_time = utc_now + jakarta_offset
    return jakarta_time.strftime("%d/%m/%Y %H:%M:%S WIB")


# --- Load & Save PIC (Tidak Berubah) ---
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


# --- Load & Save Last State (Modifikasi Poin 2) ---
def load_last_state():
    global last_api_state
    if os.path.exists(LAST_STATE_FILE):
        try:
            with open(LAST_STATE_FILE, 'r') as f:
                data = json.load(f)
                
                if "status" in data:
                    last_api_state = data.get("status", "UP").upper()
                elif "is_down" in data:
                    last_api_state = "DOWN" if data.get("is_down") else "UP"
                
            print(f"[{get_jakarta_time()}] Loaded last_api_state = {last_api_state}")
        except Exception as e:
            print(f"[{get_jakarta_time()}] Failed to load last state: {e}")
            last_api_state = None
    else:
        last_api_state = None


def save_last_state(state: str, reason: str, date_str: str):
    """Menyimpan status TERKINI ke file last_api_status.json"""
    data = {
        "status": state.lower(),
        "date": date_str,
        "message": reason
    }
    try:
        with open(LAST_STATE_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print(f"[{get_jakarta_time()}] Saved last_api_state = {state}")
    except Exception as e:
        print(f"[{get_jakarta_time()}] FAILED to save last_api_state: {e}")


def log_state_change(state: str, reason: str, date_str: str):
    """Menyimpan riwayat perubahan status ke history file"""
    history = []
    if os.path.exists(HISTORY_LOG_FILE):
        try:
            with open(HISTORY_LOG_FILE, 'r') as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        except Exception:
            history = []

    new_entry = {
        "status": state.lower(),
        "date": date_str,
        "message": reason
    }
    
    history.append(new_entry)
    
    if len(history) > HISTORY_MAX_ENTRIES:
        history = history[-HISTORY_MAX_ENTRIES:]
        
    try:
        with open(HISTORY_LOG_FILE, 'w') as f:
            json.dump(history, f, indent=4)
        print(f"[{get_jakarta_time()}] Logged state change to history file.")
    except Exception as e:
        print(f"[{get_jakarta_time()}] FAILED to log state change: {e}")


# --- Kirim Pesan (Tidak Berubah) ---
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
                    text=f"⚠️ <b>Failed to send message</b>\n\n👤 Chat ID: <code>{chat_id}</code>\n❌ Error: <code>{str(e)}</code>",
                    parse_mode="HTML"
                )
            except Exception as e2:
                print(f"[{get_jakarta_time()}] Failed to notify admin: {e2}")
            if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                registered_pics_ids.remove(chat_id)
                await save_registered_pics()


# --- Cek API (Modifikasi Poin 1 & 2) ---
async def check_api_status(bot: Bot):
    global last_api_state, consecutive_failures, consecutive_successes
    now = get_jakarta_time()

    print(f"[{now}] [APICheckLoop] Checking API {API_TO_MONITOR_URL}...")

    current_local_state = "UP"
    reason = "Service is operational"

    try:
        response = requests.get(API_TO_MONITOR_URL, timeout=5)
        code = response.status_code
        text = response.text.lower().strip()

        if code != 200 or any(err in text for err in ["error", "502", "503", "bad gateway", "not found"]):
            current_local_state = "DOWN"
            reason = f"HTTP {code} - Bad response detected"
    except requests.exceptions.ConnectionError:
        current_local_state = "DOWN"
        reason = "Connection failed - Server may be offline"
    except requests.exceptions.Timeout:
        current_local_state = "DOWN"
        reason = "Request timeout - Server not responding"
    except Exception as e:
        current_local_state = "DOWN"
        reason = f"Unexpected error: {e}"

    if current_local_state == "UP":
        consecutive_successes += 1
        consecutive_failures = 0
    else:
        consecutive_failures += 1
        consecutive_successes = 0

    print(f"[{now}] DEBUG: State={current_local_state} (Last={last_api_state}) | Successes={consecutive_successes}/{UP_THRESHOLD} | Failures={consecutive_failures}/{DOWN_THRESHOLD}")

    if last_api_state is None:
        last_api_state = current_local_state
        msg = (
            f"🤖 <b>AwarenixBot Activated</b>\n\n"
            f"🌐 <b>Monitoring:</b>\n"
            f"<code>{API_TO_MONITOR_URL}</code>\n\n"
            f"📅 <b>Started:</b> {now}\n"
            f"📊 <b>Initial Status:</b> {reason}\n"
            f"✅ <b>System monitoring is now active</b>"
        )
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="HTML")
        save_last_state(last_api_state, reason, now)
        log_state_change(last_api_state, reason, now)
        consecutive_failures = 0
        consecutive_successes = 0

    elif last_api_state == "UP" and consecutive_failures >= DOWN_THRESHOLD:
        msg = (
            f"🚨 <b>SERVICE DOWN ALERT</b>\n\n"
            f"🌐 <b>Target URL:</b>\n"
            f"<code>{API_TO_MONITOR_URL}</code>\n\n"
            f"📅 <b>Detected:</b> {now}\n"
            f"❌ <b>Issue:</b> {reason}\n"
            f"⚠️ <b>Action Required:</b>\n"
            f"Please check the server or VM immediately."
        )
        await send_alert_to_pics(bot, msg)
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📣 <b>Status Changed: UP → DOWN</b>\n\n{msg}" + get_command_list(),
            parse_mode="HTML"
        )
        last_api_state = "DOWN"
        save_last_state("DOWN", reason, now)
        log_state_change("DOWN", reason, now)
        consecutive_failures = 0

    elif last_api_state == "DOWN" and consecutive_successes >= UP_THRESHOLD:
        msg = (
            f"✅ <b>SERVICE RUNNING</b>\n\n"
            f"🌐 <b>Target URL:</b>\n"
            f"<code>{API_TO_MONITOR_URL}</code>\n\n"
            f"📅 <b>Restored:</b> {now}\n"
            f"✔️ <b>Status:</b> {reason}\n"
            f"<b>System is running again</b>"
        )
        await send_alert_to_pics(bot, msg)
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📣 <b>Status Changed: DOWN → UP</b>\n\n{msg}" + get_command_list(),
            parse_mode="HTML"
        )
        last_api_state = "UP"
        save_last_state("UP", reason, now)
        log_state_change("UP", reason, now)
        consecutive_successes = 0

    else:
        print(f"[{now}] No confirmed state change, skip alert.")


# --- Handle Telegram Commands (Modifikasi Poin 3) ---
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
                        msg = (
                            f"🤖 <b>Welcome to AwarenixBot!</b>\n\n"
                            f"✅ <b>Registration Successful</b>\n\n"
                            f"You will now receive API status alerts automatically.\n"
                        )
                        await bot.send_message(
                            chat_id=chat_id,
                            text=msg + get_command_list(),
                            parse_mode="HTML"
                        )
                        admin_msg = (
                            f"👤 <b>New PIC Registered</b>\n\n"
                            f"📅 <b>Time:</b> {get_jakarta_time()}\n"
                            f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n"
                            f"👨 <b>Name:</b> {full_name}\n"
                            f"🔗 <b>Username:</b> {username}\n"
                        )
                        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML")
                    else:
                        msg = (
                            f"ℹ️ <b>Already Registered</b>\n\n"
                            f"You're already subscribed to alerts.\n"
                        )
                        await bot.send_message(
                            chat_id=chat_id,
                            text=msg + get_command_list(),
                            parse_mode="HTML"
                        )

                elif text == "/stop":
                    if chat_id in registered_pics_ids:
                        registered_pics_ids.remove(chat_id)
                        await save_registered_pics()
                        msg = (
                            f"🛑 <b>Unsubscribed Successfully</b>\n\n"
                            f"You will no longer receive alerts from AwarenixBot.\n\n"
                            f"Use /start anytime to subscribe again.\n"
                        )
                        await bot.send_message(
                            chat_id=chat_id,
                            text=msg + get_command_list(),
                            parse_mode="HTML"
                        )
                    else:
                        msg = (
                            f"ℹ️ <b>Not Registered</b>\n\n"
                            f"You're not subscribed to alerts yet.\n\n"
                            f"Use /start to subscribe.\n"
                        )
                        await bot.send_message(
                            chat_id=chat_id,
                            text=msg + get_command_list(),
                            parse_mode="HTML"
                        )

                elif text == "/status":
                    msg = (
                        f"📊 <b>Status History</b>\n\n"
                        f"<b>Last 5 Status Changes:</b>\n\n"
                    )
                    if not os.path.exists(HISTORY_LOG_FILE):
                        msg += f"No history available yet.\n"
                    else:
                        try:
                            with open(HISTORY_LOG_FILE, 'r') as f:
                                history = json.load(f)
                            if not history or not isinstance(history, list):
                                msg += f"History file is empty.\n"
                            else:
                                last_5_entries = history[-5:]
                                last_5_entries.reverse()
                                
                                for idx, item in enumerate(last_5_entries, 1):
                                    status_icon = "✅" if item.get('status') == 'up' else '🚨'
                                    date = item.get('date', 'N/A')
                                    reason = item.get('message', 'N/A')
                                    status_text = item.get('status', 'N/A').upper()
                                    
                                    msg += f"{status_icon} <b>#{idx} - {status_text}</b>\n"
                                    msg += f"🕒 {date}\n"
                                    msg += f"📝 <i>{reason}</i>\n\n"
                                
                                    
                        except Exception as e:
                            msg += f"❌ Failed to read history file\n\n{e}\n"
                    
                    await bot.send_message(
                        chat_id=chat_id,
                        text=msg + get_command_list(),
                        parse_mode="HTML"
                    )

                elif text == "/checknow":
                    now = get_jakarta_time()
                    check_msg = (
                        f"🔍 <b>Live Status Check</b>\n\n"
                    )
                    try:
                        response = requests.get(API_TO_MONITOR_URL, timeout=5)
                        code = response.status_code
                        status_icon = "✅" if code == 200 else "⚠️"
                        check_msg += (
                            f"🌐 <b>URL:</b>\n<code>{API_TO_MONITOR_URL}</code>\n\n"
                            f"📅 <b>Checked:</b> {now}\n"
                            f"{status_icon} <b>HTTP Status:</b> {code}\n"
                        )
                    except Exception as e:
                        check_msg += (
                            f"🌐 <b>URL:</b>\n<code>{API_TO_MONITOR_URL}</code>\n\n"
                            f"📅 <b>Checked:</b> {now}\n"
                            f"❌ <b>Error:</b> Unable to reach server\n\n"
                            f"<i>{str(e)}</i>\n"
                        )
                    
                    await bot.send_message(
                        chat_id=chat_id,
                        text=check_msg + get_command_list(),
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