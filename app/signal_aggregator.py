"""
Signal Aggregator v3.3 FINAL: Zonas + MFE + Invalidación + Funding.
FIX: MFE se persiste en DB con update_mfe().
FIX: Bug #1, #2, #3, #7 aplicados.
"""
import time
from typing import Dict, Any
from app.cartografo import ejecutar_cartografo
from app.brujula import calcular_estado
# FIX: agregar update_mfe al import
from app.database import get_open_signals, open_signal, close_signal, mark_invalidation_warned, update_mfe
from app.telegram import enviar_alerta_apertura, enviar_alerta_cierre, enviar_alerta_invalidation_approach
from app.config import (
    MIN_SCORE_TO_TRADE, ALLOWED_REGIMES, TOTAL_ROUND_TRIP_COST_PERCENT,
    FUNDING_EXTREME, INVALIDATION_WARN_DIST, MIN_RR_RATIO, INVALIDATION_COOLDOWN,
)

MIN_FUERZA_SENAL = 2
MAX_DIST_SENAL = 1.5
CAOS_HARD_GATE = 0.75
MIN_DURATION_NEUTRAL = 180
MIN_DURATION_FLIP = 60

def _decidir_direccion(estado_key, b15, fza, dist, p_caos):
    """Retorna (direction, score) con escala 0-6."""
    if p_caos >= CAOS_HARD_GATE: return "NEUTRAL", 0
    if estado_key == "bull-fuerte": return "LONG", 6 if fza >= 2 else 4
    if estado_key == "bear-fuerte": return "SHORT", 6 if fza >= 2 else 4
    if estado_key == "giro": return ("LONG" if b15 == "BULL" else "SHORT"), 5
    if estado_key in ("bull-debil", "bear-debil"):
        if fza >= MIN_FUERZA_SENAL and dist <= MAX_DIST_SENAL:
            return ("LONG" if estado_key == "bull-debil" else "SHORT"), 3
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

