"""Read documents (PDF, Word, Excel, text) and split them into sections.

Each section keeps where it came from, so every later finding can cite its
source:
  - PDF:   split at clause headings; every character is mapped to its page
  - Word:  split at headings and numbered clauses; tables kept in place;
           page numbers taken from Word's own layout where Word saved them
  - Excel: one block of rows per section; every line is mapped to its row
  - Text:  split at clause headings; every character is mapped to its line

What counts as a heading is generic (numbered clauses, "Section 4",
"Schedule 2" and so on). A domain pack can add its own heading patterns in
pack.yaml under ingest: extra_heading_patterns.
"""

from __future__ import annotations

import bisect
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".csv"}

# Plain-English explanations for file types we cannot read.
UNSUPPORTED_ADVICE = {
    ".doc": "this is an old-style Word file. Open it in Word and use File > Save As > Word Document (.docx)",
    ".xls": "this is an old-style Excel file. Open it in Excel and use File > Save As > Excel Workbook (.xlsx)",
    ".rtf": "Rich Text files are not read. Open it in Word and save it as a Word Document (.docx)",
    ".zip": "this is a ZIP file. Unzip it first (right-click > Extract All) and run the tool on the unzipped folder",
    ".msg": "e-mails are not read. Save any attachments into the folder instead",
    ".eml": "e-mails are not read. Save any attachments into the folder instead",
}
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic"}
DRAWING_TYPES = {".dwg", ".dxf", ".dgn", ".ifc", ".rvt"}

# Headings recognised in any domain. Each pattern matches only the label
# ("4.2", "Clause 7", "Schedule 3") at the start of a line. Word labels must be
# capitalised: a line starting "clause 4.2 of ..." is a sentence, not a heading.
_HEADING_WORDS = ["Clause", "Section", "Part", "Schedule", "Appendix", "Annex", "Annexure",
                  "Article", "Chapter"]
DEFAULT_HEADING_PATTERNS = [
    "(?:" + "|".join(w + "|" + w.upper() for w in _HEADING_WORDS) + r")\s+[A-Z0-9]+(?:\.[0-9]+)*(?=[\s.:)\-–]|$)",
    r"\d{1,3}(?:\.\d{1,3}){0,4}\.?(?=\s+[A-Z(\"'‘“])",
    r"\d{1,3}(?:\.\d{1,3}){2,4}\.?(?=\s+[a-z])",   # "12.5.1 on insolvency" (never a decimal)
]
# A line like "10 December 2026" or "30 Working Days" is not a heading.
NOT_HEADING_WORDS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "item", "items", "sum", "days", "weeks", "months", "years",
    "working", "calendar", "business", "per", "hours", "minutes",
}
# Quantity abbreviations ("64 Nr piles", "2 No. pumps"). Exact spelling, so that
# "26. NO PARTNERSHIP" is still a heading.
QUANTITY_WORDS = {"Nr", "Nr.", "nr", "nr.", "No.", "no.", "Nos", "Nos.", "nos", "nos."}
# If the previous line ends with one of these words, the next line continues
# the sentence ("... in accordance with / Clause 4.2"), so it is not a heading.
JOINING_WORDS = {
    "a", "an", "and", "as", "at", "by", "clause", "clauses", "for", "from", "in", "of", "on",
    "or", "paragraph", "paragraphs", "part", "per", "pursuant", "schedule", "section",
    "sections", "than", "the", "this", "that", "to", "under", "with", "within", "see",
    "appendix", "annex", "article", "is", "are", "be", "shall", "will", "which",
}
# Words that mark a title as a top-level part of a document, such as a schedule.
TOP_LEVEL_WORDS = re.compile(r"^(schedule|appendix|annex|annexure)\b", re.IGNORECASE)
NUMBERED = re.compile(r"\d+(?:\.\d+)*")


class FileReadError(Exception):
    """A file could not be read. The message is in plain English."""


