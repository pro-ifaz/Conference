# How the 9 Review Points Were Addressed

1. **Data strategy** — Done. Train 2019→Apr 2025, back-test 1/3/6/12 months (May/Jul/Oct 2025, Apr 2026),
   scenario uses all 88 months. New notebook generated with executed outputs and figures.
2. **Claims about prior work** — Done. We researched the published papers. Biswas & Basak (2019)
   document a single train–test regression split. After researching, we state we *have not seen
   documented evidence* of source-verification audits, post-release back-testing, or XAI in the
   prior Bangladesh studies — phrased so it does not overstate.
3. **Software as a contribution** — Done. Added as Contribution #4 and a dedicated section, written
   as bullet points.
4. **Definitions for everyone** — Done. A "Key words in plain language" subsection explains
   horizon, back-testing, rolling-origin, leak-free, and practical accuracy in kid-friendly terms.
5. **Five-step audit, numbered + simple English** — Done. The audit is a numbered 1–5 list using
   plain phrases ("Do the numbers add up?", "Does each number match the original document?").
6. **Less repetition** — Done. Jargon phrases are introduced once, then referred to simply.
7. **Scannable format** — Done. Bullets and numbered lists throughout (contributions, audit,
   methods, software, limitations, future work).
8. **Readable by non-experts who care about the country** — Done. Plain, direct English; the
   introduction and conclusion speak to planners and citizens, not only researchers.
9. **From-scratch rewrite after retraining** — Done. The notebook was re-run and the paper was
   written fresh around the new numbers.

## Latest revision (May 2026)
Applied after the 9 points above, during the final pre-submission pass. The numbers and the
analysis did not change.

10. **Title.** Changed to *"From Verification to Forecasting: Monitoring Official Crime Trends in
    Bangladesh."*
11. **Authorship.** Four authors with institutional emails (Ifaz Ahmed Chowdhury, Jubair Ahmed,
    Sakib Abdullah, Md. Imran Hasan Shanto — Dept. of CSE, BUBT).
12. **Companion artifacts cited.** The verified dataset and the monitoring software are now public
    repositories and are cited in the paper's references.
13. **Accuracy metrics labeled in the abstract.** An external review read the single-origin
    back-test (98.9 / 97.8 / 92.8 / 86.1, national Total Cases) and the rolling-origin average
    (94.7 → 89.9, stable categories) as inconsistent. They are not — they measure different things.
    The abstract now names both explicitly so they cannot be misread; Sections V-A and V-B already
    did. No number changed; both sets were re-verified against the output CSVs and the source
    spreadsheet (88 months, 1,584 rows, zero internal mismatches).
14. **Source citation range.** The PHQ citation range was corrected to January 2019 to match the
    dataset, with a note that 2019 comes from the consolidated annual statement while recent months
    come from monthly statements.
15. **Results JSON completeness.** `outputs/csv/_results.json` now includes the 1-month back-test
    row (98.9%), matching `backtest_3horizon_results.csv`.
