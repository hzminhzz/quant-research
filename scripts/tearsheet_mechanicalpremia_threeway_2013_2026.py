"""Skill-guided ML4T tearsheet of annual-reset Mechanical Premia native artifacts.

No fills, decisions, costs, cash or positions are re-simulated.
The linked daily curve is a DESCRIPTIVE capital-reinvestment illustration:
  previous linked close * (native daily annual-account equity / 100000).
Year-end open positions are marked and NOT carried; do not label continuous
backtest equity, realized USD ROI or investment-grade CAGR/Calmar.
"""
from __future__ import annotations

import base64
import csv
import html
import json
import math
from datetime import date
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from ml4t.diagnostic.api import PortfolioAnalysis

from scripts.report_mechanicalpremia_threeway_v1 import ROOT,OUT,TRIALS,read_cell

COLORS={"C1_DE30":"#4472C4","C2_JP225":"#ED7D31","C3_US_ONLY":"#14957E"}
LABELS={"C1_DE30":"C1 Original DE30","C2_JP225":"C2 JP225 replacement","C3_US_ONLY":"C3 US500+US100 only"}
SOURCE_TRIAL={"C1_DE30":("SOURCE-RISK-7","COST-STRESS"),
              "C2_JP225":("SOURCE-JP225-7","COST-JP225"),
              "C3_US_ONLY":("SOURCE-US2","COST-US2")}

def native_base(candidate,year):
    spec=TRIALS[candidate]
    return next(base for lo,hi,base in spec["base"] if lo<=year<=hi)

def annual_records(candidate,cost=1.0):
    leg="source" if cost==1 else "cost"
    rows=[read_cell(candidate,y,leg,cost) for y in range(2013,2027)]
    if any(r is None for r in rows):raise RuntimeError("Not all native annual results exist")
    return rows

def link_daily_proxy(candidate):
    linked=[]
    previous=1.0
    year_end_ratios=[]
    for year in range(2013,2027):
        base=native_base(candidate,year)
        trial=SOURCE_TRIAL[candidate][0]
        p=base/f"year={year}"/trial/"cost_1x"/"daily_equity.parquet"
        df=pl.read_parquet(p).filter(pl.col("day").dt.year()==year).sort("day")
        if df.is_empty():raise RuntimeError(f"No year equity for {candidate}/{year}")
        annual=read_cell(candidate,year,"source",1.)
        endpoint=float(df["equity"][-1])/100_000
        if not math.isclose(endpoint,1+annual["return_pct"]/100,rel_tol=0,abs_tol=1e-9):
            raise RuntimeError(f"Linked daily end mismatch for {candidate}/{year}")
        for d,eq in df.select("day","equity").iter_rows():
            linked.append({"date":d,"year":year,"candidate":candidate,
                           "linked_equity":previous*float(eq)/100_000})
        previous*=endpoint
        year_end_ratios.append(previous)
    daily=pl.DataFrame(linked).sort("date")
    if daily["date"].n_unique()!=daily.height:
        raise RuntimeError(f"Duplicate session-local day while linking {candidate}")
    daily=daily.with_columns(pl.col("linked_equity").pct_change().fill_null(0).alias("linked_return"))
    return daily,previous,year_end_ratios

