import os
import re
import json
import asyncio
import logging
import aiohttp
from datetime import datetime

from urllib.parse import quote
from aiohttp import web
from rapidfuzz import fuzz, process

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# =========================
# ENV
# =========================

BOT_TOKEN          = os.environ.get('BOT_TOKEN', '')
GROQ_API_KEY       = os.environ.get('GROQ_API_KEY', '')
EARNKARO_API_TOKEN = os.environ.get('EARNKARO_API_TOKEN', '')
AMAZON_TAG         = os.environ.get('AMAZON_TAG', 'dealy0c-21')
ADMIN_ID           = int(os.environ.get('ADMIN_ID', '0'))   # your Telegram user ID

PORT = int(os.environ.get('PORT', 8080))

# =========================
# USER TRACKING
#
# Stored in users.json as:
# {
#   "123456789": {
#     "name": "Ravi",
#     "username": "ravi123",
#     "first_seen": "2026-05-08 10:00",
#     "last_seen":  "2026-05-08 12:30",
#     "searches":   17
#   }, ...
# }
#
# NOTE: On Render free tier, disk resets on each redeploy.
# To persist across deploys, add a Render Disk and set
# USERS_FILE=/data/users.json in your env vars.
# =========================

USERS_FILE = os.environ.get('USERS_FILE', 'users.json')

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_users(users: dict):
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save users: {e}")

# In-memory store — loaded once at startup, written on every update
users_db: dict = load_users()

def track_user(update: Update):
    """Call at the start of every handler to record the user."""
    user = update.effective_user
    if not user:
        return

    uid = str(user.id)
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    if uid not in users_db:
        users_db[uid] = {
            'name':       user.full_name,
            'username':   user.username or '',
            'first_seen': now,
            'last_seen':  now,
            'searches':   0,
        }
        logger.info(f"[NEW USER] {user.full_name} (@{user.username}) id={uid}")
    else:
        users_db[uid]['last_seen'] = now
        users_db[uid]['name']      = user.full_name

    users_db[uid]['searches'] = users_db[uid].get('searches', 0) + 1
    save_users(users_db)

# =========================
# CATEGORIES
# =========================

CATEGORIES = {
    'electronics': {
        'keywords': [
            'mobile phone', 'smartphone', 'laptop', 'tablet',
            'earphones', 'earbuds', 'headphones', 'power bank',
            'charger', 'iphone', 'samsung', 'oneplus', 'realme', 'oppo',
        ],
        'label': '📱 Electronics',
        'platforms': ['flipkart', 'amazon']
    },
    'fashion': {
        'keywords': [
            'shirt', 'tshirt', 'hoodie', 'jeans', 'dress',
            'kurti', 'saree', 'top', 'jumpsuit', 'bra'
        ],
        'label': '👗 Fashion',
        'platforms': ['flipkart', 'myntra', 'ajio', 'amazon']
    },
    'beauty': {
        'keywords': [
            'lipstick', 'serum', 'makeup', 'skincare', 'face wash'
        ],
        'label': '💄 Beauty',
        'platforms': ['amazon', 'flipkart']
    }
}

DEFAULT_PLATFORMS = ['flipkart', 'amazon', 'myntra', 'ajio']

PLATFORM_LABELS = {
    'flipkart': '⚡ Flipkart',
    'amazon':   '📦 Amazon',
    'myntra':   '👗 Myntra',
    'ajio':     '✨ Ajio'
}

ALL_KEYWORDS = [
    (kw, cat_key)
    for cat_key, cat_data in CATEGORIES.items()
    for kw in cat_data['keywords']
]

# =========================
# EARNKARO API CONVERTER
# =========================

