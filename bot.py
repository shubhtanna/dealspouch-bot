import os, re, json, asyncio, logging, aiohttp
from datetime import datetime
from urllib.parse import quote
from aiohttp import web
from rapidfuzz import fuzz, process
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ══ ENV ══
BOT_TOKEN          = os.environ.get('BOT_TOKEN', '')
GROQ_API_KEY       = os.environ.get('GROQ_API_KEY', '')
EARNKARO_API_TOKEN = os.environ.get('EARNKARO_API_TOKEN', '')
AMAZON_TAG         = os.environ.get('AMAZON_TAG', 'dealy0c-21')
ADMIN_ID           = int(os.environ.get('ADMIN_ID', '0'))
WELCOME_IMAGE_URL  = os.environ.get('WELCOME_IMAGE_URL', '')
PORT               = int(os.environ.get('PORT', 8080))
USERS_FILE = 'users.json'

# ══ USER TRACKING ══
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_users(users):
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save users: {e}")

users_db = load_users()

def track_user(update: Update):
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

# ══ CATEGORIES ══
CATEGORIES = {
    'ethnic_women': {
        'keywords': ['saree','sari','lehenga','kurti','salwar','churidar','dupatta','anarkali','palazzo','sharara','suit set','ethnic','traditional','kurta set','ghagra','kurtis'],
        'label': '👗 Ethnic Wear',
        'platforms': ['myntra','shopsy','ajio','flipkart','amazon'],
    },
    'western_women': {
        'keywords': ['dress','top women','jeans women','skirt','crop top','jumpsuit','co-ord','bodycon','maxi dress','mini dress','blouse','women shirt','romper','midi dress','wrap dress'],
        'label': '👚 Western Wear',
        'platforms': ['myntra','ajio','flipkart','amazon','shopsy'],
    },
    'men_clothing': {
        'keywords': ['shirt men','tshirt men','t-shirt men','trouser','chinos','kurta men','sherwani','suit men','blazer men','polo shirt','men shirt','men tshirt','men kurta','men jeans','men jacket','men hoodie','jogger men','men shorts','men coat'],
        'label': "👔 Men's Wear",
        'platforms': ['myntra','ajio','flipkart','amazon','shopsy'],
    },
    'footwear': {
        'keywords': ['shoes','sneakers','sandals','heels','boots','loafers','slippers','chappal','flats','wedges','kolhapuri','sports shoes','running shoes','casual shoes','formal shoes','flip flops','crocs','mules'],
        'label': '👟 Footwear',
        'platforms': ['myntra','ajio','flipkart','amazon','shopsy'],
    },
    'bags': {
        'keywords': ['handbag','purse','clutch','tote bag','backpack','sling bag','wallet','potli','laptop bag','travel bag','duffle bag','trolley bag','gym bag','school bag','messenger bag'],
        'label': '👜 Bags & Luggage',
        'platforms': ['myntra','flipkart','amazon','ajio','shopsy'],
    },
    'jewellery': {
        'keywords': ['jewellery','jewelry','necklace','earrings','ring','bracelet','bangle','anklet','maang tikka','jhumka','pendant','chain','choker','nose ring','haar','mangalsutra','kundan','oxidized jewelry'],
        'label': '💍 Jewellery',
        'platforms': ['myntra','shopsy','amazon','flipkart','ajio'],
    },
    'innerwear': {
        'keywords': ['bra','panty','panties','innerwear','underwear','lingerie','bralette','sports bra','boxer','brief','trunk','camisole','shapewear','nightwear','nightsuit','pyjama','loungewear'],
        'label': '🩱 Innerwear & Lingerie',
        'platforms': ['myntra','flipkart','amazon','shopsy'],
    },
    'beauty': {
        'keywords': ['lipstick','foundation','mascara','serum','moisturizer','sunscreen','kajal','eyeliner','blush','perfume','skincare','makeup','face wash','shampoo','hair oil','conditioner','toner','face mask','concealer','bb cream','deodorant','body lotion','hair color','nail polish','micellar water','retinol','niacinamide'],
        'label': '💄 Beauty & Skincare',
        'platforms': ['amazon','flipkart','shopsy'],
    },
    'kids': {
        'keywords': ['kids wear','children clothes','baby clothes','toddler clothes','boy dress','girl dress','kids shoes','kids jacket','infant clothes','newborn clothes','kids kurta','baby toy','kids bag'],
        'label': '👶 Kids & Baby',
        'platforms': ['flipkart','amazon','myntra','shopsy'],
    },
    'sports': {
        'keywords': ['gym wear','yoga pants','sports jersey','track pant','sports leggings','activewear','workout clothes','fitness wear','cycling wear','swimming costume','cricket kit','football kit','badminton racket','tennis racket','dumbbells','resistance band','skipping rope','yoga mat','gym gloves'],
        'label': '🏋️ Sports & Fitness',
        'platforms': ['myntra','ajio','flipkart','amazon'],
    },
    'winter': {
        'keywords': ['jacket','hoodie','sweatshirt','sweater','coat','pullover','cardigan','windcheater','thermal wear','woolen','shawl','muffler','beanie','gloves','scarf','blanket','quilt','comforter'],
        'label': '🧥 Winter Wear',
        'platforms': ['myntra','ajio','flipkart','amazon','shopsy'],
    },
    'watches': {
        'keywords': ['watch','smartwatch','analog watch','digital watch','wristwatch','smart band','fitness band','luxury watch','sport watch','apple watch','samsung watch','fastrack','titan watch','fossil watch'],
        'label': '⌚ Watches & Wearables',
        'platforms': ['flipkart','amazon','myntra','ajio','shopsy'],
    },
    'eyewear': {
        'keywords': ['sunglasses','eyewear','spectacles','eyeglasses','goggles','reading glasses','contact lens','blue light glasses','aviator glasses','wayfarer'],
        'label': '🕶️ Eyewear',
        'platforms': ['myntra','flipkart','amazon','ajio','shopsy'],
    },
    'electronics': {
        'keywords': ['mobile phone','smartphone','laptop','tablet','earphones','earbuds','headphones','bluetooth speaker','charger','power bank','keyboard','computer mouse','monitor','smart tv','television','camera','printer','wifi router','hard disk','pen drive','ssd','webcam','microphone','gamepad','usb cable','hdmi cable','laptop stand','phone case','screen guard','tripod','drone','iphone','samsung phone','redmi','realme','oneplus','oppo','vivo','boat earphones','jbl speaker','sony headphones','lg tv','dell laptop','hp laptop','lenovo laptop','asus laptop','acer laptop','mi phone','xiaomi'],
        'label': '📱 Electronics & Gadgets',
        'platforms': ['flipkart','amazon','shopsy'],
    },
    'home_kitchen': {
        'keywords': ['bedsheet','pillow','curtain','towel','mattress','sofa','dining chair','coffee table','floor lamp','cookware set','kitchen utensils','mixer grinder','pressure cooker','water bottle','lunch box','storage box','wall art','carpet','bed cover','cushion cover','dinner set','coffee mug','electric kettle','clothes iron','vacuum cleaner','air purifier','ceiling fan','air cooler','room heater','water purifier','washing machine','refrigerator','microwave oven','induction cooktop','kitchen chimney','water heater','geyser'],
        'label': '🏠 Home & Kitchen',
        'platforms': ['flipkart','amazon','shopsy'],
    },
    'books': {
        'keywords': ['novel','fiction book','non fiction book','textbook','comic book','manga','autobiography','self help book','biography','thriller book','mystery book','romance book','poetry book','cookbook','magazine','ncert','upsc book','competitive exam book'],
        'label': '📚 Books',
        'platforms': ['amazon','flipkart'],
    },
    'toys_games': {
        'keywords': ['toy','board game','lego set','jigsaw puzzle','barbie doll','action figure','remote control car','video game','playstation','xbox','nintendo switch','rc car','soft toy','teddy bear','rubiks cube','chess set','carrom board','monopoly','uno cards'],
        'label': '🧸 Toys & Games',
        'platforms': ['flipkart','amazon','shopsy'],
    },
    'stationery': {
        'keywords': ['ballpen','fountain pen','pencil','spiral notebook','diary','daily planner','stationery set','color pencils','sketch pens','marker pens','highlighter pen','eraser','sharpener','geometry box','drawing book','canvas','acrylic paint','paint brush','watercolor'],
        'label': '✏️ Stationery & Art',
        'platforms': ['amazon','flipkart','shopsy'],
    },
    'health': {
        'keywords': ['whey protein','protein powder','creatine supplement','omega 3','multivitamin','ayurvedic medicine','herbal supplement','health drink','glucose monitor','bp monitor','digital thermometer','pulse oximeter','face mask','hand sanitizer','nebulizer','heating pad','massager','glucometer'],
        'label': '💊 Health & Wellness',
        'platforms': ['amazon','flipkart','shopsy'],
    },
    'groceries': {
        'keywords': ['basmati rice','toor dal','wheat flour','cooking oil','sugar','black salt','garam masala','green tea','instant coffee','cream biscuit','namkeen snacks','potato chips','dark chocolate','fruit juice','tomato sauce','mango pickle','pure ghee','organic honey','cashews','almonds','rolled oats','corn flakes','pasta','instant noodles'],
        'label': '🛒 Groceries & Food',
        'platforms': ['amazon','flipkart'],
    },
    'pet': {
        'keywords': ['dog food','cat food','pet collar','dog leash','cat toy','fish food','bird cage','pet bed','aquarium','pet shampoo','pet carrier','dog toy','cat litter','hamster cage','dog treat'],
        'label': '🐾 Pet Supplies',
        'platforms': ['amazon','flipkart','shopsy'],
    },
    'automotive': {
        'keywords': ['car seat cover','bike helmet','car cover','bike cover','car perfume','car charger','dash camera','parking sensor','car vacuum cleaner','air freshener car','engine oil','car tool kit','jump starter','tyre inflator','bike lock','car mat'],
        'label': '🚗 Automotive',
        'platforms': ['amazon','flipkart','shopsy'],
    },
    'office': {
        'keywords': ['office chair','study desk','file folder','whiteboard','projector','printer cartridge','office stationery','scientific calculator','stapler','a4 paper','envelope','sticky notes','id card holder','pen stand','document file'],
        'label': '💼 Office Supplies',
        'platforms': ['amazon','flipkart','shopsy'],
    },
    'furniture': {
        'keywords': ['bed frame','wardrobe','almirah','shoe rack','bookshelf','wall shelf','cabinet','dining table','study table','dressing table','recliner sofa','bean bag','hammock','ladder shelf','tv unit','center table'],
        'label': '🛋️ Furniture',
        'platforms': ['flipkart','amazon','shopsy'],
    },
}

