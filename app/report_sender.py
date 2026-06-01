"""Generador y despachador del reporte periódico de win rate.

Se llama desde el scanner cada WINRATE_REPORT_INTERVAL_HOURS horas.
No requiere parámetros — lee la configuración de .env y la DB directamente.
"""
import logging
import time
from typing import Any, Dict

from app import database
from app.notifier import dispatch_report

logger = logging.getLogger("report_sender")

_ACTION_EMOJI = {
    "LONG_FUTURES":  "📈",
    "SHORT_FUTURES": "📉",
    "BUY_SPOT":      "🟢",
    "SELL_SPOT":     "🔴",
}
_ACTION_LABEL = {
    "LONG_FUTURES":  "Long Futuros",
    "SHORT_FUTURES": "Short Futuros",
    "BUY_SPOT":      "Buy Spot",
    "SELL_SPOT":     "Sell Spot",
}


def _outcome_bar(wins: int, partials: int, losses: int, neutrals: int, total: int) -> str:
    """Barra visual: ✅W 🔶P ❌L ⏳N"""
    parts = []
    if wins:     parts.append(f"✅{wins}")
    if partials: parts.append(f"🔶{partials}")
    if losses:   parts.append(f"❌{losses}")
    if neutrals: parts.append(f"⏳{neutrals}")
    return "  ".join(parts) if parts else "⏳ sin resultados"


def _winrate_emoji(wr: float) -> str:
    if wr >= 65: return "🟢"
    if wr >= 45: return "🟡"
    return "🔴"


def _build_telegram(data: Dict[str, Any], since_hours: float) -> str:
    now_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    period  = f"últimas {int(since_hours)}h" if since_hours < 168 else f"últimos {int(since_hours//24)}d"

    lines = [
        f"📊 <b>Reporte de Win Rate</b>",
        f"<i>{period} — {now_str}</i>",
        "",
    ]

    if data["total_alerts"] == 0:
        lines.append("Sin alertas en el período.")
        return "\n".join(lines)

    for row in data["by_action"]:
        emoji  = _ACTION_EMOJI.get(row["action"], "⚠️")
        label  = _ACTION_LABEL.get(row["action"], row["action"])
        dir_wr = row.get("directional_winrate_pct", row["winrate_pct"])
        wr_em  = _winrate_emoji(dir_wr)
        evaluated = row.get("evaluated", 0)

        lines.append(f"{emoji} <b>{label}</b>  ({row['total']} alertas, {evaluated} eval.)")
        lines.append(
            _outcome_bar(row["wins"], row["partials"], row["losses"], row["neutrals"], row["total"])
        )
        ret_str = f"  |  Ret: <code>{row['avg_return_pct']:+.2f}%</code>" if evaluated > 0 else ""
        lines.append(
            f"{wr_em} Direc: <b>{dir_wr:.0f}%</b>"
            f"  Estricto: {row['winrate_pct']:.0f}%"
            + ret_str
        )
        lines.append("")

    g_dir = data.get("global_directional_winrate_pct", data["global_winrate_pct"])
    wr_em = _winrate_emoji(g_dir)
    lines.append("─────────────────────")
    lines.append(
        f"{wr_em} <b>Global: {data['total_alerts']} alertas ({data.get('total_evaluated',0)} eval.)"
        f" | Dir {g_dir:.0f}%  Estricto {data['global_winrate_pct']:.0f}%"
        f" | Ret: {data['global_avg_return_pct']:+.2f}%</b>"
    )

    if data["top_symbols"]:
        lines.append("")
        lines.append("🏆 <b>Top símbolos:</b>")
        for i, sym in enumerate(data["top_symbols"], 1):
            em = _ACTION_EMOJI.get(sym["action"], "")
            avg_ret = sym.get("avg_return_pct")
            ret_str = f"  {avg_ret:+.2f}%" if avg_ret is not None else ""
            lines.append(
                f"{i}. {em} <code>{sym['symbol']}</code>"
                f"  {sym['wins']}/{sym['total']} ({sym['winrate_pct']:.0f}%){ret_str}"
            )

    return "\n".join(lines)


def _build_discord(data: Dict[str, Any], since_hours: float) -> str:
    now_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    period  = f"últimas {int(since_hours)}h" if since_hours < 168 else f"últimos {int(since_hours//24)}d"

    lines = [
        f"📊 **Reporte de Win Rate** — {period} ({now_str})",
    ]

    if data["total_alerts"] == 0:
        lines.append("Sin alertas en el período.")
        return "\n".join(lines)

    for row in data["by_action"]:
        emoji  = _ACTION_EMOJI.get(row["action"], "⚠️")
        label  = _ACTION_LABEL.get(row["action"], row["action"])
        dir_wr = row.get("directional_winrate_pct", row["winrate_pct"])
        wr_em  = _winrate_emoji(dir_wr)
        evaluated = row.get("evaluated", 0)
        ret_str = f" | Ret: {row['avg_return_pct']:+.2f}%" if evaluated > 0 else ""
        bar = _outcome_bar(row["wins"], row["partials"], row["losses"], row["neutrals"], row["total"])
        lines.append(
            f"{emoji} **{label}** ({row['total']}/{evaluated}eval)  {bar}"
            f"  {wr_em} Dir {dir_wr:.0f}% / Estric {row['winrate_pct']:.0f}%{ret_str}"
        )

    g_dir = data.get("global_directional_winrate_pct", data["global_winrate_pct"])
    wr_em = _winrate_emoji(g_dir)
    lines.append(
        f"──────  {wr_em} **Global: {data['total_alerts']} alertas ({data.get('total_evaluated',0)} eval.)"
        f" | Dir {g_dir:.0f}%  Estric {data['global_winrate_pct']:.0f}%"
        f" | Ret: {data['global_avg_return_pct']:+.2f}%**"
    )

    if data["top_symbols"]:
        tops = "  |  ".join(
            f"{_ACTION_EMOJI.get(s['action'],'')} {s['symbol']} {s['wins']}/{s['total']} ({s['winrate_pct']:.0f}%)"
            for s in data["top_symbols"]
        )
        lines.append(f"🏆 Top: {tops}")

    return "\n".join(lines)


def send_winrate_report(since_hours: float = 24.0) -> bool:
    """Construye el reporte, lo formatea y lo envía a todos los canales.

    Retorna True si había datos para reportar y se intentó el envío.
    """
    try:
        data = database.get_winrate_summary(since_hours)
        if data["total_alerts"] == 0:
            logger.info("Reporte win rate: sin alertas en las últimas %.0fh — omitiendo", since_hours)
            return False

        msg_tg = _build_telegram(data, since_hours)
        msg_dc = _build_discord(data, since_hours)
        dispatch_report(msg_dc, msg_tg)
        logger.info(
            "Reporte win rate enviado — %d alertas | WR %.0f%% | retorno %.2f%%",
            data["total_alerts"], data["global_winrate_pct"], data["global_avg_return_pct"],
        )
        return True
    except Exception:
        logger.exception("Error al enviar reporte de win rate")
        return False
