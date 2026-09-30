"""
telegram.py
Módulo para enviar alertas a Telegram usando aiohttp.

v2.1: Mensajes en inglés.
  - Aperturas: gestión simplificada ("Define your support and resistance levels:")
  - Cierres: formato completo con estado anterior y motivo legible
  - PnL: solo se muestra si es positivo o punto de equilibrio.
         Si es negativo, se indica "unstable market".
  - Iconos según motivo: ⚪ NEUTRAL | 🔄 FLIP | 🌪️ CHAOS
"""
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" if TELEGRAM_TOKEN else None

# Umbral de punto de equilibrio (±0.1%)
PNL_EQUILIBRIO = 0.1


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
      - Positivo (> +0.1%): muestra PnL con entry/exit
      - Equilibrio (±0.1%): muestra "Break-even"
      - Negativo (< -0.1%): oculta PnL, indica "unstable market"
    """
    if pnl_percent > PNL_EQUILIBRIO:
        return f"📈 PnL: +{pnl_percent:.2f}% (entry: {_fmt_px(price_entry)} → exit: {_fmt_px(price_exit)})"
    elif pnl_percent >= -PNL_EQUILIBRIO:
        return f"📈 Break-even (entry: {_fmt_px(price_entry)} → exit: {_fmt_px(price_exit)})"
    else:
        return "⚠️ Closed due to unstable market"


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
    await _send(msg)


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
    await _send(msg)


async def _send(text: str):
    """Envía el mensaje a Telegram (texto plano, sin parse_mode)."""
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print("✅ Alerta enviada a Telegram")
                else:
                    print(f"❌ Error Telegram HTTP {resp.status}: {await resp.text()[:200]}")
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")


# ══════════════════════════════════════════════════════════════════════
# TEST LOCAL: simula los 5 escenarios para validar visualmente
# ══════════════════════════════════════════════════════════════════════
async def _run_tests():
    """Envía mensajes de prueba simulando los 5 escenarios confirmados."""
    print("=" * 60)
    print("TEST TELEGRAM v2.1 — Escenarios en inglés")
    print("=" * 60)

    if not API_URL or not TELEGRAM_CHAT_ID:
        print("❌ Telegram no configurado. Agrega TELEGRAM_TOKEN y TELEGRAM_CHAT_ID al .env")
        return

    print("Enviando 5 mensajes de prueba...\n")

    # 1. Apertura LONG
    await enviar_alerta_apertura("BTC", "LONG", 85200.0, 5, "tendencia")

    # 2. Apertura SHORT
    await enviar_alerta_apertura("ETH", "SHORT", 2680.0, 4, "tendencia")

    # 3. Cierre NEUTRAL con PnL positivo
    await enviar_alerta_cierre("BTC", "LONG", 84500.0, 86500.0, 2.34, 2720, "NEUTRAL")

    # 4. Cierre FLIP con PnL negativo (debe ocultar PnL)
    await enviar_alerta_cierre("ETH", "SHORT", 2690.0, 2750.0, -2.23, 1800, "FLIP")

    # 5. Cierre CAOS en punto de equilibrio
    await enviar_alerta_cierre("SOL", "LONG", 118.50, 118.55, 0.04, 900, "CAOS")

    print("\n✅ Revisa tu Telegram: deberías ver los 5 mensajes en inglés.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_run_tests())