DEFAULT_PLATFORMS = ['flipkart','amazon','myntra','shopsy','ajio']

PLATFORM_LABELS = {
    'flipkart' : '⚡ Flipkart',
    'myntra'   : '👗 Myntra',
    'shopsy'   : '🏷 Shopsy',
    'ajio'     : '✨ Ajio',
    'amazon'   : '📦 Amazon',
}

ALL_KEYWORDS = [(kw, cat_key) for cat_key, cat_data in CATEGORIES.items() for kw in cat_data['keywords']]

# ══ EARNKARO API ══
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
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                data = await response.json()
                if data.get("success") == 1:
                    converted = data.get("data", "")
                    urls = re.findall(r'https?://\S+', converted)
                    if urls:
                        return urls[0]
    except Exception as e:
        logger.error(f"EarnKaro API Error: {e}")
    return base_url

# ══ PLATFORM LINKS ══
async def platform_link(platform, q, q_dash, price_max=None, parsed=None):
    raw_query = parsed['query'] if parsed else ''

    if platform == 'flipkart':
        url = f"https://www.flipkart.com/search?q={q}&sort=relevance"
        if price_max:
            url += f"&p%5B%5D=facets.price_range.from%3DMin&p%5B%5D=facets.price_range.to%3D{price_max}"
        return await ek(url)

    elif platform == 'myntra':
        # ✅ Fixed: Myntra slug format without /search/
        if price_max:
            slug = quote(f"{raw_query} under {price_max}".replace(' ', '-'), safe='')
        else:
            slug = q_dash
        url = f"https://www.myntra.com/{slug}"
        return await ek(url)

    elif platform == 'shopsy':
        url = f"https://www.shopsy.in/{q_dash}/pr?sort=price_asc"
        if price_max:
            url += f"&p%5B%5D=facets.price_range.from%3DMin&p%5B%5D=facets.price_range.to%3D{price_max}"
        return await ek(url)

    elif platform == 'ajio':
        url = f"https://www.ajio.com/search/?text={q}"
        if price_max:
            url += f"&query={q}%3Arelevance%3ApriceTo%3A{price_max}"
        return await ek(url)

    elif platform == 'amazon':
        if price_max:
            search_query = quote(f"{raw_query} under {price_max}", safe='')
        else:
            search_query = q
        url = f"https://www.amazon.in/s?k={search_query}&tag={AMAZON_TAG}"
        return url

    return '#'

