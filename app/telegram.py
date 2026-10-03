"""
telegram.py v2.5 FINAL: Alertas con niveles, MFE, invalidación, reporte semanal.
FIX: enviar_reporte_semanal usa HTML en vez de Markdown.
FIX: _icono_cierre y _titulo_cierre sin trailing spaces en keys.
"""
import os
import time
import aiohttp
from dotenv import load_dotenv
from typing import Optional, Dict, Any
from app.config import VIP_CHANNEL_ID

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" if TELEGRAM_TOKEN else None
PNL_EQUILIBRIO = 0.1
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

def _fmt_px(precio: float) -> str:
    if precio <= 0: return "—"
    if precio >= 1000: return f"${precio:,.0f}"
    elif precio >= 1: return f"${precio:,.2f}"
    else: return f"${precio:,.4f}"

def _regime_en(regime: str) -> str:
    regimenes = {"tendencia": "trending", "rango": "range", "caos": "chaos"}
    return regimenes.get(regime, regime)

def _motivo_legible(exit_reason: str) -> str:
    motivos = {
        "NEUTRAL": "Bias shifted to RANGE",
        "CAOS": "Chaotic market (Markov ≥ 0.75)",
        "FLIP": "Trend reversal (FLIP)",
    }
    return motivos.get(exit_reason, exit_reason)

# FIX: keys sin trailing spaces
def _icono_cierre(exit_reason: str) -> str:
    iconos = {"NEUTRAL": "⚪", "CAOS": "🌪️", "FLIP": "🔄"}
    return iconos.get(exit_reason, "⚪")

def _titulo_cierre(exit_reason: str) -> str:
    titulos = {"NEUTRAL": "NEUTRAL", "CAOS": "CHAOS", "FLIP": "FLIP"}
    return titulos.get(exit_reason, "NEUTRAL")

# === v4.0 FIX === parse_mode=HTML en _send
async def _send(chat_id: int, text: str):
    """Envía mensaje con parse_mode=HTML."""
    if not BASE_URL:
        print("⚠️ Telegram TOKEN no configurado.")
        return False
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"✅ Mensaje enviado a {chat_id}")
                    return True
                else:
                    print(f"❌ Error Telegram HTTP {resp.status}: {await resp.text()[:200]}")
                    return False
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")
        return False

# ══════════════════════════════════════════════════════════
# ALERTAS DE TRADING
# ══════════════════════════════════════════════════════════
async def enviar_alerta_apertura(
    coin: str,
    direction: str,
    precio: float,
    score: int,
    regime: str,
    zonas: Optional[Dict[str, Any]] = None,
    setup_valid_until: int = 0,
    funding_rate: float = 0.0,
):
    """Alerta de apertura con zonas operativas."""
    if not API_URL or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado, omitiendo alerta.")
        return
    icono = "🟢" if direction == "LONG" else "🔴"
    regime_en = _regime_en(regime)
    strength = "STRONG" if score >= 5 else ("MEDIUM" if score >= 3 else "WEAK")
    if zonas and zonas.get("entry_low"):
        entry_str = f"${zonas['entry_low']:,.2f} - ${zonas['entry_high']:,.2f}"
        inv_str = f"${zonas['invalidation']:,.2f}"
        tp1_str = f"${zonas['tp1']:,.2f} (+{zonas['reward_tp1_pct']:.2f}%)"
        tp2_str = f"${zonas['tp2']:,.2f} (+{zonas['reward_tp2_pct']:.2f}%)"
        rr_str = f"{zonas['rr_ratio']:.1f}:1"
        risk_str = f"{zonas['risk_pct']:.2f}%"
        valid_str = time.strftime("%H:%M UTC", time.gmtime(setup_valid_until)) if setup_valid_until else "4h"
        niveles = (
            f"💰 Entry: {entry_str}\n"
            f"🛑 SL: {inv_str} (risk: {risk_str})\n"
            f"🎯 TP1: {tp1_str} — close 50%\n"
            f"🎯 TP2: {tp2_str} — let rest run\n"
            f"⚖️ R:R: {rr_str}\n"
            f"⏱ Valid until: {valid_str}\n"
        )
    else:
        niveles = "💰 Entry: at market\n⚙️ Define your levels.\n"
    funding_str = ""
    if abs(funding_rate) > 0.03:
        funding_str = f"⚠️ Funding: {funding_rate:+.3f}% (extreme)\n"
    msg = (
        f"{icono} <b>{coin} {direction} — CONFIRMED [{strength}]</b>\n"
        f"\n"
        f"{niveles}"
        f"\n"
        f"{funding_str}"
        f"📊 Score: {score}/6 | Regime: {regime_en}\n"
        f"\n"
        f"⚙️ Use your position sizing. Risk 1-2% of capital max."
    )
    await _send(TELEGRAM_CHAT_ID, msg)