@dataclass
class Section:
    doc: str                      # file name
    ref: str                      # human-readable location, e.g. "Z6 Delay damages (page 2)"
    text: str
    clause: str | None = None     # clause label, e.g. "Z6" or "4.2"
    heading: str | None = None    # full heading line
    # (character offset, location label) pairs: the label applies from that
    # offset until the next one. Used to find the exact page or row of a quote.
    locations: list[tuple[int, str]] = field(default_factory=list)

    def location_at(self, offset: int) -> str | None:
        """The page, row or line at a character offset within this section."""
        if not self.locations:
            return None
        i = bisect.bisect_right([o for o, _ in self.locations], offset) - 1
        return self.locations[max(i, 0)][1]

    def location_span(self) -> str | None:
        labels = list(dict.fromkeys(label for _, label in self.locations))
        if not labels:
            return None
        return labels[0] if len(labels) == 1 else _span(labels[0], labels[-1])


@dataclass
class Document:
    name: str
    path: Path
    kind: str
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # things the user should act on
    notes: list[str] = field(default_factory=list)      # things done automatically

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.sections)


@dataclass
class SkippedFile:
    name: str
    reason: str        # plain English, shown to the user
    detail: str = ""   # technical detail, kept in the audit file only


@dataclass
class Chunk:
    """A piece of text small enough to send to Claude in one call."""
    doc: str
    refs: list[str]
    text: str


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

class HeadingDetector:
    def __init__(self, extra_patterns: list[str] | None = None):
        patterns = list(extra_patterns or []) + DEFAULT_HEADING_PATTERNS
        self._regexes = [re.compile(r"^\s*(" + p + r")") for p in patterns]

    def match(self, line: str, previous: str | None = None) -> str | None:
        """Return the clause label if the line starts a new clause, else None.

        previous is the line before, used to spot a sentence that runs on.
        """
        all_capitals = not re.search(r"[a-z]", line)   # "SCHEDULE 1", "3. PAYMENT"
        if previous and not all_capitals:
            if _ends_mid_sentence(previous):
                return None
        for rx in self._regexes:
            m = rx.match(line)
            if not m:
                continue
            label = m.group(1).strip().rstrip(".")
            rest = line[m.end():].strip()
            first = re.split(r"[\s,;:]+", rest, maxsplit=1)[0] if rest else ""
            if first in QUANTITY_WORDS or first.lower().rstrip(".") in NOT_HEADING_WORDS:
                return None
            return label
        return None


def _ends_mid_sentence(text: str) -> bool:
    """True if a line stops part-way through a sentence ("... in accordance with")."""
    stripped = text.rstrip()
    if stripped.endswith((".", ":", ";", ":-")) or re.search(r"[;,]\s*(and|or)$", stripped):
        return False
    tokens = re.findall(r"[a-z]+|\d+", stripped.lower())
    return bool(tokens) and tokens[-1] in JOINING_WORDS


@dataclass
class _Line:
    text: str
    location: str | None = None
    page_tail: bool = False       # one of the last lines on a PDF page
    forced_heading: bool = False  # e.g. a Word paragraph styled as a heading
    label: str | None = None      # set by _plan_headings
    heading: bool = False         # set by _plan_headings
    contents_start: bool = False  # set by _plan_headings
    after_contents: bool = False  # set by _plan_headings


def _plan_headings(lines: list[_Line], detector: HeadingDetector | None) -> None:
    """Decide which lines start a new section. Works on the whole document at
    once, so it can recognise footnotes, repeated stamps and contents lists."""
    lines[:] = [l for l in lines if l.text.strip()]
    if detector is None:
        return
    previous = None
    for l in lines:
        l.text = l.text.strip()
        l.label = detector.match(l.text, previous)
        l.heading = l.forced_heading or l.label is not None
        previous = l.text

    # Stamps: the same "heading" four or more times is not a heading.
    counts = Counter(l.text for l in lines if l.heading and not l.forced_heading)
    for l in lines:
        if l.heading and not l.forced_heading and counts[l.text] >= 4:
            l.heading, l.label = False, None

    # Contents lists: four or more short headings close together, which either
    # end in page numbers or reappear later as real headings.
    heads = [i for i, l in enumerate(lines) if l.heading]
    run: list[int] = []

    def close_run():
        if len(run) >= 4 and sum(len(lines[i].text) <= 100 for i in run) >= 4 and _is_contents(run, lines):
            for i in range(run[0], run[-1] + 1):
                lines[i].heading, lines[i].label = False, None
            lines[run[0]].heading = lines[run[0]].contents_start = True
            # The contents list ends with its last entry (plus any wrapped line).
            end = run[-1] + 1
            if end < len(lines) and not lines[end].heading and re.search(r"\s\d{1,3}\s*$", lines[end].text):
                end += 1
            if end < len(lines) and not lines[end].heading:
                lines[end].heading = lines[end].after_contents = True

    for i in heads:
        repeats_label = lines[i].label is not None and lines[i].label in {lines[j].label for j in run}
        if run and (i - run[-1] > 2 or repeats_label):
            close_run()
            run = []
        run.append(i)
    close_run()

    # Footnotes: "1 Zero Carbon Harrogate | ..." among the last lines of a page.
    for l in lines:
        if (l.heading and not l.contents_start and not l.after_contents and not l.forced_heading and l.page_tail and l.label
                and re.fullmatch(r"\d{1,3}", l.label) and not re.match(r"\d{1,3}\.", l.text)):
            l.heading, l.label = False, None


