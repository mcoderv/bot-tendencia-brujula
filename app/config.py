"""
Configuración centralizada del Bot Tendencia.
Adaptado de mercabot_qwen Celdas 1 y 1.5 para VS Code + FastAPI.
Solo 3 activos: BTC, ETH, SOL. Sin Google Drive. Sin Colab.
"""
import os
from dotenv import load_dotenv

# ── Cargar variables de entorno desde .env ──
load_dotenv()

# ── CONFIG: Configuración global simplificada ──
TZ_NAME = os.getenv("TZ_NAME", "America/Caracas")
HL_REST_URL = os.getenv("HL_REST_URL", "https://api.hyperliquid.xyz/info")

# ── Activos ──
_assets_env = os.getenv("ASSETS", "BTC,ETH,SOL")
ASSETS = [a.strip() for a in _assets_env.split(",")]

# ── CENTRAL_PARAMS simplificado (solo lo que usa la Brújula) ──
CENTRAL_PARAMS = {
    "system": {
        "TZ_NAME": TZ_NAME,
        "HL_REST_URL": HL_REST_URL,
        "WATCHLIST": list(ASSETS),
    },
    "macro": {
        "ALL_ASSETS": list(ASSETS),
        "BIAS_THRESHOLD": 0.60,
        "REST_API_TIMEOUT": 10,
    },
    "markov": {
        "ACTIVADO": True,
        "PROBABILIDAD_BLOQUEO_ALTCOIN": 0.75,
    },
}
# ── Thresholds de la Brújula v4.0 ──
FUERZA_FUERTE = 2
FUERZA_DEBIL = 1
DIST_EXTENDIDA = 2.0
DIST_MODERADA = 1.0
MK_BLOQUEO = float(CENTRAL_PARAMS["markov"]["PROBABILIDAD_BLOQUEO_ALTCOIN"])

# ── Refresco visual (segundos entre pings de UptimeRobot) ──
REFRESH_SEG = 10

# ── Información 24/7 ──
INFO_247_TXT = (
    "🌐 Hyperliquid opera 24/7: los perps TradFi (xyz:) cotizan "
    "aunque el mercado subyacente esté cerrado."
)
# ── Banner de verificación ──
def print_config():
    print("=" * 60)
    print("🦅 BOT TENDENCIA | CONFIG")
    print("=" * 60)
    print(f"✅ TZ_NAME: {TZ_NAME}")
    print(f"✅ HL_REST_URL: {HL_REST_URL}")
    print(f"✅ ASSETS: {ASSETS}")
    print(f"✅ MK_BLOQUEO: {MK_BLOQUEO}")
    print(f"✅ REFRESH_SEG: {REFRESH_SEG}")
    print("=" * 60)

if __name__ == "__main__":
    print_config()