async def enviar_alerta_cierre(
    coin: str,
    direction: str,
    price_entry: float,
    price_exit: float,
    pnl_percent: float,
    duration_seconds: int,
    exit_reason: str,
    fee_percent: float = 0.0,
    mfe_percent: Optional[float] = None,
):
    """Alerta de cierre HONESTA con PnL neto + MFE."""
    if not API_URL or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado, omitiendo alerta.")
        return
    icono = _icono_cierre(exit_reason)
    titulo = _titulo_cierre(exit_reason)
    motivo_legible = _motivo_legible(exit_reason)
    dur_min = duration_seconds // 60
    dur_sec = duration_seconds % 60
    if pnl_percent > 0:
        pnl_line = f"📈 Result: +{pnl_percent:.2f}% (after {fee_percent:.2f}% fees)"
    elif pnl_percent < 0:
        pnl_line = f"📉 Result: {pnl_percent:.2f}% (after {fee_percent:.2f}% fees)"
    else:
        pnl_line = f"📊 Result: break-even (after {fee_percent:.2f}% fees)"
    mfe_line = ""
    if mfe_percent is not None and abs(mfe_percent) > 0.05:
        if mfe_percent > 0:
            mfe_line = f"\n📈 Max favorable: +{mfe_percent:.2f}%"
        else:
            mfe_line = f"\n📉 Max adverse: {mfe_percent:.2f}%"
    msg = (
        f"{icono} <b>{coin} {titulo} — SIGNAL CLOSED</b>\n"
        f"\n"
        f"💰 Entry: {_fmt_px(price_entry)} → Exit: {_fmt_px(price_exit)}\n"
        f"📊 Previous state: {direction}\n"
        f"{pnl_line}{mfe_line}\n"
        f"🎯 Reason: {motivo_legible}\n"
        f"⏱ Duration: {dur_min}m {dur_sec}s\n"
        f"\n"
        f"⚙️ No active signal. Waiting for new confluence."
    )
    await _send(TELEGRAM_CHAT_ID, msg)

# === v4.0 === Alerta de invalidación
async def enviar_alerta_invalidation_approach(
    coin: str,
    direction: str,
    current_price: float,
    invalidation: float,
):
    """Alerta preventiva cuando el precio se acerca a la invalidación."""
    if not API_URL or not TELEGRAM_CHAT_ID:
        return
    distance_pct = abs(current_price - invalidation) / current_price * 100
    msg = (
        f"⚠️ <b>{coin} {direction} — APPROACHING INVALIDATION</b>\n"
        f"\n"
        f"💰 Current price: {_fmt_px(current_price)}\n"
        f"🛑 Invalidation: {_fmt_px(invalidation)}\n"
        f"📏 Distance: {distance_pct:.2f}%\n"
        f"\n"
        f"⚙️ If you're still in this trade, review your risk."
    )
    await _send(TELEGRAM_CHAT_ID, msg)

# === v4.0 FIX === Reporte semanal con HTML (antes usaba Markdown)
async def enviar_reporte_semanal(stats: Dict[str, Any]):
    """Envía el reporte semanal al canal VIP."""
    if not API_URL or not TELEGRAM_CHAT_ID:
        return
    if not stats or stats.get("total", 0) == 0:
        msg = "📊 <b>WEEKLY SIGNAL REPORT</b>\n\nNo signals closed this week."
    else:
        msg = (
            f"📊 <b>WEEKLY SIGNAL REPORT</b>\n"
            f"\n"
            f"📈 Total signals: {stats['total']}\n"
            f"✅ Winners (net): {stats.get('winners', 0)} ({stats.get('win_rate', 0):.1f}%)\n"
            f"📉 Avg net PnL: {stats.get('avg_net_pnl', 0):.3f}%\n"
            f"⏱ Avg duration: {stats.get('avg_duration_min', 0):.1f} min\n"
            f"\n"
            f"🔄 By exit reason:\n"
            f"   • FLIP: {stats.get('flips', 0)}\n"
            f"   • NEUTRAL: {stats.get('neutrals', 0)}\n"
            f"   • CHAOS: {stats.get('chaos', 0)}\n"
            f"\n"
            f"⚠️ <i>This is theoretical PnL. Your results depend on entry timing and SL discipline.</i>"
        )
    await _send(TELEGRAM_CHAT_ID, msg)

# ══════════════════════════════════════════════════════════
# SISTEMA VIP
# ══════════════════════════════════════════════════════════
async def _send_user_message(chat_id: int, text: str, reply_markup: dict = None):
    if not BASE_URL:
        print("⚠️ Telegram TOKEN no configurado.")
        return False
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"✅ Mensaje enviado a {chat_id}")
                    return True
                else:
                    print(f"❌ Error Telegram HTTP {resp.status}: {await resp.text()[:200]}")
                    return False
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")
        return False

