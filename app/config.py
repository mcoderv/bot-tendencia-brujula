"""
Configuración centralizada para Bot Tendencia - Brujula MTF.
Todas las variables de entorno y constantes del sistema.
"""
import os
from typing import List

# ── Variables de entorno ──
TZ_NAME: str = os.getenv("TZ_NAME", "America/Caracas")
HL_REST_URL: str = os.getenv("HL_REST_URL", "https://api.hyperliquid.xyz/info")

# Activos a monitorear (lista desde variable de entorno separada por comas)
_assets_env = os.getenv("ASSETS", "BTC,ETH,SOL")
ASSETS: List[str] = [a.strip() for a in _assets_env.split(",") if a.strip()]

# ── Cache ──
# Tiempo en segundos antes de recalcular el estado completo
# Reducido de 300s a 60s para refresh más frecuente en la web
CACHE_TTL: int = int(os.getenv("CACHE_TTL", "60"))

# Tiempo en segundos para precios rápidos (endpoint /api/prices)
CACHE_TTL_PRECIOS: int = int(os.getenv("CACHE_TTL_PRECIOS", "30"))

# ── Thresholds del motor de decisión (Brujula v4.1) ──
# Probabilidad de caos que bloquea cualquier operación
MK_BLOQUEO: float = 0.75

# Fuerza mínima para considerar señal fuerte
FUERZA_FUERTE: int = 2
FUERZA_DEBIL: int = 1

# Distancia al ATR (en múltiplos)
DIST_EXTENDIDA: float = 2.0
DIST_MODERADA: float = 1.0

# ── UI ──
REFRESH_SEG: int = 30  # Frecuencia de refresh del frontend (ms se calculan en JS)

# Texto informativo sobre mercados 24/7
INFO_247_TXT: str = (
    "🌐 Hyperliquid opera 24/7: los perps TradFi (xyz:) "
    "cotizan aunque el mercado subyacente esté cerrado."
)

# ── Validación al importar ──
if __name__ == "__main__":
    print("=" * 60)
    print("CONFIGURACIÓN BOT TENDENCIA")
    print("=" * 60)
    print(f"  TZ_NAME:        {TZ_NAME}")
    print(f"  HL_REST_URL:    {HL_REST_URL}")
    print(f"  ASSETS:         {ASSETS}")
    print(f"  CACHE_TTL:      {CACHE_TTL}s")
    print(f"  CACHE_TTL_PRECIOS: {CACHE_TTL_PRECIOS}s")
    print(f"  MK_BLOQUEO:     {MK_BLOQUEO}")
    print(f"  FUERZA_FUERTE:  {FUERZA_FUERTE}")
    print(f"  DIST_EXTENDIDA: {DIST_EXTENDIDA}x")
    print("=" * 60)