# Crypto Research Run — 30-Day Past Market Alpha

## Conclusion

**REJECT.** The canonical 30-day market-model alpha factor failed the development gate. Mean rank IC was -0.0029 with HAC p=0.895. The 7-day and 60-day neighbors also lacked significant positive IC, so 2024–2025 OOS was not consumed.

## Source

Cakici et al. (2024), *Machine learning and the cross-section of cryptocurrency returns*, International Review of Financial Analysis, DOI 10.1016/j.irfa.2024.103244.

## Pre-Registered Specification

Rolling market-model intercept alpha over 7d / **30d canonical** / 60d; equal-weight crypto market factor; weekly long top-alpha quartile / short bottom-alpha quartile; point-in-time top-80% trailing-dollar-volume universe.

## Development Diagnostics

| Window | Mean IC | HAC p | Top-minus-bottom |
|---:|---:|---:|---:|
| 7d | 0.0014 | 0.959 | +1.26% |
| **30d** | **-0.0029** | **0.895** | **+1.30%** |
| 60d | -0.0152 | 0.572 | +0.25% |

The fixed gate required IC >=0.02, HAC p<0.05, and a positive spread. The canonical signal failed the IC conditions.

## Results

OOS consumed: **No**. OOS Sharpe, DSR, PBO and robustness are N/A.

## Multiple-Testing Audit

Previous trials 36; new trials 3; cumulative **39**.

## Decision

**REJECT**

## Provenance

Runner SHA256: `922bbb2ad6bdb2e08eb225cdb0249ff36489a7dfb7c4c13df144b54ce8e17023`.
