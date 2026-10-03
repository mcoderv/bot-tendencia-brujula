"""
Cartógrafo simplificado para Bot Tendencia.
v4.9 FINAL: Funding rates + CVD multi-TF + atr_15m expuesto.
FIX: typos de sintaxis corregidos (len, total, isinstance).
"""
import asyncio
import aiohttp
import time
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from app.config import ASSETS, HL_REST_URL

# Parámetros del Cartógrafo
MACRO_LOOKBACK_DAYS = 30
REST_API_TIMEOUT = 10
SMA_TREND_PERIOD = 50
BREAKOUT_LOOKBACK = 10
MIN_CANDLES_1H = 20
MIN_CANDLES_15M = 30
MIN_CANDLES_5M = 200
STRONG_BIAS_THRESHOLD = 2


# ══════════════════════════════════════════════════════════
# FETCH SOLO PRECIOS
# ══════════════════════════════════════════════════════════
async def _fetch_last_price(session: aiohttp.ClientSession, coin: str) -> tuple:
    """Fetch de la última vela de 5m. Retorna (precio, error)."""
    st_time = int((time.time() - 900) * 1000)
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "5m", "startTime": st_time},
    }
    try:
        async with session.post(
            HL_REST_URL, json=payload,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            data = await resp.json()
            # FIX: "le n(data)" → "len(data)"
            if isinstance(data, list) and len(data) > 0:
                last_price = float(data[-1].get("c", 0))
                return (last_price, None)
            return (0.0, "Sin datos")
    except asyncio.TimeoutError:
        return (0.0, "Timeout (5s)")
    except Exception as e:
        return (0.0, f"{type(e).__name__}: {str(e)[:80]}")


async def fetch_precios_rapidos() -> Dict[str, Dict[str, Any]]:
    """Fetch ligero: último precio de cada activo en paralelo."""
    precios = {}
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_last_price(session, coin) for coin in ASSETS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, coin in enumerate(ASSETS):
            result = results[i]
            if isinstance(result, Exception):
                precios[coin] = {"precio": 0.0, "error": str(result)}
            else:
                precio, error = result
                precios[coin] = {"precio": precio, "error": error}
    return precios


# ══════════════════════════════════════════════════════════
# FUNDING RATES
# ══════════════════════════════════════════════════════════
async def fetch_funding_rates() -> Dict[str, float]:
    """
    Fetch de funding rates actuales desde Hyperliquid.
    1 sola request para todos los activos. ~100ms.
    """
    payload = {"type": "metaAndAssetCtxs"}
    funding = {coin: 0.0 for coin in ASSETS}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                HL_REST_URL, json=payload,
                # FIX: "to tal=5" → "total=5"
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                if isinstance(data, list) and len(data) > 1:
                    asset_ctxs = data[1]
                    for ctx in asset_ctxs:
                        coin = ctx.get("coin", "")
                        if coin in funding:
                            raw_funding = ctx.get("funding", 0) or 0
                            funding[coin] = float(raw_funding) * 100
    except Exception as e:
        print(f"  WARNING fetch_funding_rates: {e}")
    return funding


# ══════════════════════════════════════════════════════════
# FETCH DE VELAS
# ══════════════════════════════════════════════════════════
async def fetch_candles(
    session: aiohttp.ClientSession,
    coin: str,
    interval: str,
    lookback_days: int = 30
) -> Optional[pd.DataFrame]:
    """Fetch de velas desde Hyperliquid REST API."""
    st_time = int((time.time() - 86400 * lookback_days) * 1000)
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": st_time},
    }
    try:
        async with session.post(
            HL_REST_URL, json=payload,
            timeout=aiohttp.ClientTimeout(total=REST_API_TIMEOUT),
        ) as resp:
            data = await resp.json()
            # FIX: "isinstan ce" → "isinstance"
            if not isinstance(data, list) or len(data) < 10:
                return None
            df = pd.DataFrame(data)
            for c in ["t", "o", "h", "l", "c", "v"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["c"])
            if len(df) < 10:
                return None
            return df
    except Exception as e:
        print(f"  WARNING fetch_candles({coin}, {interval}): {e}")
        return None