def _is_contents(run: list[int], lines: list[_Line]) -> bool:
    ending_in_number = sum(1 for i in run if re.search(r"[A-Za-z][^\d]*[\s.]\d{1,3}\s*$", _after_label(lines[i])))
    later = {(l.label, _first_word(l.text)) for l in lines[run[-1] + 1:] if l.heading}
    reappearing = sum(1 for i in run if (lines[i].label, _first_word(lines[i].text)) in later)
    return ending_in_number * 2 >= len(run) or reappearing * 2 >= len(run)


def _after_label(line: _Line) -> str:
    """The entry text after its clause label: '1 DEFINITIONS 4' -> ' DEFINITIONS 4'."""
    if line.label and line.text.startswith(line.label):
        return line.text[len(line.label):]
    return line.text


def _first_word(text: str) -> str:
    words = re.findall(r"[A-Za-z]+", text)
    return words[0].lower() if words else ""


def _span(a: str, b: str) -> str:
    """'page 2' + 'page 4' -> 'pages 2-4'; 'row 5' + 'row 9' -> 'rows 5-9'."""
    wa, _, na = a.partition(" ")
    wb, _, nb = b.partition(" ")
    if wa == wb and na and nb:
        return f"{wa}s {na}-{nb}"
    return f"{a} to {b}"


SHORT_HEADING = 70  # longer lines are numbered paragraphs, not titles


def _looks_like_title(line: str) -> bool:
    """'4. Evaluation' is a title; '4.1 Tenders will be evaluated ...' and
    '12.5 Supplier shall be entitled to terminate:-' are paragraphs."""
    stripped = line.rstrip()
    return (len(stripped) <= SHORT_HEADING and not stripped.endswith((".", ";", ",", ":", "-", ":-"))
            and not re.search(r"[;,]\s*(and|or)$", stripped) and not _ends_mid_sentence(stripped))


def _short(text: str, limit: int = SHORT_HEADING) -> str:
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