def summarize():
    if not (OUT/"summary.json").exists():raise RuntimeError("Source 252-cell audit report missing")
    prior=json.loads((OUT/"summary.json").read_text())
    if prior.get("status")!="ALL_NATIVE_ANNUAL_CELLS_VERIFIED" or prior.get("completed")!=252:
        raise RuntimeError("Unverified source matrix")
    curves={}
    aggregate={}
    years={}
    for c in TRIALS:
        annual=annual_records(c)
        years[c]=annual
        roi=math.prod(1+r["return_pct"]/100 for r in annual)-1
        roi_complete=math.prod(1+r["return_pct"]/100 for r in annual[:-1])-1
        daily,linked,year_ends=link_daily_proxy(c)
        if not math.isclose(linked-1,roi,abs_tol=2e-9,rel_tol=0):
            raise AssertionError("Annual ROI chain does not match native daily chain")
        curves[c]=daily
        costs={}
        for mult in (1.0,1.5,2.0):
            rr=annual_records(c,mult)
            costs[str(mult)]={
                "hypothetical_compounded_roi_pct":100*(math.prod(1+r["return_pct"]/100 for r in rr)-1),
                "average_annual_return_pct":mean(r["return_pct"] for r in rr),
            }
        # Calendar date series include Sunday bars and closed days.
        # PortfolioAnalysis uses actual calendar-daily frequency=365 here,
        # not the original native per-year reporting setting of 252.
        diag=PortfolioAnalysis(returns=daily["linked_return"].to_numpy(),
                               periods_per_year=365).compute_summary_stats()
        aggregate[c]={
            "hypothetical_linked_roi_pct":roi*100,
            "hypothetical_end_value_from_100000":100_000*(1+roi),
            "linked_roi_through_2025_pct":roi_complete*100,
            "mean_yearly_return_pct":mean(r["return_pct"] for r in annual),
            "win_rate_closed_trade_pct":prior["comparative_summary"][c]["source_1"]["closed_trade_win_rate_pct"],
            "closed_trades":prior["comparative_summary"][c]["source_1"]["closed_trades"],
            "calendar_daily_proxy": {
                "frequency_per_year":365,
                "sharpe":float(diag.sharpe_ratio),
                "maxdd_pct":float(diag.max_drawdown)*100,
                "sortino":float(diag.sortino_ratio) if diag.sortino_ratio is not None else None,
                "calmar":float(diag.calmar_ratio) if diag.calmar_ratio is not None else None,
            },
            "cost_stress":costs,
            "year_end_open_position_occurrences":sum(r["open_trades"] for r in annual),
            "year_end_ends":year_ends,
        }
    return curves,aggregate,years

