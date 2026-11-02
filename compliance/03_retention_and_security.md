# Retention and security policy

**Applies to:** [Business name]. **Owner:** [name]. **Last reviewed:** [date].

## Retention

| What | Where | Keep for | How it is deleted |
|---|---|---|---|
| Documents received from clients | Your client folders; `outputs/uploads` | [90] days after the report is delivered | Delete client folder; `python -m risk_engine purge` |
| Run results (extracts, quotes, audit files, report drafts) | `outputs/<run>` | [90] days | `python -m risk_engine purge` |
| Final report sent to client | [Client archive folder] | [6 years] | Manual review each year |
| Spending ledger | `ledger/` | Indefinitely (contains costs only, no personal data) | — |
| Emails with documents attached | [Email system] | [90] days | Delete attachments / emails |
| Invoices | [Accounting software] | 6 years | Accounting software |

Set `retention.keep_days` in `config/settings.yaml` to match the first two rows, and run
the purge on the **first working day of each month**:

```
python -m risk_engine purge
```

It lists what it will delete and asks you to type YES. Delete a client's files sooner if
the client asks.

## Security measures

- [ ] Full-disk encryption on every computer used (BitLocker / FileVault).
- [ ] Strong password or PIN and automatic screen lock (5 minutes).
- [ ] Operating system and Python kept up to date; antivirus on.
- [ ] The API key is kept only in an environment variable, never in files or email.
- [ ] Anthropic Console account protected with a strong password and two-factor sign-in.
- [ ] Documents received only by [secure method]; never through personal email.
- [ ] Backups (if any) encrypted, and old backups deleted on the same schedule.
- [ ] `outputs/` and `ledger/` are never committed to GitHub (the project already blocks this).
- [ ] Reports reviewed by a competent person before they leave the business.
- [ ] Only [names] have access to client documents.