async def send_welcome_message(user_id: int, username: str, is_new: bool, days_left: int = 0):
    display_name = f"@{username}" if username else "User"
    canal_button = {"inline_keyboard": [[{"text": "👉 Access VIP Channel", "url": "https://t.me/+ZGL3xNlF8lcxMjBh"}]]}
    if is_new:
        msg = (
            f"Hello {display_name}! 👋\n\n"
            f"✅ <b>Your 7-day free trial has been successfully activated.</b>\n\n"
            f"During this time, you will have full access to the exclusive signals in our VIP Channel. "
            f"We will notify you 24 hours before your trial ends so you can decide whether to continue.\n\n"
            f"Tap the button below to join the channel now! 👇\n\n"
            f"Wishing you great success in your trades! 📈"
        )
    else:
        msg = (
            f"Hello again, {display_name}! 👋\n\n"
            f"Your VIP subscription is still active. You have <b>{days_left} days</b> of access remaining.\n\n"
            f"Tap the button below to access the VIP Channel. 👇\n\n"
            f"If you have any questions, we are here to help."
        )
    await _send_user_message(user_id, msg, reply_markup=canal_button)

async def send_payment_success_message(user_id: int):
    canal_button = {"inline_keyboard": [[{"text": "👉 Access VIP Channel", "url": "https://t.me/+ZGL3xNlF8lcxMjBh"}]]}
    msg = (
        "✅ <b>Payment received successfully!</b>\n\n"
        "Your VIP Channel subscription has been extended by 30 days.\n\n"
        "Tap the button below to access the VIP Channel. 👇\n\n"
        "Thank you for trusting our signals. Wishing you great success in the market! 📈"
    )
    await _send_user_message(user_id, msg, reply_markup=canal_button)

async def send_invoice_message(user_id: int, price_stars: int):
    if not BASE_URL: return False
    url = f"{BASE_URL}/sendInvoice"
    payload = {
        "chat_id": user_id, "title": "VIP Channel Monthly Subscription",
        "description": "30 days of access to exclusive trading signals. Renew your membership to maintain uninterrupted access.",
        "payload": f"sub_{user_id}_{int(time.time())}", "provider_token": "", "currency": "XTR",
        "prices": [{"label": "30-day Membership", "amount": price_stars}]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"✅ Factura enviada a {user_id}")
                    return True
                else:
                    print(f"❌ Error enviando factura HTTP {resp.status}: {await resp.text()[:200]}")
                    return False
    except Exception as e:
        print(f"❌ Error enviando factura: {e}")
        return False

async def send_expiration_warning(user_id: int):
    msg = (
        "⚠️ <b>Important Reminder</b>\n\n"
        "Your free trial or VIP subscription is about to expire in the next 24 hours.\n\n"
        "Please initiate the bot and select the renewal option to avoid losing access to the signals. We are here to help if you have any questions!"
    )
    await _send_user_message(user_id, msg)

async def ban_chat_member(chat_id: int, user_id: int):
    if not BASE_URL: return False
    url = f"{BASE_URL}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id, "revoke_messages": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"✅ Usuario {user_id} expulsado del canal {chat_id}")
                    return True
                else:
                    print(f"❌ Error expulsando usuario HTTP {resp.status}: {await resp.text()[:200]}")
                    return False
    except Exception as e:
        print(f"❌ Error expulsando usuario: {e}")
        return False

if __name__ == "__main__":
    import asyncio
    print("=" * 60)
    print("TEST TELEGRAM v2.5 FINAL — Alertas + VIP + Reporte semanal")
    print("=" * 60)
    if not API_URL or not TELEGRAM_CHAT_ID:
        print("❌ Telegram no configurado.")
        exit(1)
    async def _test():
        zonas_ejemplo = {
            "entry_low": 94000, "entry_high": 94500, "invalidation": 93200,
            "tp1": 96800, "tp2": 98400, "risk_pct": 0.85,
            "reward_tp1_pct": 2.92, "reward_tp2_pct": 4.34, "rr_ratio": 3.4
        }
        await enviar_alerta_apertura(
            "BTC", "LONG", 94500, 5, "tendencia",
            zonas=zonas_ejemplo, setup_valid_until=int(time.time()) + 14400,
            funding_rate=0.012
        )
        await enviar_alerta_cierre(
            "BTC", "LONG", 94500, 94200, -0.32, 2700, "NEUTRAL",
            fee_percent=0.12, mfe_percent=0.42
        )
        print("\n✅ Revisa tu Telegram.")
    asyncio.run(_test())