# Build plan and decisions

The stages follow the build brief (section 12). Each stage stops for the owner's
approval before the next begins.

| Stage | Deliver | Status |
|---|---|---|
| 1. Skeleton | Project structure, config, README, cost ledger, dry-run mode | Approved |
| 2. Ingest | PDF, Word, Excel reading with section and page references | Approved |
| 3. Extract | Extraction with quote verification, using the construction pack | Built; awaiting the owner's first real run |
| 4. Calculate | **Duplicate merging**, then scoring, expected value, Monte Carlo, unit tests | Not started |
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
