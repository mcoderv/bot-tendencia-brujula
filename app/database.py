"""
database.py v5.4: FASE 3 - Realidad Financiera + VIP Completo.
"""
import os, json, time, asyncio, aiohttp
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from app.config import TOTAL_ROUND_TRIP_COST_PERCENT

load_dotenv()
TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
TURSO_HTTP_URL = TURSO_URL.replace("libsql://", "https://") if TURSO_URL else ""

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
        except: return None
    elif t == "float":
        try: return float(v) if v is not None else None
        except: return None
    elif t == "null": return None
    else: return v

async def _execute(sql, args=None):
    if not TURSO_HTTP_URL or not TURSO_TOKEN: raise ValueError("TURSO no configurado")
    url = f"{TURSO_HTTP_URL}/v2/pipeline"
    headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}
    stmt = {"sql": sql}
    if args: stmt["args"] = [_to_tagged_value(arg) for arg in args]
    payload = {"requests": [{"type": "execute", "stmt": stmt}]}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200: raise Exception(f"Turso HTTP {resp.status}")
            data = await resp.json()
    results = data.get("results", [])
    if not results: return {"rows": [], "last_insert_rowid": None}
    first = results[0]
    if first.get("type") == "error": raise Exception(f"Turso SQL error")
    result = first.get("response", {}).get("result", first.get("response", {}))
    rows = [[_extract_value(cell) for cell in row] for row in result.get("rows", [])]
    return {"rows": rows, "last_insert_rowid": _extract_value(result.get("last_insert_rowid"))}

async def init_tables():
    await _execute("CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, direction TEXT, price_entry REAL, price_exit REAL, status TEXT DEFAULT 'OPEN', pnl_percent REAL, opened_at INTEGER, closed_at INTEGER)")
    result = await _execute("PRAGMA table_info(signals)")
    existing = [row[1] for row in result.get("rows", [])]
    for col, typ in {"score": "INTEGER", "context_snapshot": "TEXT", "exit_reason": "TEXT", "regime": "TEXT", "duration_seconds": "INTEGER", "fee_percent": "REAL", "net_pnl_percent": "REAL"}.items():
        if col not in existing: await _execute(f"ALTER TABLE signals ADD COLUMN {col} {typ}")
    await _execute("CREATE INDEX IF NOT EXISTS idx_signals_coin_status ON signals(coin, status)")
    await _execute("CREATE TABLE IF NOT EXISTS subscribers (user_id INTEGER PRIMARY KEY, username TEXT, status TEXT DEFAULT 'pending', joined_channel_at INTEGER, trial_start INTEGER, subscription_end INTEGER, last_invoice_sent INTEGER DEFAULT 0)")

async def open_signal(coin, direction, price_entry, score=0, context_snapshot=None, regime="desconocido"):
    now = int(time.time())
    snap = json.dumps(context_snapshot) if context_snapshot else "{}"
    res = await _execute("INSERT INTO signals (coin, direction, price_entry, status, opened_at, score, context_snapshot, regime) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)", [coin, direction, price_entry, now, score, snap, regime])
    return res.get("last_insert_rowid")

async def close_signal(coin, price_exit, exit_reason="NEUTRAL"):
    now = int(time.time())
    res = await _execute("SELECT id, direction, price_entry, opened_at, score, regime FROM signals WHERE coin = ? AND status = 'OPEN' ORDER BY opened_at DESC LIMIT 1", [coin])
    if not res.get("rows"): return None
    row = res["rows"][0]
    sig_id, direction, p_entry, opened, score, regime = row[0], row[1], float(row[2]), row[3], row[4], row[5]
    pnl = ((price_exit / p_entry) - 1) * 100 if direction == "LONG" else ((p_entry / price_exit) - 1) * 100
    fee = TOTAL_ROUND_TRIP_COST_PERCENT * 100
    net = pnl - fee
    dur = now - opened
    await _execute("UPDATE signals SET status='CLOSED', price_exit=?, pnl_percent=?, fee_percent=?, net_pnl_percent=?, closed_at=?, exit_reason=?, duration_seconds=? WHERE id=?", [price_exit, pnl, fee, net, now, exit_reason, dur, sig_id])
    return {"signal_id": sig_id, "coin": coin, "direction": direction, "price_entry": p_entry, "price_exit": price_exit, "pnl_percent": pnl, "fee_percent": fee, "net_pnl_percent": net, "duration_seconds": dur, "score": score, "regime": regime, "exit_reason": exit_reason}