# ══ GROQ AI FALLBACK ══
async def ai_categorize(query):
    try:
        category_list = ', '.join(CATEGORIES.keys())
        prompt = f"""User typed (may have spelling mistakes): "{query}"
1. Fix spelling mistakes
2. Detect category from: {category_list}
3. If none match use "general"
Respond ONLY with JSON: {{"fixed_query": "corrected name", "category": "category_key"}}"""
        payload = json.dumps({
            "model": "llama-3.1-8b-instant",
            "temperature": 0.1,
            "max_tokens": 100,
            "messages": [{"role": "user", "content": prompt}]
        }).encode('utf-8')
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={'Content-Type':'application/json','Authorization':f'Bearer {GROQ_API_KEY}'},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                data   = await r.json()
                raw    = data['choices'][0]['message']['content']
                result = json.loads(raw.replace('```json','').replace('```','').strip())
                return result.get('fixed_query', query), result.get('category','general')
    except Exception as e:
        logger.error(f"AI error: {e}")
        return query, 'general'

# ══ PRICE PARSER ══
def parse_price(t):
    price_max = price_min = None
    m = re.search(r'(?:under|below|less than|upto|up to|within)\s*₹?\s*(\d+)', t)
    if m:
        price_max = int(m.group(1)); t = t[:m.start()].strip()
    m2 = re.search(r'(?:between\s*)?₹?\s*(\d+)\s*(?:to|-|and)\s*₹?\s*(\d+)', t)
    if m2:
        price_min, price_max = int(m2.group(1)), int(m2.group(2)); t = t[:m2.start()].strip()
    m3 = re.search(r'(?:above|more than|over)\s*₹?\s*(\d+)', t)
    if m3:
        price_min = int(m3.group(1)); t = t[:m3.start()].strip()
    return t.strip(), price_max, price_min

