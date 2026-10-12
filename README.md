# Tender Risk Reviewer (prototype)

This tool reads a construction tender pack and tells a contractor what risks they
would be taking on, what to do about them, and how much contingency to price in.

**Current status: Stage 4 of 9 (scores and contingency).** The tool reads a folder of
tender documents, splits them into clauses with page references, and asks Claude to
find the risks and answer the checklist. Every quote Claude gives is checked against
the documents by the software; findings whose quote cannot be found are set aside.
Duplicates are merged, then the software scores every risk (red, amber, green) and
simulates how much contingency to price in (P50, P80, P90). The Word report, the
opportunity finder and the bid / no-bid summary come in later stages.

> Automated risk screening for review by a competent person. Not legal advice.

---

## Part 1: One-time setup

You only do this once per computer. It takes about 10 minutes.

### Step 1. Install Python

Python is the free program that runs this tool.

**Windows**
1. Go to <https://www.python.org/downloads/> and click the yellow **Download Python** button.
2. Open the downloaded file.
3. On the first screen, **tick the box "Add python.exe to PATH"** at the bottom. This is important.
4. Click **Install Now**, then **Close** when it finishes.

**Mac**
1. Go to <https://www.python.org/downloads/> and click the yellow **Download Python** button.
2. Open the downloaded file and click through the installer (Continue, Agree, Install).

You need version 3.10 or newer. Any version you download today will be fine.

### Step 2. Get the tool onto your computer

1. Go to <https://github.com/RRHutchins/Risk>.
2. Click the branch menu near the top left (it shows a branch name such as `main`) and
   pick the branch you were told to use (for Stage 1: `claude/build-brief-stage-1-rrn4wf`).
3. Click the green **Code** button, then **Download ZIP**.
4. Find the ZIP in your Downloads folder and unzip it:
   - Windows: right-click it, choose **Extract All**, then **Extract**.
   - Mac: double-click it.
5. The unzipped folder is named after the branch, for example
   `Risk-claude-build-brief-stage-1-rrn4wf`.
   - **Windows:** "Extract All" often puts it inside a second folder with the same name,
     so you may see `Risk-claude-build-brief-stage-1-rrn4wf` inside
     `Risk-claude-build-brief-stage-1-rrn4wf`. Open folders until you reach the one that
     directly contains `README.md` and `requirements.txt`. **That is the folder to use.**
   - **Mac:** the folder directly contains `README.md` and `requirements.txt`.
6. Move that folder somewhere easy to find, for example your Documents folder, and
   rename it to `Risk`. The rest of these instructions call it the `Risk` folder.

### Step 3. Open a command window in that folder

A command window is a box where you type instructions to the computer.

**Windows**
1. Open the `Risk` folder in File Explorer. You should see files such as `README.md` and `requirements.txt`.
2. Click once in the address bar at the top (where the folder path is shown).
3. Type `cmd` and press **Enter**. A black window opens, already pointing at the folder.

**Mac**
1. Open **Terminal** (press Cmd + Space, type `Terminal`, press Enter).
2. Type `cd ` (the letters c, d, then a space). Do not press Enter yet.
3. Drag the `Risk` folder from Finder into the Terminal window. Its location appears.
4. Press **Enter**.

### Step 4. Install the tool's libraries

Copy each line below into the command window and press **Enter** after each one.
Wait for each to finish before typing the next.