async def ek(base_url):
    if not EARNKARO_API_TOKEN:
        return base_url

    payload = {"deal": base_url, "convert_option": "convert_only"}
    headers = {
        "Authorization": f"Bearer {EARNKARO_API_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://ekaro-api.affiliaters.in/api/converter/public",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                data = await response.json()
                logger.info(f"EarnKaro Response: {data}")
                if data.get("success") == 1:
                    converted = data.get("data", "")
                    urls = re.findall(r'https?://\S+', converted)
                    if urls:
                        return urls[0]
    except Exception as e:
        logger.error(f"EarnKaro API Error: {e}")

    return base_url

# =========================
# PLATFORM LINKS
# =========================

async def platform_link(platform, q, q_dash, price_max=None, parsed_query=''):

    if platform == 'flipkart':
        url = f"https://www.flipkart.com/search?q={q}&sort=relevance"
        if price_max:
            url += (
                f"&p%5B%5D=facets.price_range.from%3DMin"
                f"&p%5B%5D=facets.price_range.to%3D{price_max}"
            )
        return await ek(url)

    elif platform == 'myntra':
        # /search/{slug} works; bare /{slug} returns 0 results
        url = f"https://www.myntra.com/search/{q_dash}"
        if price_max:
            url += f"?f=Price%3A0+TO+{price_max}"
        return await ek(url)

    elif platform == 'ajio':
        url = f"https://www.ajio.com/search/?text={q}"
        return await ek(url)

    elif platform == 'amazon':
        # Embed price in query — Amazon NLP understands "kurti under 500"
        if price_max:
            search_query = quote(f"{parsed_query} under {price_max}", safe='')
        else:
            search_query = q
        url = f"https://www.amazon.in/s?k={search_query}&tag={AMAZON_TAG}"
        return url

    return '#'

# =========================
# PRICE PARSER
# =========================

def parse_price(t):
    price_max = None
    m = re.search(r'(?:under|below|less than|upto|up to)\s*₹?\s*(\d+)', t)
    if m:
        price_max = int(m.group(1))
        t = t[:m.start()].strip()
    return t.strip(), price_max

# =========================
# QUERY PARSER
# =========================

async def parse_query(text):
    t = text.lower().strip()
    t, price_max = parse_price(t)

    detected_category = None

    for cat_key, cat_data in CATEGORIES.items():
        for kw in cat_data['keywords']:
            if kw in t:
                detected_category = cat_key
                break
        if detected_category:
            break

    if not detected_category:
        kw_list = [kw for kw, _ in ALL_KEYWORDS]
        match = process.extractOne(t, kw_list, scorer=fuzz.WRatio)
        if match and match[1] >= 75:
            matched_kw = match[0]
            detected_category = next(
                cat for kw, cat in ALL_KEYWORDS if kw == matched_kw
            )

    if detected_category:
        label     = CATEGORIES[detected_category]['label']
        platforms = CATEGORIES[detected_category]['platforms']
    else:
        label     = '🛍 General'
        platforms = DEFAULT_PLATFORMS

    return {
        'query':     t,
        'price_max': price_max,
        'label':     label,
        'platforms': platforms
    }

# =========================
# KEYBOARD
# =========================

async def build_keyboard(parsed):
    q      = quote(parsed['query'], safe='')
    q_dash = quote(parsed['query'].replace(' ', '-'), safe='')
    pmax   = parsed['price_max']

    rows = []
    row  = []

    for p in parsed['platforms']:
        link = await platform_link(p, q, q_dash, pmax, parsed_query=parsed['query'])
        row.append(InlineKeyboardButton(PLATFORM_LABELS.get(p, p.title()), url=link))
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return InlineKeyboardMarkup(rows)

# =========================
# COMMANDS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    await update.message.reply_text(
        "👋 Welcome to ShopEasy Bot\n\n"
        "Send any product name.\n\n"
        "Example:\n"
        "• hoodie under 500\n"
        "• power bank\n"
        "• padded bra\n"
        "• nike shoes"
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats — admin only.
    Shows total users, today active, top searchers.
    """
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    total = len(users_db)
    today = datetime.now().strftime('%Y-%m-%d')

    active_today = sum(
        1 for u in users_db.values()
        if u.get('last_seen', '').startswith(today)
    )

    # Top 5 by searches
    top = sorted(
        users_db.items(),
        key=lambda x: x[1].get('searches', 0),
        reverse=True
    )[:5]

    top_lines = '\n'.join(
        f"  {i+1}. {u['name']} — {u.get('searches', 0)} searches"
        for i, (_, u) in enumerate(top)
    )

    await update.message.reply_text(
        f"📊 *Bot Stats*\n\n"
        f"👥 Total users: *{total}*\n"
        f"🟢 Active today: *{active_today}*\n\n"
        f"🏆 Top searchers:\n{top_lines}",
        parse_mode='Markdown'
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /broadcast <message> — admin only.
    Sends a message to ALL users who have used the bot.
    """
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <your message>")
        return

    msg    = ' '.join(context.args)
    total  = len(users_db)
    sent   = 0
    failed = 0

    await update.message.reply_text(f"📤 Broadcasting to {total} users...")

    for uid in list(users_db.keys()):
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg)
            sent += 1
            await asyncio.sleep(0.05)   # ~20 msgs/sec — stays under Telegram limits
        except Exception as e:
            logger.warning(f"Broadcast failed for {uid}: {e}")
            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast done!\n"
        f"Sent: {sent} | Failed: {failed}"
    )


# =========================
# SEARCH
# =========================

async def search_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update)

    text = update.message.text.strip()

    if len(text) < 2:
        await update.message.reply_text("Please type a product name.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action='typing'
    )

    parsed   = await parse_query(text)
    keyboard = await build_keyboard(parsed)

    price_line = ''
    if parsed['price_max']:
        price_line = f"\n💰 Budget: Under ₹{parsed['price_max']}"

    await update.message.reply_text(
        f"🔍 {parsed['query'].title()}\n"
        f"📂 {parsed['label']}"
        f"{price_line}\n\n"
        f"👇 Tap below to shop",
        reply_markup=keyboard
    )

# =========================
# HEALTH CHECK
# =========================

async def health_handler(request):
    return web.Response(
        text=json.dumps({"status": "ok", "users": len(users_db)}),
        content_type='application/json'
    )

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_handler)
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    logger.info(f"Web server running on {PORT}")

# =========================
# MAIN
# =========================

async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN missing")

    await start_web_server()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start',     start))
    app.add_handler(CommandHandler('stats',     stats_cmd))
    app.add_handler(CommandHandler('broadcast', broadcast))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, search_product)
    )

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

    logger.info("🤖 Bot LIVE")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())