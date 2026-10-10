# Tender Risk Reviewer (prototype)

This tool reads a construction tender pack and tells a contractor what risks they
would be taking on, what to do about them, and how much contingency to price in.

**Current status: Stage 2 of 9 (reading documents).** At this stage the tool can
read a folder of tender documents, split them into clauses and sections with page
references, and estimate what a real review would cost. It does **not** yet call
Claude or produce a risk register.

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
The API key line will say "not set". That is fine for now; it is needed from Stage 3.

---

## Part 2: Using the tool

Nothing in this part sends anything anywhere or costs anything.

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
| `config/settings.yaml` | **The settings you can change**: models, prices, spending cap, simulation settings. Every line is explained. |
| `packs/construction_tender/` | The construction tender "domain pack": risk categories, scales, checklist, and the instructions given to Claude. Edit these to change what the tool looks for. |
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

- Documents are read on your own computer. From Stage 3 onwards, document text is sent
  only to the Claude API (Anthropic) for review. Nothing is uploaded anywhere else.
- The API key is read from an environment variable called `ANTHROPIC_API_KEY`. It is
  never written into any file in this project. Setup instructions come with Stage 3.
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
| A document shows "probably a scanned PDF" | That PDF is an image with no text. It cannot be reviewed until it is converted with OCR software. |

---

## For developers

Run the automatic checks with `python -m pytest`. The demo pack is generated by
`tools/make_demo_pack.py` (needs `reportlab`). The design is set out in the build brief:
the engine is generic, and everything specific to construction tenders lives in
`packs/construction_tender/`.
