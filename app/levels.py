"""
levels.py — Cálculo de zonas operativas sugeridas para las alertas.
v4.0 FINAL: Edge case ATR=0 manejado (dev bug #8).
"""
from typing import Dict, Any, Optional

# Multiplicadores de ATR(15m) — AJUSTABLES
TP1_ATR_MULT = 1.0
TP2_ATR_MULT = 2.0
ENTRY_PULLBACK_ATR = 0.3
INVALIDATION_BUFFER_ATR = 0.3

# === v4.0 FIX === - Edge case: ATR muy bajo o cero
MIN_ATR_THRESHOLD = 1.0  # Mínimo ATR(15m) en USD para considerar señal válida


def calcular_zonas_operativas(
    price: float,
    direction: str,
    atr_15m: float,
    h24: float,
    l24: float,
    sma20: float,
) -> Optional[Dict[str, Any]]:
    """
    Calcula zonas operativas (entry, invalidation, TP1, TP2, R:R).
    Retorna None si los datos son insuficientes o el ATR es muy bajo.
    v4.0 FIX: maneja ATR=0 (dev bug #8 — ZeroDivisionError).
    """
    # === v4.0 FIX === - Validación robusta
    if price <= 0 or atr_15m <= 0:
        return None
    # === v4.0 FIX === - Edge case ATR muy bajo (mercado plano, fin de semana)
    if atr_15m < MIN_ATR_THRESHOLD:
        return None

    if direction == "LONG":
        entry_low = price - (ENTRY_PULLBACK_ATR * atr_15m)
        entry_high = price
        support_candidates = [v for v in [l24, sma20] if 0 < v < price]
        support = max(support_candidates) if support_candidates else price - atr_15m
        invalidation = support - (INVALIDATION_BUFFER_ATR * atr_15m)
        tp1 = entry_high + (TP1_ATR_MULT * atr_15m)
        tp2_candidate = price + (TP2_ATR_MULT * atr_15m)
        tp2 = min(h24, tp2_candidate) if 0 < h24 < tp2_candidate else tp2_candidate
    else:  # SHORT
        entry_low = price
        entry_high = price + (ENTRY_PULLBACK_ATR * atr_15m)
        resistance_candidates = [v for v in [h24, sma20] if v > price]
        resistance = min(resistance_candidates) if resistance_candidates else price + atr_15m
        invalidation = resistance + (INVALIDATION_BUFFER_ATR * atr_15m)
        tp1 = entry_low - (TP1_ATR_MULT * atr_15m)
        tp2_candidate = price - (TP2_ATR_MULT * atr_15m)
        tp2 = max(l24, tp2_candidate) if 0 < l24 > tp2_candidate else tp2_candidate

    # R:R calculation
    if direction == "LONG":
        risk = abs(entry_high - invalidation)
        reward_tp1 = abs(tp1 - entry_high)
        reward_tp2 = abs(tp2 - entry_high)
    else:
        risk = abs(invalidation - entry_low)
        reward_tp1 = abs(entry_low - tp1)
        reward_tp2 = abs(entry_low - tp2)

    # === v4.0 FIX === - Evitar ZeroDivisionError si risk=0
    if risk <= 0:
        return None
    rr_ratio = reward_tp1 / risk

    return {
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "invalidation": round(invalidation, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "risk_pct": round((risk / price) * 100, 2),
        "reward_tp1_pct": round((reward_tp1 / price) * 100, 2),
        "reward_tp2_pct": round((reward_tp2 / price) * 100, 2),
        "rr_ratio": round(rr_ratio, 2),
    }
