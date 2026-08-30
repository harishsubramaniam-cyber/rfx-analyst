"""Tie each vendor line to an RFx line.

This is the step that turns a pile of quotes into a comparison. Without it you
have five lists stacked on top of each other, which is what a spreadsheet
already gives you.

Deliberately a ladder, cheapest and most certain first:

    exact SKU → normalised SKU → dimensions → description → model adjudication

The model is the last rung, not the first. On well-formed responses it is
never reached, which keeps the pipeline fast, free and reproducible; when it
is reached it must give a reason, which is shown to the buyer.

The two "no match" outcomes are both first-class results, not errors:
    * an RFx line no vendor line claims  -> Not Quoted (coverage gap)
    * a vendor line no RFx line claims   -> Extra Line (unsolicited offer)
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import rfx as rfx_module
from .models import ExtractedLine, MatchResult
from .rfx import RfxLine
from .skus import dimension_signature, normalize_sku

# How much two descriptions must agree before they are called the same item,
# and by how far the winner must beat the runner-up. Deliberately named rather
# than buried: these two numbers decide every match the codes cannot make, and
# a buyer questioning one deserves to be shown the bar it cleared.
DESCRIPTION_FLOOR = 0.58
DESCRIPTION_MARGIN = 0.06
# A winner this far clear of the field has shown something the absolute score
# does not: that no other item on the list is remotely as good a reading of
# this line. Two people describing one product rarely reach 0.62 when they
# share no vocabulary habits -- "14in notebook, 16GB" against "Laptop 14-inch,
# 16 GB" lands at 0.605 while beating everything else by 0.43 -- so a decisive
# lead is allowed to stand in for a little absolute agreement. It is never
# allowed to stand in for the contradiction check.
DECISIVE_MARGIN = 0.25
DECISIVE_FLOOR = 0.52

# A word distinguishes one item from another when it appears on some of them
# and not most of them. "corrugated" is on nearly every line of a packaging
# catalogue and separates nothing; "die-cut" is on three and separates them
# sharply. Which words those are cannot be written down in advance, because it
# depends entirely on what is being bought -- so they are learned from the item
# list in hand. That is what makes this work on IT hardware or MRO spares
# without a line of it knowing what a corrugated box is.
MARKER_SHARE = 0.5          # on at most half the lines, or it marks nothing
# How much of their distinguishing vocabulary two lines must share before they
# are allowed to be the same item, even when their dimensions agree exactly.
MARKER_AGREEMENT = 0.34


def marker_vocabulary(descriptions: list[str]) -> set[str]:
    """The words that tell items in *this* catalogue apart."""
    texts = [d for d in descriptions if d and d.strip()]
    if len(texts) < 2:
        return set()                 # nothing to contrast against
    seen: dict[str, int] = {}
    for text in texts:
        # Only bare numbers are excluded. Excluding everything *starting*
        # with a digit threw away "3-ply", "5-ply" and "7-ply" -- so a
        # catalogue distinguished entirely by ply learned an empty vocabulary
        # and the contradiction guard could never fire on it.
        for token in {t for t in _tokens(text) if not t.isdigit()}:
            seen[token] = seen.get(token, 0) + 1
    limit = max(1, int(len(texts) * MARKER_SHARE))
    return {token for token, count in seen.items() if count <= limit}


def _markers(text: str, vocabulary: set[str]) -> set[str]:
    return _tokens(text) & vocabulary


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


# Words and units that carry no product identity in any category. Everything
# category-specific is learned (see marker_vocabulary); this list only removes
# glue.
_NOISE = {"mm", "cm", "x", "the", "a", "of", "and", "per", "with", "size",
          "item", "no", "nos", "pcs", "pc", "piece", "pieces", "each", "unit",
          "units", "approx", "approximately"}

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SPLIT_UNITS = re.compile(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)")


def _tokens(text: str) -> set[str]:
    """The words and figures that distinguish one item from another.

    Two people writing the same item apart never agree on the joins. One types
    "16GB", the other "16 GB"; one "V-belt", the other "V belt"; one "20mm",
    the other "20 mm". Comparing those literally makes the same product look
    like two, so each token is also broken at its hyphens and wherever digits
    meet letters, and every piece is kept alongside the whole. Nothing here
    knows what a GB or a mm is -- it only knows that a join is not evidence.
    """
    ordered: list[str] = []
    compounds: set[str] = set()
    for raw in _TOKEN.findall((text or "").lower()):
        parts = raw.split("-")
        if len(parts) > 1 and not any(part.isdigit() for part in parts):
            # A hyphen between two words is a word: "die-cut", "usb-c",
            # "heavy-duty". Kept whole as well as in pieces.
            compounds.add(raw)
        for part in parts:
            split = [piece for piece in _SPLIT_UNITS.split(part) if piece]
            ordered.extend(split if len(split) > 1 else [part])

    found = set(ordered) | compounds
    # Everything is normalised to the hyphenated form, however it was written.
    # "5-ply", "5 ply" and "5ply" all also yield "5-ply"; so do "27-inch",
    # "27 inch" and "27inch". Without this the hyphen is evidence of nothing
    # but one writer's habit, and two people describing one product disagree
    # on a word neither of them chose.
    for first, second in zip(ordered, ordered[1:]):
        if first.isdigit() and second.isalpha() and len(second) > 1 \
                and second not in _NOISE:
            found.add(f"{first}-{second}")

    return {t for t in found if t not in _NOISE and (len(t) > 1 or t.isdigit())}


def _agreement(a: str, b: str, vocabulary: set[str]) -> float:
    """How much two descriptions genuinely agree, 0 to 1.

    A raw character ratio was the previous test, and it is the wrong
    instrument: "Corrugated Roll - 1200 mm width" and "5-ply roll, 1200 mm
    width" are the same product and score 0.68, while two different boxes that
    happen to share a lot of boilerplate score higher. What matters is whether
    the *distinguishing* words and numbers coincide -- the ply, the shape, the
    dimensions -- so those are weighed directly, and the character ratio is
    kept only as a tie-breaker.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    # Containment rather than Jaccard: one supplier writing a longer
    # description than the other is not disagreement.
    overlap = len(ta & tb) / min(len(ta), len(tb))

    da, db = dimension_signature(a), dimension_signature(b)
    if da and db:
        dimension = 1.0 if da == db else 0.0
    else:
        dimension = 0.5                      # neither side offers the evidence

    wa, wb = _markers(a, vocabulary), _markers(b, vocabulary)
    if wa and wb:
        kind = len(wa & wb) / len(wa | wb)
    else:
        kind = 0.5

    return round(0.45 * overlap + 0.30 * dimension + 0.15 * kind
                 + 0.10 * _similarity(a, b), 3)


