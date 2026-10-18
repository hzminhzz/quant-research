# Arnal cross-sectional momentum with BTC regime conditioning

SOURCE_CAPTURE_ONLY. Source: Matias Arnal, original project: https://github.com/matiasjarnal/crypto-momentum-strategy . Publication date UNKNOWN.

The README describes 35 cryptocurrencies screened for 365 days of price history and 60-day median ADV of at least USD 5 million. Cross-sectional rankings are based on compound 10/20/60-day momentum, with within-date z-scores and outlier clipping. Its top three in-sample parameter settings are combined. It takes long positions in stronger assets and short positions in weaker assets. Position construction involves score-softmax weights, 30-day inverse volatility, weight smoothing alpha 0.25, and daily portfolio volatility targeting at 20 percent annually capped at 3x leverage. BTC relative to its 200-day moving average switches gross exposure between 1.0 and 0.5 and changes the number of positions and weighting.

AUTHOR-REPORTED RESULTS, UNVERIFIED: 2018-2022 training, 2023-2024 testing, 1.12 OOS Sharpe, -25.3 percent maximum drawdown, and an assumed 20 basis points per trade. The claimed market-neutral design also reports BTC beta 0.32; independence from the overall market is not established. README-to-notebook implementation consistency is not independently checked. Shortability and point-in-time eligibility of the chosen universe remain open.

Contrary practitioner evidence: https://github.com/prams2104/crypto-momentum-backtest reports out-of-sample weakening of a different 20-day rank momentum strategy and cost-sensitive short-term reversal. This is not the same strategy.

Unknown: trade clock, exact order fills, eligible prop-firm instruments, margin, leverage and drawdown permissions, shorting, financing and weekend constraints. No funding-based alpha, no ATS execution, no backtest, no protected reads and no orders.