async def get_open_signals():
    res = await _execute("SELECT id, coin, direction, price_entry, opened_at, score, regime FROM signals WHERE status = 'OPEN'")
    return [{"id": r[0], "coin": r[1], "direction": r[2], "price_entry": float(r[3]), "opened_at": r[4], "score": r[5], "regime": r[6]} for r in res.get("rows", [])]

async def get_stats():
    tot = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED'")
    tc = tot["rows"][0][0] if tot["rows"] else 0
    win = await _execute("SELECT COUNT(*) FROM signals WHERE status = 'CLOSED' AND net_pnl_percent > 0")
    w = win["rows"][0][0] if win["rows"] else 0
    pnl = await _execute("SELECT SUM(net_pnl_percent) FROM signals WHERE status = 'CLOSED'")
    tp = pnl["rows"][0][0] if pnl["rows"] and pnl["rows"][0][0] else 0.0
    return {"total_closed": tc, "winners": w, "losers": tc - w, "win_rate": round((w/tc*100) if tc>0 else 0, 2), "total_pnl": round(tp, 2)}

# --- FUNCIONES VIP ---
async def get_subscriber(user_id):
    res = await _execute("SELECT user_id, username, status, joined_channel_at, trial_start, subscription_end, last_invoice_sent FROM subscribers WHERE user_id = ?", [user_id])
    if not res.get("rows"): return None
    r = res["rows"][0]
    return {"user_id": r[0], "username": r[1], "status": r[2], "joined_channel_at": r[3], "trial_start": r[4], "subscription_end": r[5], "last_invoice_sent": r[6]}

async def register_subscriber(user_id, username, joined_channel_at):
    await _execute("INSERT INTO subscribers (user_id, username, status, joined_channel_at) VALUES (?, ?, 'pending', ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, joined_channel_at=excluded.joined_channel_at", [user_id, username, joined_channel_at])

async def activate_trial(user_id):
    now = int(time.time())
    await _execute("UPDATE subscribers SET status='trial', trial_start=?, subscription_end=? WHERE user_id=?", [now, now + 604800, user_id])

async def activate_paid(user_id):
    now = int(time.time())
    sub = await get_subscriber(user_id)
    new_end = (sub["subscription_end"] + 2592000) if sub and sub.get("subscription_end") and sub["subscription_end"] > now else now + 2592000
    await _execute("UPDATE subscribers SET status='active', subscription_end=? WHERE user_id=?", [new_end, user_id])

async def get_pending_activations(hours=24):
    res = await _execute("SELECT user_id, username, joined_channel_at FROM subscribers WHERE status='pending' AND joined_channel_at < ?", [int(time.time()) - hours*3600])
    return [{"user_id": r[0], "username": r[1], "joined_channel_at": r[2]} for r in res.get("rows", [])]

async def get_expiring_soon(hours=24):
    now = int(time.time())
    res = await _execute("SELECT user_id, username, subscription_end FROM subscribers WHERE status IN ('trial','active') AND subscription_end <= ? AND subscription_end > ? AND COALESCE(last_invoice_sent,0) < ?", [now + hours*3600, now, now - 43200])
    return [{"user_id": r[0], "username": r[1], "subscription_end": r[2]} for r in res.get("rows", [])]

async def get_expired():
    res = await _execute("SELECT user_id, username FROM subscribers WHERE status IN ('trial','active') AND subscription_end < ?", [int(time.time())])
    return [{"user_id": r[0], "username": r[1]} for r in res.get("rows", [])]

async def mark_invoice_sent(user_id):
    await _execute("UPDATE subscribers SET last_invoice_sent=? WHERE user_id=?", [int(time.time()), user_id])

async def update_subscriber_status(user_id, status):
    await _execute("UPDATE subscribers SET status=? WHERE user_id=?", [status, user_id])