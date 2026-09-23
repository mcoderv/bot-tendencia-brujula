"""
Brujula MTF v4.0 adaptada para FastAPI.
Motor de decision con 9 estados. Sin IPython.display.
Retorna HTML string para servir como pagina web.
v4.1: Precio actual en cada card (footer)
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Tuple

from app.config import (
    ASSETS, TZ_NAME, MK_BLOQUEO,
    FUERZA_FUERTE, FUERZA_DEBIL,
    DIST_EXTENDIDA, DIST_MODERADA,
    REFRESH_SEG, INFO_247_TXT,
)

# Escala tipografica
FS_ROOT = 16.8
FS_H1 = 19.2
FS_H2 = 14.4
FS_SMALL = 13.2
FS_MINI = 12.0
FS_MTF = 10.0
FS_ICON = 43.2

# Geometria
COL_CARDS_PCT = 63
COL_LEYENDA_PCT = 37
COLS_POR_FILA = 3


def _norm_bias(b: str) -> str:
    b = str(b or "RANGO").upper().strip()
    if b in ("BULL", "BUY", "STRONG BULLISH"):
        return "BULL"
    if b in ("BEAR", "SELL", "STRONG BEARISH"):
        return "BEAR"
    return "RANGO"


def calcular_estado(coin: str, ctx: Dict[str, Any]) -> Tuple:
    """
    Retorna tupla de 10 elementos:
    (bias_1h, bias_15m, bias_5m, fuerza_15m, dist_atr, p_caos,
     estado_key, color_key, divergencia, precio)
    """
    if not ctx or not isinstance(ctx, dict):
        return ("RANGO", "RANGO", "RANGO", 0, 0.0, 0.0,
                "sin-datos", "D", False, 0.0)

    try:
        b1h = _norm_bias(ctx.get("bias_1h", "RANGO"))
        b15 = _norm_bias(ctx.get("bias_15m", "RANGO"))
        b5 = _norm_bias(ctx.get("bias_visual", "RANGO"))
        fza = int(ctx.get("fuerza_15m", 0) or 0)
        dist = float(ctx.get("dist_atr_15m", 0.0) or 0.0)
        _regimen = ctx.get("regimen", None)
        p_caos = float((_regimen or {}).get("p_caos", 0.0) or 0.0)
        precio = float(ctx.get("precio_ejecucion", 0.0) or 0.0)
    except (TypeError, ValueError):
        return ("RANGO", "RANGO", "RANGO", 0, 0.0, 0.0,
                "sin-datos", "D", False, 0.0)

    divergencia = (b5 != b15)

    # #1 HARD GATE: CAOS
    if p_caos >= MK_BLOQUEO:
        return (b1h, b15, b5, fza, dist, p_caos, "caos", "K", divergencia, precio)

    # #3 1H EN RANGO
    if b1h == "RANGO":
        if b15 == b5 and b15 != "RANGO" and fza >= FUERZA_FUERTE:
            if b15 == "BULL":
                return (b1h, b15, b5, fza, dist, p_caos, "bull-debil", "Gl", divergencia, precio)
            else:
                return (b1h, b15, b5, fza, dist, p_caos, "bear-debil", "Rl", divergencia, precio)
        return (b1h, b15, b5, fza, dist, p_caos, "no-operar", "D", divergencia, precio)

    # #4 ALINEACION TOTAL
    if b1h == b15 == b5 and b15 != "RANGO":
        if fza >= FUERZA_FUERTE:
            key = "bull-fuerte" if b15 == "BULL" else "bear-fuerte"
            col = "G" if b15 == "BULL" else "R"
        else:
            key = "bull-debil" if b15 == "BULL" else "bear-debil"
            col = "Gl" if b15 == "BULL" else "Rl"
        return (b1h, b15, b5, fza, dist, p_caos, key, col, divergencia, precio)

    # #5 GIRO / COUNTER-TREND
    if b15 != b1h and b5 != b1h and b15 == b5 and b15 != "RANGO":
        if fza >= FUERZA_FUERTE:
            return (b1h, b15, b5, fza, dist, p_caos, "giro", "Y", divergencia, precio)
        else:
            return (b1h, b15, b5, fza, dist, p_caos, "counter", "O", divergencia, precio)

    # #6 PULLBACK
    if b15 != b1h and b5 != b15 and b15 != "RANGO":
        return (b1h, b15, b5, fza, dist, p_caos, "pullback", "C", divergencia, precio)

    # #7 FALLBACK
    return (b1h, b15, b5, fza, dist, p_caos, "no-operar", "D", divergencia, precio)


def _color_letter(letter: str) -> str:
    return {
        "G": "#22c55e",
        "Gl": "#4ade80",
        "R": "#ef4444",
        "Rl": "#f87171",
        "Y": "#eab308",
        "O": "#f0883e",
        "C": "#39c5cf",
        "D": "#768390",
        "K": "#6b7280",
        "B": "#a371f7",
    }.get(letter, "#adbac7")


def _estado_peso(key: str) -> int:
    return {
        "giro": 0,
        "counter": 1,
        "caos": 2,
        "bear-fuerte": 3,
        "bear-debil": 4,
        "pullback": 5,
        "bull-fuerte": 6,
        "bull-debil": 7,
        "no-operar": 8,
        "sin-datos": 9,
    }.get(key, 10)


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _icono_para_estado(key: str) -> str:
    return {
        "bull-fuerte": "⬆️⬆️⬆️",
        "bull-debil": "⬆️",
        "bear-fuerte": "⬇️⬇️⬇️",
        "bear-debil": "⬇️",
        "pullback": "⏳",
        "giro": "🔄",
        "counter": "⚡",
        "no-operar": "➖",
        "caos": "⚪",
        "sin-datos": "❓",
    }.get(key, "➖")


def _label_corto(key: str) -> str:
    return {
        "bull-fuerte": "BULL FUERTE",
        "bull-debil": "BULL DÉBIL",
        "bear-fuerte": "BEAR FUERTE",
        "bear-debil": "BEAR DÉBIL",
        "pullback": "PULLBACK — ESPERAR",
        "giro": "GIRO DE TENDENCIA",
        "counter": "COUNTER-TREND",
        "no-operar": "NO OPERAR",
        "caos": "CAOS (MARKOV)",
        "sin-datos": "SIN DATOS",
    }.get(key, "—")


def _bias_html(b: str) -> str:
    c = {"BULL": "#22c55e", "BEAR": "#ef4444"}.get(b, "#eab308")
    return f'<span style="color:{c};font-weight:700;">{_esc(b)}</span>'


def _format_precio(precio: float) -> str:
    """Formatea el precio según su magnitud."""
    if precio <= 0:
        return "—"
    if precio >= 1000:
        return f"${precio:,.0f}"
    elif precio >= 1:
        return f"${precio:,.2f}"
    else:
        return f"${precio:,.4f}"


def _render_card(coin: str, b1h: str, b15: str, b5: str, fza: int,
                 dist: float, p_caos: float, key: str,
                 color_letter: str, div: bool, precio: float) -> str:
    col = _color_letter(color_letter)
    bg = f"{col}1A"
    border = f"{col}80"

    icono = _icono_para_estado(key)
    label = _label_corto(key)

    warn = ' <span style="color:#eab308;" title="Divergencia 5m vs 15m">⚠️</span>' if div else ""
    mtf = (
        f'<span style="color:#768390;">1H</span> {_bias_html(b1h)}'
        f'<span style="color:#555;">·</span>'
        f'<span style="color:#768390;">15m</span> {_bias_html(b15)}'
        f'<span style="color:#555;">·</span>'
        f'<span style="color:#768390;">5m</span> {_bias_html(b5)}'
        f"{warn}"
    )

    fza_col = "#22c55e" if fza >= 2 else ("#eab308" if fza >= 1 else "#768390")
    dist_col = "#ef4444" if dist >= DIST_EXTENDIDA else ("#eab308" if dist >= DIST_MODERADA else "#768390")
    caos_col = "#ef4444" if p_caos >= 0.40 else ("#eab308" if p_caos >= 0.20 else "#768390")
    precio_col = "#22c55e" if precio > 0 else "#768390"

    html = (
        f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
        f'padding:8px 10px;margin:0;display:flex;flex-direction:column;box-sizing:border-box;">'

        # ── HEADER: coin + precio + alineación MTF ──
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
        f'border-bottom:1px solid {border};padding-bottom:6px;margin-bottom:6px;gap:6px;">'
        f'<div style="display:flex;flex-direction:column;gap:2px;">'
        f'<span style="font-size:{FS_H1}px;font-weight:800;color:#ffffff;white-space:nowrap;">{_esc(coin)}</span>'
        f'<span style="font-size:{FS_MINI}px;color:{precio_col};font-weight:600;font-family:ui-monospace,Consolas,monospace;">{_format_precio(precio)}</span>'
        f'</div>'
        f'<span style="font-size:{FS_MTF}px;text-align:right;line-height:1.5;letter-spacing:-0.2px;">{mtf}</span>'
        f'</div>'

        # ── CENTRO: icono + label ──
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:center;'
        f'text-align:center;padding:4px 0;">'
        f'<div style="font-size:{FS_ICON}px;line-height:1;color:{col};">{_esc(icono)}</div>'
        f'<div style="font-size:{FS_H2}px;color:{col};font-weight:700;margin-top:4px;'
        f'text-transform:uppercase;letter-spacing:0.5px;">{_esc(label)}</div>'
        f'</div>'

        # ── FOOTER: FZA · DIST · CAOS ──
        f'<div style="border-top:1px solid {border};padding-top:6px;margin-top:6px;'
        f'display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 6px;'
        f'font-family:ui-monospace,Consolas,monospace;font-size:{FS_MINI}px;">'
        f'<span style="color:#768390;">FZA: <span style="color:{fza_col};font-weight:700;">{fza}/3</span></span>'
        f'<span style="color:#768390;">DIST: <span style="color:{dist_col};font-weight:700;">{dist:.1f}×</span></span>'
        f'<span style="color:#768390;">CAOS: <span style="color:{caos_col};font-weight:700;">{p_caos:.2f}</span></span>'
        f'</div>'

        f'</div>'
    )
    return html


def _render_grupo(titulo: str, coins: list, estados: dict) -> str:
    orden = sorted(coins, key=lambda c: (_estado_peso(estados[c][6]), c))
    cards = "".join(_render_card(c, *estados[c]) for c in orden)
    bloque = ""
    if titulo:
        bloque += (
            f'<div style="color:#768390;font-size:{FS_MINI}px;font-weight:700;'
            f'letter-spacing:0.5px;margin:0 0 4px 2px;">{_esc(titulo)}</div>'
        )
    bloque += (
        f'<div style="display:grid;grid-template-columns:repeat({COLS_POR_FILA}, minmax(0,1fr));'
        f'gap:10px;margin-bottom:12px;align-items:stretch;">{cards}</div>'
    )
    return bloque


def render_brujula(gem_context: Dict[str, Dict[str, Any]]) -> str:
    """Genera el HTML completo de la Brujula."""
    ahora = datetime.now(ZoneInfo(TZ_NAME)).strftime("%H:%M:%S")

    estados = {}
    for coin in ASSETS:
        ctx = gem_context.get(coin, {})
        estados[coin] = calcular_estado(coin, ctx)

    crypto_coins = [c for c in estados if not str(c).startswith("xyz:")]
    tradfi_coins = [c for c in estados if str(c).startswith("xyz:")]

    grupos_html = _render_grupo("🪙 CRYPTO", crypto_coins, estados)
    if tradfi_coins:
        grupos_html += _render_grupo("🏧 TRADFI (perps 24/7)", tradfi_coins, estados)

    header = (
        f'<div style="border:1px solid #30363d;border-radius:8px;padding:8px 14px;'
        f'margin-bottom:10px;background:rgba(57,197,207,0.07);">'
        f'<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;">'
        f'<div style="font-weight:800;color:#39c5cf;font-size:{FS_H1}px;">🧭 BRÚJULA MTF v4.1</div>'
        f'<div style="color:#768390;font-size:{FS_H2}px;">⏱ {ahora} · 1H+15m+5m · On-demand</div>'
        f'</div>'
        f'<div style="border-top:1px solid #30363d;margin-top:6px;padding-top:6px;'
        f'color:#39c5cf;font-size:{FS_SMALL}px;">{_esc(INFO_247_TXT)}</div>'
        f'</div>'
    )

    legend = (
        f'<div style="flex:1;background:#0e0e14;border:1px solid #30363d;border-radius:6px;'
        f'padding:10px 14px;font-size:{FS_SMALL}px;color:#adbac7;line-height:1.65;'
        f'box-sizing:border-box;">'
        f'<div style="color:#39c5cf;font-weight:700;margin-bottom:6px;font-size:{FS_H2}px;">'
        f'📖 Leyenda — 9 estados MTF</div>'

        f'<b style="color:#22c55e;">⬆️⬆️⬆️ BULL FUERTE:</b> 1H+15m+5m BULL + fza≥2<br>'
        f'<b style="color:#4ade80;">⬆️ BULL DÉBIL:</b> 1H+15m+5m BULL + fza≤1<br>'
        f'<b style="color:#ef4444;">⬇️⬇️⬇️ BEAR FUERTE:</b> 1H+15m+5m BEAR + fza≥2<br>'
        f'<b style="color:#f87171;">⬇️ BEAR DÉBIL:</b> 1H+15m+5m BEAR + fza≤1<br>'
        f'<b style="color:#39c5cf;">⏳ PULLBACK:</b> 15m contra 1H, 5m sin confirmar<br>'
        f'<b style="color:#eab308;">🔄 GIRO:</b> 15m+5m contra 1H + fza≥2<br>'
        f'<b style="color:#f0883e;">⚡ COUNTER:</b> 15m+5m contra 1H + fza≤1<br>'
        f'<b style="color:#768390;">➖ NO OPERAR:</b> Rango o sin dirección<br>'
        f'<b style="color:#6b7280;">⚪ CAOS:</b> p_caos ≥ {MK_BLOQUEO:.2f}<br>'

        f'<br><b style="color:#eab308;">⚠️ Divergencia:</b> 5m ≠ 15m en el header.'
        f'</div>'
    )

    disclaimer = (
        f'<div style="background:rgba(234,179,8,0.06);border:1px solid #eab308;border-radius:6px;'
        f'padding:8px 12px;margin-top:10px;color:#eab308;font-size:{FS_H2}px;">'
        f'⚠️ Esta herramienta muestra el <b>estado actual</b> del mercado. '
        f'<b>NO predice</b> movimientos futuros. Usá tu criterio.'
        f'</div>'
    )

    body = (
        f'<div style="display:flex;gap:12px;align-items:stretch;">'
        f'<div style="flex:0 0 {COL_CARDS_PCT}%;min-width:0;">{grupos_html}</div>'
        f'<div style="flex:0 0 {COL_LEYENDA_PCT}%;min-width:0;display:flex;">{legend}</div>'
        f'</div>'
    )

    return (
        f'<div style="font-family:ui-monospace,Consolas,monospace;font-size:{FS_ROOT}px;color:#adbac7;'
        f'max-width:1300px;box-sizing:border-box;background:#0d1117;padding:16px;border-radius:12px;">'
        f'{header}'
        f'{body}'
        f'{disclaimer}'
        f'</div>'
    )