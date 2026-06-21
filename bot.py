import os
import argparse
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

from modules.mt5_service import MT5Service
from modules.market_data import get_market_snapshot
from modules.indicator_engine import calculate_indicators
from modules.trend_analyzer import analyze_trend
from modules.decision_engine import calculate_decision

# Konfigurasi Bot Telegram
TELEGRAM_BOT_TOKEN="8617765204:AAH7DBU-EDA5L7RRmnIP1Ss5cGzfctLgz7w"
WHITELISTED_USER = "husadamr"

# Variabel Global
ai_client = None
ai_model = None
mt5_service = MT5Service()

# Cache JSON Context
_market_context_cache = {}

def get_latest_market_context(symbol: str) -> dict:
    return _market_context_cache.get(symbol, None)

def build_market_context_json(symbol: str) -> dict:
    if not mt5_service.conn and not mt5_service.connect():
        return {}
        
    # 2. Account info
    acc = mt5_service.get_account_info()
    if not acc:
        return
        
    inds = calculate_indicators(mt5_service, symbol)
    if not inds:
        return {}
        
    ema_txt = f"EMA50 berada di {'atas' if inds['ema50'] > inds['ema200'] else 'bawah'} EMA200"
    
    # Hitung via Decision Engine
    decision = calculate_decision(inds)
    
    # Gabungkan data untuk JSON
    data = {
        "symbol": symbol,
        "trend": decision['dominant_action'],  
        "confidence": int(decision['confidence'] * 100),
        "strength": decision['action'],
        "buy_score": decision['buy_score'],
        "sell_score": decision['sell_score'],
        "market_bias": decision['action'],
        "ema50": inds['ema50'],
        "ema200": inds['ema200'],
        "adx": inds['adx'],
        "atr": inds['atr'],
        "signal_summary": [ema_txt, f"ADX={inds['adx']}", f"ATR={inds['atr']}"]
    }
    
    _market_context_cache[symbol] = data
    return data

def get_mt5_context(symbol: str = None):
    if not mt5_service.conn and not mt5_service.connect():
        return "Gagal terhubung ke MT5."
    
    ctx = []
    
    # 1. Account Info
    acc = mt5_service.get_account_info()
    if acc:
        ctx.append(f"[ACCOUNT]\nBalance: {acc['balance']} | Equity: {acc['equity']} | Free Margin: {acc['margin_free']} | Profit: {acc['profit']}")
        
    # 2. Terminal Info
    term = mt5_service.get_terminal_info()
    if term:
        ctx.append(f"[CONNECTION]\nConnected: {term['connected']} | Trade Allowed: {term['trade_allowed']}")
        
    # 3. Posisi Aktif
    positions = mt5_service.get_positions()
    if positions:
        pos_list = []
        for p in positions:
            tipe = "BUY" if p['type'] == 0 else "SELL"
            pos_list.append(f"{tipe} {p['symbol']} Vol:{p['volume']} Open:{p['price_open']} Profit:{p['profit']}")
        ctx.append("[OPEN POSITIONS]\n" + "\n".join(pos_list))
    else:
        ctx.append("[OPEN POSITIONS]\nTidak ada posisi terbuka.")
        
    # 4. Market Context (baru)
    if symbol:
        ctx.append(build_market_context(symbol))
        
    return "\n\n".join(ctx)

def build_market_context(symbol: str) -> str:
    data = build_market_context_json(symbol)
    if not data:
        return f"[MARKET CONTEXT]\nData untuk {symbol} tidak tersedia atau market tutup."
        
    msg = "[MARKET CONTEXT]\n"
    msg += f"Symbol: {data['symbol']}\n\n"
    msg += f"Trend:\n{data['trend']}\n\n"
    msg += f"Trend Strength:\n{data['strength']} ({data['confidence']}%)\n\n"
    msg += f"Scores:\nBUY Score: {data['buy_score']} | SELL Score: {data['sell_score']}\n\n"
    msg += f"Indicators:\nEMA50={data['ema50']}\nEMA200={data['ema200']}\nADX={data['adx']}\nATR14={data['atr']}\n\n"
    
    msg += "Signal Summary:\n"
    for s in data['signal_summary']:
        msg += f"- {s}\n"
        
    msg += f"\nMarket Bias:\n{data['market_bias']}\n\n"
    
    return msg

def get_status_text():
    if not mt5_service.conn and not mt5_service.connect(): return "❌ Gagal terhubung ke MT5."
    acc = mt5_service.get_account_info()
    pos = mt5_service.get_positions()
    if not acc: return "❌ Gagal membaca info akun."
    return f"📊 *STATUS AKUN*\n\nBalance: ${acc['balance']}\nEquity: ${acc['equity']}\nMargin Free: ${acc['margin_free']}\nOpen Positions: {len(pos) if pos else 0}"

def get_positions_text():
    if not mt5_service.conn and not mt5_service.connect(): return "❌ Gagal terhubung ke MT5."
    pos = mt5_service.get_positions()
    if not pos: return "Tidak ada posisi terbuka."
    msg = "💼 *POSISI AKTIF*\n\n"
    for p in pos:
        tipe = "🟢 BUY" if p['type'] == 0 else "🔴 SELL"
        msg += f"{tipe} *{p['symbol']}*\nLot: {p['volume']} | Open: {p['price_open']} | Profit: ${p['profit']}\n\n"
    return msg