class _SectionBuilder:
    """Turns planned lines into sections with readable references."""

    def __init__(self, doc_name: str):
        self.doc_name = doc_name
        self.sections: list[Section] = []
        self._lines: list[str] = []
        self._locs: list[tuple[int, str]] = []
        self._size = 0
        self._name: str | None = None
        self._clause: str | None = None
        self._heading: str | None = None
        self._titles: list[tuple[str | None, str]] = []   # (label, text) of every title so far
        self._top: str | None = None                      # current schedule / appendix, if any

    def build(self, lines: list[_Line]) -> list[Section]:
        for l in lines:
            if l.heading:
                self._start(l)
            self._append(l.text, l.location)
        self._flush()
        return self.sections

    def _start(self, l: _Line) -> None:
        self._flush()
        self._clause, self._heading = l.label, l.text[:200]
        if l.contents_start:
            self._name, self._clause = "contents list", None
            return
        if l.after_contents:
            self._name, self._clause, self._heading = "text after the contents list", None, None
            return
        if l.forced_heading or _looks_like_title(l.text):
            title = _short(l.text)
            if TOP_LEVEL_WORDS.match(l.text):
                self._top = _short(l.text, 40)
                self._name = title
            else:
                self._name = title + (f" in {self._top}" if self._top else "")
            self._titles.append((l.label, title))
            return
        # A numbered paragraph: name it by its number and the title it sits under.
        parent = self._parent_for(l.label)
        label = l.label or _short(l.text, 40)
        if label[:1].isdigit():
            in_schedule = parent and (TOP_LEVEL_WORDS.match(parent) or (self._top and parent != self._top))
            label = ("paragraph " if in_schedule else "clause ") + label
        name = label
        if parent:
            name += f" in '{parent}'"
        if self._top and parent != self._top:
            name += f", {self._top}"
        self._name = name

    def _parent_for(self, label: str | None) -> str | None:
        if not self._titles:
            return None
        if label and NUMBERED.fullmatch(label):
            for t_label, t_text in reversed(self._titles):
                if t_label and NUMBERED.fullmatch(t_label):
                    if label.startswith(t_label + "."):
                        return t_text
                elif t_label is None or not t_label[:1].isdigit():
                    return t_text   # a schedule or unnumbered title bounds the search
        return self._titles[-1][1]

    def _append(self, text: str, location: str | None) -> None:
        if location and (not self._locs or self._locs[-1][1] != location):
            self._locs.append((self._size, location))
        self._lines.append(text)
        self._size += len(text) + 1

    def _flush(self) -> None:
        if not self._lines:
            return
        section = Section(self.doc_name, "", "\n".join(self._lines), self._clause, self._heading, self._locs)
        name = self._name or "start of document"
        span = section.location_span()
        section.ref = f"{name} ({span})" if span else name
        self.sections.append(section)
        self._lines, self._locs, self._size = [], [], 0
        self._name = self._clause = self._heading = None


