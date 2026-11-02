# Data protection impact assessment (DPIA)

**Processing:** AI-assisted review of tender and project documents using the Tender Risk
Reviewer and the Claude API.  **Prepared by:** [name]  **Date:** [date]
**ICO registration:** ZC288139  **Next review:** [date + 12 months, or on any major change]

## 1. Why a DPIA

The processing uses new technology (an AI service) and sends document text, which may
contain personal data, to a supplier outside the UK. A DPIA is good practice here even if
it is not strictly required.

## 2. Description of the processing

- **Nature:** documents are split into sections on our computer. Section text is sent to
  the Claude API, which proposes risks with word-for-word quotes. The software checks the
  quotes, scores the risks and writes a Word report and Excel register. Files are stored
  on our computer under `outputs/`.
- **Scope:** names, job titles, signatures, contact details and CVs appearing incidentally
  in documents. About [number] reviews a year, [number] pages each.
- **Context:** data subjects are mainly business contacts and staff named in commercial
  documents. They would reasonably expect the documents to be read by the client's
  advisers. They may not expect AI to be used, so the privacy notice and client terms say so.
- **Purpose:** identify risks and recommend contingency. Personal data is not needed for
  the purpose; it is incidental.

## 3. Necessity and proportionality

- Lawful basis: contract with the client (we are processor) — see `02_record_of_processing.md`.
- Data minimisation: [ask clients to leave out CVs, personal appendices and signed forms
  where possible; remove them before review if received].
- AI outputs are not used to make decisions about individuals.
- Retention limited to [90] days for working files (automated purge command).
- Transparency: privacy notice; client terms name Anthropic as sub-processor.

## 4. Risks

| Risk to individuals | Likelihood | Severity | Overall |
|---|---|---|---|
| Unauthorised access to documents on our computer (loss, theft) | Possible | Moderate | Medium |
| Supplier (Anthropic) breach or misuse | Remote | Moderate | Low |
| Transfer to the USA without adequate safeguards | Remote | Moderate | Low (once safeguard confirmed) |
| Data kept longer than needed | Possible | Minimal | Low |
| Client not aware AI is used | Possible | Minimal | Low |

## 5. Measures to reduce the risks

| Risk | Measure | Result |
|---|---|---|
| Unauthorised access | Disk encryption, screen lock, access limited — `03_retention_and_security.md` | Reduced |
| Supplier | Anthropic DPA accepted on [date]; Anthropic's API data retention: [record from Anthropic's terms]; model training on API data: [record]; [consider zero-data-retention if offered] | Reduced |
| Transfer | Safeguard relied on: [DPF UK Extension / IDTA / UK Addendum] — checked on [date] | Reduced |
| Retention | `retention.keep_days` + monthly purge | Reduced |
| Awareness | Client processing terms and privacy notice name AI use and Anthropic | Eliminated |

## 6. Sign-off

| Item | Name / date | Notes |
|---|---|---|
| Measures approved by | | |
| Residual risk accepted by | | If residual risk stays high, you must consult the ICO before starting |
| Advice from [adviser], if any | | |
