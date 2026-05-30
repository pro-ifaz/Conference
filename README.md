# Bangladesh Reported-Crime Forecasting & Monitoring — Complete Package (Option B, May 2026)

This package contains everything for the IEEE paper *"From Verification to Forecasting:
Monitoring Official Crime Trends in Bangladesh"* plus the working monitoring software.

**Authors:** Ifaz Ahmed Chowdhury, Jubair Ahmed, Sakib Abdullah, and Md. Imran Hasan Shanto
(Dept. of CSE, BUBT, Dhaka, Bangladesh).

## What changed in this version (Option B)
The earlier version trained on Jan 2020–May 2025 and tested on a continuous June 2025–April 2026
window. This version uses a cleaner, stronger protocol:

- **Training data now starts in January 2019** (national Total Cases, 88 months total), so the
  models (for every crime category) learn from a full pre-pandemic baseline and treat the 2020 COVID drop as a mid-series
  event rather than a starting shock.
- **Post-release back-test at four horizons.** We train only up to **April 2025**, then forecast
  **1, 3, 6, and 12 months ahead** (May, July, October 2025, and April 2026) and compare each
  against the real PHQ numbers released later.
- **Back-test result (national Total Cases, single origin):** 98.9% at 1 month, 97.8% at 3 months,
  92.8% at 6 months, 86.1% at 12 months.
- **Rolling-origin validation (averaged over the stable categories):** 94.7% at 1 month down to
  89.9% at 12 months. The back-test and the rolling-origin numbers measure different things and are
  reported separately.
- The December 2027 projection now uses all 88 verified months, but remains a planning scenario
  with no accuracy claim.

### Latest update (May 2026)
Final pre-submission pass on the paper; the analysis and all numbers are unchanged.
- Retitled to *"From Verification to Forecasting: Monitoring Official Crime Trends in Bangladesh."*
- Author block finalized (four authors with institutional emails).
- Public **dataset** and **monitoring-software** repositories added to the paper's references.
- Abstract now explicitly labels the two accuracy metrics — the single-origin back-test (national
  Total Cases) and the rolling-origin average (stable categories) — so they are not mistaken for an
  inconsistency.
- PHQ source citation range corrected to January 2019 (2019 is from the consolidated annual
  statement; recent months from monthly statements).
- `outputs/csv/_results.json` back-test array completed with the 1-month horizon (98.9%).

## Folder guide
```
README.md                         <- this file
OPTION_B_CHANGES.md               <- detailed list of changes vs the old version
CONTEXT_NOTES.md                  <- the 9 review points and how each was addressed
dataset/                          <- verified source spreadsheet (Jan 2019 - Apr 2026)
notebooks/                        <- executed analysis notebook (all numbers + figures)
ieee_paper/                       <- main.pdf, main.tex, references.bib, figures/
software_crime_monitoring_system/ <- production Streamlit monitoring app (18/18 tests)
outputs/csv/                      <- all result tables
outputs/figures/                  <- all 7 paper figures (PNG)
```

## How to reproduce
```bash
# 1. Re-run the analysis
cd notebooks
pip install pandas numpy statsmodels lightgbm scikit-learn matplotlib
jupyter notebook bd_crime_thesis_OPTION_B_2026May.ipynb   # Run All

# 2. Rebuild the paper
cd ../ieee_paper
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex

# 3. Run the monitoring app
cd ../software_crime_monitoring_system
pip install -r requirements.txt
streamlit run app.py
```

## Honest boundaries
This system forecasts **reported** crime counts (what police recorded), not hidden crime, and does
not predict individuals or locations. Short-term forecasts are stronger than long-term ones. The
2027 figures are a scenario, not a verified prediction.