def _build_sections(doc_name: str, lines: list[_Line], detector: HeadingDetector | None) -> list[Section]:
    _plan_headings(lines, detector)
    return _SectionBuilder(doc_name).build(lines)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _normalise_furniture(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


FURNITURE_TOP, FURNITURE_BOTTOM = 6, 4   # lines checked at the top and bottom of each page


def _edge_indexes(lines: list[str]) -> set[int]:
    filled = [i for i, l in enumerate(lines) if l.strip()]
    return set(filled[:FURNITURE_TOP] + filled[-FURNITURE_BOTTOM:])


def _strip_page_furniture(pages: list[list[str]], doc: Document,
                          detector: HeadingDetector | None = None) -> list[list[str]]:
    """Remove headers and footers repeated on most pages (e.g. 'Page 3 of 40').
    Lines that look like clause headings are never removed."""
    with_text = [p for p in pages if any(l.strip() for l in p)]
    if len(with_text) < 3:
        return pages
    counts: Counter = Counter()
    originals: dict[str, str] = {}
    for lines in with_text:
        keys = {_normalise_furniture(lines[i]) for i in _edge_indexes(lines)}
        counts.update(keys)
        for i in _edge_indexes(lines):
            originals.setdefault(_normalise_furniture(lines[i]), lines[i].strip())
    threshold = max(3, (len(with_text) + 1) // 2)
    repeated = {k for k, n in counts.items()
                if n >= threshold and k and not (detector and detector.match(originals[k]))}
    if not repeated:
        return pages
    cleaned = []
    for lines in pages:
        edges = _edge_indexes(lines)
        cleaned.append([l for i, l in enumerate(lines)
                        if not (i in edges and _normalise_furniture(l) in repeated)])
    examples = [originals[k] for k in sorted(repeated)][:3]
    doc.notes.append(f"Removed {len(repeated)} repeated page header/footer line(s), e.g. "
                     + "; ".join(f"'{e}'" for e in examples))
    return cleaned


def read_pdf(path: Path, detector: HeadingDetector) -> Document:
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    doc = Document(path.name, path, "PDF")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                pass
        raw_pages = [(p.extract_text() or "") for p in reader.pages]
    except FileNotDecryptedError as e:
        raise FileReadError("this PDF is password protected. Save an unprotected copy and try again") from e
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        raise FileReadError("this file is damaged or is not a real PDF") from e

    pages = [p.split("\n") for p in raw_pages]
    blank = [i + 1 for i, p in enumerate(raw_pages) if not p.strip()]
    if blank and len(blank) == len(raw_pages):
        doc.warnings.append("No readable text found. This is probably a scanned PDF; it cannot be "
                            "reviewed until it has been converted to text with OCR software.")
        return doc
    if blank:
        doc.warnings.append(f"{len(blank)} of {len(raw_pages)} page(s) have no readable text and will "
                            f"not be reviewed (pages {_page_list(blank)}). They may be scanned images "
                            f"or drawings.")

    pages = _strip_page_furniture(pages, doc, detector)
    planned: list[_Line] = []
    for number, lines in enumerate(pages, start=1):
        filled = [l for l in lines if l.strip()]
        for i, line in enumerate(filled):
            planned.append(_Line(line, f"page {number}", page_tail=i >= len(filled) - 3))
    doc.sections = _build_sections(path.name, planned, detector)
    return doc


def _page_list(pages: list[int]) -> str:
    return ", ".join(str(p) for p in pages[:15]) + (" ..." if len(pages) > 15 else "")


def read_docx(path: Path, detector: HeadingDetector) -> Document:
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table

    doc = Document(path.name, path, "Word")
    try:
        d = docx.Document(str(path))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as e:
        raise FileReadError("this file is damaged or is not a real Word file. If it is an old-style "
                            ".doc file renamed to .docx, open it in Word and Save As .docx") from e

    body_xml = d.element.body.xml
    has_layout_pages = "lastRenderedPageBreak" in body_xml
    page = 1
    planned: list[_Line] = []

    def page_label() -> str | None:
        return f"page {page}" if has_layout_pages else None

    for block in d.iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                cells: list[str] = []
                for c in row.cells:
                    t = " ".join(c.text.split())
                    if not cells or cells[-1] != t:   # merged cells repeat their text
                        cells.append(t)
                if any(cells):
                    planned.append(_Line(" | ".join(cells), page_label()))
            continue
        # paragraph: a page break at its very start moves it to the next page;
        # a break part-way through means it starts on this page and runs on.
        breaks_after = 0
        if has_layout_pages:
            breaks = block.rendered_page_breaks
            before = breaks[0].preceding_paragraph_fragment if breaks else None
            if breaks and (before is None or not before.text.strip()):
                page += 1
                breaks_after = len(breaks) - 1
            else:
                breaks_after = len(breaks)
        text = block.text
        style = (block.style.name if block.style is not None else "") or ""
        is_heading = style.lower().startswith(("heading", "title"))
        planned.append(_Line(text, page_label(), forced_heading=is_heading and bool(text.strip())))
        page += breaks_after
    doc.sections = _build_sections(path.name, planned, detector)

    if not doc.sections:
        doc.warnings.append("The Word file contains no text.")
    if not has_layout_pages and doc.sections:
        doc.notes.append("Word did not save page layout in this file, so references use headings "
                         "rather than page numbers.")
    if "w:numPr" in body_xml:
        doc.notes.append("Some paragraphs use Word's automatic numbering. Those numbers are not part of "
                         "the text, so references use the nearest heading instead.")
    return doc


def read_xlsx(path: Path, rows_per_section: int = 50) -> Document:
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    doc = Document(path.name, path, "Excel")
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        raise FileReadError("this file is damaged or is not a real Excel file. If it is an old-style "
                            ".xls file, open it in Excel and Save As .xlsx") from e
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                doc.notes.append(f"Sheet '{ws.title}' is hidden in Excel; it has been read anyway.")
            rows: list[tuple[int, str]] = []
            for r_index, row in enumerate(ws.iter_rows(values_only=True), start=1):
                cells = ["" if v is None else str(v).strip() for v in row]
                while cells and not cells[-1]:
                    cells.pop()
                if any(cells):
                    rows.append((r_index, " | ".join(cells)))
            for start in range(0, len(rows), rows_per_section):
                block = rows[start:start + rows_per_section]
                sections = _build_sections(path.name, [_Line(line, f"row {r}") for r, line in block], None)
                for sec in sections:
                    sec.ref = f"sheet '{ws.title}' ({sec.location_span()})"
                    sec.heading = f"sheet '{ws.title}'"
                doc.sections.extend(sections)
    finally:
        wb.close()
    if not doc.sections:
        doc.warnings.append("The spreadsheet contains no data.")
    return doc


def read_text(path: Path, detector: HeadingDetector) -> Document:
    doc = Document(path.name, path, "Text")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    planned = [_Line(line, f"line {n}") for n, line in enumerate(text.splitlines(), start=1)]
    doc.sections = _build_sections(path.name, planned, None if path.suffix.lower() == ".csv" else detector)
    if not doc.sections:
        doc.warnings.append("The file is empty.")
    return doc


# ---------------------------------------------------------------------------
# Folder reading
# ---------------------------------------------------------------------------

def _skip_reason(suffix: str) -> str:
    if suffix in UNSUPPORTED_ADVICE:
        return UNSUPPORTED_ADVICE[suffix]
    if suffix in IMAGE_TYPES:
        return "pictures are not read (photographs and scans need converting to text first)"
    if suffix in DRAWING_TYPES:
        return "drawings are not read"
    return f"files of type '{suffix or 'no extension'}' are not read"


def read_folder(folder: Path, accepted: list[str] | None = None,
                extra_heading_patterns: list[str] | None = None,
                rows_per_section: int = 50) -> tuple[list[Document], list[SkippedFile]]:
    """Read every supported file in a folder and its sub-folders."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    allowed = set(s.lower() for s in (accepted or SUPPORTED)) & SUPPORTED
    detector = HeadingDetector(extra_heading_patterns)
    docs: list[Document] = []
    skipped: list[SkippedFile] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = str(path.relative_to(folder))
        if path.name.startswith(("~$", ".")) or path.name.lower() in {"thumbs.db", "desktop.ini"}:
            continue  # Office lock files and system files
        suffix = path.suffix.lower()
        if suffix not in allowed:
            skipped.append(SkippedFile(rel, _skip_reason(suffix)))
            continue
        try:
            if suffix == ".pdf":
                doc = read_pdf(path, detector)
            elif suffix == ".docx":
                doc = read_docx(path, detector)
            elif suffix in (".xlsx", ".xlsm"):
                doc = read_xlsx(path, rows_per_section)
            else:
                doc = read_text(path, detector)
        except FileReadError as e:
            skipped.append(SkippedFile(rel, str(e), _detail(e)))
            continue
        except PermissionError as e:
            skipped.append(SkippedFile(rel, "the file is open in another program or you do not have "
                                            "permission to read it. Close it and try again", _detail(e)))
            continue
        except Exception as e:  # a damaged file must not stop the whole run
            skipped.append(SkippedFile(rel, "this file could not be read. It may be damaged or password "
                                            "protected", _detail(e)))
            continue
        doc.name = rel
        for s in doc.sections:
            s.doc = rel
        docs.append(doc)
    return docs, skipped


def _detail(e: Exception) -> str:
    cause = e.__cause__ or e
    return f"{cause.__class__.__name__}: {cause}"


# ---------------------------------------------------------------------------
# Chunking for the API
# ---------------------------------------------------------------------------

def chunk_documents(docs: list[Document], max_chars: int) -> list[Chunk]:
    """Group sections into chunks of at most max_chars characters.

    Sections from the same document are combined while they fit. A section
    longer than the limit is split at line boundaries. Chunks never mix
    documents, so every finding has one source file. Each section in a chunk
    is labelled with its reference, e.g. "[Z6 Delay damages (page 2)]".
    """
    chunks: list[Chunk] = []
    for doc in docs:
        refs: list[str] = []
        buf: list[str] = []
        size = 0

        def flush():
            nonlocal refs, buf, size
            if buf:
                chunks.append(Chunk(doc.name, refs, "\n\n".join(buf)))
            refs, buf, size = [], [], 0

        for section in doc.sections:
            label = f"[{section.ref}]"
            for piece in _split(section.text, max_chars - len(label) - 1):
                block = f"{label}\n{piece}"
                if buf and size + len(block) > max_chars:
                    flush()
                if section.ref not in refs:
                    refs.append(section.ref)
                buf.append(block)
                size += len(block) + 2
        flush()
    return chunks


def _split(text: str, limit: int) -> list[str]:
    limit = max(200, limit)
    if len(text) <= limit:
        return [text]
    pieces, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single enormous line
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:limit])
            line = line[limit:]
        if current and len(current) + len(line) + 1 > limit:
            pieces.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces
