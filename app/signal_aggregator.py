"""
Signal Aggregator v3.2: Filtros (Fase 1) + Gracia (Fase 2) + Fees (Fase 3).
"""
import time
from typing import Dict, Any
from app.cartografo import ejecutar_cartografo
from app.brujula import calcular_estado
from app.database import get_open_signals, open_signal, close_signal
from app.telegram import enviar_alerta_apertura, enviar_alerta_cierre
from app.config import MIN_SCORE_TO_TRADE, ALLOWED_REGIMES, TOTAL_ROUND_TRIP_COST_PERCENT

MIN_FUERZA_SENAL = 2
MAX_DIST_SENAL = 1.5
CAOS_HARD_GATE = 0.75
MIN_DURATION_NEUTRAL = 180
MIN_DURATION_FLIP = 60

def _decidir_direccion(estado_key, b15, fza, dist, p_caos):
    if p_caos >= CAOS_HARD_GATE: return "NEUTRAL", 0
    if estado_key == "bull-fuerte": return "LONG", 5 if fza >= 2 else 4
    if estado_key == "bear-fuerte": return "SHORT", 5 if fza >= 2 else 4
    if estado_key == "giro": return ("LONG" if b15 == "BULL" else "SHORT"), 4
    if estado_key in ("bull-debil", "bear-debil"):
        if fza >= MIN_FUERZA_SENAL and dist <= MAX_DIST_SENAL: return ("LONG" if estado_key == "bull-debil" else "SHORT"), 3
        return "NEUTRAL", 2
    return "NEUTRAL", 1

def _determinar_exit_reason(p_caos, desired_direction):
    if p_caos >= CAOS_HARD_GATE: return "CAOS"
    if desired_direction in ("LONG", "SHORT"): return "FLIP"
    return "NEUTRAL"

