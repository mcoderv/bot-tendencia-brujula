"""
FastAPI app para Bot Tendencia - Brujula MTF.
Sirve el dashboard como pagina web bajo demanda.
v4.7: Integración completa con Signal Aggregator, Turso y Telegram.
"""
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.cartografo import ejecutar_cartografo, fetch_precios_rapidos
from app.brujula import render_brujula
from app.signal_aggregator import evaluar_y_ejecutar_senales
from app.config import ASSETS, TZ_NAME, HL_REST_URL, CACHE_TTL, CACHE_TTL_PRECIOS

app = FastAPI(
    title="Bot Tendencia - Brujula MTF",
    description="Dashboard on-demand para analisis multi-timeframe de crypto",
    version="4.7.0",
)

# Cache separado para estado completo, precios y señales
_cache = {
    "gem_context": None,
    "timestamp": 0.0,
}

_cache_html = {
    "html": None,
    "gem_timestamp": 0.0,
}

_cache_precios = {
    "data": None,
    "timestamp": 0.0,
}

_cache_senales = {
    "data": None,
    "timestamp": 0.0,
}


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Endpoint para UptimeRobot - respuesta rapida. Acepta GET y HEAD."""
    return {"status": "ok", "service": "bot-tendencia-brujula"}


@app.api_route("/api/prices", methods=["GET", "HEAD"])
async def api_prices():
    """
    Endpoint ligero: solo precios actuales de los activos.
    Cache de 30s para refresh frecuente sin saturar Hyperliquid.
    """
    now = time.time()
    if _cache_precios["data"] is None or (now - _cache_precios["timestamp"]) > CACHE_TTL_PRECIOS:
        _cache_precios["data"] = await fetch_precios_rapidos()
        _cache_precios["timestamp"] = now

    return JSONResponse(content={
        "assets": ASSETS,
        "timestamp": int(_cache_precios["timestamp"]),
        "cache_ttl": CACHE_TTL_PRECIOS,
        "prices": _cache_precios["data"],
    })


@app.get("/api/data")
async def api_data():
    """Retorna los datos crudos del Cartografo en JSON (estado completo)."""
    now = time.time()
    if _cache["gem_context"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        _cache["gem_context"] = await ejecutar_cartografo()
        _cache["timestamp"] = now
        _cache_html["html"] = None
        _cache_senales["data"] = None  # Invalidar cache de señales también

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
    
    # Paso 1: asegurar que gem_context y señales estén actualizados
    if _cache["gem_context"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        t0 = time.time()
        _cache["gem_context"] = await ejecutar_cartografo()
        _cache["timestamp"] = now
        _cache_html["html"] = None
        _cache_html["gem_timestamp"] = _cache["timestamp"]
        
        # Ejecutar Signal Aggregator (Turso + Telegram)
        print("\n🔄 Ejecutando Signal Aggregator (Turso + Telegram)...")
        try:
            # Esta función decide LONG/SHORT/NEUTRAL, guarda en Turso y envía a Telegram si hay cambio
            _cache_senales["data"] = await evaluar_y_ejecutar_senales()
            _cache_senales["timestamp"] = now
            print("✅ Signal Aggregator completado")
        except Exception as e:
            print(f"❌ Error en Signal Aggregator: {e}")
            _cache_senales["data"] = None

    # Paso 2: asegurar que el HTML esté generado
    if _cache_html["html"] is None:
        t0 = time.time()
        # Pasar las señales al renderizador para el panel de acción
        base_html = render_brujula(_cache["gem_context"], _cache_senales["data"])
        elapsed = time.time() - t0
        footer = (
            f'<div style="text-align:center;color:#768390;font-size:12px;margin-top:8px;">'
            f'Calculado en {elapsed:.1f}s · Cache {CACHE_TTL}s · Precios cada {CACHE_TTL_PRECIOS}s</div>'
        )
        _cache_html["html"] = base_html + footer
        _cache_html["gem_timestamp"] = _cache["timestamp"]

    # Paso 3: JavaScript para countdown + polling de precios
    js_code = f"""
    <script>
    (function() {{
        var countdown = {CACHE_TTL_PRECIOS};
        var countdownEl = null;
        function formatPrice(p) {{
            if (p <= 0) return '—';
            if (p >= 1000) return '$' + p.toLocaleString('en-US', {{maximumFractionDigits: 0}});
            if (p >= 1) return '$' + p.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
            return '$' + p.toLocaleString('en-US', {{minimumFractionDigits: 4, maximumFractionDigits: 4}});
        }}
        function crearCountdown() {{
            var container = document.createElement('div');
            container.style.cssText = 'position:fixed;top:10px;right:10px;background:#1a1a2e;border:1px solid #30363d;border-radius:6px;padding:6px 12px;color:#768390;font-size:12px;font-family:ui-monospace,Consolas,monospace;z-index:9999;';
            countdownEl = container;
            document.body.appendChild(container);
            updateCountdown();
        }}
        function updateCountdown() {{
            if (countdownEl) {{
                countdownEl.textContent = '⏱ Refresh precios: ' + countdown + 's';
            }}
        }}
        function fetchPrices() {{
            fetch('/api/prices')
            .then(function(r) {{ return r.json(); }})
            .then(function(data) {{
                var prices = data.prices || {{}};
                for (var coin in prices) {{
                    if (prices[coin] && prices[coin].precio > 0) {{
                        var el = document.querySelector('[data-coin-precio="' + coin + '"]');
                        if (el) {{
                            el.textContent = formatPrice(prices[coin].precio);
                        }}
                    }}
                }}
            }})
            .catch(function(err) {{
                console.warn('Error fetching prices:', err);
            }});
        }}
        function tick() {{
            countdown--;
            if (countdown <= 0) {{
                fetchPrices();
                countdown = {CACHE_TTL_PRECIOS};
            }}
            updateCountdown();
        }}
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', function() {{
                crearCountdown();
                setInterval(tick, 1000);
            }});
        }} else {{
            crearCountdown();
            setInterval(tick, 1000);
        }}
    }})();
    </script>
    """

    # Paso 4: wrapper HTML completo
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
        f'{_cache_html["html"]}'
        f'{js_code}'
        '</body></html>'
    )

    return HTMLResponse(content=page)


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("BOT TENDENCIA - BRUJULA MTF v4.7")
    print("=" * 60)
    print(f"  Activos: {ASSETS}")
    print(f"  API: {HL_REST_URL}")
    print(f"  TZ: {TZ_NAME}")
    print(f"  Abriendo en http://127.0.0.1:8000")
    print(f"  Precios en vivo: cada {CACHE_TTL_PRECIOS}s")
    print(f"  Análisis MTF + Señales: cada {CACHE_TTL}s")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8000)