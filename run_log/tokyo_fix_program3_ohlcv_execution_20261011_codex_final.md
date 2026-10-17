Completed Program 3. [Full report](/home/quant/dev/quant/quant-research/docs/audit/tokyo_fix_program3_ohlcv_execution_20261011_v1.md).

At the assumed 1-pip roundtrip cost:

- Gotobi market benchmark: **+$212.27**.
- **11 of 12** conservative limit models lost money.
- The remaining model earned **+$18.99**, but lost money with the additional crossing buffer.
- Every limit model lost money in Jan–Aug 2026.

Independent verification passed **8,730 fills** and all 56 cost scenarios. The initial precision-defective runs remain preserved; corrected runs are authoritative.

The holdout remains sealed. All **811 checked original files** remain unchanged. Focused regressions passed 51 tests; final Program 3 tests passed 20. The full repository suite stalled and was interrupted.

**Robustness criterion failed. Strategy remains NOT_APPROVED.**