**Windows**
```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The `py` command is installed by the python.org installer in Step 1. If you already
had Python from somewhere else (for example the Microsoft Store or Anaconda) and
`py` is "not recognized", either install Python from python.org as in Step 1, or
use `python` instead of `py` in the first line: `python -m venv .venv`.

**Mac**
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

What these do: the first line creates a private workspace for the tool (a folder
called `.venv`), the second switches it on, and the third downloads the libraries
the tool needs. You will see a lot of text scroll past; that is normal.

After the second line, your command line starts with `(.venv)`. That shows the
workspace is switched on.

### Step 5. Check everything worked

```
python -m risk_engine check
```

You should see a list of items marked `installed` or `loaded`, ending with **All good.**
The API key line will say "not set" until you do Step 6.

### Step 6. Set up your Claude API key (needed for finding risks)

The API key is like a password that lets the tool use your Anthropic account. Keep it
private. It is never stored in this project's files.

**Get a key**
1. Go to <https://console.anthropic.com> and sign in.
2. Add credit under **Settings > Billing** if you have not already.
3. Recommended safety net: under **Settings > Limits**, set a monthly spend limit
   (for example $100, your build-and-test budget). Anthropic then refuses anything
   beyond it, whatever happens on your computer.
4. Go to **Settings > API Keys**, click **Create Key**, give it a name such as
   `tender-risk`, and copy the key. It starts `sk-ant-`. You will not be shown it again.

**Store the key on your computer**

- **Windows:** in the command window, type the line below, replacing the example with
  your key (keep the quotes), and press Enter:
  ```
  setx ANTHROPIC_API_KEY "sk-ant-your-key-here"
  ```
  You should see `SUCCESS: Specified value was saved.` **Close the command window and
  open a new one** (Step 3), then switch the workspace on again. The key only works in
  windows opened after this.
- **Mac:** in Terminal, type the line below, replacing the example with your key (keep
  both sets of quotes), and press Enter:
  ```
  echo 'export ANTHROPIC_API_KEY="sk-ant-your-key-here"' >> ~/.zshrc
  ```
  **Close Terminal and open it again** (Step 3), then switch the workspace on again.

Check it worked: run `python -m risk_engine check`. The API key line should say `found`.

To change the key later, repeat the step with the new key (on a Mac, also delete the
old line from the file `.zshrc` in your home folder).

---

## Part 2: Using the tool

Only `extract` sends anything anywhere or costs anything. Everything else is free and
stays on your computer.

### Every time you start

Open a command window in the `Risk` folder (Step 3 above), then switch the workspace on:

- Windows: `.venv\Scripts\activate`
- Mac: `source .venv/bin/activate`

### Check how the documents were split (Stage 2)

This reads every document, splits it into clauses and sections, and lists them so you
can check that the references are right.

- Windows: `python -m risk_engine ingest samples\demo_tender`
- Mac: `python -m risk_engine ingest samples/demo_tender`

For each document you will see a numbered list of its sections, each with a reference
such as `Z3 Ground conditions (pages 1-2)` or `clause 4.2 in '4. Evaluation' (page 2)`.
The same list, **with the full text of every section**, is saved as `sections.xlsx` in
a new folder inside `outputs`. The window shows exactly where. Open it in Excel to
check the splitting. Its second sheet lists every file with any warnings or notes.

How references work:

| File type | Split into | Reference shows |
|---|---|---|
| PDF | clauses and headings | the page, or pages if a clause runs over a page break |
| Word | headings and numbered clauses (tables stay with their clause) | the page as Word last laid it out, where Word saved this |
| Excel | blocks of 50 rows per sheet | the sheet and row numbers |
| Text | clauses and headings | the line numbers |

Things to know:
- Headers and footers repeated on most PDF pages (such as "Page 3 of 40") are removed
  automatically, and a note says so.
- A contents list at the front of a document is kept together as one section called
  "contents list", so its entries are not mistaken for the clauses themselves.
- Footnotes, cross-references that happen to start a line ("... in accordance with /
  Clause 4.2"), and repeated stamps (such as "REDACTED UNDER FOIA 43 COMMERCIAL
  INTERESTS") are kept as text but do not start new sections.
- Numbered items inside a schedule or appendix are called "paragraph" and name their
  schedule, for example `paragraph 1.1 in '1. WORKS PERIOD REPORTING', SCHEDULE 6`.
- Word's automatic paragraph numbering is not part of the text, so where a document
  relies on it, references use the nearest heading instead. A note tells you when.
- Files that cannot be read are listed with the reason and what to do, for example
  "this is an old-style Word file. Open it in Word and use File > Save As > Word
  Document (.docx)".

### Estimate the cost of a review (dry run)

A dry run reads the documents in the same way and then estimates what a real review
would cost.

- Windows: `python -m risk_engine dry-run samples\demo_tender`
- Mac: `python -m risk_engine dry-run samples/demo_tender`

You will see:
- each document that was read, its type, and how much text it contains
- any warnings (for example, a scanned PDF with no readable text)
- any files that were skipped, and why
- an estimated cost for a real review, step by step, compared with your per-run cap
- where the sections list and the audit file were saved

Add `--batch` at the end to see the cost using batch pricing (half price, for
unattended runs where speed does not matter).

### Use your own tender pack

1. Put all the tender documents in one folder. PDF, Word (`.docx`), Excel (`.xlsx`),
   text and CSV files are read. Sub-folders are included.
2. Type `python -m risk_engine ingest ` or `python -m risk_engine dry-run ` (with a
   space at the end), then drag the folder into the command window, and press **Enter**.

If you type the path yourself and it contains spaces, put it in double quotes, for example:
`python -m risk_engine dry-run "C:\Tenders\Riverside Bridge"`

The sample in `samples/demo_tender` is a small, made-up tender pack used for testing.

### Find the risks (Stage 3; spends API credit)

- Windows: `python -m risk_engine extract samples\demo_tender`
- Mac: `python -m risk_engine extract samples/demo_tender`

Before anything is sent, the tool shows how many pieces of text it will send, the
estimated cost, your per-run cap and your remaining budget. It stops by itself if the
estimate is over the cap or your budget. Type `yes` and press Enter to start, or just
press Enter to cancel.

While it runs, each piece is listed as it finishes, with the number of findings and
its cost. Pieces are sent four at a time, so a typical tender pack takes a few
minutes. The demo pack costs about $0.15. If the run would pass the per-run cap, it
stops before sending the next piece and keeps what it has done.

When it finishes, it saves a new folder in `outputs` containing:

| File | What it is |
|---|---|
| `records.xlsx` | **Open this.** The findings, for you to check. See below. |
| `extraction_audit.json` | Everything needed to reproduce and audit the run: every finding, every quote check, the exact instructions sent to Claude, the model used, tokens and cost of each call. |
| `sections.xlsx` | How the documents were split (as in Stage 2). |

`records.xlsx` has five sheets:
- **Run summary**: pieces reviewed, findings accepted and excluded, share of quotes
  verified, checklist questions answered, cost and time.
- **Risk records**: each finding, with its type (threat or opportunity), category,
  description, the document and exact reference (worked out by the software from where
  the quote was found), the quote, Claude's likelihood and impact judgements with
  reasons, existing controls, suggested response and confidence.
- **Excluded**: findings set aside, each with the reason, for example "quote not
  verified: quote not found in the document". These are not used further.
- **Checklist**: the 10 checklist questions, each "answered" (with its quote),
  "answer found but quote not verified", or "not found in the documents".
- **Pieces reviewed**: every piece of text sent, and whether Claude reviewed it.
  Anything marked refused, too_long or skipped was **not reviewed** and needs a look
  by hand.

Likelihood and impact are Claude's judgements, given with reasons. Scores, money and
contingency are calculated by the software in Stage 4.

### Review a tender pack in one go (Stages 3 and 4; spends API credit)

```
python -m risk_engine review samples\demo_tender --contract-value 2500000
```
(On a Mac, use `/` instead of `\`.) The contract value can be written as `2500000`,
`2,500,000`, `2.5m` or `750k`. Leave it out to see percentages only.

This does everything in the two sections above and below in one run: it shows the
estimate and asks you to confirm, finds the risks, merges duplicates, and works out
scores and contingency. The per-run cap covers the whole run.

### Work out scores and contingency (Stage 4)

If you have already run `extract`, you can calculate (or recalculate) from its results
without reading the documents again:

```
python -m risk_engine calculate "outputs\<the run folder>" --contract-value 2500000
```
Tip: type the start of the command, then drag the run folder from `outputs` into the
window. This makes one small call to Claude to merge duplicates (usually under $0.05).
Add `--no-merge` to skip that and spend nothing.

**Changing Claude's judgements.** Open `records.xlsx` in the run folder, and in the
**Risk records** sheet change any of: *Likelihood (1-5)*, *Impact min %*, *Impact
likely %*, *Impact max %*, *Correlation group*. To leave a risk out, delete its row.
Save, close Excel, and run `calculate` again. Your changes are used and listed in the
results under **Your edits**. Every calculation is saved in a new folder, so earlier
results are never overwritten. The same records always give exactly the same numbers.

**What you get** (`risk_calculation.xlsx`, in a new folder inside the run folder):

| Sheet | What it shows |
|---|---|
| Summary | Red / amber / green counts, expected value, and contingency at P10, P50, P80, P90 and the mean, as % of contract value and in money. Simulation settings. |
| Register | Every risk, red first, with its rating colour, score, probability, impact range, expected value, flags and all its sources. |
| Top contributors | The risks that drive the P80 contingency most, with a bar chart (the "tornado"). |
| Cumulative curve | The chance that the net risk cost stays at or below each value, with a chart. Read P80 as: "an 80% chance the risk cost is no more than this". |
| Merging | Which records were merged as duplicates, and any groupings refused by the software. |
| Your edits | Changes taken from `records.xlsx`. |

**How the numbers are worked out** (all by the software, never by Claude):
- **Score** = likelihood score x impact score (impact score from the *most likely*
  impact, using the bands in the pack). Red 15 and above, amber 8 to 14, green 7 and
  below. Any uncapped liability or uncapped delay damages is red whatever its score.
- **Probability** used in the simulation is the middle of each likelihood band
  (for example "Possible", 15 to 35%, uses 25%).
- **Expected value** = probability x most likely impact, added up, with opportunities
  counted as savings.
- **Simulation**: 10,000 runs. In each, every risk happens or not according to its
  probability, and if it happens its cost is drawn from its minimum / most likely /
  maximum range (a PERT curve). Risks with the same correlation group tend to happen
  together and be large together (correlation 0.5). Opportunities reduce the total.
  The random seed is fixed, so the same inputs always give the same answer.
- The **simulated mean** is usually higher than the expected value, because the
  simulation uses the whole impact range while the expected value uses only the most
  likely figure.
- **Duplicate merging**: Claude suggests which records describe the same risk; the
  software checks each suggestion (same type, no record used twice) and keeps the
  numbers of the strongest record, with every source quote.

All of these settings (iterations, seed, PERT or triangular, correlation, percentiles,
scales and thresholds) can be changed in `config/settings.yaml` and the pack's
`pack.yaml`.

### See your spending to date

```
python -m risk_engine ledger
```

This shows the total spent so far, your overall budget, and what remains. Dry runs
are recorded with an estimate but $0 actual spend. Times on screen are your computer's
local time. The ledger file itself (`ledger/spend_ledger.csv`) records times in UTC
(UK winter time), so it reads the same on any computer.

---

## Part 3: What is where

| Folder or file | What it is |
|---|---|
| `config/settings.yaml` | **The settings you can change**: models, prices, spending cap, how hard Claude thinks, simulation settings. Every line is explained. |
| `packs/construction_tender/` | The construction tender "domain pack": risk categories, scales, checklist, worked examples, and the instructions given to Claude (`extract_prompt.md`, in plain English). Edit these to change what the tool looks for. |
| `samples/demo_tender/` | A small, made-up tender pack for testing. |
| `outputs/` | Results of each run, one folder per run, including the sections list and the audit file. Each folder is named with the date, the time and a short random code, so no run ever overwrites another. Stays on your computer. |
| `ledger/spend_ledger.csv` | The running record of every run and every dollar spent. Opens in Excel. Stays on your computer. |
| `risk_engine/` | The program itself. You never need to edit this. |
| `tests/` | Automatic checks that the calculations are right. |

### Changing a setting

Open `config/settings.yaml` in Notepad (Windows) or TextEdit (Mac). Change the number
after the colon, keeping the spaces at the start of the line exactly as they were, and
save. For example, to raise the per-run cap to $5, change `per_run_cap_usd: 3.00` to
`per_run_cap_usd: 5.00`.

On a Mac, if TextEdit shows formatting options, choose **Format > Make Plain Text** before saving.

---

## Your data and your API key

- Documents are read on your own computer. Only the `extract` command sends document
  text anywhere, and then only to the Claude API (Anthropic) for review. Nothing is
  uploaded anywhere else.
- The API key is read from an environment variable called `ANTHROPIC_API_KEY` (see
  Step 6). It is never written into any file in this project, the logs or the audit file.
- `outputs/` and `ledger/` are excluded from GitHub, so your results stay private.

---

## Troubleshooting

| You see | What to do |
|---|---|
| `'py' is not recognized` | See the note under Step 4: install Python from python.org, or use `python` instead of `py`. |
| `'python' is not recognized` or `command not found: python` | On Windows, reinstall Python and tick "Add python.exe to PATH". On a Mac, use `python3` instead of `python` before switching the workspace on. |
| `No such file or directory: 'requirements.txt'` | You are in the wrong folder, often the outer of two folders with the same name. See Step 2, point 5. |
| `No module named risk_engine` | The command window is not in the `Risk` folder. Repeat Step 3. |
| `No module named yaml` (or another name) | The workspace is not switched on. Run the activate line from "Every time you start". |
| `Folder not found` | Check the spelling, or drag the folder into the window instead of typing it. |
| `STOPPED: no API key found` | Do Step 6, then open a new command window. |
| `The API key was rejected` | The key was mistyped or has been deleted. Create a new one (Step 6). |
| `Your Anthropic credit balance is too low` | Add credit at console.anthropic.com under Settings > Billing. |
| `STOPPED: the estimate is over the per-run cap` | Raise `per_run_cap_usd` in `config/settings.yaml`, or run on fewer documents. |
| `impacts must be in order` (after editing records.xlsx) | On the row named, make sure Impact min % <= Impact likely % <= Impact max %. |
| `No extraction results in ...` | Give `calculate` the run folder made by `extract` (inside `outputs`), not the tender folder. |
| `Duplicate merging needs the API key` | Do Step 6, or add `--no-merge`. |
| A piece is marked `refused` or `too_long` | That part of the documents was not reviewed. Check it by hand. For `too_long`, lowering `max_chunk_tokens` in the settings sends smaller pieces. |
| A document shows "probably a scanned PDF" | That PDF is an image with no text. It cannot be reviewed until it is converted with OCR software. |

---

## For developers

Run the automatic checks with `python -m pytest`. The demo pack is generated by
`tools/make_demo_pack.py` (needs `reportlab`). The design is set out in the build brief:
the engine is generic, and everything specific to construction tenders lives in
`packs/construction_tender/`.