def _figures(text: str) -> set[str]:
    """The bare numbers in a description."""
    return {t for t in _tokens(text) if t.isdigit()}


def _contradicts(a: str, b: str, vocabulary: set[str]) -> bool:
    """True when both texts name a product type and the types disagree.

    A shared dimension is strong evidence, but it is not proof: a 3-ply box and
    a die-cut box can be 300x200x150 mm alike. Matching them produces a wrong
    price on the right row, which is worse than no price at all -- the buyer
    has no way to see that anything went astray.
    """
    # Figures first, because a number is the least ambiguous thing either
    # side says. When each names a figure the other does not -- 6204 against
    # 6205, 24-inch against 27-inch, 75 GSM against 80 GSM, M10 grade 5
    # against grade 8 -- they are describing different items, however alike
    # the rest of the words read. Without this a whole catalogue that varies
    # only by number collapsed onto one row.
    fa, fb = _figures(a), _figures(b)
    if (fa - fb) and (fb - fa):
        return True

    wa, wb = _markers(a, vocabulary), _markers(b, vocabulary)
    if not (wa and wb):
        return False
    # Proportional, not binary. Requiring merely *one* word in common let a
    # 3-ply box and a die-cut box pass on the strength of both saying "box" --
    # so what matters is the share of distinguishing words they agree on, not
    # whether any single one coincides.
    return len(wa & wb) / len(wa | wb) < MARKER_AGREEMENT


@dataclass
class MatchReport:
    """Everything the UI needs to explain coverage for one vendor."""
    pairs: list[tuple[ExtractedLine, MatchResult]] = field(default_factory=list)
    by_sku: dict[str, ExtractedLine] = field(default_factory=dict)
    match_by_sku: dict[str, MatchResult] = field(default_factory=dict)
    not_quoted: list[str] = field(default_factory=list)
    extra_lines: list[ExtractedLine] = field(default_factory=list)
    duplicates: list[tuple[str, ExtractedLine]] = field(default_factory=list)

    @property
    def coverage(self) -> tuple[int, int]:
        return len(self.by_sku), rfx_module.active().line_count

    @property
    def coverage_label(self) -> str:
        quoted, total = self.coverage
        return f"{quoted}/{total}"


