"""
database.py
Módulo de conexión a Turso usando SQL over HTTP.
No usa libsql-client (deprecado). Usa aiohttp directamente.
Endpoint: https://<db>.turso.io/v2/pipeline

Tabla 'signals' con campos enriquecidos Tier 1+2:
  - score: calidad de señal (0-6 factores alineados)
  - context_snapshot: JSON con foto completa de factores al abrir
  - exit_reason: motivo del cierre (NEUTRAL, CAOS, FLIP, DIVERGENCE)
  - regime: régimen de mercado al abrir (tendencia, rango, caos)
  - duration_seconds: duración total de la señal
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
    """
    Convierte un valor Python al formato tagged que espera Turso.
    Formato validado con diagnóstico:
      - str   -> {"type": "text",    "value": "BTC"}       (string nativo)
      - float -> {"type": "float",   "value": 83500.0}     (número nativo)
      - int   -> {"type": "integer", "value": "1790632758"} (como string)
      - None  -> {"type": "null"}
    """
    if value is None:
        return {"type": "null"}
    elif isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    elif isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    elif isinstance(value, float):
        return {"type": "float", "value": value}  # NÚMERO NATIVO
    elif isinstance(value, str):
        return {"type": "text", "value": value}
    elif isinstance(value, bytes):
        return {"type": "blob", "base64": value.hex()}
    else:
        return {"type": "text", "value": str(value)}


def _extract_value(tagged: Any) -> Any:
    """
    Extrae el valor Python desde un objeto tagged de Turso.
    Ej: {"type": "integer", "value": "5"} -> 5 (int)
        {"type": "float",   "value": 25.75} -> 25.75
        {"type": "text",    "value": "BTC"} -> "BTC"
    """
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
    """
    Ejecuta una sentencia SQL en Turso via HTTP.
    Retorna: {"rows": [[...], ...], "last_insert_rowid": int|None}
    """
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

    # Estructura real: response.result.{rows, last_insert_rowid}
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
    """
    Crea la tabla 'signals' con todos los campos Tier 1+2.
    Usa PRAGMA table_info para migrar de forma quirúrgica solo las columnas faltantes.
    """
    # 1. Crear tabla base si no existe
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

    # 2. Obtener columnas existentes reales
    result = await _execute("PRAGMA table_info(signals)")
    existing_columns = [row[1] for row in result.get("rows", [])]

    # 3. Definir columnas esperadas y sus tipos
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
                print(f"  ✅ Columna agregada: {col_name}")
            except Exception as e:
                print(f"  ⚠️ Warning al agregar columna {col_name}: {e}")
        else:
            print(f"  ✅ Columna ya existe: {col_name}")

    # 5. Crear índice para búsquedas rápidas
    await _execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_coin_status
        ON signals(coin, status)
    """)

    print("✅ Tablas de Turso inicializadas correctamente (estructura Tier 1+2)")


async def open_signal(
    coin: str,
    direction: str,
    price_entry: float,
    score: int = 0,
    context_snapshot: Dict[str, Any] = None,
    regime: str = "desconocido",
) -> int:
    """
    Guarda una nueva señal abierta en Turso.
    
    Args:
        coin: activo (BTC, ETH, SOL)
        direction: LONG o SHORT
        price_entry: precio al abrir
        score: cuántos de 6 factores alineados (0-6)
        context_snapshot: dict con foto completa de factores
        regime: tendencia, rango o caos
    
    Retorna el ID de la señal creada.
    """
    now = int(time.time())
    snapshot_json = json.dumps(context_snapshot, ensure_ascii=False) if context_snapshot else "{}"

    result = await _execute(
        """
        INSERT INTO signals (
            coin, direction, price_entry, status, opened_at,
            score, context_snapshot, regime
        )
        VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)
        """,
        [coin, direction, price_entry, now, score, snapshot_json, regime]
    )

    signal_id = result.get("last_insert_rowid")
    print(f"✅ Señal abierta: {coin} {direction} @ {price_entry} | Score: {score}/6 | Régimen: {regime} (ID: {signal_id})")
    return signal_id