def get_analyze_text(symbol):
    if not mt5_service.conn and not mt5_service.connect(): return "❌ Gagal terhubung ke MT5."
    snap = get_market_snapshot(mt5_service, symbol)
    inds = calculate_indicators(mt5_service, symbol)
    
    if not snap and not inds: return f"❌ Simbol {symbol} tidak valid."
    if not inds: return f"❌ Gagal menghitung indikator untuk {symbol}. Market tutup atau belum ditambahkan ke Market Watch."
    
    # Ambil JSON Context dari cache (sudah diproses oleh Decision Engine via get_mt5_context)
    build_market_context_json(symbol)
    data = get_latest_market_context(symbol)
    
    msg = f"📈 *ANALISA {symbol}*\n\n"
    msg += f"Action: *{data['strength']}*\n"
    msg += f"Dominant: *{data['trend']}*\n"
    msg += f"Confidence: {data['confidence']}%\n\n"
    msg += f"Scores: BUY ({data['buy_score']}) | SELL ({data['sell_score']})\n\n"
    msg += f"EMA50: {data['ema50']}\n"
    msg += f"EMA200: {data['ema200']}\n"
    msg += f"ADX: {data['adx']}\n"
    msg += f"ATR14: {data['atr']}"
    
    if snap:
        msg += f"\n\nBid: {snap['bid']}\nAsk: {snap['ask']}"
        
    return msg

def get_main_menu():
    keyboard = [
        [KeyboardButton("📊 Status Akun"), KeyboardButton("💼 Posisi Aktif")],
        [KeyboardButton("📈 Analisa XAUUSD#"), KeyboardButton("📈 Analisa EURUSD#")]
    ]
    # Parameter `persistent` dihapus karena tidak didukung pada versi python-telegram-bot saat ini
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != WHITELISTED_USER: return
    await update.message.reply_text(get_status_text(), parse_mode='Markdown')

async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != WHITELISTED_USER: return
    await update.message.reply_text(get_positions_text(), parse_mode='Markdown')

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != WHITELISTED_USER: return
    if not context.args:
        await update.message.reply_text("Format salah. Gunakan: /analyze XAUUSD")
        return
        
    symbol = context.args[0].upper()
    status_msg = await update.message.reply_text(f"🔍 Menganalisa {symbol}...")
    await status_msg.edit_text(get_analyze_text(symbol), parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != WHITELISTED_USER: return
    await update.message.reply_text("🤖 Bot MT5 AI Agent Aktif.\nPilih menu di bawah:", reply_markup=get_main_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if user != WHITELISTED_USER: return
        
    user_text = update.message.text
    
    # Deteksi teks dari Reply Keyboard atau Command bawaan
    target_symbol = "XAUUSD#"
    is_command = False
    
    if user_text == "📊 Status Akun":
        await update.message.reply_text(get_status_text(), parse_mode='Markdown')
        return
    elif user_text == "💼 Posisi Aktif":
        await update.message.reply_text(get_positions_text(), parse_mode='Markdown')
        return
    elif user_text.startswith("📈 Analisa "):
        symbol = user_text.replace("📈 Analisa ", "").strip()
        msg = await update.message.reply_text(f"🔍 Menganalisa {symbol}...")
        await msg.edit_text(get_analyze_text(symbol), parse_mode='Markdown')
        return

    # Jika bukan dari tombol, gunakan AI
    status_msg = await update.message.reply_text("🔄 Menganalisa...")
    
    # Deteksi otomatis pair yang ditanyakan user. (Hanya cari huruf besar min 6 karakter)
    import re
    detected_pairs = re.findall(r'\b[A-Z]{6}\b', user_text.upper())
    
    # Jika ketemu pair valid 6 huruf (contoh: USDJPY), tambahkan #
    if detected_pairs:
        target_symbol = detected_pairs[0] + "#"
            
    mt5_context = get_mt5_context(target_symbol)
    
    try:
        response = await ai_client.chat.completions.create(
            model=ai_model,
            stream=True,
            messages=[
                {
                    "role": "system", 
                    "content": f"Kamu adalah asisten trading profesional.\n\n{mt5_context}\n\n"
                               f"Aturan:\n"
                               f"- Jangan memberikan kepastian profit.\n"
                               f"- Selalu jelaskan alasan analisa.\n"
                               f"- Gunakan data market context yang diberikan.\n"
                               f"- Jika confidence < 60 maka sarankan wait/no trade."
                },
                {"role": "user", "content": user_text}
            ]
        )
        reply = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                reply += chunk.choices[0].delta.content
        
        await status_msg.edit_text(reply)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error AI: {str(e)}")

def main():
    global ai_client, ai_model
    
    parser = argparse.ArgumentParser(description="MT5 AI Telegram Bot")
    parser.add_argument("--base-url", type=str, required=True, help="OpenAI Compatible API Base URL")
    parser.add_argument("--api-key", type=str, required=True, help="API Key untuk AI")
    parser.add_argument("--model", type=str, required=True, help="Nama model AI (misal: gpt-3.5-turbo)")
    args = parser.parse_args()
    
    ai_model = args.model
    ai_client = AsyncOpenAI(
        api_key=args.api_key,
        base_url=args.base_url
    )
    
    print("Menguji koneksi ke MT5 Container via RPyC...")
    if mt5_service.connect():
        print("✅ Berhasil terhubung ke MT5 RPC Server (Port 18812).")
    else:
        print("⚠️ Peringatan: Tidak bisa terhubung ke MT5 RPC Server. Pastikan container jalan.")
    
    print("Memulai bot Telegram...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()

if __name__ == "__main__":
    main()