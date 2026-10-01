"""
database.py
Módulo de conexión a Turso usando SQL over HTTP.
No usa libsql-client (deprecado). Usa aiohttp directamente.
Endpoint: https://<db>.turso.io/v2/pipeline
"""
import os
import json
import time
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
TURSO_HTTP_URL = TURSO_URL.replace("libsql://", "https://") if TURSO_URL else ""

def _to_tagged_value(value: Any) -> Dict[str, Any]:
    """Convierte un valor Python al formato tagged que espera Turso."""
    if value is None:
        return {"type": "null"}
    elif isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    elif isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    elif isinstance(value, float):
        return {"type": "float", "value": value}
    elif isinstance(value, str):
        return {"type": "text", "value": value}
    elif isinstance(value, bytes):
        return {"type": "blob", "base64": value.hex()}
    else:
        return {"type": "text", "value": str(value)}

def _extract_value(tagged: Any) -> Any:
    """Extrae el valor Python desde un objeto tagged de Turso."""
    if tagged is None:
        return None
    if not isinstance(tagged, dict):
        return tagged
    t = tagged.get("type")
    v = tagged.get("value")
    if t == "integer":
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    elif t == "float":
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    elif t == "null":
        return None
    else:
        return v

async def _execute(sql: str, args: list = None) -> Dict[str, Any]:
    """Ejecuta una sentencia SQL en Turso via HTTP."""
    if not TURSO_HTTP_URL or not TURSO_TOKEN:
        raise ValueError("TURSO_URL y TURSO_TOKEN deben estar configurados")
    
    url = f"{TURSO_HTTP_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json",
    }
    stmt = {"sql": sql}
    if args:
        tagged_args = [_to_tagged_value(arg) for arg in args]
        stmt["args"] = tagged_args
        
    payload = {
        "requests": [
            {"type": "execute", "stmt": stmt}
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise Exception(f"Turso HTTP {resp.status}: {body[:200]}")
            data = await resp.json()
            
    results = data.get("results", [])
    if not results:
        return {"rows": [], "last_insert_rowid": None}
        
    first = results[0]
    if first.get("type") == "error":
        raise Exception(f"Turso SQL error: {first.get('error', {}).get('message', 'Desconocido')}")
        
    response = first.get("response", {})
    result = response.get("result", response)
    raw_rows = result.get("rows", [])
    rows = [[_extract_value(cell) for cell in row] for row in raw_rows]
    last_insert_rowid_raw = result.get("last_insert_rowid")
    last_insert_rowid = _extract_value(last_insert_rowid_raw)
    
    return {
        "rows": rows,
        "last_insert_rowid": last_insert_rowid,
    }

async def init_tables():
    """Crea las tablas 'signals' y 'subscribers' si no existen."""
    # 1. Crear tabla signals base si no existe
    await _execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coin TEXT NOT NULL,
        direction TEXT NOT NULL,
        price_entry REAL NOT NULL,
        price_exit REAL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        pnl_percent REAL,
        opened_at INTEGER NOT NULL,
        closed_at INTEGER
    )
    """)
    
    # 2. Obtener columnas existentes reales de signals
    result = await _execute("PRAGMA table_info(signals)")
    existing_columns = [row[1] for row in result.get("rows", [])]
    
    # 3. Definir columnas esperadas y sus tipos para signals
    expected_columns = {
        "score": "INTEGER",
        "context_snapshot": "TEXT",
        "exit_reason": "TEXT",
        "regime": "TEXT",
        "duration_seconds": "INTEGER"
    }
    
    # 4. Agregar solo las que faltan (Migración quirúrgica)
    for col_name, col_type in expected_columns.items():
        if col_name not in existing_columns:
            try:
                await _execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
                print(f"  ✅ Columna agregada a signals: {col_name}")
            except Exception as e:
                print(f"  ⚠️ Warning al agregar columna {col_name}: {e}")
                
    # 5. Crear índice para búsquedas rápidas en signals
    await _execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_coin_status
        ON signals(coin, status)
    """)
    
    # 6. Crear tabla subscribers para el sistema VIP
    await _execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        status TEXT DEFAULT 'pending',
        joined_channel_at INTEGER,
        trial_start INTEGER,
        subscription_end INTEGER,
        last_invoice_sent INTEGER DEFAULT 0
    )
    """)
    print("  ✅ Tabla 'subscribers' verificada/creada.")
    print("✅ Tablas de Turso inicializadas correctamente.")

# ==============================================================================
# FUNCIONES EXISTENTES: SIGNALS (Sin cambios)
# ==============================================================================

async def open_signal(coin: str, direction: str, price_entry: float, score: int = 0, context_snapshot: Dict[str, Any] = None, regime: str = "desconocido") -> int:
    now = int(time.time())
    snapshot_json = json.dumps(context_snapshot, ensure_ascii=False) if context_snapshot else "{}"
    result = await _execute(
        """
        INSERT INTO signals (coin, direction, price_entry, status, opened_at, score, context_snapshot, regime)
        VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)
        """,
        [coin, direction, price_entry, now, score, snapshot_json, regime]
    )
    signal_id = result.get("last_insert_rowid")
    print(f"✅ Señal abierta: {coin} {direction} @ {price_entry} | Score: {score}/6 | Régimen: {regime} (ID: {signal_id})")
    return signal_id

async def close_signal(coin: str, price_exit: float, exit_reason: str = "NEUTRAL") -> Optional[Dict[str, Any]]:
    now = int(time.time())
    result = await _execute(
        """
        SELECT id, direction, price_entry, opened_at, score, regime
        FROM signals WHERE coin = ? AND status = 'OPEN' ORDER BY opened_at DESC LIMIT 1
        """,
        [coin]
    )
    rows = result.get("rows", [])
    if not rows:
        return None
        
    row = rows[0]
    signal_id, direction, price_entry, opened_at, score, regime = row[0], row[1], float(row[2]), row[3], row[4], row[5]
    
    pnl_percent = ((price_exit / price_entry) - 1) * 100 if direction == "LONG" else ((price_entry / price_exit) - 1) * 100
    duration_seconds = now - opened_at
    
    await _execute(
        """
        UPDATE signals SET status = 'CLOSED', price_exit = ?, pnl_percent = ?, closed_at = ?, exit_reason = ?, duration_seconds = ?
        WHERE id = ?
        """,
        [price_exit, pnl_percent, now, exit_reason, duration_seconds, signal_id]
    )
    
    result_data = {
        "signal_id": signal_id, "coin": coin, "direction": direction, "price_entry": price_entry,
        "price_exit": price_exit, "pnl_percent": pnl_percent, "duration_seconds": duration_seconds,
        "score": score, "regime": regime, "exit_reason": exit_reason,
    }
    print(f"✅ Señal cerrada: {coin} {direction} | PnL: {pnl_percent:+.2f}% | Motivo: {exit_reason} | Duración: {duration_seconds}s")
    return result_data

async def get_open_signals() -> List[Dict[str, Any]]:
    result = await _execute("SELECT id, coin, direction, price_entry, opened_at, score, regime FROM signals WHERE status = 'OPEN' ORDER BY opened_at DESC")
    return [{"id": r[0], "coin": r[1], "direction": r[2], "price_entry": float(r[3]), "opened_at": r[4], "score": r[5], "regime": r[6]} for r in result.get("rows", [])]

async def get_last_closed_signal(coin: str) -> Optional[Dict[str, Any]]:
    result = await _execute(
        """
        SELECT id, direction, price_entry, price_exit, pnl_percent, opened_at, closed_at, score, context_snapshot, exit_reason, regime, duration_seconds
        FROM signals WHERE coin = ? AND status = 'CLOSED' ORDER BY closed_at DESC LIMIT 1
        """, [coin]
    )
    rows = result.get("rows", [])
    if not rows: return None
    row = rows[0]
    context_snapshot = None
    if row[8]:
        try: context_snapshot = json.loads(row[8])
        except (json.JSONDecodeError, TypeError): pass
        
    return {
        "id": row[0], "coin": coin, "direction": row[1], "price_entry": float(row[2]) if row[2] else None,
        "price_exit": float(row[3]) if row[3] else None, "pnl_percent": float(row[4]) if row[4] else None,
        "opened_at": row[5], "closed_at": row[6], "score": row[7], "context_snapshot": context_snapshot,
        "exit_reason": row[9], "regime": row[10], "duration_seconds": row[11],
    }

async def get_stats() -> Dict[str, Any]:
    result_total = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED'")
    total_closed = result_total["rows"][0][0] if result_total["rows"] else 0
    result_winners = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED' AND pnl_percent > 0")
    winners = result_winners["rows"][0][0] if result_winners["rows"] else 0
    result_pnl = await _execute("SELECT SUM(pnl_percent) FROM signals WHERE status = 'CLOSED'")
    total_pnl = result_pnl["rows"][0][0] if result_pnl["rows"] and result_pnl["rows"][0][0] else 0.0
    win_rate = (winners / total_closed * 100) if total_closed > 0 else 0.0
    return {"total_closed": total_closed, "winners": winners, "losers": total_closed - winners, "win_rate": round(win_rate, 2), "total_pnl": round(total_pnl, 2)}

# ==============================================================================
# FUNCIONES NUEVAS: SUBSCRIBERS (Sistema VIP)
# ==============================================================================

async def get_subscriber(user_id: int) -> Optional[Dict[str, Any]]:
    """Obtiene los datos de un suscriptor por su user_id."""
    result = await _execute(
        "SELECT user_id, username, status, joined_channel_at, trial_start, subscription_end, last_invoice_sent FROM subscribers WHERE user_id = ?",
        [user_id]
    )
    rows = result.get("rows", [])
    if not rows:
        return None
    row = rows[0]
    return {
        "user_id": row[0], "username": row[1], "status": row[2],
        "joined_channel_at": row[3], "trial_start": row[4],
        "subscription_end": row[5], "last_invoice_sent": row[6]
    }

async def register_subscriber(user_id: int, username: str, joined_channel_at: int):
    """Registra un nuevo usuario o actualiza su fecha de entrada al canal."""
    await _execute(
        """
        INSERT INTO subscribers (user_id, username, status, joined_channel_at)
        VALUES (?, ?, 'pending', ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            joined_channel_at = excluded.joined_channel_at,
            status = CASE WHEN status = 'pending' THEN 'pending' ELSE status END
        """,
        [user_id, username, joined_channel_at]
    )

async def activate_trial(user_id: int):
    """Activa la prueba de 7 días para un usuario."""
    now = int(time.time())
    end = now + (7 * 24 * 60 * 60)  # 7 días en segundos
    await _execute(
        "UPDATE subscribers SET status = 'trial', trial_start = ?, subscription_end = ? WHERE user_id = ?",
        [now, end, user_id]
    )

async def activate_paid(user_id: int):
    """Extiende la suscripción 30 días a partir de la fecha actual o de la fecha de vencimiento (lo que sea mayor)."""
    now = int(time.time())
    sub = await get_subscriber(user_id)
    if sub and sub.get("subscription_end") and sub["subscription_end"] > now:
        new_end = sub["subscription_end"] + (30 * 24 * 60 * 60)
    else:
        new_end = now + (30 * 24 * 60 * 60)
    
    await _execute(
        "UPDATE subscribers SET status = 'active', subscription_end = ? WHERE user_id = ?",
        [new_end, user_id]
    )

async def get_pending_activations(hours: int = 24) -> List[Dict[str, Any]]:
    """Obtiene usuarios que entraron al canal pero no activaron su prueba en X horas."""
    now = int(time.time())
    threshold = now - (hours * 60 * 60)
    result = await _execute(
        "SELECT user_id, username, joined_channel_at FROM subscribers WHERE status = 'pending' AND joined_channel_at < ?",
        [threshold]
    )
    return [{"user_id": r[0], "username": r[1], "joined_channel_at": r[2]} for r in result.get("rows", [])]

async def get_expiring_soon(hours: int = 24) -> List[Dict[str, Any]]:
    """Obtiene usuarios cuya suscripción expira en las próximas X horas y no han recibido recordatorio reciente."""
    now = int(time.time())
    threshold = now + (hours * 60 * 60)
    # Evitamos spam: solo si no se ha enviado factura en las últimas 12 horas
    safe_reminder_threshold = now - (12 * 60 * 60)
    
    result = await _execute(
        """
        SELECT user_id, username, subscription_end FROM subscribers
        WHERE status IN ('trial', 'active') 
          AND subscription_end <= ? 
          AND subscription_end > ?
          AND COALESCE(last_invoice_sent, 0) < ?
        """,
        [threshold, now, safe_reminder_threshold]
    )
    return [{"user_id": r[0], "username": r[1], "subscription_end": r[2]} for r in result.get("rows", [])]

async def get_expired() -> List[Dict[str, Any]]:
    """Obtiene usuarios cuya suscripción ya venció y deben ser expulsados."""
    now = int(time.time())
    result = await _execute(
        "SELECT user_id, username FROM subscribers WHERE status IN ('trial', 'active') AND subscription_end < ?",
        [now]
    )
    return [{"user_id": r[0], "username": r[1]} for r in result.get("rows", [])]

async def mark_invoice_sent(user_id: int):
    """Marca que se le envió una factura al usuario para evitar spam."""
    now = int(time.time())
    await _execute(
        "UPDATE subscribers SET last_invoice_sent = ? WHERE user_id = ?",
        [now, user_id]
    )

async def update_subscriber_status(user_id: int, status: str):
    """Actualiza el estado de un suscriptor (ej: a 'banned' o 'expired')."""
    await _execute(
        "UPDATE subscribers SET status = ? WHERE user_id = ?",
        [status, user_id]
    )

# ==============================================================================
# TESTS LOCALES
# ==============================================================================

async def run_tests():
    """Ejecuta tests básicos de conexión y estructura."""
    print("=" * 60)
    print("TEST DE CONEXIÓN A TURSO")
    print("=" * 60)
    print(f"  URL: {TURSO_HTTP_URL}")
    print(f"  Token: ...{TURSO_TOKEN[-6:] if TURSO_TOKEN else 'NO CONFIGURADO'}")
    print()
    
    try:
        print("📝 Paso 1: Inicializando tablas...")
        await init_tables()
        
        print("\n📝 Paso 2: Probando registro de suscriptor...")
        await register_subscriber(123456789, "test_user", int(time.time()))
        sub = await get_subscriber(123456789)
        print(f"   Usuario registrado: {sub['username']} (Estado: {sub['status']})")
        
        print("\n📝 Paso 3: Probando activación de trial...")
        await activate_trial(123456789)
        sub = await get_subscriber(123456789)
        print(f"   Estado actualizado a: {sub['status']} | Vence: {time.ctime(sub['subscription_end'])}")
        
        print("\n✅ Todos los tests de base de datos pasaron correctamente.")
    except Exception as e:
        print(f"❌ Error en tests: {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())