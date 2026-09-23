"""
FastAPI app para Bot Tendencia - Brujula MTF.
Sirve el dashboard como pagina web bajo demanda.
"""
import asyncio
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.cartografo import ejecutar_cartografo
from app.brujula import render_brujula
from app.config import ASSETS, TZ_NAME, HL_REST_URL

app = FastAPI(
    title="Bot Tendencia - Brujula MTF",
    description="Dashboard on-demand para analisis multi-timeframe de crypto",
    version="1.0.0",
)

# Cache simple en memoria para evitar recalcular muy seguido
_cache = {
    "gem_context": None,
    "timestamp": 0.0,
    "html": None,
}
CACHE_TTL = 300  # 5 minutos


@app.get("/health")
async def health():
    """Endpoint para UptimeRobot - respuesta rapida."""
    return {"status": "ok", "service": "bot-tendencia-brujula"}


@app.get("/api/data")
async def api_data():
    """Retorna los datos crudos del Cartografo en JSON."""
    now = time.time()
    if _cache["gem_context"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        _cache["gem_context"] = await ejecutar_cartografo()
        _cache["timestamp"] = now
        _cache["html"] = None  # invalidar HTML cache

    return JSONResponse(content={
        "assets": ASSETS,
        "timestamp": int(_cache["timestamp"]),
        "cache_ttl": CACHE_TTL,
        "data": _cache["gem_context"],
    })


@app.get("/", response_class=HTMLResponse)
async def index():
    """Pagina principal - renderiza la Brujula."""
    now = time.time()

    # Recalcular si el cache expiro
    if _cache["gem_context"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        t0 = time.time()
        _cache["gem_context"] = await ejecutar_cartografo()
        _cache["timestamp"] = now
        elapsed = time.time() - t0
        _cache["html"] = render_brujula(_cache["gem_context"])
        _cache["html"] += (
            f'<div style="text-align:center;color:#768390;font-size:12px;margin-top:8px;">'
            f'Calculado en {elapsed:.1f}s · Cache {CACHE_TTL}s</div>'
        )

    # Wrapper HTML completo
    page = (
        '<!DOCTYPE html>'
        '<html lang="es"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>🧭 Brujula MTF - Bot Tendencia</title>'
        '<style>'
        'body { margin: 0; padding: 20px; background: #010409; display: flex; '
        'justify-content: center; font-family: ui-monospace, Consolas, monospace; }'
        '</style>'
        '</head><body>'
        f'{_cache["html"]}'
        '</body></html>'
    )

    return HTMLResponse(content=page)


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("BOT TENDENCIA - BRUJULA MTF")
    print("=" * 60)
    print(f"  Activos: {ASSETS}")
    print(f"  API: {HL_REST_URL}")
    print(f"  TZ: {TZ_NAME}")
    print(f"  Abriendo en http://127.0.0.1:8000")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8000)