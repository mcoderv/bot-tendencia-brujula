"""
telegram.py
Módulo para enviar alertas a Telegram y gestionar el sistema VIP.
v2.4: + Botón de acceso al canal VIP en mensajes de bienvenida.
      + Sistema VIP completo con mensajes en inglés.
      + Restricción de 1 solo trial por usuario.
      + Facturas con Telegram Stars.
Las funciones de alertas de trading se mantienen 100% intactas.
"""
import os
import time
import aiohttp
from dotenv import load_dotenv
from app.config import VIP_CHANNEL_ID

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" if TELEGRAM_TOKEN else None

# Umbral de punto de equilibrio (±0.1%)
PNL_EQUILIBRIO = 0.1

# URLs base de la API de Telegram
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

def _fmt_px(precio: float) -> str:
    """Formatea precio según magnitud."""
    if precio <= 0:
        return "—"
    if precio >= 1000:
        return f"${precio:,.0f}"
    elif precio >= 1:
        return f"${precio:,.2f}"
    else:
        return f"${precio:,.4f}"

def _regime_en(regime: str) -> str:
    """Traduce el régimen a inglés para el mensaje."""
    regimenes = {
        "tendencia": "trending",
        "rango": "range",
        "caos": "chaos",
    }
    return regimenes.get(regime, regime)

def _motivo_legible(exit_reason: str) -> str:
    """Convierte el código de motivo en texto legible en inglés."""
    motivos = {
        "NEUTRAL": "Bias shifted to RANGE",
        "CAOS": "Chaotic market (Markov ≥ 0.75)",
        "FLIP": "Trend reversal (FLIP)",
    }
    return motivos.get(exit_reason, exit_reason)

def _icono_cierre(exit_reason: str) -> str:
    """Icono del encabezado según el motivo del cierre."""
    iconos = {
        "NEUTRAL": "⚪",
        "CAOS": "🌪️",
        "FLIP": "🔄",
    }
    return iconos.get(exit_reason, "⚪")

def _titulo_cierre(exit_reason: str) -> str:
    """Palabra del título en inglés según el motivo del cierre."""
    titulos = {
        "NEUTRAL": "NEUTRAL",
        "CAOS": "CHAOS",
        "FLIP": "FLIP",
    }
    return titulos.get(exit_reason, "NEUTRAL")

def _linea_pnl(pnl_percent: float, price_entry: float, price_exit: float) -> str:
    """
    Genera la línea de PnL según las reglas confirmadas:
    - Positivo ( > +0.1%): muestra PnL con entry/exit
    - Equilibrio (±0.1%): muestra "Break-even"
    - Negativo ( < -0.1%): oculta PnL, indica "unstable market"
    """
    if pnl_percent > PNL_EQUILIBRIO:
        return f"📈 PnL: +{pnl_percent:.2f}% (entry: {_fmt_px(price_entry)} → exit: {_fmt_px(price_exit)})"
    elif pnl_percent >= -PNL_EQUILIBRIO:
        return f"📈 Break-even (entry: {_fmt_px(price_entry)} → exit: {_fmt_px(price_exit)})"
    else:
        return "⚠️ Closed due to unstable market"


# ==============================================================================
# FUNCIONES EXISTENTES: ALERTAS DE TRADING (Intactas)
# ==============================================================================

async def enviar_alerta_apertura(coin: str, direction: str, precio: float, score: int, regime: str):
    """Alerta de apertura de señal LONG/SHORT (en inglés)."""
    if not API_URL or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado, omitiendo alerta.")
        return
    
    icono = "🟢" if direction == "LONG" else "🔴"
    regime_en = _regime_en(regime)
    msg = (
        f"{icono} {coin} {direction} — SUGGESTED SIGNAL\n"
        f"\n"
        f"💰 Current price: {_fmt_px(precio)}\n"
        f"📊 Score: {score}/6 | Regime: {regime_en}\n"
        f"\n"
        f"⚙️ Management:\n"
        f"Define your support and resistance levels:"
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
):
    """
    Alerta de cierre de señal con formato completo (en inglés).
    Muestra PnL solo si es positivo o punto de equilibrio.
    """
    if not API_URL or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado, omitiendo alerta.")
        return
    
    icono = _icono_cierre(exit_reason)
    titulo = _titulo_cierre(exit_reason)
    motivo_legible = _motivo_legible(exit_reason)
    linea_pnl = _linea_pnl(pnl_percent, price_entry, price_exit)
    dur_min = duration_seconds // 60
    dur_sec = duration_seconds % 60
    
    msg = (
        f"{icono} {coin} {titulo} — SIGNAL CLOSED\n"
        f"\n"
        f"💰 Current price: {_fmt_px(price_exit)}\n"
        f"📊 Previous state: {direction}\n"
        f"{linea_pnl}\n"
        f"🎯 Reason: {motivo_legible}\n"
        f"⏱️ Duration: {dur_min}m {dur_sec}s\n"
        f"\n"
        f"⚙️ No active position. Waiting for new confluence."
    )
    await _send(TELEGRAM_CHAT_ID, msg)


