# Source archive: Mechanical Premia two-engine MVP

- Article: [Building a Multi-Strategy Portfolio (Part 1): Sizing Fast Engines vs. Patient Setups](https://mechanicalpremia.substack.com/p/building-a-multi-strategy-portfolio)
- Author: Mechanical Risk Premia
- Published: 2026-09-01T10:37:50+00:00
- Retrieved: 2026-10-13, via TinyFish `fetch_content`.
- Original MQL5 implementation: complete code block is present in the cited article. The source remains at the author URL; this archive records identity and audit scope without duplicating the full source code.
- Source-review targets: H1/D1 parameters and signal timing; `iBands` buffer indices; ATR windows and median selection; repeated D1 evaluation on each new H1; H1 stop initialization and trailing; D1 ghost stop used for sizing without a broker stop; account/margin sizing; and source exit conditions.
- Retrieved article states the H1 `iBands` upper buffer is index 1 and lower is index 2. The code calls buffer 1 for the H1 breakout threshold. The D1 manager uses buffers 1 and 2 for `%B`. Confirmed against the fetched code block; upstream MQL5 API documentation still requires separate source attribution for formal API semantics.
- Reported source portfolio risk split: 76.64% D1 and 23.36% H1, derived in the article from historical loss and frequency inputs. It is treated as a fixed hypothesis only.
- Scope limitation: the article's original broker instruments, tick values, commissions, spreads, financing, execution records, and full historical dataset are not supplied by this archive. Local ES/NQ files cannot be claimed to reproduce MT5 broker execution.
