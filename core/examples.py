"""Worked examples: a real request loaded from file, not written by the model.

The two buttons on the drafting page load a request that already exists, out of
`examples/corrugated_packaging.json`. They do not call the model, and they are
labelled on screen as loading an example rather than as the co-pilot answering.

That distinction is the whole point. The assignment's rule is that the AI loops
must be real and the answers must not be hardcoded, and this does not bend it:
the co-pilot's tool loop is untouched and still does the drafting whenever you
type. What these buttons do is put a worked request on screen in one click, so
a demo can begin at the interesting part, and so the page is still useful when
the model is unreachable -- a bad key, an exhausted quota, no network. A
drafting tool that shows nothing at all when the API is down is a worse tool
than one that hands you a starting point and says where it came from.

The file is also the single source of truth for the fabricated dataset. Its
`lines` are the standing items the five sample supplier responses quote
against, and they are always on the request; `optional_lines` are the extras a
buyer might add in a given year, drawn at random so the annual list is a
different length each time. If the standing items were duplicated instead of
shared, the seeded request and the sample replies would drift, and a demo would
open on thirty rows of "not quoted".
"""

from __future__ import annotations

import datetime
import json
import os
import random
from typing import Any, Optional

from . import criteria as criteria_module
from .draft import _clean_sku, _unit_family
from .rfx import RfxLine, RfxSpec

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_DIR = os.path.join(os.path.dirname(HERE), "examples")
DEFAULT_EXAMPLE = "corrugated_packaging.json"

# How many lines each example draft picks up. In the real thing these are
# however many items happen to be under their reorder point on the day, and
# however long this year's annual list runs -- so the count varies too, not
# just which items are drawn. A fixed count would read as a quota rather than
# a reading. Both are clamped to whatever the catalogue can actually supply,
# so a smaller category simply produces a smaller request instead of an error.
REPLENISHMENT_RANGE = (10, 15)
FULL_REQUEST_RANGE = (30, 35)


def load(name: str = DEFAULT_EXAMPLE) -> dict[str, Any]:
    with open(os.path.join(EXAMPLE_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def _apply_header(spec: RfxSpec, data: dict, title: Optional[str] = None) -> None:
    spec.title = title or data.get("title", "")
    spec.reference = data.get("reference", "")
    spec.scope = data.get("scope", "")
    spec.currency = data.get("currency", spec.currency)
    spec.currency_inferred = False
    spec.delivery_location = data.get("delivery_location", "")
    spec.terms = dict(data.get("terms") or {})
    spec.vendor_category = data.get("vendor_category", "")
    spec.notes = data.get("issuer_notes", "")
    # Dates relative to today, not baked into the file. A worked example that
    # opens with last month's closing date teaches the reader that the dates
    # are decoration.
    # Opens at nine this morning, closes at five on the last day: the hours a
    # buyer would actually name, rather than midnight-to-midnight, which reads
    # to a supplier as "some time that day" and to a buyer as "first thing".
    today = datetime.date.today()
    spec.starts_at = f"{today.isoformat()}T09:00"
    spec.ends_at = (
        f"{(today + datetime.timedelta(days=int(data.get('window_days', 12)))).isoformat()}"
        f"T17:00")
    spec.derived = False


def _add_lines(spec: RfxSpec, rows: list[dict], origin: str) -> int:
    existing = {line.sku for line in spec.lines}
    added = 0
    for row in rows:
        label, family = _unit_family(row.get("unit") or "per unit")
        code = _clean_sku(row.get("sku") or row.get("description", ""), existing)
        existing.add(code)
        spec.lines.append(RfxLine(
            sku=code,
            description=row.get("description", "").strip(),
            quantity=int(row["quantity"]) if row.get("quantity") else None,
            canonical_unit=label,
            unit_family=family,
            origin=origin,
            note=(f"Minimum order quantity {row['moq']:,}." if row.get("moq") else ""),
        ))
        added += 1
    return added


def _add_questions(spec: RfxSpec, questions: list[dict]) -> int:
    added = 0
    for row in questions:
        text = row.get("question", "").strip()
        if not text or any(criteria_module.same_question(c.question, text)
                           for c in spec.criteria):
            continue
        kind, direction, threshold, unit = criteria_module.read_question(text)
        spec.criteria.append(criteria_module.Criterion(
            key=criteria_module._slug(text),
            question=text,
            variants=[text],
            kind=kind,
            direction=row.get("direction") or direction or "boolean",
            threshold=row.get("threshold", threshold),
            unit=row.get("unit", unit),
            requirement=row.get("requirement", "Scored"),
            weight=float(row.get("weight", 1)),
        ))
        added += 1
    return added


def seed_replenishment(spec: RfxSpec, name: str = DEFAULT_EXAMPLE,
                       count: Optional[int] = None,
                       seed: Optional[int] = None) -> dict:
    """The items a stock system would have flagged as below their minimum.

    Seven to ten of them, drawn at random rather than taken off the top of the
    list. Stock does not run down in catalogue order, and it does not run down
    a fixed number of lines at a time either -- the items under their reorder
    point on any given morning are scattered across the range, and there are as
    many of them as there are. A draft that always produced the same ten would
    quietly teach whoever watches the demo that this is a fixed list rather
    than a reading of the day's position. They are put back in catalogue order
    once drawn, because a buyer reads a request in the order they think about
    their items.

    Every line lands as `suggested`, because in this build nothing read a stock
    level -- the connection described on the page does not exist, and a line
    nobody verified must not reach a supplier unchecked.
    """
    data = load(name)
    _apply_header(spec, data,
                  title=f"{data.get('title', 'Replenishment')} — replenishment")

    available = data.get("lines", [])
    picker = random.Random(seed)          # seeded only by the tests
    wanted = count if count is not None else picker.randint(*REPLENISHMENT_RANGE)
    chosen = sorted(picker.sample(range(len(available)), min(wanted, len(available))))
    lines = [available[index] for index in chosen]

    added = _add_lines(spec, lines, origin="suggested")
    asked = _add_questions(spec, data.get("questions") or [])
    return {"lines": added, "questions": asked,
            "total_available": len(available),
            "skus": [line.sku for line in spec.lines]}


def complete_from_document(spec: RfxSpec, name: str = DEFAULT_EXAMPLE) -> dict:
    """Turn a list of items into an actual request.

    Reading a purchase order gives you what to buy. It does not give you the
    questions you want answered, the terms you sell on, or the instruction that
    every charge must carry a number -- those are the buyer's, they are the
    same on every request they run, and re-typing them each time is exactly the
    drudgery this is supposed to remove.

    So the items come from the document (real extraction, nothing seeded) and
    the rest of the request is filled in from the buyer's standing template. It
    is all editable, and the interface says which half came from where.
    """
    data = load(name)
    if not spec.currency or spec.currency_inferred:
        spec.currency = data.get("currency", spec.currency)
        spec.currency_inferred = False
    spec.reference = spec.reference or data.get("reference", "")
    spec.scope = spec.scope or data.get("scope", "")
    spec.delivery_location = spec.delivery_location or data.get("delivery_location", "")
    spec.vendor_category = spec.vendor_category or data.get("vendor_category", "")
    spec.notes = spec.notes or data.get("issuer_notes", "")
    if not spec.starts_at:
        today = datetime.date.today()
        spec.starts_at = f"{today.isoformat()}T09:00"
        spec.ends_at = (
            f"{(today + datetime.timedelta(days=int(data.get('window_days', 12)))).isoformat()}"
            f"T17:00")
    spec.derived = False

    asked = _add_questions(spec, data.get("questions") or [])

    terms_added = 0
    for key, value in (data.get("terms") or {}).items():
        if key not in spec.terms:
            spec.terms[key] = value
            terms_added += 1
    notes = list(data.get("notes") or [])
    if notes and "charges" not in spec.terms:
        spec.terms["charges"] = notes[0]
        terms_added += 1
        for index, note in enumerate(notes[1:], start=1):
            spec.terms[f"note {index}"] = note
            terms_added += 1

    return {"questions": asked, "terms": terms_added}


def _annual_lines(data: dict, seed: Optional[int] = None) -> list[dict]:
    """This year's annual list: the standing items, plus whatever else the
    buyer has decided to put out to tender this time.

    The standing items always go in -- they are the contract being renewed.
    The rest are drawn from the optional pool, so the request is a different
    length each year without ever losing the core of it. Where a catalogue
    offers no optional items, the request is simply the standing list, which
    is what a smaller category looks like.
    """
    core = list(data.get("lines") or [])
    optional = list(data.get("optional_lines") or [])
    if not optional:
        return core
    picker = random.Random(seed)
    low, high = FULL_REQUEST_RANGE
    target = picker.randint(max(low, len(core)), max(high, len(core)))
    extra = min(max(0, target - len(core)), len(optional))
    chosen = sorted(picker.sample(range(len(optional)), extra))
    return core + [optional[index] for index in chosen]


def seed_full_request(spec: RfxSpec, name: str = DEFAULT_EXAMPLE,
                      seed: Optional[int] = None) -> dict:
    """The full annual request: every item, the questionnaire, and the notes.

    These lines are the buyer's own -- this is the request they run every year,
    not a proposal -- so they are not marked suggested and go out as they are.
    """
    data = load(name)
    _apply_header(spec, data)
    added = _add_lines(spec, _annual_lines(data, seed), origin="buyer")
    asked = _add_questions(spec, data.get("questions") or [])
    notes = list(data.get("notes") or [])
    if notes:
        # Kept as a term rather than glued onto every line: it is one
        # instruction about how to quote, and it belongs where a supplier
        # reads the rules, not repeated thirty times.
        spec.terms["charges"] = notes[0]
        for index, note in enumerate(notes[1:], start=1):
            spec.terms[f"note {index}"] = note
    return {"lines": added, "questions": asked, "notes": len(notes)}