def make_graphs(curves,aggregate,years):
    # 1. Linked NAV figure — simulated capital linking, not continuous native account.
    fig,ax=plt.subplots(figsize=(11.3,4.8))
    for c,d in curves.items():
        x=d["date"].to_list()
        y=100_000*d["linked_equity"].to_numpy()
        ax.plot(x,y,color=COLORS[c],label=LABELS[c],linewidth=1.75)
    ax.set(title="Hypothetical chained annual NAV (not continuous native backtest)",
           ylabel="Synthetic price-unit NAV; start 100,000",xlabel="Date")
    ax.grid(alpha=.25);ax.legend(loc="upper left")
    fig.tight_layout();fig.savefig(OUT/"linked_nav_hypothetical.png",dpi=150);plt.close(fig)

    fig,ax=plt.subplots(figsize=(11.3,4.8))
    for c,d in curves.items():
        v=d["linked_equity"].to_numpy()
        dd=100*(v/np.maximum.accumulate(np.r_[1.,v])[1:]-1)
        ax.plot(d["date"].to_list(),dd,color=COLORS[c],label=LABELS[c],linewidth=1.3)
    ax.set(title="Drawdown on artificial annual-linked NAV (not native continuous DD)",
           ylabel="Hypothetical chained drawdown (%)",xlabel="Date")
    ax.grid(alpha=.25);ax.legend(loc="lower left")
    fig.tight_layout();fig.savefig(OUT/"linked_drawdown_hypothetical.png",dpi=150);plt.close(fig)

    fig,ax=plt.subplots(figsize=(11.5,5))
    x=np.arange(14);bw=.25
    for k,c in enumerate(TRIALS):
        ax.bar(x+(k-1)*bw,[r["return_pct"] for r in years[c]],width=bw,
               color=COLORS[c],label=LABELS[c])
    ax.set_xticks(x,["2026*" if y==2026 else str(y) for y in range(2013,2027)],rotation=45)
    ax.set(title="Actual native annual-reset net returns (2026* partial through Oct 11)",
           ylabel="Annual reset-account return (%)",xlabel="Scored year")
    ax.axhline(0,color="black",linewidth=.7)
    ax.grid(axis="y",alpha=.25);ax.legend()
    fig.tight_layout();fig.savefig(OUT/"annual_native_returns.png",dpi=150);plt.close(fig)

    # Monthly heatmap of artificial linked account, safe as descriptive plot only.
    fig,axes=plt.subplots(3,1,figsize=(11.5,9),sharex=True)
    for ax,(c,d) in zip(axes,curves.items()):
        month=(d.with_columns(month=pl.col("date").dt.month(),year=pl.col("date").dt.year())
               .group_by("year","month").agg(pl.col("linked_equity").last().alias("last"))
               .sort("year","month")
               .with_columns(pl.col("last").pct_change().fill_null(pl.col("last")-1).alias("monthly_return")))
        matrix=np.full((14,12),np.nan)
        for r in month.iter_rows(named=True):
            matrix[r["year"]-2013,r["month"]-1]=100*r["monthly_return"]
        m=ax.imshow(matrix,aspect="auto",cmap="RdYlGn",vmin=-3,vmax=3)
        ax.set_title(LABELS[c],loc="left",size=10)
        ax.set_yticks(np.arange(14),[str(y) for y in range(2013,2027)],fontsize=8)
        ax.set_xticks(np.arange(12),["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
    fig.colorbar(m,ax=axes.ravel().tolist(),label="Approx. monthly price-unit return (%)",fraction=.018)
    fig.subplots_adjust(left=.09,right=.88,top=.94,bottom=.07,hspace=.3)
    fig.savefig(OUT/"monthly_heatmap_hypothetical.png",dpi=150);plt.close(fig)

def html_report(aggregate,years):
    annualhead="<tr><th>Year</th>"+ "".join(f"<th>{html.escape(LABELS[c])}</th>" for c in TRIALS)+"</tr>"
    annualrows=[]
    for year in range(2013,2027):
        nums=[next(r["return_pct"] for r in years[c] if r["year"]==year) for c in TRIALS]
        annualrows.append("<tr><td>"+(str(year)+" YTD" if year==2026 else str(year))+"</td>"+
                          "".join(f"<td>{x:+.2f}%</td>" for x in nums)+"</tr>")
    agg="<tr><th>Metric</th>"+ "".join(f"<th>{html.escape(LABELS[c])}</th>" for c in TRIALS)+"</tr>"
    for label,fun in [
        ("Annual-linked illustrative ROI",lambda a:f"{a['hypothetical_linked_roi_pct']:+.2f}%"),
        ("Illustrative ending value (100k)",lambda a:f"{a['hypothetical_end_value_from_100000']:,.2f}"),
        ("Mean yearly return",lambda a:f"{a['mean_yearly_return_pct']:+.2f}%"),
        ("Native closed trades",lambda a:str(a["closed_trades"])),
        ("Native closed-trade win rate",lambda a:f"{a['win_rate_closed_trade_pct']:.1f}%"),
        ("1.5x cost illustrative ROI",lambda a:f"{a['cost_stress']['1.5']['hypothetical_compounded_roi_pct']:+.2f}%"),
        ("2x cost illustrative ROI",lambda a:f"{a['cost_stress']['2.0']['hypothetical_compounded_roi_pct']:+.2f}%"),
        ("Linked-proxy Sharpe, calendar daily",lambda a:f"{a['calendar_daily_proxy']['sharpe']:.2f}"),
        ("Linked-proxy MDD",lambda a:f"{a['calendar_daily_proxy']['maxdd_pct']:.2f}%"),
        ("Year-end open-position occurrences",lambda a:str(a["year_end_open_position_occurrences"]))
    ]:
        agg+="<tr><td>"+html.escape(label)+"</td>"+ "".join(f"<td>{fun(aggregate[c])}</td>" for c in TRIALS)+"</tr>"
    imgs=[]
    for path,label in [
        ("linked_nav_hypothetical.png","Illustrative linked NAV"),
        ("linked_drawdown_hypothetical.png","Illustrative linked drawdown"),
        ("annual_native_returns.png","Verified native annual returns"),
        ("monthly_heatmap_hypothetical.png","Descriptive monthly linked returns"),
    ]:
        b=base64.b64encode((OUT/path).read_bytes()).decode()
        imgs.append(f"<h2>{html.escape(label)}</h2><img style='max-width:100%;height:auto' src='data:image/png;base64,{b}'/>")
    page="""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>ML4T Mechanical Premia 3-Candidate Tearsheet</title><style>
body{max-width:1170px;margin:35px auto;padding:0 18px;font-family:Arial,sans-serif;color:#182230;line-height:1.48}
h1{font-size:25px}h2{font-size:19px;margin-top:31px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #ddd;text-align:right;padding:8px}td:first-child,th:first-child{text-align:left}
thead{background:#f2f4f7}.warning{border-left:4px solid #cc9c24;padding:12px;background:#fcf8ec}
small{color:#555}footer{margin:45px 0;color:#626b76;font-size:12px}
</style></head><body><h1>Mechanical Premia: 3-Candidate ML4T Tearsheet</h1>
<div class="warning"><b>NON-EXECUTABLE RESEARCH PROXY.</b> Years 2013-2025 are separate $100k native annual accounts.
2026 ends October 11. Annual compounding here is an <b>illustration only</b>, not a continuous
native account, verified strategy ROI, or broker-realized USD PnL. JPY/EUR/USD point-unit conversion,
actual bid/ask spreads, financing, lot multipliers, overnight carry and H1 initial-stop timing are unqualified.
The candidates are post-selected from observed history: no fresh OOS period.</div>
<h2>Summary</h2><table><thead>"""+agg.split("</tr>")[0]+"</tr></thead><tbody>"+agg.split("</tr>",1)[1]+"</tbody></table>"
    page+="<h2>Native annual-reset returns (1x direct cost)</h2><table><thead>"+annualhead+"</thead><tbody>"+"".join(annualrows)+"</tbody></table>"
    page+="".join(imgs)
    page+="<h2>Scientific interpretation</h2><p>C3 has the highest illustrated return, but C1 showed lower worst individual-year drawdown. The chart series require annual capital resetting and a hypothetical link that does not carry open trades. Do not treat any linked-proxy Sharpe/Calmar as a valid native continuous investment metric.</p>"
    page+="<footer>Source: native ml4t.backtest.Engine summaries, trades, fills and daily equity Parquet; computed diagnostics via ml4t.diagnostic.api.PortfolioAnalysis; ML4T tearsheet procedure applied with Matplotlib because the installed optional Plotly package is unavailable. No parameters optimized. No live orders.</footer></body></html>"
    (OUT/"tearsheet.html").write_text(page)

def main():
    curves,aggregate,years=summarize()
    OUT.mkdir(parents=True,exist_ok=True)
    make_graphs(curves,aggregate,years)
    html_report(aggregate,years)
    artifact={"status":"ML4T_TEARSHEET_PROXY_RECONCILED",
              "native_cells_verified":252,
              "important_warning":"Hypothetical linked annual resets, NOT continuous native backtest or tradable USD ROI",
              "meta":{"period":"2013 Jan1 through 2026 Oct11","tools":["ml4t.backtest.Engine","ml4t.diagnostic.api.PortfolioAnalysis","Matplotlib"],
                      "risk_metric_calendar_days_per_year":365,
                      "not_used":"ml4t.diagnostic.visualization native Plotly tearsheet unavailable due to missing optional plotly package"},
              "candidates":aggregate}
    (OUT/"linked_roi_diagnostics.json").write_text(json.dumps(artifact,indent=2)+"\n")
    print(json.dumps({"status":artifact["status"],
                      "tearsheet":str(OUT/"tearsheet.html"),
                      "linked":{c:{
                           "roi":a["hypothetical_linked_roi_pct"],
                           "sharpe_proxy":a["calendar_daily_proxy"]["sharpe"],
                           "maxdd_proxy":a["calendar_daily_proxy"]["maxdd_pct"],
                           "stress2_roi":a["cost_stress"]["2.0"]["hypothetical_compounded_roi_pct"]
                       }for c,a in aggregate.items()}},indent=2))
if __name__=="__main__":main()