async def close_signal(
    coin: str,
    price_exit: float,
    exit_reason: str = "NEUTRAL",
) -> Optional[Dict[str, Any]]:
    """
    Cierra la señal abierta más reciente para un coin.
    Calcula PnL y duration_seconds automáticamente.
    
    Args:
        coin: activo
        price_exit: precio al cerrar
        exit_reason: NEUTRAL, CAOS, FLIP o DIVERGENCE
    """
    now = int(time.time())

    # Buscar la señal abierta más reciente
    result = await _execute(
        """
        SELECT id, direction, price_entry, opened_at, score, regime
        FROM signals
        WHERE coin = ? AND status = 'OPEN'
        ORDER BY opened_at DESC
        LIMIT 1
        """,
        [coin]
    )

    rows = result.get("rows", [])
    if not rows:
        return None

    row = rows[0]
    signal_id = row[0]
    direction = row[1]
    price_entry = float(row[2])
    opened_at = row[3]
    score = row[4]
    regime = row[5]

    # Calcular PnL
    if direction == "LONG":
        pnl_percent = ((price_exit / price_entry) - 1) * 100
    else:  # SHORT
        pnl_percent = ((price_entry / price_exit) - 1) * 100

    duration_seconds = now - opened_at

    # Actualizar la señal con todos los campos de cierre
    await _execute(
        """
        UPDATE signals
        SET status = 'CLOSED', price_exit = ?, pnl_percent = ?, closed_at = ?,
            exit_reason = ?, duration_seconds = ?
        WHERE id = ?
        """,
        [price_exit, pnl_percent, now, exit_reason, duration_seconds, signal_id]
    )

    result_data = {
        "signal_id": signal_id,
        "coin": coin,
        "direction": direction,
        "price_entry": price_entry,
        "price_exit": price_exit,
        "pnl_percent": pnl_percent,
        "duration_seconds": duration_seconds,
        "score": score,
        "regime": regime,
        "exit_reason": exit_reason,
    }

    print(f"✅ Señal cerrada: {coin} {direction} | PnL: {pnl_percent:+.2f}% | Motivo: {exit_reason} | Duración: {duration_seconds}s")
    return result_data


async def get_open_signals() -> List[Dict[str, Any]]:
    """Retorna todas las señales actualmente abiertas."""
    result = await _execute(
        """
        SELECT id, coin, direction, price_entry, opened_at, score, regime
        FROM signals
        WHERE status = 'OPEN'
        ORDER BY opened_at DESC
        """
    )

    return [
        {
            "id": row[0],
            "coin": row[1],
            "direction": row[2],
            "price_entry": float(row[3]),
            "opened_at": row[4],
            "score": row[5],
            "regime": row[6],
        }
        for row in result.get("rows", [])
    ]


async def get_last_closed_signal(coin: str) -> Optional[Dict[str, Any]]:
    """Retorna la última señal cerrada de un coin (con todos los campos enriquecidos)."""
    result = await _execute(
        """
        SELECT id, direction, price_entry, price_exit, pnl_percent,
               opened_at, closed_at, score, context_snapshot, exit_reason,
               regime, duration_seconds
        FROM signals
        WHERE coin = ? AND status = 'CLOSED'
        ORDER BY closed_at DESC
        LIMIT 1
        """,
        [coin]
    )

    rows = result.get("rows", [])
    if not rows:
        return None

    row = rows[0]
    
    # Deserializar context_snapshot si existe
    context_snapshot = None
    if row[8]:
        try:
            context_snapshot = json.loads(row[8])
        except (json.JSONDecodeError, TypeError):
            context_snapshot = None

    return {
        "id": row[0],
        "coin": coin,
        "direction": row[1],
        "price_entry": float(row[2]) if row[2] is not None else None,
        "price_exit": float(row[3]) if row[3] is not None else None,
        "pnl_percent": float(row[4]) if row[4] is not None else None,
        "opened_at": row[5],
        "closed_at": row[6],
        "score": row[7],
        "context_snapshot": context_snapshot,
        "exit_reason": row[9],
        "regime": row[10],
        "duration_seconds": row[11],
    }


