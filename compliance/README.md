# Data protection pack

Drafts to help you meet UK GDPR and the Data Protection Act 2018 when you use the
Tender Risk Reviewer. **They are templates, not legal advice.** Fill in every
`[square bracket]`, read each document properly, and get advice if you are unsure (the
ICO's free helpline for small businesses is 0303 123 1113).

ICO registration number: **ZC288139**

## Checklist

| # | Step | Where | Who | Status |
|---|------|-------|-----|--------|
| 1 | Register with the ICO and pay the fee | ico.org.uk | You | Done (ZC288139) |
| 1a | Renew the fee every year; update the entry if details change | ico.org.uk | You | Diary reminder: [renewal date] |
| 2 | Keep a record of what you process | [02_record_of_processing.md](02_record_of_processing.md) | You fill in | Draft |
| 3 | Work out your role and lawful basis for each kind of work | [02_record_of_processing.md](02_record_of_processing.md) | You fill in | Draft |
| 4a | Accept Anthropic's Data Processing Addendum and check its UK transfer terms | Anthropic Console / [anthropic.com/legal](https://www.anthropic.com/legal) | You | To do |
| 4b | Put processing terms in place with each client | [05_client_processing_terms.md](05_client_processing_terms.md) | You and each client | Draft |
| 5 | Publish a privacy notice | [01_privacy_notice.md](01_privacy_notice.md) | You publish it (website, proposals) | Draft |
| 6 | Data protection impact assessment | [04_dpia.md](04_dpia.md) | You review and sign | Draft |
| 7 | Retention and security | [03_retention_and_security.md](03_retention_and_security.md); `python -m risk_engine purge` | Tool + you | Tool done; policy draft |
| 8 | Breach procedure and log | [06_breach_procedure_and_log.md](06_breach_procedure_and_log.md) | You | Draft |
| 9 | Handle rights requests (access, erasure etc.) | [07_rights_requests.md](07_rights_requests.md) | You | Draft |

## What is already done in the software

- The ICO number is printed in the footer of every Word report and on the web page
  (`ico_registration` in `config/settings.yaml`).
- Documents are processed on your computer; text is sent only to the Claude API.
- `outputs/` and `ledger/` are never uploaded to GitHub.
- The API key is never written into any file.
- `python -m risk_engine purge` deletes run results and uploaded documents older than
  `retention.keep_days` (90 days by default) in `config/settings.yaml`.

## Things only you can do

- Pay and renew the ICO fee.
- Accept Anthropic's DPA (it is part of Anthropic's Commercial Terms for API customers) and
  read how long Anthropic keeps API data and what UK transfer safeguard it relies on.
  Record what you find in the DPIA, section 5.
- Agree processing terms with clients and sign them.
- Publish the privacy notice and keep it up to date.
- Turn on full-disk encryption (BitLocker on Windows, FileVault on Mac) and a screen lock.
- Set a monthly reminder to run `python -m risk_engine purge`.
