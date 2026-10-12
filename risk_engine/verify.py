"""Quote verification: does a quoted passage really appear in the source?

Claude is told to quote word for word. This module checks that in code, and
finds the exact section and page (or row, or line) where the quote sits.

Matching tolerates differences that are not differences of wording:
  - spacing and line breaks ("liability   shall" = "liability shall")
  - curly versus straight quotation marks and apostrophes, and dash styles
  - words broken across lines with a hyphen ("obliga-" / "tion")
  - the case of the first letter only ("If the ..." for "... if the ...")
  - spaces wrongly inserted inside words by PDF text extraction
    ("previo usly", "A greement"), and hyphens; reported as a
    spacing-tolerant match
Anything else, including any change of wording, spelling or punctuation, or
joining separate passages with "...", fails verification.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from risk_engine.ingest import Document, Section

_CHAR_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2212": "-", "\u00a0": " ", "\u2007": " ", "\u202f": " ",
}
_SOFT_HYPHEN = "\u00ad"
_HYPHENS = "-\u2010\u2011"
MIN_QUOTE_CHARS = 12  # shorter quotes match too easily to prove anything

# Tried in order: (method name, ignore spaces and hyphens, join words hyphenated
# at a line break). The second keeps the hyphen, for "fit-for-" / "purpose".
_METHODS = [("exact", False, True), ("exact", False, False), ("spacing-tolerant", True, True)]


@dataclass
class QuoteMatch:
    verified: bool
    method: str = ""              # "exact" or "spacing-tolerant"
    section: Section | None = None
    location: str | None = None   # e.g. "page 14"
    reason: str = ""              # why verification failed

    @property
    def ref(self) -> str | None:
        """Reference built by code from where the quote was actually found."""
        if not self.section:
            return None
        name = self.section.ref.rsplit(" (", 1)[0] if self.section.ref.endswith(")") else self.section.ref
        return f"{name} ({self.location})" if self.location else name


def _normalise_with_map(text: str, drop_spaces: bool, join_hyphens: bool = True) -> tuple[str, list[int]]:
    """Normalised text, plus for each normalised character its index in the original."""
    out: list[str] = []
    index: list[int] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == _SOFT_HYPHEN:
            i += 1
            continue
        if ch in _HYPHENS and i + 1 < n and text[i + 1] == "\n" and out and out[-1].isalpha():
            if not join_hyphens:
                out.append("-")
                index.append(i)
            i += 2
            continue
        ch = unicodedata.normalize("NFKC", _CHAR_MAP.get(ch, ch))
        if drop_spaces and ch == "-":
            i += 1
            continue
        for c in ch:
            if c.isspace():
                if drop_spaces or not out or out[-1] == " ":
                    continue
                c = " "
            out.append(c)
            index.append(i)
        i += 1
    return "".join(out), index


def normalise(text: str, drop_spaces: bool = False, join_hyphens: bool = True) -> str:
    return _normalise_with_map(text, drop_spaces, join_hyphens)[0].strip()


def find_quote(quote: str, doc: Document) -> QuoteMatch:
    """Look for a quote anywhere in one document."""
    if not quote or not quote.strip():
        return QuoteMatch(False, reason="no quote given")
    if "..." in quote or "\u2026" in quote:
        return QuoteMatch(False, reason="quote joins separate passages with '...'")
    if len(normalise(quote)) < MIN_QUOTE_CHARS:
        return QuoteMatch(False, reason="quote too short to verify")

    # The document as one text, with each section's start offset, so that a
    # quote running over two sections can still be found.
    starts: list[int] = []
    pos = 0
    for s in doc.sections:
        starts.append(pos)
        pos += len(s.text) + 1
    full = "\n".join(s.text for s in doc.sections)

    for method, drop, join in _METHODS:
        hay, index = _normalise_with_map(full, drop, join)
        needle = normalise(quote, drop, join)
        at = hay.find(needle)
        if at < 0 and needle[:1].isalpha():
            at = hay.find(needle[:1].swapcase() + needle[1:])
        if at < 0:
            continue
        original = index[at]
        k = max(i for i, st in enumerate(starts) if st <= original)
        section = doc.sections[k]
        return QuoteMatch(True, method, section, section.location_at(original - starts[k]))
    return QuoteMatch(False, reason="quote not found in the document")