def calc_bias_1h(df: pd.DataFrame) -> str:
    """Calcula bias de 1H usando SMA + breakout."""
    if df is None or len(df) < MIN_CANDLES_1H:
        return "RANGO"
    last = float(df["c"].iloc[-1])
    w = min(SMA_TREND_PERIOD, len(df))
    sma = float(df["c"].rolling(w).mean().iloc[-1])
    fb = bool(df["l"].iloc[-1] > df["h"].iloc[-3]) if len(df) >= 3 else False
    fe = bool(df["h"].iloc[-1] < df["l"].iloc[-3]) if len(df) >= 3 else False
    if last > sma and fb:
        return "BULL"
    if last < sma and fe:
        return "BEAR"
    bw = min(BREAKOUT_LOOKBACK, len(df) - 1)
    if bw > 0:
        if last > df["h"].rolling(bw).max().iloc[-2] and last > sma:
            return "BULL"
        if last < df["l"].rolling(bw).min().iloc[-2] and last < sma:
            return "BEAR"
    return "RANGO"


def calc_15m_data(df: pd.DataFrame) -> Dict[str, Any]:
    """Calcula bias, fuerza, distancia ATR, SMA20 y ATR en 15m."""
    default = {
        "bias_15m": "RANGO", "fuerza_15m": 0,
        "dist_atr_15m": 0.0, "sma20_15m": 0.0, "atr_15m": 0.0,
    }
    if df is None or len(df) < MIN_CANDLES_15M:
        return default
    last = float(df["c"].iloc[-1])
    w20 = min(20, len(df))
    w50 = min(50, len(df))
    sma20 = float(df["c"].rolling(w20).mean().iloc[-1])
    sma50 = float(df["c"].rolling(w50).mean().iloc[-1])
    df = df.copy()
    df["tr"] = np.maximum(
        df["h"] - df["l"],
        np.maximum(
            abs(df["h"] - df["c"].shift(1)),
            abs(df["l"] - df["c"].shift(1)),
        ),
    )
    atr = float(df["tr"].rolling(14).mean().iloc[-1]) if len(df) >= 14 else last * 0.01
    if atr <= 0 or not np.isfinite(atr):
        atr = last * 0.01
    bias = "RANGO"
    if last > sma20 and sma20 > sma50:
        bias = "BULL"
    elif last < sma20 and sma20 < sma50:
        bias = "BEAR"
    dist_atr = abs(last - sma20) / atr if atr > 0 else 0.0
    alineado = (bias == "BULL" and sma20 > sma50) or (bias == "BEAR" and sma20 < sma50)
    roc = 0.0
    if len(df) >= 5:
        prev_c = float(df["c"].iloc[-5])
        if prev_c > 0:
            roc = ((last / prev_c) - 1) * 100
    fuerza = 0
    if bias == "BULL":
        if dist_atr >= 2.0 and alineado and roc > 0.3:
            fuerza = 3
        elif dist_atr >= 1.0 or (alineado and roc > 0.1):
            fuerza = 2
        elif dist_atr >= 0.3 or roc > 0:
            fuerza = 1
    elif bias == "BEAR":
        if dist_atr >= 2.0 and alineado and roc < -0.3:
            fuerza = 3
        elif dist_atr >= 1.0 or (alineado and roc < -0.1):
            fuerza = 2
        elif dist_atr >= 0.3 or roc < 0:
            fuerza = 1
    return {
        "bias_15m": bias,
        "fuerza_15m": fuerza,
        "dist_atr_15m": round(dist_atr, 2),
        "sma20_15m": round(sma20, 6),
        "atr_15m": round(atr, 6),
    }


def calc_h24_l24(df_1h: pd.DataFrame) -> tuple:
    """Calcula el máximo y mínimo de las últimas 24 horas."""
    if df_1h is None or len(df_1h) == 0:
        return (0.0, 0.0)
    n = min(24, len(df_1h))
    last_24h = df_1h.tail(n)
    h24 = float(last_24h["h"].max())
    l24 = float(last_24h["l"].min())
    return (h24, l24)


# === v4.0 === CVD multi-TF
def calc_cvd(df: pd.DataFrame, lookback: int = 18) -> float:
    """Calcula Cumulative Volume Delta normalizado en [-1, 1]."""
    if df is None or len(df) < lookback:
        return 0.0
    delta = np.where(df["c"] >= df["o"], df["v"], -df["v"])
    cvd_raw = float(np.sum(delta[-lookback:]))
    vol_sum = float(np.sum(df["v"].iloc[-lookback:]))
    if vol_sum <= 0:
        return 0.0
    cvd = cvd_raw / vol_sum
    return max(-1.0, min(1.0, cvd))


def calc_bias_visual(df: pd.DataFrame) -> str:
    """Bias visual desde velas 5m con CVD."""
    if df is None or len(df) < MIN_CANDLES_5M:
        return "RANGO"
    df = df.copy()
    last = float(df["c"].iloc[-1])
    w20 = min(20, len(df))
    w50 = min(50, len(df))
    sma20 = float(df["c"].rolling(w20).mean().iloc[-1])
    sma50 = float(df["c"].rolling(w50).mean().iloc[-1])
    poc = float(df["c"].iloc[df["v"].idxmax()])
    poc_score = 1 if last > poc else -1
    h24 = float(df["h"].max())
    l24 = float(df["l"].min())
    rango = h24 - l24
    if rango > 0:
        tsup = h24 - (rango / 3)
        tinf = l24 + (rango / 3)
        if last >= tsup:
            caja = 1
        elif last <= tinf:
            caja = -1
        else:
            caja = 0
    else:
        caja = 0
    cvd = calc_cvd(df, lookback=18)
    rs = 2 if cvd > 0.3 else (1 if cvd > 0.1 else (-2 if cvd < -0.3 else (-1 if cvd < -0.1 else 0)))
    macro_score = poc_score + caja + rs
    if abs(macro_score) >= STRONG_BIAS_THRESHOLD and rs == 0:
        return "RANGO"
    elif macro_score >= STRONG_BIAS_THRESHOLD:
        return "BULL"
    elif macro_score <= -STRONG_BIAS_THRESHOLD:
        return "BEAR"
    return "RANGO"


def estimar_regimen_markov(df_1h: pd.DataFrame) -> Dict[str, Any]:
    """Estimación de régimen caótico basada en volatilidad."""
    try:
        if df_1h is None or len(df_1h) < 60:
            return {"p_caos": 0.5, "estado_actual": 0}
        closes = pd.to_numeric(df_1h["c"], errors="coerce").dropna()
        if len(closes) < 60:
            return {"p_caos": 0.5, "estado_actual": 0}
        vol = closes.pct_change().dropna().abs()
        if len(vol) < 60:
            return {"p_caos": 0.5, "estado_actual": 0}
        thr = vol.quantile(0.75)
        states = (vol > thr).astype(int).values
        counts = np.zeros((2, 2))
        for i in range(len(states) - 1):
            counts[states[i], states[i + 1]] += 1
        prior = np.array([[0.95, 0.05], [0.10, 0.90]]) * 10
        matriz = counts + prior
        matriz = matriz / matriz.sum(axis=1, keepdims=True)
        estado = int(states[-1])
        p_caos = round(float(matriz[estado, 1]), 4)
        return {
            "p_caos": p_caos, "estado_actual": estado, "n_muestras": int(len(states)),
        }
    except Exception:
        return {"p_caos": 0.5, "estado_actual": 0}


