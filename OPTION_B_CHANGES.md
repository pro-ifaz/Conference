# Option B — Detailed Changes vs. the Previous Version

## 1. Data strategy (the core change)
| | Old version | New version (Option B) |
|---|---|---|
| Training start | Jan 2020 | **Jan 2019** |
| Total series length | 76 months | **88 months** (all 15 categories, after adding verified 2019 data) |
| Training cutoff for testing | May 2025 | **April 2025** |
| Test design | continuous Jun 2025–Apr 2026 | **3 separate horizons: 3, 6, 12 months** |
| Test target months | 12 months in a row | **Jul 2025, Oct 2025, Apr 2026** |
| 2027 projection base | data to Apr 2026 | data to Apr 2026 (88 months) |

Why this is better: starting in 2019 gives a full normal pre-COVID baseline, so the pandemic drop
is learned as a mid-series event. Three horizon-specific back-tests are more informative than one
continuous window, and each lands on a real, separately verified month.

## 2. New headline numbers (national Total Cases, ensemble)
- 3-month (Jul 2025): **97.8%** practical accuracy
- 6-month (Oct 2025): **92.8%**
- 12-month (Apr 2026): **86.1%**
- Mean: **92.2%**

## 3. Model ranking (rolling-origin, stable categories)
1. Ensemble — **8.96% MAPE, MASE 0.577**, beats Seasonal Naive 75% of the time
2. ETS 9.64% · Seasonal Naive 9.84% · Theta 10.19% · SARIMA 10.23% · ARIMA 10.63%
3. Naive 12.35% · LightGBM 14.82%

(These improved from the earlier 2020-start category numbers because the verified 2019 category
data was added — see Section 6.)

## 4. Robustness fix
A sanity guard was added to the forecasting library: any model output that is non-finite,
negative, or absurdly large (e.g. an occasional SARIMA divergence on the COVID break) is rejected
and replaced by the Seasonal Naive forecast, with the event logged. This prevents a single bad fit
from poisoning the ensemble and is recorded for audit.

## 5. Everything regenerated
New rolling-origin results, new 3-horizon back-test, new XAI (feature importance + error by
category), new scenario, and all 7 figures were regenerated from the executed notebook. The paper
was rewritten from scratch.


## 6. Verified 2019 category data added (final update)
Earlier, only national Total Cases was available for 2019, so per-category analysis started in 2020.
The signed PHQ "Crime Statistics, January--December 2019" statement was then provided, giving the
full 15-category breakdown for all 12 months of 2019. Each month's 15 categories were checked to
sum exactly to the printed monthly Total Cases (12 of 12 match). With this added:
- **Every crime category now spans 88 months (Jan 2019 -- Apr 2026).**
- Stable-category accuracy improved at every horizon (12-month: 87.9% -> 89.9%).
- The headline back-test (97.8 / 92.8 / 86.1) is unchanged, because Total Cases already used 88 months.
- The previous "category data only from 2020" limitation is now fully resolved.
