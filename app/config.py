"""
Configuración centralizada para Bot Tendencia - Brujula MTF.
v5.5 FINAL: Parámetros ajustados según auditoría del dev.
"""
import os
from typing import List

# ── Variables de entorno ──
TZ_NAME: str = os.getenv("TZ_NAME", "America/Caracas")
HL_REST_URL: str = os.getenv("HL_REST_URL", "https://api.hyperliquid.xyz/info")

# Activos a monitorear
_assets_env = os.getenv("ASSETS", "BTC,ETH")
ASSETS: List[str] = [a.strip() for a in _assets_env.split(",") if a.strip()]

# ── Cache ──
CACHE_TTL: int = int(os.getenv("CACHE_TTL", "60"))
CACHE_TTL_PRECIOS: int = int(os.getenv("CACHE_TTL_PRECIOS", "30"))

# ── Thresholds del motor de decisión (Brujula v4.1) ──
MK_BLOQUEO: float = 0.75
FUERZA_FUERTE: int = 2
FUERZA_DEBIL: int = 1
DIST_EXTENDIDA: float = 2.0
DIST_MODERADA: float = 1.0

# === v4.0 FINAL === - Filtros de Calidad ajustados
MIN_SCORE_TO_TRADE: int = int(os.getenv("MIN_SCORE_TO_TRADE", "3"))  # era 5
_regimes_env = os.getenv("ALLOWED_REGIMES", "tendencia")
ALLOWED_REGIMES: List[str] = [r.strip().lower() for r in _regimes_env.split(",") if r.strip()]

# === v4.0 FINAL === - Funding filter ajustado (dev sugerencia: 0.08 era muy permisivo, 0.05 muy agresivo)
FUNDING_EXTREME: float = float(os.getenv("FUNDING_EXTREME", "0.06"))  # compromise

# === v4.0 FINAL === - Invalidación ajustada (dev sugerencia: 1.0% en vez de 0.5%)
INVALIDATION_WARN_DIST: float = float(os.getenv("INVALIDATION_WARN_DIST", "1.0"))

# === v4.0 FINAL === - R:R mínimo (mantengo 1.5, mido y ajusto)
MIN_RR_RATIO: float = float(os.getenv("MIN_RR_RATIO", "1.5"))

# === v4.0 FINAL === - Cooldown de alerta de invalidación
INVALIDATION_COOLDOWN: int = int(os.getenv("INVALIDATION_COOLDOWN", "900"))  # 15 min

# ── Realidad Financiera ──
TAKER_FEE_PERCENT: float = float(os.getenv("TAKER_FEE_PERCENT", "0.00035"))
MAKER_FEE_PERCENT: float = float(os.getenv("MAKER_FEE_PERCENT", "0.00020"))
ESTIMATED_SLIPPAGE_PERCENT: float = float(os.getenv("ESTIMATED_SLIPPAGE_PERCENT", "0.00050"))
TOTAL_ROUND_TRIP_COST_PERCENT: float = (2 * TAKER_FEE_PERCENT) + ESTIMATED_SLIPPAGE_PERCENT

# ── UI ──
REFRESH_SEG: int = 30
INFO_247_TXT: str = (
    "🌐 Hyperliquid opera 24/7: los perps TradFi (xyz:) "
    "cotizan aunque el mercado subyacente esté cerrado."
)

# ── Sistema VIP ──
VIP_CHANNEL_ID: int = int(os.getenv("VIP_CHANNEL_ID", "-1004377941254"))
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "7"))
SUBSCRIPTION_DAYS: int = int(os.getenv("SUBSCRIPTION_DAYS", "30"))

# === v4.0 FINAL === - A/B test pricing conservador (dev sugerencia: 90 en vez de 100)
SUBSCRIPTION_PRICE: int = int(os.getenv("SUBSCRIPTION_PRICE", "90"))

PENDING_ACTIVATION_HOURS: int = int(os.getenv("PENDING_ACTIVATION_HOURS", "24"))

# === v4.0 FINAL === - Seguridad: secret_token para webhook de Telegram
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
# === v4.0 FINAL === - Seguridad: API key para endpoints internos
API_KEY: str = os.getenv("API_KEY", "")


if __name__ == "__main__":
    print("=" * 60)
    print("CONFIGURACIÓN BOT TENDENCIA v5.5 FINAL")
    print("=" * 60)
    print(f"  TZ_NAME:             {TZ_NAME}")
    print(f"  HL_REST_URL:         {HL_REST_URL}")
    print(f"  ASSETS:              {ASSETS}")
    print(f"  CACHE_TTL:           {CACHE_TTL}s")
    print("-" * 60)
    print(f"  MIN_SCORE_TO_TRADE:  {MIN_SCORE_TO_TRADE}")
    print(f"  FUNDING_EXTREME:     {FUNDING_EXTREME}%")
    print(f"  INVALIDATION_WARN:   {INVALIDATION_WARN_DIST}%")
    print(f"  INVALIDATION_CD:     {INVALIDATION_COOLDOWN}s")
    print(f"  MIN_RR_RATIO:        {MIN_RR_RATIO}")
    print("-" * 60)
    print(f"  SUBSCRIPTION_PRICE:  {SUBSCRIPTION_PRICE} Stars")
    print(f"  WEBHOOK_SECRET:      {'✅ configured' if WEBHOOK_SECRET else '❌ NOT SET'}")
    print(f"  API_KEY:             {'✅ configured' if API_KEY else '❌ NOT SET'}")
    print("=" * 60)