# === v4.0 FIX === Bug #1, #2, #3, #7 + MFE persistido
async def evaluar_y_ejecutar_senales():
    """Ciclo completo con todos los fixes aplicados."""
    print("\n🔄 Evaluando señales...")
    gem_context = await ejecutar_cartografo()
    open_signals_db = await get_open_signals()
    open_dict = {s["coin"]: s for s in open_signals_db}
    now = int(time.time())
    for coin, ctx in gem_context.items():
        estado_tuple = calcular_estado(coin, ctx)
        (b1h, b15, b5, fza, dist, p_caos, estado_key, color_letter, divergencia, precio) = estado_tuple
        desired_direction, score = _decidir_direccion(estado_key, b15, fza, dist, p_caos)
        # FIX Bug #3: funding_rate con or 0.0 para evitar None
        funding_rate = ctx.get("funding_rate", 0.0) or 0.0
        regime_str = "caos" if p_caos >= CAOS_HARD_GATE else ("tendencia" if b1h != "RANGO" else "rango")
        context_snapshot = {
            "bias_1h": b1h, "bias_15m": b15, "bias_visual": b5,
            "fuerza_15m": fza, "dist_atr_15m": dist, "p_caos": p_caos,
            "regime": regime_str, "funding_rate": funding_rate,
        }
        db_signal = open_dict.get(coin)
        if db_signal:
            current_direction = db_signal["direction"]
            opened_at = db_signal["opened_at"]
            price_entry = db_signal["price_entry"]
            duration_seconds = now - opened_at
            # FIX Bug #1: MFE verificado para LONG y SHORT
            if current_direction == "LONG":
                mfe = ((precio / price_entry) - 1) * 100 if price_entry > 0 else 0.0
            else:  # SHORT
                mfe = ((price_entry / precio) - 1) * 100 if precio > 0 else 0.0
            # FIX: Persistir MFE en DB (antes se calculaba pero no se guardaba)
            await update_mfe(coin, mfe)
            # FIX Bug #7: invalidation_warned_at (timestamp) + cooldown
            invalidation = db_signal.get("invalidation")
            invalidation_warned_at = db_signal.get("invalidation_warned_at", 0) or 0
            if invalidation and invalidation > 0:
                dist_to_inv = abs(precio - invalidation) / precio * 100 if precio > 0 else 0
                time_since_warn = now - invalidation_warned_at if invalidation_warned_at else 999999
                if dist_to_inv < INVALIDATION_WARN_DIST and time_since_warn > INVALIDATION_COOLDOWN:
                    print(f"  ⚠️ [INVALIDATION] {coin} {current_direction} a {dist_to_inv:.2f}% de invalidación")
                    await enviar_alerta_invalidation_approach(coin, current_direction, precio, invalidation)
                    await mark_invalidation_warned(db_signal["id"])
            # Chequear cambio de bias (cierre)
            if desired_direction == "NEUTRAL" or desired_direction != current_direction:
                exit_reason = _determinar_exit_reason(p_caos, desired_direction)
                skip_close = False
                if exit_reason == "NEUTRAL" and duration_seconds < MIN_DURATION_NEUTRAL:
                    print(f"  ⏳ [GRACIA] {coin} ignora NEUTRAL ({duration_seconds}s)"); skip_close = True
                elif exit_reason == "FLIP" and duration_seconds < MIN_DURATION_FLIP:
                    print(f"  ⏳ [GRACIA] {coin} ignora FLIP ({duration_seconds}s)"); skip_close = True
                if not skip_close:
                    print(f"  🔄 Cerrando {coin} {current_direction} (motivo: {exit_reason}, fee: {TOTAL_ROUND_TRIP_COST_PERCENT*100:.2f}%)")
                    closed_data = await close_signal(coin, precio, exit_reason=exit_reason)
                    if closed_data:
                        await enviar_alerta_cierre(
                            coin, current_direction,
                            closed_data["price_entry"], precio,
                            closed_data["net_pnl_percent"],
                            closed_data["duration_seconds"],
                            closed_data["exit_reason"],
                            fee_percent=closed_data.get("fee_percent", 0.12),
                            mfe_percent=mfe,
                        )
        else:
            # FIX Bug #2: check explícito de zonas None
            if desired_direction in ("LONG", "SHORT"):
                if score >= MIN_SCORE_TO_TRADE and regime_str in ALLOWED_REGIMES:
                    # Filtro de funding rate extremo
                    if abs(funding_rate) > FUNDING_EXTREME:
                        print(f"  ⏸️ [FUNDING] {coin} ignorado: funding {funding_rate:+.3f}% extremo")
                        continue
                    # Calcular zonas operativas
                    from app.levels import calcular_zonas_operativas
                    atr_15m = ctx.get("atr_15m", 0.0) or 0.0
                    h24 = ctx.get("h24", 0.0) or 0.0
                    l24 = ctx.get("l24", 0.0) or 0.0
                    sma20 = ctx.get("sma20_15m", 0.0) or 0.0
                    zonas = calcular_zonas_operativas(precio, desired_direction, atr_15m, h24, l24, sma20)
                    # FIX Bug #2: check explícito None
                    if zonas is None:
                        print(f"  ⏸️ [ZONAS] {coin} descartado: no se pudieron calcular zonas (ATR bajo o datos insuficientes)")
                        continue
                    if zonas.get("rr_ratio", 0) < MIN_RR_RATIO:
                        print(f"  ⏸️ [R:R] {coin} descartado: R:R {zonas.get('rr_ratio', 0):.2f} < {MIN_RR_RATIO}")
                        continue
                    setup_valid_until = now + 4 * 3600
                    signal_id = await open_signal(
                        coin, desired_direction, precio, score, context_snapshot, regime_str,
                        invalidation=zonas.get("invalidation")
                    )
                    if signal_id:
                        await enviar_alerta_apertura(
                            coin, desired_direction, precio, score, regime_str,
                            zonas=zonas, setup_valid_until=setup_valid_until,
                            funding_rate=funding_rate
                        )
                else:
                    print(f"  ⏸️ [FILTRO] {coin} ignorado (Score {score} o Régimen {regime_str})")
    return generar_senales(gem_context)

if __name__ == "__main__":
    import asyncio
    print("=" * 60)
    print("TEST SIGNAL AGGREGATOR v3.3 FINAL (MFE persistido)")
    print("=" * 60)
    async def test():
        senales = await evaluar_y_ejecutar_senales()
        print("\n" + "=" * 60)
        print("SEÑALES PARA EL PANEL WEB:")
        print("=" * 60)
        for coin, s in senales.items():
            print(f"  {coin:5s} → {s['direction']:7s} {s['icono']} | {s['mensaje']}")
    asyncio.run(test())