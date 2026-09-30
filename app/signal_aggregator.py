"""
Signal Aggregator - Orquesta señales con Turso + Telegram.
LONG / SHORT / NEUTRAL con persistencia y alertas.

v2.2: Escenarios de Telegram confirmados:
  - FLIP solo cierra (no abre nueva señal inmediatamente)
  - exit_reason distingue CAOS / FLIP / NEUTRAL
  - Retorna formato compatible con el panel web de la brújula
"""
from typing import Dict, Any
from app.cartografo import ejecutar_cartografo
from app.brujula import calcular_estado
from app.database import get_open_signals, open_signal, close_signal
from app.telegram import enviar_alerta_apertura, enviar_alerta_cierre

# ── Umbrales para señales ──
MIN_FUERZA_SENAL = 2
MAX_DIST_SENAL = 1.5
CAOS_HARD_GATE = 0.75


def _decidir_direccion(estado_key: str, b15: str, fza: int, dist: float, p_caos: float) -> tuple:
    """
    Determina la dirección deseada (LONG/SHORT/NEUTRAL) y el score (0-6).
    Retorna (direction, score).
    """
    if p_caos >= CAOS_HARD_GATE:
        return "NEUTRAL", 0

    if estado_key == "bull-fuerte":
        return "LONG", 5 if fza >= 2 else 4

    if estado_key == "bear-fuerte":
        return "SHORT", 5 if fza >= 2 else 4

    if estado_key == "giro":
        return ("LONG" if b15 == "BULL" else "SHORT"), 4

    if estado_key in ("bull-debil", "bear-debil"):
        if fza >= MIN_FUERZA_SENAL and dist <= MAX_DIST_SENAL:
            return ("LONG" if estado_key == "bull-debil" else "SHORT"), 3
        return "NEUTRAL", 2

    return "NEUTRAL", 1


def _determinar_exit_reason(p_caos: float, desired_direction: str) -> str:
    """
    Determina el motivo del cierre con prioridad:
      1. CAOS   → p_caos >= 0.75 (mercado impredecible)
      2. FLIP   → cambio de dirección LONG↔SHORT
      3. NEUTRAL→ mercado pasó a RANGO
    """
    if p_caos >= CAOS_HARD_GATE:
        return "CAOS"
    if desired_direction in ("LONG", "SHORT"):
        return "FLIP"
    return "NEUTRAL"


