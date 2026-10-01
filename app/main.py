"""
FastAPI app para Bot Tendencia - Brujula MTF.
Sirve el dashboard como pagina web bajo demanda.
v5.1: + Webhook para Telegram + Revisión de suscripciones en /tick.
- Las señales se evalúan automáticamente aunque nadie visite la web.
- GitHub Actions llama a /tick cada 15 min para mantener Render despierto y revisar VIPs.
- /webhook recibe /start, pagos y entradas al canal.
"""
import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.cartografo import ejecutar_cartografo, fetch_precios_rapidos
from app.brujula import render_brujula
from app.signal_aggregator import evaluar_y_ejecutar_senales
from app.config import ASSETS, TZ_NAME, HL_REST_URL, CACHE_TTL, CACHE_TTL_PRECIOS, VIP_CHANNEL_ID

# --- NUEVOS IMPORTS PARA SISTEMA VIP ---
from app.subscriptions import run_subscription_checks, handle_start_command, handle_successful_payment
from app.database import register_subscriber
# ---------------------------------------

# ── Intervalo del scheduler interno (segundos) ──
SCHEDULER_INTERVAL = 60

# ======================================================================
# SCHEDULER INTERNO: ejecuta Signal Aggregator cada 60s en background
# ======================================================================
async def signal_scheduler():
    """
    Bucle infinito que ejecuta Signal Aggregator cada SCHEDULER_INTERVAL segundos.
    Corre en background mientras el servicio esté activo.
    """
    await asyncio.sleep(5)
    print(f"✅ Scheduler de señales iniciado (cada {SCHEDULER_INTERVAL}s)")
    
    while True:
        try:
            print(f"\n⏰ [{time.strftime('%H:%M:%S')}] Scheduler ejecutando Signal Aggregator...")
            t0 = time.time()
            senales = await evaluar_y_ejecutar_senales()
            elapsed = time.time() - t0
            print(f"✅ [{time.strftime('%H:%M:%S')}] Scheduler completado en {elapsed:.1f}s — {len(senales)} activos evaluados")
        except asyncio.CancelledError:
            print("🛑 Scheduler detenido por cancelación")
            break
        except Exception as e:
            print(f"❌ [{time.strftime('%H:%M:%S')}] Error en scheduler: {type(e).__name__}: {e}")
        
        await asyncio.sleep(SCHEDULER_INTERVAL)

# ======================================================================
# LIFESPAN: inicia el scheduler al arrancar la aplicación
# ======================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicia el scheduler al arrancar y lo detiene al cerrar."""
    task = asyncio.create_task(signal_scheduler())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Bot Tendencia - Brujula MTF",
    description="Dashboard on-demand + scheduler para señales 24/7 + VIP",
    version="5.1.0",
    lifespan=lifespan,
)

# ── Cache compartido ──
_cache = {"gem_context": None, "timestamp": 0.0}
_cache_html = {"html": None, "gem_timestamp": 0.0}
_cache_precios = {"data": None, "timestamp": 0.0}
_cache_senales = {"data": None, "timestamp": 0.0}

# ======================================================================
# ENDPOINTS
# ======================================================================

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Endpoint para GitHub Actions / UptimeRobot - respuesta rapida."""
    return {"status": "ok", "service": "bot-tendencia-brujula"}

@app.get("/tick")
async def tick():
    """
    Endpoint para GitHub Actions (llamado cada 15 min).
    Ejecuta Signal Aggregator y revisa suscripciones VIP.
    """
    try:
        t0 = time.time()
        
        # 1. Evaluar señales de trading
        senales = await evaluar_y_ejecutar_senales()
        
        # 2. NUEVO: Revisar suscripciones VIP (vencimientos, recordatorios, expulsiones)
        await run_subscription_checks()

        elapsed = time.time() - t0
        print(f"✅ [/tick] Completado en {elapsed:.1f}s — {len(senales)} activos evaluados")
        
        return {
            "status": "ok",
            "elapsed_seconds": round(elapsed, 2),
            "assets_evaluated": len(senales),
            "timestamp": int(time.time()),
        }
    except Exception as e:
        print(f"❌ [/tick] Error: {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# --- NUEVO ENDPOINT: WEBHOOK DE TELEGRAM ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Recibe actualizaciones de Telegram (mensajes, pagos, entradas al canal).
    """
    try:
        update = await request.json()
        
        # 1. Mensajes de texto (ej. /start)
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            username = msg["from"].get("username", "")
            text = msg.get("text", "")
            
            if text and text.startswith("/start"):
                print(f"🚀 Comando /start recibido de {username} ({chat_id})")
                await handle_start_command(chat_id, username)
                
            if "successful_payment" in msg:
                user_id = msg["from"]["id"]
                print(f"💰 Pago exitoso detectado para user_id: {user_id}")
                await handle_successful_payment(user_id)
                
        # 2. Cambios de estado en el canal (entradas/salidas)
        elif "chat_member" in update:
            cm = update["chat_member"]
            chat_id = cm["chat"]["id"]
            user_id = cm["new_chat_member"]["user"]["id"]
            username = cm["new_chat_member"]["user"].get("username", "")
            new_status = cm["new_chat_member"]["status"]
            
            if chat_id == VIP_CHANNEL_ID and new_status in ("member", "administrator"):
                now = int(time.time())
                await register_subscriber(user_id, username, now)
                print(f"👤 Nuevo usuario detectado en canal VIP: {username} ({user_id})")

        return {"ok": True} # Siempre devolver OK a Telegram
    except Exception as e:
        print(f"❌ [/webhook] Error procesando update: {e}")
        return {"ok": True}