async def ejecutar_cartografo() -> Dict[str, Dict[str, Any]]:
    """Análisis macro completo + funding rates + atr_15m."""
    gem_context: Dict[str, Dict[str, Any]] = {}
    async with aiohttp.ClientSession() as session:
        funding_task = fetch_funding_rates()
        tasks = {}
        for coin in ASSETS:
            tasks[coin] = {
                "1h": fetch_candles(session, coin, "1h", MACRO_LOOKBACK_DAYS),
                "15m": fetch_candles(session, coin, "15m", min(MACRO_LOOKBACK_DAYS, 7)),
                "5m": fetch_candles(session, coin, "5m", min(MACRO_LOOKBACK_DAYS, 3)),
            }
        funding_rates = await funding_task
        for coin in ASSETS:
            try:
                df_1h, df_15m, df_5m = await asyncio.gather(
                    tasks[coin]["1h"], tasks[coin]["15m"], tasks[coin]["5m"],
                    return_exceptions=True,
                )
                if isinstance(df_1h, Exception): df_1h = None
                if isinstance(df_15m, Exception): df_15m = None
                if isinstance(df_5m, Exception): df_5m = None
                bias_1h = calc_bias_1h(df_1h)
                data_15m = calc_15m_data(df_15m)
                bias_visual = calc_bias_visual(df_5m)
                regimen = estimar_regimen_markov(df_1h)
                h24, l24 = calc_h24_l24(df_1h)
                precio = 0.0
                if df_5m is not None and len(df_5m) > 0:
                    precio = float(df_5m["c"].iloc[-1])
                elif df_15m is not None and len(df_15m) > 0:
                    precio = float(df_15m["c"].iloc[-1])
                gem_context[coin] = {
                    "bias_1h": bias_1h,
                    "bias_15m": data_15m["bias_15m"],
                    "bias_visual": bias_visual,
                    "fuerza_15m": data_15m["fuerza_15m"],
                    "dist_atr_15m": data_15m["dist_atr_15m"],
                    "sma20_15m": data_15m["sma20_15m"],
                    "atr_15m": data_15m["atr_15m"],
                    "h24": h24,
                    "l24": l24,
                    "regimen": regimen,
                    "precio_ejecucion": precio,
                    "funding_rate": funding_rates.get(coin, 0.0),
                    "timestamp": int(time.time()),
                }
            except Exception as e:
                print(f"  WARNING Error procesando {coin}: {e}")
                gem_context[coin] = {
                    "bias_1h": "RANGO", "bias_15m": "RANGO", "bias_visual": "RANGO",
                    "fuerza_15m": 0, "dist_atr_15m": 0.0, "sma20_15m": 0.0,
                    "atr_15m": 0.0, "h24": 0.0, "l24": 0.0,
                    "regimen": {"p_caos": 0.5, "estado_actual": 0},
                    "precio_ejecucion": 0.0, "funding_rate": 0.0,
                    "timestamp": int(time.time()),
                }
    return gem_context


if __name__ == "__main__":
    print("=" * 60)
    print("CARTOGRAFO v4.9 FINAL (typos corregidos)")
    print("=" * 60)
    print(f"   Activos: {ASSETS}")
    print(f"   API: {HL_REST_URL}")
    print()
    print("🔍 Test fetch_precios_rapidos...")
    precios = asyncio.run(fetch_precios_rapidos())
    for coin, data in precios.items():
        if data["error"]:
            print(f"  {coin}: ERROR - {data['error']}")
        else:
            print(f"  {coin}: ${data['precio']:,.2f}")
    print()
    print("🔍 Test fetch_funding_rates...")
    funding = asyncio.run(fetch_funding_rates())
    for coin, fr in funding.items():
        print(f"  {coin}: {fr:+.4f}%")
    print()
    print("🔍 Test ejecutar_cartografo...")
    result = asyncio.run(ejecutar_cartografo())
    for coin, ctx in result.items():
        regimen = ctx.get("regimen", {})
        print(f"  {coin}:")
        print(f"    1H: {ctx['bias_1h']}")
        print(f"    15m: {ctx['bias_15m']} | FZA: {ctx['fuerza_15m']}/3 | DIST: {ctx['dist_atr_15m']}x")
        print(f"    ATR(15m): ${ctx['atr_15m']:,.2f}")
        print(f"    h24: ${ctx['h24']:,.2f} | l24: ${ctx['l24']:,.2f}")
        print(f"    5m: {ctx['bias_visual']}")
        print(f"    CAOS: {regimen.get('p_caos', 0):.2f}")
        print(f"    Funding: {ctx.get('funding_rate', 0):+.4f}%")
        print(f"    Precio: ${ctx['precio_ejecucion']:,.2f}")
        print()
    print("=" * 60)