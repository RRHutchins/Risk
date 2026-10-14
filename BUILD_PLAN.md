# Build plan and decisions

The stages follow the build brief (section 12). Each stage stops for the owner's
approval before the next begins. On 14 October 2026 the owner asked for all remaining
stages to be finished without stopping.

| Stage | Deliver | Status |
|---|---|---|
| 1. Skeleton | Project structure, config, README, cost ledger, dry-run mode | Approved |
| 2. Ingest | PDF, Word, Excel reading with section and page references | Approved |
| 3. Extract | Extraction with quote verification, using the construction pack | Built and tested without the API (see below); owner chose to proceed |
| 4. Calculate | **Duplicate merging**, then scoring, expected value, Monte Carlo, unit tests | Built; owner asked to finish all stages |
| 5. Report | Word, Excel, JSON outputs | Built |
| 6. Opportunity and synthesis | Opportunity finder, narrative, bid / no-bid summary | Built |
| 7. Interface | Local web page and batch mode | Built |
| 8. Test and tune | Run 30 to 50 public tender packs; fix what breaks | Tools built; the 30-50 live pack runs need the owner's key and downloaded packs |
| 9. Second pack | Minimal `generic_iso31000` pack | Built; runs with zero engine changes |

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
- **Numbers in the written summary** (Stage 6): Claude writes figures only as
  placeholders (for example {P80_MONEY}) that code fills in; any other figure not
  present in the facts supplied (calculated values, IDs, clause references, quotes) is
  removed and counted in the report's method section.
- **Bid / no-bid**: a rule-based indicator from the pack's `decision` rules is always
  shown; Claude's written view is compared with it and any difference is flagged.
- **Opportunity finder model**: Sonnet (the classification model) proposes
  mitigations and opportunities; Opus writes the summary, as the brief suggests.
- **Batch mode** (Stage 7): extraction uses the Message Batches service at half
  price; the small merging, opportunity and summary steps use normal calls. Per-pack
  cap and total budget are checked before sending, because a batch cannot be stopped.
- **Stage 8 without live runs**: the test, regression and target-checking tools are
  built and tested with a simulated batch service. Testing at realistic scale with
  stand-in findings quoting the real Bradford agreement found and fixed two problems:
  documents that contain dotted signature lines ("....") were wrongly rejected as
  joined passages, and a stray copy of the tool's own reference label in a quote is
  now removed before checking. Word's private bullet symbols are removed from chart
  labels. The 30 to 50 live pack runs remain for the owner.
- **Engine wording** was made pack-driven in its own commit (ccaf86a) before the second
  pack was added; the generic pack was then added with no engine changes.