def match_one(
    line: ExtractedLine,
    rfx_lines: list[RfxLine],
    vocabulary: Optional[set[str]] = None,
) -> MatchResult:
    """Where one vendor line belongs, by the rungs above. Public because
    core/derive.py groups on exactly the same decision.

    `vocabulary` is the distinguishing-word set for this item list; it is
    derived from `rfx_lines` when not supplied, and passed in by match_lines
    so a whole response shares one reading of the catalogue.
    """
    if vocabulary is None:
        vocabulary = marker_vocabulary([rfx.description for rfx in rfx_lines])
    # Rung 1 + 2: SKU
    candidate = normalize_sku(line.vendor_sku)
    if candidate is None:
        candidate = normalize_sku(line.description)

    # Checked against the lines we were actually given. Consulting the global
    # active request instead was wrong whenever the two differ -- which is
    # exactly the case while the spine is still being derived.
    known = {rfx.sku for rfx in rfx_lines}
    if candidate and candidate in known:
        exact = (line.vendor_sku or "").strip().upper() == candidate
        return MatchResult(
            rfx_sku=candidate,
            basis="exact_sku" if exact else "normalized_sku",
            confidence=1.0 if exact else 0.97,
            reason=("SKU quoted verbatim." if exact
                    else f"SKU '{line.vendor_sku}' normalised to {candidate}."),
        )

    text = " ".join(filter(None, [line.vendor_sku, line.description]))

    # Rung 3: dimensions plus a discriminating word
    signature = dimension_signature(text)
    if signature:
        hits = [
            rfx for rfx in rfx_lines
            if dimension_signature(rfx.description) == signature
        ]
        if len(hits) == 1 and not _contradicts(text, hits[0].description,
                                               vocabulary):
            return MatchResult(hits[0].sku, "dimensions", 0.88,
                               f"Dimensions {signature} are unique to this line.")
        if len(hits) == 1:
            # Same size, different product. Fall through and let the
            # description rung decide, rather than asserting a match the
            # wording flatly denies.
            hits = []
        if len(hits) > 1:
            words = _markers(text, vocabulary)
            refined = [rfx for rfx in hits
                       if _markers(rfx.description, vocabulary) & words]
            if len(refined) == 1:
                return MatchResult(
                    refined[0].sku, "dimensions", 0.85,
                    f"Dimensions {signature} plus "
                    f"{sorted(_markers(refined[0].description, vocabulary) & words)}.",
                )

    # Rung 4: what the descriptions agree about
    scored = sorted(
        ((_agreement(text, rfx.description, vocabulary), rfx)
         for rfx in rfx_lines),
        key=lambda pair: pair[0], reverse=True,
    )
    # Candidates the evidence rules out are not rivals. Leaving them in the
    # field made a contradicted near-miss suppress the correct match: a 32 GB
    # laptop scoring second stopped a 16 GB one from being recognised, though
    # its own figures had already disqualified it.
    viable = [(score, rfx) for score, rfx in scored
              if not _contradicts(text, rfx.description, vocabulary)]
    if viable:
        best_score, best = viable[0]
        if len(viable) < 2:
            # Nothing plausible to be better than, so the match stands on its
            # own agreement alone. This is also what stops the first line of a
            # derived comparison from swallowing every line after it.
            clears = best_score >= DESCRIPTION_FLOOR
            runner_up = 0.0
        else:
            runner_up = viable[1][0]
            lead = best_score - runner_up
            clears = ((best_score >= DESCRIPTION_FLOOR and lead >= DESCRIPTION_MARGIN)
                      or (best_score >= DECISIVE_FLOOR and lead >= DECISIVE_MARGIN))
        if clears:
            return MatchResult(best.sku, "description", round(best_score, 3),
                               f"Descriptions agree {best_score:.0%}, "
                               f"next best {runner_up:.0%}.")

    return MatchResult(None, "unmatched", 0.0,
                       "No SKU, dimensions or description close enough to an RFx line.")


def match_lines(
    lines: list[ExtractedLine],
    rfx_lines: Optional[list[RfxLine]] = None,
    adjudicate: Optional[Callable[[ExtractedLine, list[RfxLine]], MatchResult]] = None,
) -> MatchReport:
    """Match a vendor's extracted lines against the RFx.

    `adjudicate` is the optional final rung: a callable that asks the model to
    decide, used only for lines the deterministic rungs could not place.
    """
    rfx_lines = rfx_lines or rfx_module.active().lines
    vocabulary = marker_vocabulary([rfx.description for rfx in rfx_lines])
    report = MatchReport()

    for line in lines:
        result = match_one(line, rfx_lines, vocabulary)

        if result.rfx_sku is None and adjudicate is not None:
            try:
                adjudicated = adjudicate(line, rfx_lines)
                if adjudicated and adjudicated.rfx_sku in {rfx.sku for rfx in rfx_lines}:
                    result = adjudicated
            except Exception:
                pass  # a failed adjudication leaves the line unmatched, which is safe

        report.pairs.append((line, result))

        if result.rfx_sku is None:
            report.extra_lines.append(line)
            continue

        existing = report.match_by_sku.get(result.rfx_sku)
        if existing is None or result.confidence > existing.confidence:
            if existing is not None:
                report.duplicates.append((result.rfx_sku, report.by_sku[result.rfx_sku]))
            report.by_sku[result.rfx_sku] = line
            report.match_by_sku[result.rfx_sku] = result
        else:
            report.duplicates.append((result.rfx_sku, line))

    report.not_quoted = [rfx.sku for rfx in rfx_lines if rfx.sku not in report.by_sku]
    return report
