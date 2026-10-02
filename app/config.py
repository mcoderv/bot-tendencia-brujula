"""
Configuración centralizada para Bot Tendencia - Brujula MTF.
v5.3: FASE 3 - Realidad Financiera (Comisiones y Slippage de Hyperliquid).
"""
import os
from typing import List

TZ_NAME: str = os.getenv("TZ_NAME", "America/Caracas")
HL_REST_URL: str = os.getenv("HL_REST_URL", "https://api.hyperliquid.xyz/info")

_assets_env = os.getenv("ASSETS", "BTC,ETH")
ASSETS: List[str] = [a.strip() for a in _assets_env.split(",") if a.strip()]

CACHE_TTL: int = int(os.getenv("CACHE_TTL", "60"))
CACHE_TTL_PRECIOS: int = int(os.getenv("CACHE_TTL_PRECIOS", "30"))

MK_BLOQUEO: float = 0.75
FUERZA_FUERTE: int = 2
FUERZA_DEBIL: int = 1
DIST_EXTENDIDA: float = 2.0
DIST_MODERADA: float = 1.0

MIN_SCORE_TO_TRADE: int = int(os.getenv("MIN_SCORE_TO_TRADE", "5"))
_regimes_env = os.getenv("ALLOWED_REGIMES", "tendencia")
ALLOWED_REGIMES: List[str] = [r.strip().lower() for r in _regimes_env.split(",") if r.strip()]

# FASE 3: Comisiones
TAKER_FEE_PERCENT: float = float(os.getenv("TAKER_FEE_PERCENT", "0.00035"))
MAKER_FEE_PERCENT: float = float(os.getenv("MAKER_FEE_PERCENT", "0.00020"))
ESTIMATED_SLIPPAGE_PERCENT: float = float(os.getenv("ESTIMATED_SLIPPAGE_PERCENT", "0.00050"))
TOTAL_ROUND_TRIP_COST_PERCENT: float = (2 * TAKER_FEE_PERCENT) + ESTIMATED_SLIPPAGE_PERCENT

REFRESH_SEG: int = 30
INFO_247_TXT: str = "🌐 Hyperliquid opera 24/7: los perps TradFi (xyz:) cotizan aunque el mercado subyacente esté cerrado."

VIP_CHANNEL_ID: int = int(os.getenv("VIP_CHANNEL_ID", "-1004377941254"))
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "7"))
SUBSCRIPTION_DAYS: int = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
SUBSCRIPTION_PRICE: int = int(os.getenv("SUBSCRIPTION_PRICE", "80"))
PENDING_ACTIVATION_HOURS: int = int(os.getenv("PENDING_ACTIVATION_HOURS", "24"))