import asyncio
import json
import os
import requests
from telegram import Bot
from telegram.error import TelegramError
from datetime import datetime, timedelta

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = '7956809240:AAFiHa-y6Gi-aIVKGa3wm92X-DZpI4Bdlxg'
API_TO_MONITOR_URL = 'https://dashboard.kliktrap.com' 
API_CHECK_INTERVAL_SECONDS = 60 
REGISTERED_PICS_FILE = 'registered_pics.json'

# --- Inisialisasi Global ---
registered_pics_ids = []
last_update_id = None 

# --- Fungsi Utilitas Waktu ---
def get_jakarta_time():
    """Mengembalikan waktu saat ini dalam format WIB (GMT+7)."""
    utc_now = datetime.utcnow()
    jakarta_offset = timedelta(hours=7)
    jakarta_time = utc_now + jakarta_offset
    return jakarta_time.strftime("%d/%m/%Y %H:%M:%S WIB")

# --- Fungsi Persistensi Data PIC ---
async def load_registered_pics():
    """Memuat daftar chat ID PIC dari file JSON."""
    global registered_pics_ids
    if os.path.exists(REGISTERED_PICS_FILE):
        with open(REGISTERED_PICS_FILE, 'r') as f:
            try:
                data = json.load(f)
                registered_pics_ids = list(set(data)) 
                print(f"[{get_jakarta_time()}] Loaded {len(registered_pics_ids)} registered PICs from {REGISTERED_PICS_FILE}")
            except json.JSONDecodeError:
                print(f"[{get_jakarta_time()}] Error decoding {REGISTERED_PICS_FILE}. Starting with empty list.")
                registered_pics_ids = []
    else:
        print(f"[{get_jakarta_time()}] File {REGISTERED_PICS_FILE} not found. Starting with empty list.")
        registered_pics_ids = []

async def save_registered_pics():
    """Menyimpan daftar chat ID PIC ke file JSON."""
    with open(REGISTERED_PICS_FILE, 'w') as f:
        json.dump(list(set(registered_pics_ids)), f, indent=4) 
    print(f"[{get_jakarta_time()}] Saved {len(registered_pics_ids)} registered PICs to {REGISTERED_PICS_FILE}")

# --- Fungsi Pemantauan API ---
async def check_api_status(bot: Bot):
    """Memeriksa status API dan mengirim alert jika down."""
    task = asyncio.current_task()
    task_name = task.get_name() if task and hasattr(task, "get_name") else "UnknownTask"
    
    # Escape URL untuk MarkdownV2 jika perlu, terutama tanda titik
    escaped_api_url = API_TO_MONITOR_URL.replace('.', '\\.') 
    
    print(f"[{get_jakarta_time()}] [{task_name}] Checking API status at {API_TO_MONITOR_URL}...")
    try:
        response = requests.get(API_TO_MONITOR_URL, timeout=5) 
        if response.status_code != 200:
            message = (
                f"🚨 *ALERT: API di `{escaped_api_url}` mengembalikan status code "
                f"*{response.status_code}*\\! Mohon segera dicek\\."
            )
            await send_alert_to_pics(bot, message)
            print(f"[{get_jakarta_time()}] API down! Alert sent for status code {response.status_code}.")
        else:
            print(f"[{get_jakarta_time()}] API is up and running. Status: {response.status_code}")
    except requests.exceptions.ConnectionError:
        message = (
            f"🚨 *ALERT: API di `{escaped_api_url}` tidak bisa diakses atau mungkin mati\\!* "
            f"Mohon segera dicek\\."
        )
        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] API down! Alert sent due to connection error.")
    except requests.exceptions.Timeout:
        message = (
            f"🚨 *ALERT: API di `{escaped_api_url}` tidak merespons dalam waktu yang ditentukan\\!* "
            f"Mohon segera dicek\\."
        )
        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] API down! Alert sent due to timeout.")
    except Exception as e:
        message = (
            f"🚨 *ALERT: Terjadi error tidak terduga saat memeriksa API di `{escaped_api_url}`:* "
            f"`{e}`\\."
        )
        await send_alert_to_pics(bot, message)
        print(f"[{get_jakarta_time()}] API check failed with unexpected error: {e}")

async def send_alert_to_pics(bot: Bot, message: str):
    """Mengirim pesan alert ke semua PIC yang terdaftar."""
    if not registered_pics_ids:
        print(f"[{get_jakarta_time()}] No PICs registered to receive alerts. Alert not sent.")
        return

    for chat_id in registered_pics_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            print(f"[{get_jakarta_time()}] Alert sent to chat ID: {chat_id}")
        except TelegramError as e:
            print(f"[{get_jakarta_time()}] Could not send message to chat ID {chat_id}: {e}")
            if "blocked by the user" in str(e).lower() or "chat not found" in str(e).lower():
                print(f"[{get_jakarta_time()}] Removing invalid/blocked chat ID: {chat_id}")
                registered_pics_ids.remove(chat_id)
                await save_registered_pics() 