# ══ QUERY PARSER ══
async def parse_query(text):
    t = text.lower().strip()
    t, price_max, price_min = parse_price(t)
    detected_category = None

    # Step 1 — whole word exact match
    for cat_key, cat_data in CATEGORIES.items():
        for kw in cat_data['keywords']:
            if re.search(r'\b' + re.escape(kw) + r'\b', t):
                detected_category = cat_key
                break
        if detected_category: break

    fixed_query = t

    # Step 2 — fuzzy match (min 5 chars to avoid short word false matches)
    if not detected_category and len(t) >= 5:
        kw_list = [kw for kw, _ in ALL_KEYWORDS]
        match   = process.extractOne(t, kw_list, scorer=fuzz.WRatio)
        if match and match[1] >= 75:
            matched_kw = match[0]
            if len(t) / len(matched_kw) >= 0.6:
                detected_category = next(cat for kw, cat in ALL_KEYWORDS if kw == matched_kw)
                logger.info(f"Fuzzy: '{t}' → '{matched_kw}' ({match[1]}%)")

    # Step 3 — AI fallback
    if not detected_category and GROQ_API_KEY:
        fixed_query, detected_category = await ai_categorize(t)
        logger.info(f"AI: '{t}' → '{fixed_query}' / '{detected_category}'")
        if detected_category not in CATEGORIES:
            detected_category = None

    if detected_category and detected_category in CATEGORIES:
        label     = CATEGORIES[detected_category]['label']
        platforms = CATEGORIES[detected_category]['platforms']
    else:
        label     = '🛍 General'
        platforms = DEFAULT_PLATFORMS

    return {
        'query'    : fixed_query.strip(),
        'price_max': price_max,
        'price_min': price_min,
        'label'    : label,
        'platforms': platforms,
    }

# ══ BUILD KEYBOARD ══
async def build_keyboard(parsed):
    q      = quote(parsed['query'], safe='')
    q_dash = parsed['query'].strip().lower().replace(' ', '-')
    pmax   = parsed['price_max']
    rows, row = [], []
    for p in parsed['platforms']:
        link = await platform_link(p, q, q_dash, pmax, parsed=parsed)
        row.append(InlineKeyboardButton(PLATFORM_LABELS.get(p, p.title()), url=link))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

