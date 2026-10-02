"""
database.py
Módulo de conexión a Turso usando SQL over HTTP.
v5.4: FASE 3 - Realidad Financiera (fee_percent y net_pnl_percent).
"""
import os
import json
import time
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
TURSO_HTTP_URL = TURSO_URL.replace("libsql://", "https://") if TURSO_URL else ""

# ── FASE 3: Importar costo real de operación ──
from app.config import TOTAL_ROUND_TRIP_COST_PERCENT

def _to_tagged_value(value: Any) -> Dict[str, Any]:
    if value is None: return {"type": "null"}
    elif isinstance(value, bool): return {"type": "integer", "value": "1" if value else "0"}
    elif isinstance(value, int): return {"type": "integer", "value": str(value)}
    elif isinstance(value, float): return {"type": "float", "value": value}
    elif isinstance(value, str): return {"type": "text", "value": value}
    elif isinstance(value, bytes): return {"type": "blob", "base64": value.hex()}
    else: return {"type": "text", "value": str(value)}

def _extract_value(tagged: Any) -> Any:
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

async def _execute(sql: str, args: list = None) -> Dict[str, Any]:
    if not TURSO_HTTP_URL or not TURSO_TOKEN:
        raise ValueError("TURSO_URL y TURSO_TOKEN deben estar configurados")
    
    url = f"{TURSO_HTTP_URL}/v2/pipeline"
    headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [_to_tagged_value(arg) for arg in args]
        
    payload = {"requests": [{"type": "execute", "stmt": stmt}]}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                raise Exception(f"Turso HTTP {resp.status}: {await resp.text()[:200]}")
            data = await resp.json()
            
    results = data.get("results", [])
    if not results: return {"rows": [], "last_insert_rowid": None}
        
    first = results[0]
    if first.get("type") == "error":
        raise Exception(f"Turso SQL error: {first.get('error', {}).get('message', 'Desconocido')}")
        
    result = first.get("response", {}).get("result", first.get("response", {}))
    rows = [[_extract_value(cell) for cell in row] for row in result.get("rows", [])]
    
    return {"rows": rows, "last_insert_rowid": _extract_value(result.get("last_insert_rowid"))}

async def init_tables():
    await _execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT NOT NULL, direction TEXT NOT NULL,
        price_entry REAL NOT NULL, price_exit REAL, status TEXT NOT NULL DEFAULT 'OPEN',
        pnl_percent REAL, opened_at INTEGER NOT NULL, closed_at INTEGER)""")
    
    result = await _execute("PRAGMA table_info(signals)")
    existing_columns = [row[1] for row in result.get("rows", [])]
    
    expected_columns = {"score": "INTEGER", "context_snapshot": "TEXT", "exit_reason": "TEXT", 
                        "regime": "TEXT", "duration_seconds": "INTEGER", "fee_percent": "REAL", "net_pnl_percent": "REAL"}
    
    for col_name, col_type in expected_columns.items():
        if col_name not in existing_columns:
            try:
                await _execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
                print(f"  ✅ Columna agregada a signals: {col_name}")
            except Exception as e:
                print(f"  ⚠️ Warning al agregar columna {col_name}: {e}")
                
    await _execute("CREATE INDEX IF NOT EXISTS idx_signals_coin_status ON signals(coin, status)")
    
    await _execute("""CREATE TABLE IF NOT EXISTS subscribers (
        user_id INTEGER PRIMARY KEY, username TEXT, status TEXT DEFAULT 'pending',
        joined_channel_at INTEGER, trial_start INTEGER, subscription_end INTEGER, last_invoice_sent INTEGER DEFAULT 0)""")
    print("✅ Tablas de Turso inicializadas correctamente.")

async def open_signal(coin: str, direction: str, price_entry: float, score: int = 0, context_snapshot: Dict[str, Any] = None, regime: str = "desconocido") -> int:
    now = int(time.time())
    snapshot_json = json.dumps(context_snapshot, ensure_ascii=False) if context_snapshot else "{}"
    result = await _execute(
        "INSERT INTO signals (coin, direction, price_entry, status, opened_at, score, context_snapshot, regime) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)",
        [coin, direction, price_entry, now, score, snapshot_json, regime]
    )
    print(f"✅ Señal abierta: {coin} {direction} @ {price_entry} | Score: {score}/6 | Régimen: {regime}")
    return result.get("last_insert_rowid")

async def close_signal(coin: str, price_exit: float, exit_reason: str = "NEUTRAL") -> Optional[Dict[str, Any]]:
    now = int(time.time())
    result = await _execute("SELECT id, direction, price_entry, opened_at, score, regime FROM signals WHERE coin = ? AND status = 'OPEN' ORDER BY opened_at DESC LIMIT 1", [coin])
    rows = result.get("rows", [])
    if not rows: return None
        
    row = rows[0]
    signal_id, direction, price_entry, opened_at, score, regime = row[0], row[1], float(row[2]), row[3], row[4], row[5]
    
    pnl_percent = ((price_exit / price_entry) - 1) * 100 if direction == "LONG" else ((price_entry / price_exit) - 1) * 100
    fee_percent = TOTAL_ROUND_TRIP_COST_PERCENT * 100
    net_pnl_percent = pnl_percent - fee_percent
    duration_seconds = now - opened_at
    
    await _execute(
        "UPDATE signals SET status = 'CLOSED', price_exit = ?, pnl_percent = ?, fee_percent = ?, net_pnl_percent = ?, closed_at = ?, exit_reason = ?, duration_seconds = ? WHERE id = ?",
        [price_exit, pnl_percent, fee_percent, net_pnl_percent, now, exit_reason, duration_seconds, signal_id]
    )
    
    print(f"✅ Señal cerrada: {coin} {direction} | Bruto: {pnl_percent:+.2f}% | Neto: {net_pnl_percent:+.2f}% (Fee: {fee_percent:.2f}%) | Motivo: {exit_reason}")
    return {"signal_id": signal_id, "coin": coin, "direction": direction, "price_entry": price_entry, "price_exit": price_exit, "pnl_percent": pnl_percent, "fee_percent": fee_percent, "net_pnl_percent": net_pnl_percent, "duration_seconds": duration_seconds, "score": score, "regime": regime, "exit_reason": exit_reason}

async def get_open_signals() -> List[Dict[str, Any]]:
    result = await _execute("SELECT id, coin, direction, price_entry, opened_at, score, regime FROM signals WHERE status = 'OPEN' ORDER BY opened_at DESC")
    return [{"id": r[0], "coin": r[1], "direction": r[2], "price_entry": float(r[3]), "opened_at": r[4], "score": r[5], "regime": r[6]} for r in result.get("rows", [])]

async def get_stats() -> Dict[str, Any]:
    result_total = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED'")
    total_closed = result_total["rows"][0][0] if result_total["rows"] else 0
    result_winners = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED' AND net_pnl_percent > 0")
    winners = result_winners["rows"][0][0] if result_winners["rows"] else 0
    result_pnl = await _execute("SELECT SUM(net_pnl_percent) FROM signals WHERE status = 'CLOSED'")
    total_pnl = result_pnl["rows"][0][0] if result_pnl["rows"] and result_pnl["rows"][0][0] else 0.0
    win_rate = (winners / total_closed * 100) if total_closed > 0 else 0.0
    return {"total_closed": total_closed, "winners": winners, "losers": total_closed - winners, "win_rate": round(win_rate, 2), "total_pnl": round(total_pnl, 2)}

# (El resto de funciones VIP se mantienen igual, no las modifiqué aquí para ahorrar espacio, pero asegúrate de que estén en tu archivo)