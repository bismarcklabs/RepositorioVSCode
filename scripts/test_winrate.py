import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.database import get_winrate_summary
from app.report_sender import _build_telegram, _build_discord

data = get_winrate_summary(since_hours=8)
print("total_alerts:", data["total_alerts"])
print("total_evaluated:", data["total_evaluated"])
print("global_winrate_pct (estricto):", data["global_winrate_pct"])
print("global_directional_winrate_pct:", data["global_directional_winrate_pct"])
print()
for r in data["by_action"]:
    print(
        f"{r['action']}: eval={r['evaluated']} W={r['wins']} P={r['partials']} L={r['losses']}"
        f" | estricto={r['winrate_pct']}% direc={r['directional_winrate_pct']}%"
        f" | ret={r['avg_return_pct']:+.2f}%"
    )
print()
msg = _build_telegram(data, 8)
print("Telegram preview (ASCII):")
print(msg.encode("ascii", errors="replace").decode("ascii"))