# ==============================================================================
# FUNCIONES NUEVAS: SISTEMA VIP Y SUSCRIPCIONES (Mensajes en Inglés)
# ==============================================================================

async def _send_user_message(chat_id: int, text: str, reply_markup: dict = None):
    """Envía un mensaje a un chat específico (usuario o canal)."""
    if not BASE_URL:
        print("⚠️ Telegram TOKEN no configurado.")
        return False
    
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
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

async def _send(chat_id: int, text: str):
    """Wrapper para mantener compatibilidad con las funciones de alertas existentes."""
    await _send_user_message(chat_id, text)

async def send_welcome_message(user_id: int, username: str, is_new: bool, days_left: int = 0):
    """Envía mensaje de bienvenida o recordatorio de días restantes (EN INGLÉS).
    Siempre incluye botón de acceso al canal VIP."""
    display_name = f"@{username}" if username else "User"
    
    # Botón de acceso al canal VIP (siempre presente)
    canal_button = {
        "inline_keyboard": [[
            {"text": "👉 Access VIP Channel", "url": "https://t.me/+ZGL3xNlF8lcxMjBh"}
        ]]
    }
    
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
    """Confirma que el pago fue recibido y la suscripción extendida (EN INGLÉS)."""
    # Botón de acceso al canal VIP
    canal_button = {
        "inline_keyboard": [[
            {"text": "👉 Access VIP Channel", "url": "https://t.me/+ZGL3xNlF8lcxMjBh"}
        ]]
    }
    
    msg = (
        "✅ <b>Payment received successfully!</b>\n\n"
        "Your VIP Channel subscription has been extended by 30 days.\n\n"
        "Tap the button below to access the VIP Channel. 👇\n\n"
        "Thank you for trusting our signals. Wishing you great success in the market! 📈"
    )
    await _send_user_message(user_id, msg, reply_markup=canal_button)

async def send_invoice_message(user_id: int, price_stars: int):
    """Envía una factura de Telegram Stars al usuario (EN INGLÉS)."""
    if not BASE_URL:
        return False
    
    url = f"{BASE_URL}/sendInvoice"
    # Para Telegram Stars, provider_token va vacío y currency es "XTR"
    payload = {
        "chat_id": user_id,
        "title": "VIP Channel Monthly Subscription",
        "description": "30 days of access to exclusive trading signals. Renew your membership to maintain uninterrupted access.",
        "payload": f"sub_{user_id}_{int(time.time())}",
        "provider_token": "",  # Obligatorio vacío para Stars
        "currency": "XTR",     # Código de moneda para Telegram Stars
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
    """Envía una advertencia final si la factura falla o como recordatorio de texto (EN INGLÉS)."""
    msg = (
        "⚠️ <b>Important Reminder</b>\n\n"
        "Your free trial or VIP subscription is about to expire in the next 24 hours.\n\n"
        "Please initiate the bot and select the renewal option to avoid losing access to the signals. We are here to help if you have any questions!"
    )
    await _send_user_message(user_id, msg)

async def ban_chat_member(chat_id: int, user_id: int):
    """Expulsa y bloquea a un usuario del canal VIP."""
    if not BASE_URL:
        return False
    
    url = f"{BASE_URL}/banChatMember"
    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "revoke_messages": False  # No borramos su historial, solo lo sacamos
    }
    
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

# ==============================================================================
# TEST LOCAL (Opcional)
# ==============================================================================

async def _run_tests():
    """Envía mensajes de prueba simulando los escenarios."""
    print("=" * 60)
    print("TEST TELEGRAM v2.4 — Alertas + VIP + Botón Canal")
    print("=" * 60)
    if not API_URL or not TELEGRAM_CHAT_ID:
        print("❌ Telegram no configurado. Agrega TELEGRAM_TOKEN y TELEGRAM_CHAT_ID al .env")
        return
    
    print("Enviando mensajes de prueba...\n")
    await enviar_alerta_apertura("BTC", "LONG", 85200.0, 5, "tendencia")
    await enviar_alerta_cierre("BTC", "LONG", 84500.0, 86500.0, 2.34, 2720, "NEUTRAL")
    
    # Prueba de VIP (reemplaza 123456789 con tu user_id real de Telegram para probar)
    # await send_welcome_message(123456789, "test_user", is_new=True)
    print("\n✅ Revisa tu Telegram.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(_run_tests())