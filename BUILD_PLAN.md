# Build plan and decisions

The stages follow the build brief (section 12). Each stage stops for the owner's
approval before the next begins.

| Stage | Deliver | Status |
|---|---|---|
| 1. Skeleton | Project structure, config, README, cost ledger, dry-run mode | Approved |
| 2. Ingest | PDF, Word, Excel reading with section and page references | Approved |
| 3. Extract | Extraction with quote verification, using the construction pack | Built and tested without the API (see below); owner chose to proceed |
| 4. Calculate | **Duplicate merging**, then scoring, expected value, Monte Carlo, unit tests | Built; awaiting approval |
| 5. Report | Word, Excel, JSON outputs | Not started |
| 6. Opportunity and synthesis | Opportunity finder, narrative, bid / no-bid summary | Not started |
| 7. Interface | Local web page and batch mode | Not started |
| 8. Test and tune | Run 30 to 50 public tender packs; fix what breaks | Not started |
| 9. Second pack | Minimal `generic_iso31000` pack | Not started |

## Decisions

- **Duplicate merging moves into Stage 4** (owner, 11 October 2026). The brief's
  `classify` module (merge duplicates; Claude, then code) is not in any stage of the
  brief's table. It runs before scoring, so that one risk found in two documents is
  not counted twice in the contingency. Every merged record keeps all its source
  quotes and references.
- **No server-side refusal fallback** (Stage 3). For Sonnet 5.5 it only retries
  declines about cyber-attacks or building rival AI models, which tender documents do
  not trigger, and it is not available in batch mode. Declined pieces are reported as
  not reviewed.
- **Extraction effort set to "medium"** (Stage 3) to control cost; adjustable in
  `config/settings.yaml`.
- **Regression set**: the Harrogate invitation to tender and the Bradford supply
  agreement (public documents supplied by the owner, kept outside the repository)
  are the first two of the three fixed regression packs (brief section 13).
- **Stage 3 accepted without a live run** (owner, 12 October 2026): no time to run it.
  Tested instead with a simulated Claude, a wire-level test of the real SDK, and quotes
  written from page images of the Bradford agreement (17 of 17 handled correctly).
  The first real run is still the true acceptance test; check its Run summary sheet.
- **Simulated mean versus expected value**: the brief defines expected value with the
  most likely impact; the simulation uses the full PERT range. Both are reported, and
  the difference is explained in the outputs.
- **Correlation method**: risks in the same correlation group are correlated in whether
  they occur (Gaussian copula) and in size (Iman-Conover rank reordering), at the
  configured correlation (default 0.5).
- **Tornado measure**: each risk's average cost in the simulated runs near P80
  (between P75 and P85), so the bars roughly add up to the P80 figure.
- **Merged numbers**: a merged risk keeps the likelihood and impacts of its strongest
  member (highest probability x most likely impact); merging never invents numbers.