# -------------------------------------------

@app.api_route("/api/prices", methods=["GET", "HEAD"])
async def api_prices():
    """Endpoint ligero: solo precios actuales (cache 30s)."""
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
    """Retorna los datos crudos del Cartografo en JSON."""
    now = time.time()
    if _cache["gem_context"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        _cache["gem_context"] = await ejecutar_cartografo()
        _cache["timestamp"] = now
        _cache_html["html"] = None
        _cache_senales["data"] = None
        
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
    
    if _cache["gem_context"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        t0 = time.time()
        _cache["gem_context"] = await ejecutar_cartografo()
        _cache["timestamp"] = now
        _cache_html["html"] = None
        
        try:
            _cache_senales["data"] = await evaluar_y_ejecutar_senales()
            _cache_senales["timestamp"] = now
        except Exception as e:
            print(f"❌ Error en Signal Aggregator (index): {e}")
            _cache_senales["data"] = None
            
    if _cache_html["html"] is None:
        t0 = time.time()
        base_html = render_brujula(_cache["gem_context"], _cache_senales["data"])
        elapsed = time.time() - t0
        footer = (
            f'<div style="text-align:center;color:#768390;font-size:12px;margin-top:8px;">'
            f'Calculado en {elapsed:.1f}s · Cache {CACHE_TTL}s · Precios cada {CACHE_TTL_PRECIOS}s · Scheduler cada {SCHEDULER_INTERVAL}s</div>'
        )
        _cache_html["html"] = base_html + footer
        _cache_html["gem_timestamp"] = _cache["timestamp"]
        
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
            if (countdownEl) {{ countdownEl.textContent = '⏱ Refresh precios: ' + countdown + 's'; }}
        }}
        function fetchPrices() {{
            fetch('/api/prices')
            .then(function(r) {{ return r.json(); }})
            .then(function(data) {{
                var prices = data.prices || {{}};
                for (var coin in prices) {{
                    if (prices[coin] && prices[coin].precio > 0) {{
                        var el = document.querySelector('[data-coin-precio="' + coin + '"]');
                        if (el) {{ el.textContent = formatPrice(prices[coin].precio); }}
                    }}
                }}
            }}).catch(function(err) {{ console.warn('Error fetching prices:', err); }});
        }}
        function tick() {{
            countdown--;
            if (countdown <= 0) {{ fetchPrices(); countdown = {CACHE_TTL_PRECIOS}; }}
            updateCountdown();
        }}
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', function() {{ crearCountdown(); setInterval(tick, 1000); }});
        }} else {{ crearCountdown(); setInterval(tick, 1000); }}
    }})();
    </script>
    """
    
    page = (
        '<!DOCTYPE html><html lang="es"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>🧭 Brujula MTF - Bot Tendencia</title>'
        '<style>body { margin: 0; padding: 20px; background: #010409; display: flex; justify-content: center; font-family: ui-monospace, Consolas, monospace; }</style>'
        '</head><body>'
        f'{_cache_html["html"]}'
        f'{js_code}'
        '</body></html>'
    )
    
    return HTMLResponse(content=page)

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("BOT TENDENCIA - BRUJULA MTF v5.1 (+ VIP)")
    print("=" * 60)
    print(f"  Activos: {ASSETS}")
    print(f"  API: {HL_REST_URL}")
    print(f"  TZ: {TZ_NAME}")
    print(f"  Abriendo en http://127.0.0.1:8000")
    print(f"  Precios en vivo: cada {CACHE_TTL_PRECIOS}s")
    print(f"  Scheduler interno: cada {SCHEDULER_INTERVAL}s")
    print(f"  Endpoint /tick: para GitHub Actions cada 15 min")
    print(f"  Endpoint /webhook: para Telegram")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8000)