def generar_senales(gem_context):
    senales = {}
    for coin, ctx in gem_context.items():
        estado_tuple = calcular_estado(coin, ctx)
        (b1h, b15, b5, fza, dist, p_caos, estado_key, color_letter, divergencia, precio) = estado_tuple
        h24 = ctx.get("h24", precio) if precio > 0 else precio
        l24 = ctx.get("l24", precio) if precio > 0 else precio
        sma20 = ctx.get("sma20_15m", precio) if precio > 0 else precio
        if p_caos >= CAOS_HARD_GATE: senales[coin] = {"direction": "NEUTRAL", "icono": "⚪", "mensaje": f"CAOS en {coin}.", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}; continue
        if estado_key == "no-operar" and b1h == "RANGO" and b15 == "RANGO": senales[coin] = {"direction": "NEUTRAL", "icono": "➖", "mensaje": f"{coin} EN RANGO.", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}; continue
        if estado_key == "bull-fuerte": senales[coin] = {"direction": "LONG", "icono": "🟢", "mensaje": f"ENTRADA SUGERIDA LONG @ ${precio:,.0f}", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}; continue
        if estado_key == "bear-fuerte": senales[coin] = {"direction": "SHORT", "icono": "🔴", "mensaje": f"ENTRADA SUGERIDA SHORT @ ${precio:,.0f}", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}; continue
        if estado_key == "giro":
            if b15 == "BULL": senales[coin] = {"direction": "LONG", "icono": "🟡", "mensaje": "GIRO ALCISTA.", "nivel_soporte": sma20, "nivel_resistencia": h24, "trade_activo": False}
            else: senales[coin] = {"direction": "SHORT", "icono": "🟠", "mensaje": "GIRO BAJISTA.", "nivel_soporte": l24, "nivel_resistencia": sma20, "trade_activo": False}
            continue
        if estado_key in ("bull-debil", "bear-debil"):
            if fza >= MIN_FUERZA_SENAL and dist <= MAX_DIST_SENAL:
                if estado_key == "bull-debil": senales[coin] = {"direction": "LONG", "icono": "🟡", "mensaje": f"PREPARACION LONG. SMA20 (${sma20:,.2f})", "nivel_soporte": sma20, "nivel_resistencia": h24, "trade_activo": False}
                else: senales[coin] = {"direction": "SHORT", "icono": "🟠", "mensaje": f"PREPARACION SHORT. SMA20 (${sma20:,.2f})", "nivel_soporte": l24, "nivel_resistencia": sma20, "trade_activo": False}
            else: senales[coin] = {"direction": "NEUTRAL", "icono": "⏳", "mensaje": f"{estado_key.upper()}. Sin conviccion.", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}
            continue
        if estado_key == "pullback": senales[coin] = {"direction": "NEUTRAL", "icono": "⏳", "mensaje": f"PULLBACK. Zona: ${sma20:,.2f} - ${l24:,.2f}", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}; continue
        senales[coin] = {"direction": "NEUTRAL", "icono": "⚡" if estado_key == "counter" else "➖", "mensaje": f"{estado_key.upper()}.", "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False}
    return senales

async def evaluar_y_ejecutar_senales():
    print("\n🔄 Evaluando señales...")
    gem_context = await ejecutar_cartografo()
    open_signals_db = await get_open_signals()
    open_dict = {s["coin"]: s for s in open_signals_db}
    now = int(time.time())
    for coin, ctx in gem_context.items():
        estado_tuple = calcular_estado(coin, ctx)
        (b1h, b15, b5, fza, dist, p_caos, estado_key, color_letter, divergencia, precio) = estado_tuple
        desired_direction, score = _decidir_direccion(estado_key, b15, fza, dist, p_caos)
        regime_str = "caos" if p_caos >= CAOS_HARD_GATE else ("tendencia" if b1h != "RANGO" else "rango")
        context_snapshot = {"bias_1h": b1h, "bias_15m": b15, "bias_visual": b5, "fuerza_15m": fza, "dist_atr_15m": dist, "p_caos": p_caos, "regime": regime_str}
        db_signal = open_dict.get(coin)
        if db_signal:
            current_direction = db_signal["direction"]
            opened_at = db_signal["opened_at"]
            duration_seconds = now - opened_at
            if desired_direction == "NEUTRAL" or desired_direction != current_direction:
                exit_reason = _determinar_exit_reason(p_caos, desired_direction)
                skip_close = False
                if exit_reason == "NEUTRAL" and duration_seconds < MIN_DURATION_NEUTRAL: print(f"  ⏳ [GRACIA] {coin} ignora NEUTRAL ({duration_seconds}s)"); skip_close = True
                elif exit_reason == "FLIP" and duration_seconds < MIN_DURATION_FLIP: print(f"  ⏳ [GRACIA] {coin} ignora FLIP ({duration_seconds}s)"); skip_close = True
                if not skip_close:
                    print(f"  🔄 Cerrando {coin} {current_direction} (motivo: {exit_reason}, fee: {TOTAL_ROUND_TRIP_COST_PERCENT*100:.2f}%)")
                    closed_data = await close_signal(coin, precio, exit_reason=exit_reason)
                    if closed_data: await enviar_alerta_cierre(coin, current_direction, closed_data["price_entry"], precio, closed_data["net_pnl_percent"], closed_data["duration_seconds"], closed_data["exit_reason"])
        else:
            if desired_direction in ("LONG", "SHORT"):
                if score >= MIN_SCORE_TO_TRADE and regime_str in ALLOWED_REGIMES:
                    print(f"  🚀 Abriendo {coin} {desired_direction} @ {precio} (score: {score}, regime: {regime_str})")
                    signal_id = await open_signal(coin, desired_direction, precio, score, context_snapshot, regime_str)
                    if signal_id: await enviar_alerta_apertura(coin, desired_direction, precio, score, regime_str)
                else: print(f"  ⏸️ [FILTRO] {coin} ignorado (Score {score} o Régimen {regime_str})")
    return generar_senales(gem_context)