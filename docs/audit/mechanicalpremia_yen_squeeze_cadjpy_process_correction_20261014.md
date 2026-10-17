# CORRECTION: CADJPY source availability, 2026-10-14

Read-only independent verification after `mechanicalpremia-yen-squeeze-proxy-20261014` was frozen:
- CADJPY staging location: `/home/quant/dev/quant/ml4t-data/.data/staging/dukascopy-cadjpy-20261013/`.
- The source downloader **WAS AND IS RUNNING**, contrary to the assertion in the frozen two-pair YAML that no active downloader was visible. `ps` showed PID 2317144, started under parent 2247666, with command `node -e` using installed Dukascopy-node and an Arrow file per year.
- The `cadjpy_2023.arrow` file exists, schema `timestamp[ms]`, OHLCV float64, symbol; 371788 rows. `cadjpy_2024.arrow` had not yet appeared at the time of this correction. Do not read 2025+ source data.
- The original two-pair session is ALREADY FROZEN. Do not change its spec or claim CADJPY was never being downloaded. Preserve its trial history and correct the factual assertion in research reporting.
- When 2024 arrives, create ANOTHER distinct pre-registered, frozen three-pair session **before any three-pair performance run**. The old two-pair session remains legitimate as a distinct exploratory sensitivity, not three-pair source replication. Require a development-only CADJPY input checksum/coverage audit and independent validation.
- Do NOT interrupt, re-run or replace the downloader; preserve unrelated concurrent data work.
