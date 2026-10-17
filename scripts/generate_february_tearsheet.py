"""Generate comparative tearsheet for February 2026 exit policy benchmarks."""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs/audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

policies = [
    "Baseline (Z=0.0 + 25s Taker)",
    "Ekström Early (Z=0.5 + 25s Taker)",
    "Ekström Pure Maker (Z=0.5, 0 Taker)",
]

gross_alpha = [13.81, 32.46, 20.81]
maker_spread = [64.98, 79.86, 38.86]
repeg_cost = [-63.20, -60.60, -85.12]
taker_cost = [-104.68, -121.54, 0.00]
net_pnl = [-89.10, -69.81, -25.46]
cost_per_m = [78.37, 54.91, 37.43]
win_rates = [39.5, 40.6, 63.7]
volumes_k = [1136.9, 1271.5, 680.2]

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.patch.set_facecolor("#ffffff")

# 1. PnL Decomposition Stack
x = np.arange(len(policies))
width = 0.55

axes[0, 0].bar(x, gross_alpha, width, label="Gross Alpha", color="#2ca02c", alpha=0.85)
axes[0, 0].bar(x, maker_spread, width, bottom=gross_alpha, label="Maker Spread Capture", color="#1f77b4", alpha=0.85)
axes[0, 0].bar(x, repeg_cost, width, label="Re-peg Cost", color="#ff7f0e", alpha=0.85)
axes[0, 0].bar(x, taker_cost, width, bottom=repeg_cost, label="Taker Cost", color="#d62728", alpha=0.85)
axes[0, 0].plot(x, net_pnl, color="black", marker="o", linewidth=2.5, label="Net Realized PnL")
axes[0, 0].axhline(0, color="gray", linestyle="--")
axes[0, 0].set_title("1. PnL & Microstructure Cost Decomposition ($)", fontsize=11, fontweight="bold")
axes[0, 0].set_xticks(x)
axes[0, 0].set_xticklabels(policies, rotation=12, ha="right", fontsize=9)
axes[0, 0].set_ylabel("USD ($)")
axes[0, 0].legend(loc="lower left", fontsize=8.5)
axes[0, 0].grid(True, linestyle="--", alpha=0.5)

# 2. Net PnL Comparison
colors = ["#d62728", "#ff7f0e", "#2ca02c"]
bars = axes[0, 1].bar(x, net_pnl, width, color=colors, alpha=0.85, edgecolor="black")
for bar, val in zip(bars, net_pnl):
    axes[0, 1].text(bar.get_x() + bar.get_width()/2, val - 4, f"${val:+.2f}", ha="center", va="top", fontweight="bold", fontsize=10)
axes[0, 1].axhline(0, color="gray", linestyle="--")
axes[0, 1].set_title("2. Net Realized PnL (Feb 1-7, 183.5M Events)", fontsize=11, fontweight="bold")
axes[0, 1].set_xticks(x)
axes[0, 1].set_xticklabels(policies, rotation=12, ha="right", fontsize=9)
axes[0, 1].set_ylabel("Net PnL ($)")
axes[0, 1].grid(True, linestyle="--", alpha=0.5)

# 3. Effective Cost per $1M Volume
bars3 = axes[1, 0].bar(x, cost_per_m, width, color=["#d62728", "#ff7f0e", "#1f77b4"], alpha=0.85, edgecolor="black")
for bar, val in zip(bars3, cost_per_m):
    axes[1, 0].text(bar.get_x() + bar.get_width()/2, val + 2, f"${val:.2f}/$1M", ha="center", va="bottom", fontweight="bold", fontsize=10)
axes[1, 0].set_title("3. Effective Volume Farming Friction ($ per $1M Farmed)", fontsize=11, fontweight="bold")
axes[1, 0].set_xticks(x)
axes[1, 0].set_xticklabels(policies, rotation=12, ha="right", fontsize=9)
axes[1, 0].set_ylabel("Friction Cost / $1M ($)")
axes[1, 0].grid(True, linestyle="--", alpha=0.5)

# 4. Win Rate vs Volume Farmed
ax_vol = axes[1, 1]
ax_wr = ax_vol.twinx()

bars4 = ax_vol.bar(x - 0.15, volumes_k, width=0.3, color="#17becf", alpha=0.8, label="Volume Farmed ($k)")
lines4 = ax_wr.plot(x + 0.15, win_rates, color="#e377c2", marker="s", markersize=8, linewidth=2.5, label="Win Rate (%)")

ax_vol.set_ylabel("Farmed Volume ($k)", color="#17becf")
ax_wr.set_ylabel("Win Rate (%)", color="#e377c2")
ax_vol.set_xticks(x)
ax_vol.set_xticklabels(policies, rotation=12, ha="right", fontsize=9)
ax_vol.set_title("4. Volume Farmed vs Trade Win Rate", fontsize=11, fontweight="bold")
ax_vol.grid(True, linestyle="--", alpha=0.5)

plt.tight_layout()
out_file = OUT_DIR / "february_2026_exit_benchmark_tearsheet.png"
plt.savefig(out_file, dpi=200, bbox_inches="tight")
plt.close()
print(f"Saved February tearsheet: {out_file}")