def generar_senales(gem_context: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Genera señales accionables para cada activo (para el panel web de la brújula).
    Usa h24/l24/sma20_15m del contexto con fallback al precio actual.
    """
    senales = {}
    for coin, ctx in gem_context.items():
        estado_tuple = calcular_estado(coin, ctx)
        (b1h, b15, b5, fza, dist, p_caos, estado_key, color_letter, divergencia, precio) = estado_tuple

        # Datos del contexto (con fallback al precio si el cartógrafo no los provee aún)
        h24 = ctx.get("h24", precio) if precio > 0 else precio
        l24 = ctx.get("l24", precio) if precio > 0 else precio
        sma20 = ctx.get("sma20_15m", precio) if precio > 0 else precio

        if p_caos >= CAOS_HARD_GATE:
            senales[coin] = {
                "direction": "NEUTRAL", "icono": "⚪",
                "mensaje": f"CAOS en {coin}. Mercado impredecible.",
                "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
            }
            continue

        if estado_key == "no-operar" and b1h == "RANGO" and b15 == "RANGO":
            senales[coin] = {
                "direction": "NEUTRAL", "icono": "➖",
                "mensaje": f"{coin} EN RANGO. Esperar confirmacion.",
                "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
            }
            continue

        if estado_key == "bull-fuerte":
            senales[coin] = {
                "direction": "LONG", "icono": "🟢",
                "mensaje": f"ENTRADA SUGERIDA LONG @ ${precio:,.0f}",
                "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
            }
            continue

        if estado_key == "bear-fuerte":
            senales[coin] = {
                "direction": "SHORT", "icono": "🔴",
                "mensaje": f"ENTRADA SUGERIDA SHORT @ ${precio:,.0f}",
                "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
            }
            continue

        if estado_key == "giro":
            if b15 == "BULL":
                senales[coin] = {
                    "direction": "LONG", "icono": "🟡",
                    "mensaje": "GIRO ALCISTA detectado. Confirmar con 1H.",
                    "nivel_soporte": sma20, "nivel_resistencia": h24, "trade_activo": False,
                }
            else:
                senales[coin] = {
                    "direction": "SHORT", "icono": "🟠",
                    "mensaje": "GIRO BAJISTA detectado. Confirmar con 1H.",
                    "nivel_soporte": l24, "nivel_resistencia": sma20, "trade_activo": False,
                }
            continue

        if estado_key in ("bull-debil", "bear-debil"):
            if fza >= MIN_FUERZA_SENAL and dist <= MAX_DIST_SENAL:
                if estado_key == "bull-debil":
                    senales[coin] = {
                        "direction": "LONG", "icono": "🟡",
                        "mensaje": f"PREPARACION LONG. Vigila ruptura SMA20 (${sma20:,.2f})",
                        "nivel_soporte": sma20, "nivel_resistencia": h24, "trade_activo": False,
                    }
                else:
                    senales[coin] = {
                        "direction": "SHORT", "icono": "🟠",
                        "mensaje": f"PREPARACION SHORT. Vigila ruptura SMA20 (${sma20:,.2f})",
                        "nivel_soporte": l24, "nivel_resistencia": sma20, "trade_activo": False,
                    }
            else:
                senales[coin] = {
                    "direction": "NEUTRAL", "icono": "⏳",
                    "mensaje": f"{estado_key.upper()}. Sin conviccion suficiente.",
                    "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
                }
            continue

        if estado_key == "pullback":
            senales[coin] = {
                "direction": "NEUTRAL", "icono": "⏳",
                "mensaje": f"PULLBACK. Zona de entrada: ${sma20:,.2f} - ${l24:,.2f}",
                "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
            }
            continue

        senales[coin] = {
            "direction": "NEUTRAL",
            "icono": "⚡" if estado_key == "counter" else "➖",
            "mensaje": f"{estado_key.upper()}. Esperar mejor setup.",
            "nivel_soporte": l24, "nivel_resistencia": h24, "trade_activo": False,
        }

    return senales


async def evaluar_y_ejecutar_senales() -> Dict[str, Dict[str, Any]]:
    """
    Ciclo completo: evalúa mercado, compara con Turso, abre/cierra señales
    y envía alertas a Telegram.

    v2.2: FLIP solo cierra (no abre nueva señal inmediatamente).
          exit_reason distingue CAOS / FLIP / NEUTRAL.

    Retorna las señales en formato compatible con el panel web de la brújula.
    """
    print("\n🔄 Evaluando señales...")

    # 1. Obtener estado actual del mercado
    gem_context = await ejecutar_cartografo()

    # 2. Leer señales abiertas en Turso
    open_signals_db = await get_open_signals()
    open_dict = {s["coin"]: s for s in open_signals_db}

    # 3. Evaluar cada activo
    for coin, ctx in gem_context.items():
        estado_tuple = calcular_estado(coin, ctx)
        (b1h, b15, b5, fza, dist, p_caos, estado_key, color_letter, divergencia, precio) = estado_tuple

        # Determinar dirección deseada y score
        desired_direction, score = _decidir_direccion(estado_key, b15, fza, dist, p_caos)

        # Régimen y contexto completo
        regime_str = "caos" if p_caos >= CAOS_HARD_GATE else ("tendencia" if b1h != "RANGO" else "rango")
        context_snapshot = {
            "bias_1h": b1h,
            "bias_15m": b15,
            "bias_visual": b5,
            "fuerza_15m": fza,
            "dist_atr_15m": dist,
            "p_caos": p_caos,
            "regime": regime_str,
        }

        # 4. Comparar con señal abierta en Turso
        db_signal = open_dict.get(coin)

        if db_signal:
            current_direction = db_signal["direction"]

            # ¿Cambió el estado? (a NEUTRAL o a dirección opuesta)
            if desired_direction == "NEUTRAL" or desired_direction != current_direction:
                exit_reason = _determinar_exit_reason(p_caos, desired_direction)
                print(f"  🔄 Cerrando {coin} {current_direction} → {desired_direction} (motivo: {exit_reason})")

                closed_data = await close_signal(coin, precio, exit_reason=exit_reason)
                if closed_data:
                    await enviar_alerta_cierre(
                        coin,
                        current_direction,
                        closed_data["price_entry"],
                        precio,
                        closed_data["pnl_percent"],
                        closed_data["duration_seconds"],
                        closed_data["exit_reason"],
                    )
                # NOTA: En FLIP no abrimos nueva señal aquí.
                # Se abrirá en el próximo ciclo si el estado sigue siendo fuerte.
        else:
            # No hay señal abierta: abrir si hay convicción LONG/SHORT
            if desired_direction in ("LONG", "SHORT"):
                print(f"  🚀 Abriendo {coin} {desired_direction} @ {precio} (score: {score}/6)")
                signal_id = await open_signal(
                    coin, desired_direction, precio, score, context_snapshot, regime_str
                )
                if signal_id:
                    await enviar_alerta_apertura(coin, desired_direction, precio, score, regime_str)

    # 5. Retornar señales en formato compatible con el panel web
    return generar_senales(gem_context)


if __name__ == "__main__":
    import asyncio

    print("=" * 60)
    print("TEST DE SIGNAL AGGREGATOR v2.2")
    print("=" * 60)
    print("Ejecutando ciclo completo: cartógrafo → Turso → Telegram")
    print()

    async def test():
        senales = await evaluar_y_ejecutar_senales()
        print("\n" + "=" * 60)
        print("SEÑALES PARA EL PANEL WEB:")
        print("=" * 60)
        for coin, s in senales.items():
            print(f"  {coin:5s} → {s['direction']:7s} {s['icono']} | {s['mensaje']}")

    asyncio.run(test())