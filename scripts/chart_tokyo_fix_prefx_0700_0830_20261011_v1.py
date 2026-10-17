"""Charts of frozen 07:00 Gotobi results. Descriptive; not parameter selection."""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT=Path(__file__).resolve().parents[1]/"run_log/tokyo_fix_prefx_0700_0830_20261011_v1"
def read(p):
    return json.loads((OUT/p).read_text())
def main():
    got=read("T1_native_gotobi/result.json")
    ordinary=read("T2_native_ordinary/result.json")
    years=[x["year"] for x in got["years"]]
    g=[x["net_usd"] for x in got["years"]]
    o=[x["net_usd"] for x in ordinary["years"]]
    fig,ax=plt.subplots(figsize=(10,5))
    loc=list(range(len(years)))
    ax.bar([x-.19 for x in loc],g,width=.37,label="Gotobi 07:00 long")
    ax.bar([x+.19 for x in loc],o,width=.37,label="Ordinary-day 07:00 long")
    ax.axhline(0,color="gray",lw=.8)
    ax.set_xticks(loc,[str(y)+("*" if y==2026 else "") for y in years])
    ax.set_ylabel("Net USD P&L")
    ax.set_title("07:00-08:30 JST native market execution, 1 pip round-trip cost")
    ax.legend()
    fig.text(.1,.005,"* 2026 Jan-Aug only. Fixed $10k base USD notional; prior years retrospective.",fontsize=9)
    fig.tight_layout(rect=[0,.035,1,1])
    fig.savefig(OUT/"annual_pnl.png",dpi=150)
    plt.close(fig)
    cost=read("T3_cost_sensitivity/result.json")
    seq=sorted(cost["native_cost_runs"],key=lambda x:x["cost_pips"])
    fig,ax=plt.subplots(figsize=(8,5))
    ax.plot([x["cost_pips"] for x in seq],[x["metrics"]["net_usd"] for x in seq],marker="o")
    ax.axhline(0,color="gray",lw=.8)
    ax.axvline(cost["usd_breakeven_roundtrip_pips"],ls="--",color="gray")
    ax.set(xlabel="Assumed round-trip cost (USDJPY pips)",
           ylabel="Net USD P&L over full study",title="07:00 Gotobi — transaction-cost sensitivity")
    fig.tight_layout()
    fig.savefig(OUT/"cost_sensitivity.png",dpi=150)
    plt.close(fig)
    reg=read("T4_regimes/result.json")["slices"]
    vals=[x for x in reg if x["feature"]=="rv" and x["period"] in ("retrospective2024_25","stress2026")]
    lookup={(x["period"],x["regime"]):x["net_usd"] for x in vals}
    labels=["low","mid","high"]
    fig,ax=plt.subplots(figsize=(8,5))
    ax.bar([i-.2 for i in range(3)],[lookup.get(("retrospective2024_25",r),0) for r in labels],
           width=.39,label="2024-25")
    ax.bar([i+.2 for i in range(3)],[lookup.get(("stress2026",r),0) for r in labels],
           width=.39,label="2026 Jan-Aug")
    ax.axhline(0,color="gray",lw=.8)
    ax.set_xticks(range(3),labels)
    ax.set(xlabel="Prior 30-min realized volatility tercile, thresholds fitted 2020-23",
           ylabel="Net USD P&L, 1 pip reference cost",title="Regime stability (descriptive, varying sample counts)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT/"regime_stability.png",dpi=150)
    plt.close(fig)
    print("Charts saved:",*[str(OUT/p) for p in ("annual_pnl.png","cost_sensitivity.png","regime_stability.png")])
if __name__=="__main__":main()