async def get_stats() -> Dict[str, Any]:
    """Retorna estadísticas generales de las señales (para diagnóstico)."""
    # Total de señales cerradas
    result_total = await _execute(
        "SELECT COUNT(*) FROM signals WHERE status = 'CLOSED'"
    )
    total_closed = result_total["rows"][0][0] if result_total["rows"] else 0

    # Ganadoras vs perdedoras
    result_winners = await _execute(
        "SELECT COUNT(*) FROM signals WHERE status = 'CLOSED' AND pnl_percent > 0"
    )
    winners = result_winners["rows"][0][0] if result_winners["rows"] else 0

    # PnL acumulado
    result_pnl = await _execute(
        "SELECT SUM(pnl_percent) FROM signals WHERE status = 'CLOSED'"
    )
    total_pnl = result_pnl["rows"][0][0] if result_pnl["rows"] and result_pnl["rows"][0][0] else 0.0

    # Win rate
    win_rate = (winners / total_closed * 100) if total_closed > 0 else 0.0

    return {
        "total_closed": total_closed,
        "winners": winners,
        "losers": total_closed - winners,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
    }


async def run_tests():
    """Ejecuta todos los tests de Turso con campos enriquecidos."""
    print("=" * 60)
    print("TEST DE CONEXIÓN A TURSO (Tier 1+2)")
    print("=" * 60)
    print(f"  URL: {TURSO_HTTP_URL}")
    print(f"  Token: ...{TURSO_TOKEN[-6:] if TURSO_TOKEN else 'NO CONFIGURADO'}")
    print()

    # 1. Inicializar tablas (con migración de columnas nuevas)
    print("📝 Paso 1: Creando/migrando tablas...")
    try:
        await init_tables()
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    # 2. Abrir señal con todos los campos enriquecidos
    print("\n📝 Paso 2: Abriendo señal BTC LONG con contexto completo...")
    test_context = {
        "bias_1h": "BULL",
        "bias_15m": "BULL",
        "bias_visual": "BULL",
        "fuerza_15m": 3,
        "dist_atr_15m": 2.1,
        "p_caos": 0.21,
    }
    try:
        signal_id = await open_signal(
            coin="BTC",
            direction="LONG",
            price_entry=83500.0,
            score=5,
            context_snapshot=test_context,
            regime="tendencia",
        )
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    # 3. Cerrar señal con exit_reason
    print("\n📝 Paso 3: Cerrando señal BTC @ $84,200 (motivo: NEUTRAL)...")
    try:
        closed = await close_signal("BTC", 84200.0, exit_reason="NEUTRAL")
        if closed:
            print(f"   ID: {closed['signal_id']}")
            print(f"   Entry: ${closed['price_entry']:,.2f}")
            print(f"   Exit: ${closed['price_exit']:,.2f}")
            print(f"   PnL: {closed['pnl_percent']:+.2f}%")
            print(f"   Score: {closed['score']}/6")
            print(f"   Régimen: {closed['regime']}")
            print(f"   Motivo cierre: {closed['exit_reason']}")
            print(f"   Duración: {closed['duration_seconds']}s")
        else:
            print("   ⚠️ No se encontró señal abierta")
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    # 4. Consultar última señal cerrada (verificar context_snapshot)
    print("\n📝 Paso 4: Verificando última señal cerrada de BTC...")
    try:
        last = await get_last_closed_signal("BTC")
        if last:
            print(f"   PnL: {last['pnl_percent']:+.2f}%")
            print(f"   Score: {last['score']}/6")
            print(f"   Régimen: {last['regime']}")
            print(f"   Exit reason: {last['exit_reason']}")
            print(f"   Duración: {last['duration_seconds']}s")
            if last['context_snapshot']:
                print(f"   Context snapshot: {json.dumps(last['context_snapshot'], ensure_ascii=False)}")
            else:
                print("   ⚠️ Context snapshot vacío")
        else:
            print("   ⚠️ No hay señales cerradas")
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    # 5. Estadísticas generales
    print("\n📝 Paso 5: Estadísticas generales...")
    try:
        stats = await get_stats()
        print(f"   Total señales cerradas: {stats['total_closed']}")
        print(f"   Ganadoras: {stats['winners']} | Perdedoras: {stats['losers']}")
        print(f"   Win rate: {stats['win_rate']}%")
        print(f"   PnL acumulado: {stats['total_pnl']:+.2f}%")
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    print("\n" + "=" * 60)
    print("✅ Todos los tests pasaron")
    print("=" * 60)
    return True


if __name__ == "__main__":
    asyncio.run(run_tests())