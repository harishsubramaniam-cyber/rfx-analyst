"""How clearly one number was read, judged on evidence rather than assertion.

A model asked "how confident are you?" will answer 0.95 to almost everything,
including the figure it half-guessed off a photograph. That number is worse
than useless on a screen a buyer is about to commit four crore against: it
looks like a check and is actually a shrug.

So the model's own figure is only the starting point here. It is then adjusted
by things that can be verified after the fact:

  * did it hand back the supplier's exact words for this number, or nothing?
  * how did this line get tied to the buyer's item -- by its code, or by a
    description that merely looked similar?
  * did the supplier state the unit, or did we infer it?
  * did the supplier state a currency anywhere?
  * did the number come off a spreadsheet cell or a photograph of paper?

Every one of those is checkable by a person holding the same documents, which
is the whole point: the score has to be defensible, not confident. Each factor
also leaves a note behind, so a low score can always answer "low because what?"
"""

from __future__ import annotations

import os
from typing import Optional

# Photographs and scans lose detail before anything reads them; a spreadsheet
# cell arrives as an exact value. This is about the medium, not the supplier.
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff"}

# Weights are deliberately mild. Each is a reason to look twice, not a verdict,
# and they compound: a photographed price matched on a fuzzy description with
# no snippet lands far lower than any single factor would put it.
NO_SNIPPET = (0.82, "no verbatim text was captured for this number")
PHOTOGRAPH = (0.93, "read from a photograph rather than a data file")
UNIT_UNSTATED = (0.93, "the supplier did not state what one price covers")
CURRENCY_UNSTATED = (0.96, "the supplier never stated a currency")
RERENDERED = (0.90, "the file's text layer was damaged and had to be re-read")


def _is_photograph(source_file: Optional[str], locator: Optional[str]) -> bool:
    if locator and "photo" in locator.lower():
        return True
    if not source_file:
        return False
    return os.path.splitext(source_file)[1].lower() in _IMAGE_EXTENSIONS


def score(
    stated: float,
    *,
    snippet: Optional[str],
    match_basis: str,
    match_confidence: float,
    unit_stated: bool,
    currency_stated: bool,
    source_file: Optional[str] = None,
    source_locator: Optional[str] = None,
    rerendered: bool = False,
) -> tuple[float, list[str]]:
    """Return (confidence 0-1, the reasons it is not higher)."""
    # An absent or absurd self-report is treated as a middling one rather than
    # as a zero: silence is not evidence of a bad read.
    value = stated if 0.0 < stated <= 1.0 else 0.80
    notes: list[str] = []

    def apply(factor_note: tuple[float, str]) -> None:
        nonlocal value
        factor, note = factor_note
        value *= factor
        notes.append(note)

    if not snippet:
        apply(NO_SNIPPET)
    if _is_photograph(source_file, source_locator):
        apply(PHOTOGRAPH)
    if not unit_stated:
        apply(UNIT_UNSTATED)
    if not currency_stated:
        apply(CURRENCY_UNSTATED)
    if rerendered:
        apply(RERENDERED)

    # How the line was tied to the buyer's item. An exact code is free; a
    # description that merely looked similar is the single largest doubt there
    # is about a number, because it may be the right price for the wrong item.
    if match_basis in ("description", "llm_adjudicated"):
        value *= 0.70 + 0.30 * max(0.0, min(1.0, match_confidence))
        notes.append("matched on the description, not on an item code")
    elif match_basis == "dimensions":
        value *= 0.95
        notes.append("matched on dimensions rather than an item code")

    return round(max(0.05, min(0.99, value)), 2), notes
