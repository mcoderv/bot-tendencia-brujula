"""
database.py v5.5 FINAL: Columnas v4.0 + invalidation_warned_at (timestamp) +
session cache + auth helpers.
FIX: typo "exit _reason" → "exit_reason" en get_weekly_stats.
FIX: Unclosed client session warning al ejecutar como test.
"""
import os, json, time, asyncio, aiohttp
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from app.config import TOTAL_ROUND_TRIP_COST_PERCENT

load_dotenv()
TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
TURSO_HTTP_URL = TURSO_URL.replace("libsql://", "https://") if TURSO_URL else ""

# === v4.0 === Sesión aiohttp cacheada
_session: Optional[aiohttp.ClientSession] = None

async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300),
        )
    return _session

async def close_session():
    """Cierra la sesión global (llamar en shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None

def _to_tagged_value(value):
    if value is None: return {"type": "null"}
    elif isinstance(value, bool): return {"type": "integer", "value": "1" if value else "0"}
    elif isinstance(value, int): return {"type": "integer", "value": str(value)}
    elif isinstance(value, float): return {"type": "float", "value": value}
    elif isinstance(value, str): return {"type": "text", "value": value}
    elif isinstance(value, bytes): return {"type": "blob", "base64": value.hex()}
    else: return {"type": "text", "value": str(value)}

def _extract_value(tagged):
    if tagged is None: return None
    if not isinstance(tagged, dict): return tagged
    t, v = tagged.get("type"), tagged.get("value")
    if t == "integer":
        try: return int(v) if v is not None else None
        except (TypeError, ValueError): return None
    elif t == "float":
        try: return float(v) if v is not None else None
        except (TypeError, ValueError): return None
    elif t == "null": return None
    else: return v

async def _execute(sql, args=None):
    if not TURSO_HTTP_URL or not TURSO_TOKEN: raise ValueError("TURSO no configurado")
    url = f"{TURSO_HTTP_URL}/v2/pipeline"
    headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}
    stmt = {"sql": sql}
    if args: stmt["args"] = [_to_tagged_value(arg) for arg in args]
    payload = {"requests": [{"type": "execute", "stmt": stmt}]}
    session = await _get_session()
    async with session.post(url, json=payload, headers=headers) as resp:
        if resp.status != 200: raise Exception(f"Turso HTTP {resp.status}")
        data = await resp.json()
    results = data.get("results", [])
    if not results: return {"rows": [], "last_insert_rowid": None}
    first = results[0]
    if first.get("type") == "error": raise Exception(f"Turso SQL error")
    result = first.get("response", {}).get("result", first.get("response", {}))
    rows = [[_extract_value(cell) for cell in row] for row in result.get("rows", [])]
    return {"rows": rows, "last_insert_rowid": _extract_value(result.get("last_insert_rowid"))}

# === v4.0 FIX === Verificación de columnas antes de SELECT
async def _ensure_column(table: str, col: str, col_type: str) -> bool:
    """Asegura que una columna exista. Retorna True si existe o se creó."""
    try:
        result = await _execute(f"PRAGMA table_info({table})")
        existing = [row[1] for row in result.get("rows", [])]
        if col not in existing:
            await _execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            print(f"  ✅ Columna agregada a {table}: {col}")
            return True
        return True
    except Exception as e:
        print(f"  ⚠️ Error verificando columna {col}: {e}")
        return False

async def init_tables():
    """Crea tablas + migración de columnas v4.0 + índices."""
    # 1. Tabla signals
    await _execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT, direction TEXT, price_entry REAL, price_exit REAL,
            status TEXT DEFAULT 'OPEN', pnl_percent REAL, opened_at INTEGER, closed_at INTEGER
        )
    """)
    # Cada columna se asegura individualmente
    columns_to_add = {
        "score": "INTEGER",
        "context_snapshot": "TEXT",
        "exit_reason": "TEXT",
        "regime": "TEXT",
        "duration_seconds": "INTEGER",
        "fee_percent": "REAL",
        "net_pnl_percent": "REAL",
        "invalidation": "REAL",
        "invalidation_warned_at": "INTEGER DEFAULT 0",
        "mfe_percent": "REAL",
    }
    for col, typ in columns_to_add.items():
        await _ensure_column("signals", col, typ)
    await _execute("CREATE INDEX IF NOT EXISTS idx_signals_coin_status ON signals(coin, status)")
    # 2. Tabla subscribers
    await _execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY, username TEXT, status TEXT DEFAULT 'pending',
            joined_channel_at INTEGER, trial_start INTEGER,
            subscription_end INTEGER, last_invoice_sent INTEGER DEFAULT 0
        )
    """)
    # Índices para subscribers
    await _execute("CREATE INDEX IF NOT EXISTS idx_subs_status_end ON subscribers(status, subscription_end)")
    await _execute("CREATE INDEX IF NOT EXISTS idx_subs_status_joined ON subscribers(status, joined_channel_at)")
    print("  ✅ Tabla 'subscribers' verificada/creada.")
    print("✅ Tablas de Turso inicializadas correctamente.")

async def open_signal(coin, direction, price_entry, score=0, context_snapshot=None,
                      regime="desconocido", invalidation=None):
    """Abre una nueva señal. v4.0: acepta invalidation."""
    now = int(time.time())
    snap = json.dumps(context_snapshot) if context_snapshot else "{}"
    res = await _execute(
        """INSERT INTO signals
        (coin, direction, price_entry, status, opened_at, score, context_snapshot, regime, invalidation)
        VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)""",
        [coin, direction, price_entry, now, score, snap, regime, invalidation]
    )
    return res.get("last_insert_rowid")

async def close_signal(coin, price_exit, exit_reason="NEUTRAL"):
    """Cierra la señal abierta del coin."""
    now = int(time.time())
    try:
        res = await _execute(
            """SELECT id, direction, price_entry, opened_at, score, regime, invalidation, mfe_percent
            FROM signals WHERE coin = ? AND status = 'OPEN' ORDER BY opened_at DESC LIMIT 1""",
            [coin]
        )
        has_invalidation_col = True
    except Exception:
        res = await _execute(
            """SELECT id, direction, price_entry, opened_at, score, regime
            FROM signals WHERE coin = ? AND status = 'OPEN' ORDER BY opened_at DESC LIMIT 1""",
            [coin]
        )
        has_invalidation_col = False
    if not res.get("rows"): return None
    row = res["rows"][0]
    if has_invalidation_col:
        sig_id, direction, p_entry, opened, score, regime, invalidation, mfe = (
            row[0], row[1], float(row[2]), row[3], row[4], row[5], row[6], row[7]
        )
    else:
        sig_id, direction, p_entry, opened, score, regime = (
            row[0], row[1], float(row[2]), row[3], row[4], row[5]
        )
        invalidation, mfe = None, None
    pnl = ((price_exit / p_entry) - 1) * 100 if direction == "LONG" else ((p_entry / price_exit) - 1) * 100
    fee = TOTAL_ROUND_TRIP_COST_PERCENT * 100
    net = pnl - fee
    dur = now - opened
    await _execute(
        """UPDATE signals SET status='CLOSED', price_exit=?, pnl_percent=?, fee_percent=?, net_pnl_percent=?,
        closed_at=?, exit_reason=?, duration_seconds=? WHERE id=?""",
        [price_exit, pnl, fee, net, now, exit_reason, dur, sig_id]
    )
    return {
        "signal_id": sig_id, "coin": coin, "direction": direction, "price_entry": p_entry,
        "price_exit": price_exit, "pnl_percent": pnl, "fee_percent": fee, "net_pnl_percent": net,
        "duration_seconds": dur, "score": score, "regime": regime, "exit_reason": exit_reason,
        "invalidation": invalidation, "mfe_percent": mfe,
    }

async def get_open_signals():
    """Lee señales abiertas con invalidation_warned_at."""
    try:
        res = await _execute(
            """SELECT id, coin, direction, price_entry, opened_at, score, regime,
            invalidation, invalidation_warned_at FROM signals WHERE status = 'OPEN'"""
        )
        return [{
            "id": r[0], "coin": r[1], "direction": r[2], "price_entry": float(r[3]),
            "opened_at": r[4], "score": r[5], "regime": r[6],
            "invalidation": r[7], "invalidation_warned_at": r[8] or 0
        } for r in res.get("rows", [])]
    except Exception:
        res = await _execute(
            "SELECT id, coin, direction, price_entry, opened_at, score, regime FROM signals WHERE status = 'OPEN'"
        )
        return [{
            "id": r[0], "coin": r[1], "direction": r[2], "price_entry": float(r[3]),
            "opened_at": r[4], "score": r[5], "regime": r[6],
            "invalidation": None, "invalidation_warned_at": 0
        } for r in res.get("rows", [])]

async def get_stats():
    tot = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED'")
    tc = tot["rows"][0][0] if tot["rows"] else 0
    win = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED' AND net_pnl_percent > 0")
    w = win["rows"][0][0] if win["rows"] else 0
    pnl = await _execute("SELECT SUM(net_pnl_percent) FROM signals WHERE status = 'CLOSED'")
    tp = pnl["rows"][0][0] if pnl["rows"] and pnl["rows"][0][0] else 0.0
    return {"total_closed": tc, "winners": w, "losers": tc - w, "win_rate": round((w/tc*100) if tc > 0 else 0, 2), "total_pnl": round(tp, 2)}

# === v4.0 FIX === timestamp en vez de boolean
async def mark_invalidation_warned(signal_id: int):
    """Marca el timestamp de la última alerta de invalidación."""
    now = int(time.time())
    try:
        await _execute(
            "UPDATE signals SET invalidation_warned_at = ? WHERE id = ?",
            [now, signal_id]
        )
    except Exception:
        pass

async def update_mfe(coin: str, mfe_percent: float):
    """Actualiza el MFE (Max Favorable Excursion) de la señal abierta."""
    try:
        await _execute(
            "UPDATE signals SET mfe_percent = ? WHERE coin = ? AND status = 'OPEN'",
            [mfe_percent, coin]
        )
    except Exception:
        pass

async def get_weekly_stats() -> Dict[str, Any]:
    """Estadísticas agregadas de los últimos 7 días en 1 sola query."""
    seven_days_ago = int(time.time()) - 7 * 86400
    # FIX: "exit _reason" → "exit_reason" (typo corregido)
    res = await _execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN exit_reason = 'FLIP' THEN 1 ELSE 0 END) as flips,
            SUM(CASE WHEN exit_reason = 'NEUTRAL' THEN 1 ELSE 0 END) as neutrals,
            SUM(CASE WHEN exit_reason = 'CAOS' THEN 1 ELSE 0 END) as chaos,
            COALESCE(AVG(duration_seconds), 0) as avg_dur,
            COALESCE(AVG(net_pnl_percent), 0) as avg_pnl,
            SUM(CASE WHEN net_pnl_percent > 0 THEN 1 ELSE 0 END) as winners
        FROM signals
        WHERE status = 'CLOSED' AND closed_at >= ?
    """, [seven_days_ago])
    if not res.get("rows"):
        return {"total": 0, "flips": 0, "neutrals": 0, "chaos": 0, "avg_duration_min": 0, "avg_net_pnl": 0, "winners": 0, "win_rate": 0}
    r = res["rows"][0]
    total = r[0] or 0
    return {
        "total": int(total),
        "flips": int(r[1] or 0),
        "neutrals": int(r[2] or 0),
        "chaos": int(r[3] or 0),
        "avg_duration_min": round((r[4] or 0) / 60, 1),
        "avg_net_pnl": round(float(r[5] or 0), 3),
        "winners": int(r[6] or 0),
        "win_rate": round((r[6] or 0) / total * 100, 1) if total > 0 else 0,
    }

# ══════════════════════════════════════════════════════════
# SUBSCRIBERS (sin cambios)
# ══════════════════════════════════════════════════════════
async def get_subscriber(user_id):
    res = await _execute(
        "SELECT user_id, username, status, joined_channel_at, trial_start, subscription_end, last_invoice_sent "
        "FROM subscribers WHERE user_id = ?", [user_id]
    )
    if not res.get("rows"): return None
    r = res["rows"][0]
    return {
        "user_id": r[0], "username": r[1], "status": r[2], "joined_channel_at": r[3],
        "trial_start": r[4], "subscription_end": r[5], "last_invoice_sent": r[6]
    }

async def register_subscriber(user_id, username, joined_channel_at):
    await _execute(
        """INSERT INTO subscribers (user_id, username, status, joined_channel_at)
        VALUES (?, ?, 'pending', ?)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username, joined_channel_at=excluded.joined_channel_at""",
        [user_id, username, joined_channel_at]
    )

async def activate_trial(user_id):
    now = int(time.time())
    await _execute(
        "UPDATE subscribers SET status='trial', trial_start=?, subscription_end=? WHERE user_id=?",
        [now, now + 604800, user_id]
    )

async def activate_paid(user_id):
    now = int(time.time())
    sub = await get_subscriber(user_id)
    new_end = (sub["subscription_end"] + 2592000) if sub and sub.get("subscription_end") and sub["subscription_end"] > now else now + 2592000
    await _execute(
        "UPDATE subscribers SET status='active', subscription_end=? WHERE user_id=?",
        [new_end, user_id]
    )

async def get_pending_activations(hours=24):
    res = await _execute(
        "SELECT user_id, username, joined_channel_at FROM subscribers WHERE status='pending' AND joined_channel_at < ?",
        [int(time.time()) - hours*3600]
    )
    return [{"user_id": r[0], "username": r[1], "joined_channel_at": r[2]} for r in res.get("rows", [])]

async def get_expiring_soon(hours=24):
    now = int(time.time())
    res = await _execute(
        """SELECT user_id, username, subscription_end FROM subscribers
        WHERE status IN ('trial','active') AND subscription_end <= ? AND subscription_end > ?
        AND COALESCE(last_invoice_sent,0) < ?""",
        [now + hours*3600, now, now - 43200]
    )
    return [{"user_id": r[0], "username": r[1], "subscription_end": r[2]} for r in res.get("rows", [])]

async def get_expired():
    res = await _execute(
        "SELECT user_id, username FROM subscribers WHERE status IN ('trial','active') AND subscription_end < ?",
        [int(time.time())]
    )
    return [{"user_id": r[0], "username": r[1]} for r in res.get("rows", [])]

async def mark_invoice_sent(user_id):
    await _execute("UPDATE subscribers SET last_invoice_sent=? WHERE user_id=?", [int(time.time()), user_id])

async def update_subscriber_status(user_id, status):
    await _execute("UPDATE subscribers SET status=? WHERE user_id=?", [status, user_id])

# === v4.0 FIX === Test runner con cierre de sesión
if __name__ == "__main__":
    async def _test():
        print("=" * 60)
        print("TEST DATABASE v5.5 FINAL")
        print("=" * 60)
        await init_tables()
        print("\n✅ Test completado. Cerrando sesión...")
        await close_session()
        print("✅ Sesión cerrada correctamente.")
    
    asyncio.run(_test())