# ══ WELCOME TEXT ══
WELCOME_TEXT = (
    "👋 *Welcome to ShopEasy Bot!* 🛍\n\n"
    "Find the best deals from top Indian platforms instantly!\n\n"
    "━━━━━━━━━━━━━━━━━\n"
    "*🛒 What I can find:*\n"
    "👗 Ethnic & Western Wear\n"
    "👔 Men's Clothing\n"
    "👟 Footwear & Bags\n"
    "💍 Jewellery\n"
    "💄 Beauty & Skincare\n"
    "🩱 Innerwear & Lingerie\n"
    "📱 Electronics & Gadgets\n"
    "🏠 Home & Kitchen\n"
    "👶 Kids & Baby\n"
    "🏋️ Sports & Fitness\n"
    "📚 Books & Stationery\n"
    "💊 Health & Wellness\n"
    "🛒 Groceries\n"
    "🚗 Automotive\n"
    "🛋️ Furniture & more!\n\n"
    "━━━━━━━━━━━━━━━━━\n"
    "*💡 Examples:*\n"
    "• `blue cotton saree`\n"
    "• `power bank 20000mah`\n"
    "• `midi dress under 1000`\n"
    "• `black hoodie under 500`\n"
    "• `nike sneakers between 1000 and 3000`\n\n"
    "*Platforms:*\n"
    "⚡ Flipkart | 📦 Amazon | 👗 Myntra\n"
    "🏷 Shopsy | ✨ Ajio\n\n"
    "_Type any product to get started_ 👇"
)

# ══ HANDLERS ══
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if WELCOME_IMAGE_URL:
        await update.message.reply_photo(photo=WELCOME_IMAGE_URL, caption=WELCOME_TEXT, parse_mode='Markdown')
    else:
        await update.message.reply_text(WELCOME_TEXT, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*📖 How to use:*\n\n"
        "*Basic:* `blue cotton saree`\n\n"
        "*Price filter:*\n"
        "`hoodie under 500`\n"
        "`shirt between 500 and 2000`\n"
        "`watch above 1000`\n\n"
        "*Tips:*\n"
        "✅ Add color, brand, size\n"
        "✅ Works even with spelling mistakes!\n\n"
        "/categories — see all categories\n"
        "/stats — bot stats (admin only)",
        parse_mode='Markdown'
    )

async def categories_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["*📂 All Categories:*\n"]
    for cat_data in CATEGORIES.values():
        sample = ', '.join(cat_data['keywords'][:3])
        lines.append(f"{cat_data['label']}\n_e.g. {sample}_\n")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    total       = len(users_db)
    today       = datetime.now().strftime('%Y-%m-%d')
    active_today = sum(1 for u in users_db.values() if u.get('last_seen','').startswith(today))
    top = sorted(users_db.items(), key=lambda x: x[1].get('searches',0), reverse=True)[:5]
    top_lines = '\n'.join(
        f"  {i+1}. {u['name']} — {u.get('searches',0)} searches"
        for i, (_, u) in enumerate(top)
    )
    await update.message.reply_text(
        f"📊 *Bot Stats*\n\n"
        f"👥 Total users: {total}\n"
        f"🟢 Active today: {active_today}\n\n"
        f"🏆 Top searchers:\n{top_lines}",
        parse_mode='Markdown'
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <your message>")
        return
    msg    = ' '.join(context.args)
    total  = len(users_db)
    sent   = failed = 0
    await update.message.reply_text(f"📤 Broadcasting to {total} users...")
    for uid in list(users_db.keys()):
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Broadcast failed for {uid}: {e}")
            failed += 1
    await update.message.reply_text(f"✅ Done!\nSent: {sent} | Failed: {failed}")

async def search_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("Please type a product name 🛍")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    parsed   = await parse_query(text)
    keyboard = await build_keyboard(parsed)

    price_line = ''
    if parsed['price_max'] and parsed['price_min']:
        price_line = f"\n💰 *Budget:* ₹{parsed['price_min']} – ₹{parsed['price_max']}"
    elif parsed['price_max']:
        price_line = f"\n💰 *Budget:* Under ₹{parsed['price_max']}"
    elif parsed['price_min']:
        price_line = f"\n💰 *Budget:* Above ₹{parsed['price_min']}"

    plats = ' | '.join([PLATFORM_LABELS.get(p,'') for p in parsed['platforms']])
    await update.message.reply_text(
        f"🔍 *{parsed['query'].title()}*\n"
        f"📂 *Category:* {parsed['label']}{price_line}\n\n"
        f"🛒 _{plats}_\n\n"
        f"👇 *Tap to shop:*",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    logger.info(f"'{text}' → '{parsed['query']}' | {parsed['label']} | max=₹{parsed['price_max']}")

# ══ HEALTH CHECK ══
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
    logger.info(f"✅ Web server on port {PORT}")

# ══ MAIN ══
async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set!")
    await start_web_server()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start',      start))
    app.add_handler(CommandHandler('help',       help_cmd))
    app.add_handler(CommandHandler('categories', categories_cmd))
    app.add_handler(CommandHandler('stats',      stats_cmd))
    app.add_handler(CommandHandler('broadcast',  broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_product))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    logger.info("🤖 ShopEasy Bot is LIVE!")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())