# --- Fungsi Penanganan Update Telegram ---
async def handle_updates(bot: Bot):
    """Menangani update dari Telegram, khususnya untuk perintah /start dan /stop."""
    global last_update_id 
    
    task = asyncio.current_task()
    task_name = task.get_name() if task and hasattr(task, "get_name") else "UnknownTask"
    print(f"[{get_jakarta_time()}] [{task_name}] Checking for new Telegram updates (offset: {last_update_id})...")
    
    try:
        # Gunakan last_update_id + 1 sebagai offset untuk mencegah pemrosesan update yang sama
        updates = await bot.get_updates(offset=last_update_id + 1 if last_update_id is not None else None, timeout=10) 

        if not updates:
            print(f"[{get_jakarta_time()}] No new updates found.")
        else:
            for update in updates:
                # Perbarui last_update_id setelah memproses setiap update
                # Ini penting untuk memastikan update berikutnya dimulai dari ID yang benar
                if update.update_id >= (last_update_id if last_update_id is not None else 0):
                    last_update_id = update.update_id

                if update.message and update.message.text:
                    chat_id = update.message.chat.id
                    message_text = update.message.text
                    chat_title = update.message.chat.title if update.message.chat.title else "Personal Chat" 

                    print(f"[{get_jakarta_time()}] Processing message from Chat ID: {chat_id} | Chat Title: {chat_title} | Message: {message_text} | Update ID: {update.update_id}")

                    if message_text == '/start':
                        if chat_id not in registered_pics_ids:
                            registered_pics_ids.append(chat_id)
                            await save_registered_pics() 
                            await bot.send_message(chat_id=chat_id, text="Terima kasih telah memulai AwarenixBot! Anda akan menerima peringatan jika API bermasalah.")
                            print(f"[{get_jakarta_time()}] Added new PIC: {chat_id}")
                        else:
                            # Jika sudah terdaftar, tidak perlu mengirim pesan lagi
                            print(f"[{get_jakarta_time()}] Chat ID {chat_id} already registered.")
                            # Anda bisa memilih untuk tidak mengirim pesan sama sekali di sini
                            # Atau mengirim pesan konfirmasi singkat:
                            # await bot.send_message(chat_id=chat_id, text="Anda sudah terdaftar untuk menerima peringatan.")
                            pass # Tidak melakukan apa-apa jika user sudah terdaftar dan mengirim /start lagi
                    elif message_text == '/stop':
                        if chat_id in registered_pics_ids:
                            registered_pics_ids.remove(chat_id)
                            await save_registered_pics() 
                            await bot.send_message(chat_id=chat_id, text="Anda telah berhenti menerima peringatan dari AwarenixBot.")
                            print(f"[{get_jakarta_time()}] Removed PIC: {chat_id}")
                        else:
                            await bot.send_message(chat_id=chat_id, text="Anda tidak terdaftar untuk menerima peringatan.")
                    else:
                        # Pesan "Halo! Saya AwarenixBot..." hanya dikirim jika:
                        # 1. Ini adalah pesan pertama dari user dan user belum terdaftar
                        # 2. User mengirim pesan selain /start atau /stop
                        # Karena kita sudah mengelola offset, ini akan jarang terjadi berulang
                        # kecuali memang ada banyak pesan acak dari user
                        await bot.send_message(chat_id=chat_id, text="Halo! Saya AwarenixBot. Kirim `/start` untuk mendaftar menerima peringatan API, atau `/stop` untuk berhenti.")
    except TelegramError as e:
        print(f"[{get_jakarta_time()}] Error while fetching or handling updates: {e}")
    except Exception as e:
        print(f"[{get_jakarta_time()}] An unexpected error occurred in handle_updates: {e}")

# --- Fungsi Utama Bot ---
async def main():
    """Fungsi utama untuk menjalankan bot."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Muat PIC yang terdaftar saat bot dimulai
    await load_registered_pics()

    async def telegram_update_loop():
        """Loop untuk memeriksa dan memproses update Telegram."""
        while True:
            await handle_updates(bot)
            await asyncio.sleep(1) # Tunggu 1 detik sebelum cek update lagi

    async def api_check_loop():
        """Loop untuk memeriksa status API secara berkala."""
        while True:
            await check_api_status(bot)
            await asyncio.sleep(API_CHECK_INTERVAL_SECONDS) # Tunggu sesuai interval

    # Buat dan jalankan task secara bersamaan
    telegram_update_task = asyncio.create_task(
        telegram_update_loop(), name="TelegramUpdateLoop"
    )

    api_check_task = asyncio.create_task(
        api_check_loop(), name="APICheckLoop"
    )

    # Tunggu kedua task selesai (atau berjalan selamanya)
    await asyncio.gather(telegram_update_task, api_check_task)

if __name__ == '__main__':
    print(f"[{get_jakarta_time()}] Starting AwarenixBot...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"[{get_jakarta_time()}] \nBot stopped by user (Ctrl+C).")
    except Exception as e:
        print(f"[{get_jakarta_time()}] An error occurred: {e}")