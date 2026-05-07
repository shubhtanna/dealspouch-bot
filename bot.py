import os
import re
import json
import asyncio
import logging
import aiohttp

from urllib.parse import quote
from urllib.request import urlopen, Request

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

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
EARNKARO_API_TOKEN = os.environ.get('EARNKARO_API_TOKEN', '')
AMAZON_TAG = os.environ.get('AMAZON_TAG', 'dealy0c-21')

PORT = int(os.environ.get('PORT', 8080))

# =========================
# CATEGORIES
# =========================

CATEGORIES = {
    'electronics': {
        'keywords': [
            'mobile phone',
            'smartphone',
            'laptop',
            'tablet',
            'earphones',
            'earbuds',
            'headphones',
            'power bank',
            'charger',
            'iphone',
            'samsung',
            'oneplus',
            'realme',
            'oppo',
        ],
        'label': '📱 Electronics',
        'platforms': ['flipkart', 'amazon']
    },

    'fashion': {
        'keywords': [
            'shirt',
            'tshirt',
            'hoodie',
            'jeans',
            'dress',
            'kurti',
            'saree',
            'top',
            'jumpsuit',
            'bra'
        ],
        'label': '👗 Fashion',
        'platforms': ['flipkart', 'myntra', 'ajio', 'amazon']
    },

    'beauty': {
        'keywords': [
            'lipstick',
            'serum',
            'makeup',
            'skincare',
            'face wash'
        ],
        'label': '💄 Beauty',
        'platforms': ['amazon', 'flipkart']
    }
}

DEFAULT_PLATFORMS = [
    'flipkart',
    'amazon',
    'myntra',
    'ajio'
]

PLATFORM_LABELS = {
    'flipkart': '⚡ Flipkart',
    'amazon': '📦 Amazon',
    'myntra': '👗 Myntra',
    'ajio': '✨ Ajio'
}

ALL_KEYWORDS = [
    (kw, cat_key)
    for cat_key, cat_data in CATEGORIES.items()
    for kw in cat_data['keywords']
]

# =========================
# EARNKARO API CONVERTER
# FIX: regex was r'https?://\\S+' (double backslash = literal \S, matches nothing)
#      corrected to r'https?://\S+' (single backslash = proper \S word boundary)
# =========================

async def ek(base_url):

    if not EARNKARO_API_TOKEN:
        return base_url

    payload = {
        "deal": base_url,
        "convert_option": "convert_only"
    }

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

                    # ✅ FIXED: was r'https?://\\S+' — double backslash made \S literal,
                    #    so findall never matched any URL and always fell back to base_url
                    urls = re.findall(r'https?://\S+', converted)

                    if urls:
                        return urls[0]

    except Exception as e:
        logger.error(f"EarnKaro API Error: {e}")

    return base_url

# =========================
# PLATFORM LINKS
# =========================

async def platform_link(platform, q, q_dash, price_max=None):

    if platform == 'flipkart':

        url = f"https://www.flipkart.com/search?q={q}&sort=relevance"

        if price_max:
            url += (
                f"&p%5B%5D=facets.price_range.from%3DMin"
                f"&p%5B%5D=facets.price_range.to%3D{price_max}"
            )

        return await ek(url)

    elif platform == 'myntra':

        url = f"https://www.myntra.com/{q_dash}"

        if price_max:
            url += f"?f=Price%3A0%20TO%20{price_max}"

        return await ek(url)

    elif platform == 'ajio':

        url = f"https://www.ajio.com/search/?text={q}"

        return await ek(url)

    elif platform == 'amazon':

        url = f"https://www.amazon.in/s?k={q}&tag={AMAZON_TAG}"

        return url

    return '#'

# =========================
# PRICE PARSER
# =========================

def parse_price(t):

    price_max = None

    m = re.search(
        r'(?:under|below|less than|upto|up to)\s*₹?\s*(\d+)',
        t
    )

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

        match = process.extractOne(
            t,
            kw_list,
            scorer=fuzz.WRatio
        )

        if match and match[1] >= 75:

            matched_kw = match[0]

            detected_category = next(
                cat
                for kw, cat in ALL_KEYWORDS
                if kw == matched_kw
            )

    if detected_category:

        label = CATEGORIES[detected_category]['label']

        platforms = CATEGORIES[detected_category]['platforms']

    else:

        label = '🛍 General'

        platforms = DEFAULT_PLATFORMS

    return {
        'query': t,
        'price_max': price_max,
        'label': label,
        'platforms': platforms
    }

# =========================
# KEYBOARD
# =========================

async def build_keyboard(parsed):

    q = quote(parsed['query'], safe='')

    q_dash = quote(
        parsed['query'].replace(' ', '-'),
        safe=''
    )

    pmax = parsed['price_max']

    rows = []
    row = []

    for p in parsed['platforms']:

        link = await platform_link(
            p,
            q,
            q_dash,
            pmax
        )

        row.append(
            InlineKeyboardButton(
                PLATFORM_LABELS.get(p, p.title()),
                url=link
            )
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return InlineKeyboardMarkup(rows)

# =========================
# START COMMAND
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🛍 Welcome to Dealspouch Bot 🤖\n\n"
"Find products from all top shopping apps instantly 🚀\n\n"
"✅ Flipkart\n"
"✅ Amazon\n"
"✅ Myntra\n"
"✅ Ajio\n"
"✅ Shopsy\n\n"
"Example:\n"
"• hoodie under 500\n"
"• power bank 20000mah\n"
"• nike shoes\n"
"• saree under 999\n"
"• wireless earbuds\n\n"
"🔥 Smart Search\n"
"🔥 Budget Filters\n"
"🔥 Fast Shopping Links\n\n"
"⌨️ Type any product name and get instant shopping links 👇"

    )

# =========================
# SEARCH
# =========================

async def search_product(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if len(text) < 2:

        await update.message.reply_text(
            "Please type a product name."
        )

        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action='typing'
    )

    parsed = await parse_query(text)

    keyboard = await build_keyboard(parsed)

    price_line = ''

    if parsed['price_max']:

        price_line = (
            f"\n💰 Budget: Under ₹{parsed['price_max']}"
        )

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
    return web.Response(text="Bot Alive")

async def start_web_server():

    app = web.Application()

    app.router.add_get('/', health_handler)

    app.router.add_get('/health', health_handler)

    runner = web.AppRunner(app)

    await runner.setup()

    await web.TCPSite(
        runner,
        '0.0.0.0',
        PORT
    ).start()

    logger.info(f"Web server running on {PORT}")

# =========================
# MAIN
# =========================

async def main():

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN missing")

    await start_web_server()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            search_product
        )
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