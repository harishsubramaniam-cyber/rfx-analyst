"""Model-driven extraction, with provenance as a hard requirement.

The single rule that shapes this prompt: a number without a verbatim quote of
where it came from is worse than no number, because it looks equally
trustworthy on screen. So every line must carry the text it was read from, and
the extractor is told to return null rather than infer.

The RFx line list is supplied to the model, but only as an index for
identifying WHICH line a quote refers to. It is never a source of prices --
the prompt says so explicitly, and the matcher re-derives the SKU
deterministically afterwards anyway, so a hallucinated SKU cannot survive.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Optional

from . import config, llm
from .models import (DocumentPayload, ExtractedLine, MatchResult, SourceRef,
                     TermItem, VendorResponse)
from . import rfx as rfx_module
from .rfx import RfxLine

EXTRACTION_PROMPT = """You are a procurement analyst extracting a supplier's
response to an RFx. You are reading ONE supplier document.

{rfx_block}SUPPLIER DOCUMENT: {filename}
{reader_note}

DOCUMENT CONTENT
========================================
{content}
========================================

YOUR TASK
Extract what this supplier actually said. Nothing more.

ABSOLUTE RULES

1. NEVER invent a value. If the document does not state something, return null.

2. Any item list shown above is ONLY to help you identify which item a quote
   refers to. It is NOT a source of prices, units or currencies. Never copy a
   number from it. If no list was given, simply report every item this supplier
   priced, using their own item codes.

3. Every line you return MUST include a `source.snippet` containing the
   VERBATIM text from the document that the price was read from. If you cannot
   quote it, do not report it.

4. `source.locator` must give the position using this document's addressing
   scheme: {locator_hint}

5. Preserve the supplier's own words in `unit_text`. Write "per 100 pcs",
   "/kg", "per box/set" exactly as printed. Do NOT translate them into the
   buyer's unit. Someone downstream converts these; your job is to report them
   faithfully.

6. `currency` is what THIS LINE states. If the line shows only a number, use
   the document's currency. If the document never states a currency anywhere,
   set both the line currency and `document_currency` to null. Do not assume.

7. `conditions` is for a qualifier attached to ONE price -- a note in that
   row's remarks column, a footnote marker on that line, a sentence naming
   that item: "subject to print plate charges", "rest same as last year's
   rate", "priced for 180 GSM outer". Verbatim.

   Small print that covers the whole document -- a footer, a terms-and-
   conditions block, "all rates subject to confirmation", "E&OE", "prices
   exclude GST" -- is NOT a per-line condition. Put it in `terms` once. It
   applies to every price precisely because it was written about none of them,
   and repeating it on thirty lines buries the one row that really is
   conditional.

8. If the supplier refers to a document you were not given ("our standard 2025
   rate card", "last year's agreed rate"), add it to `unresolved_references`.

9. If a line is simply absent from the document, DO NOT return it. Absence is
   information and is handled downstream. Never emit a placeholder row.

10. `confidence` is 0 to 1 and describes how clearly THIS value was printed --
    nothing else. It is not how sure you are of your own work, and a uniform
    score across a document tells the buyer nothing. Discriminate:

      0.97-0.99  an exact figure in a clean spreadsheet cell or a text PDF
      0.90-0.96  clear print, but re-typed by you from a table or paragraph
      0.80-0.89  legible photograph or scan; digits unambiguous
      0.60-0.79  photograph with glare, skew, a crossed-out or handwritten
                 correction, a smudged or partly cropped digit
      below 0.6  you are reading a character you could reasonably get wrong

    Two lines on the same page can differ: a rate at a fold or under a shadow
    scores lower than the row above it. Judge each number on its own.

QUALITY AND COMPLIANCE QUESTIONS
The buyer sent this supplier a questionnaire. Report every question this
document answers, IN THE SUPPLIER'S OWN WORDS. Do not translate their phrasing
into a standard set, and do not invent questions the document does not address.

For each one give:
  "question"     - the question as printed or implied in THIS document
  "answer"       - exactly "Yes", "No", "Partial" or "Unanswered"
  "stated_value" - any specific figure they gave: "96.4%", "90,000 units/month",
                   "0.6%", "30-35 days". null if they gave no figure.
  "evidence"     - what backs the claim, verbatim: a certificate number, "copy
                   enclosed", "valid to Nov 2027", an attached third-party test
                   report. null if they offered nothing.
  "note"         - any explanation, caveat or remediation they added, verbatim.

A figure is worth far more to the buyer than a bare Yes, so if the document
states one you MUST capture it in `stated_value`. A supplier who discloses an
uncomfortable number is being useful; do not round it, soften it, or drop it.

TERMS
Capture freight, payment, validity, tax and discount statements. For a
discount, put the qualifying condition in `trigger` and the percentage in
`value`. Do not apply discounts to the line prices.

`freight_included` is true only if the document says freight is included in
the quoted rates, false if it says freight is extra, null if it is silent.

RETURN ONLY VALID JSON in exactly this shape:

{{
  "vendor": "the supplier's COMPANY name as printed on the document. If this is
             an email with no company name anywhere, derive a readable company
             name from the sender's domain. Never return an email address, a
             person's name, or a file name.",
  "document_currency": null,
  "freight_included": null,
  "payment_terms_days": null,
  "lead_time_days": null,
  "overall_confidence": 0.0,
  "extraction_notes": "anything the buyer should know about reading this document",
  "unresolved_references": [],
  "lines": [
    {{
      "vendor_sku": "",
      "description": "",
      "quoted_value": null,
      "currency": null,
      "unit_text": "",
      "quantity": null,
      "lead_time_days": null,
      "confidence": 0.0,
      "conditions": [],
      "notes": "",
      "source": {{"locator": "", "snippet": ""}}
    }}
  ],
  "questionnaire": [
    {{"question": "", "answer": "Yes|No|Partial|Unanswered",
      "stated_value": null, "evidence": null, "note": null}}
  ],
  "terms": [
    {{"kind": "freight|payment|validity|discount|tax|other",
      "text": "verbatim", "trigger": null, "value": null}}
  ]
}}
"""


def _reader_note(payload: DocumentPayload) -> str:
    if payload.images and not payload.text:
        return ("This document is supplied as IMAGES. Read the prices directly from "
                "the image. Take care with digits and currency symbols; where a "
                "character is genuinely unclear, lower the confidence for that line "
                "rather than guessing.")
    if payload.images and payload.text:
        return "This document is supplied as text AND page images. Prefer the images where they disagree."
    return "This document is supplied as extracted text with position markers."


def build_prompt(payload: DocumentPayload) -> str:
    content = payload.text[: config.MAX_DOC_CHARS] if payload.text else "(see attached images)"
    if payload.text and len(payload.text) > config.MAX_DOC_CHARS:
        content += "\n\n[TRUNCATED -- document exceeded the size limit]"

    # The item list is included only when the buyer's request is actually
    # known. When the comparison spine is being built from the responses
    # themselves there is nothing to show, and the model simply reports every
    # item the supplier priced -- which is less leading anyway.
    spec = rfx_module.active()
    rfx_block = ""
    if spec.lines:
        rfx_block = ("THE BUYER ASKED FOR PRICES ON THESE ITEMS:\n"
                     f"{spec.prompt_table()}\n\n")

    return EXTRACTION_PROMPT.format(
        rfx_block=rfx_block,
        filename=payload.file,
        reader_note=_reader_note(payload),
        content=content,
        locator_hint=payload.locator_hint or "quote the surrounding text",
    )


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

# The first number in a piece of text, with thousands separators attached to
# it. Deliberately anchored to a digit run rather than assembled character by
# character: the old version kept every digit, dot and minus sign in the string
# and threw the rest away, so "30-35 days" became "30-35" and then, failing
# float(), None -- a stated lead time silently discarded. "1.2 to 1.4 mm"
# became "1.21.4". A range gives up its first number here, which is the
# conservative end for a lead time and the one a buyer would read.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _as_float(value: Any) -> Optional[float]:
    """A number from whatever the model returned, or None. Never a NaN."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        # JSON admits Infinity and NaN, and Python's parser accepts both. One
        # of either in a quantity or a price poisons every sum it reaches, and
        # int(inf) raises OverflowError far downstream of the cell that caused
        # it. Refuse it here, where the value still has a name.
        return number if math.isfinite(number) else None
    match = _NUMBER.search(str(value))
    if not match:
        return None
    try:
        number = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any) -> Optional[int]:
    number = _as_float(value)
    if number is None or abs(number) >= 1e15:
        return None
    return int(number)


def _as_list(value: Any) -> list[str]:
    """A list of strings from a field the schema says is a list.

    A model asked for `["subject to plate charges"]` sometimes answers
    `"subject to plate charges"`, and iterating a string yields its letters --
    so one condition became twenty-six, each a single character, printed under
    the price as its qualifications. A lone string is one item.
    """
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


_EMAIL = re.compile(r"^[^@\s]+@([^@\s]+)$")


def clean_vendor_name(raw: Optional[str], fallback: str) -> str:
    """Make the supplier name fit to print in a column header.

    Emails arrive with no letterhead, so the model often reports the sender
    address as the supplier. A buyer should not be comparing prices from
    "sales@primepack.example". Rate cards, meanwhile, are frequently set in
    full caps, which shouts in a table.
    """
    name = (raw or "").strip().strip("\"'")
    if not name:
        return fallback

    match = _EMAIL.match(name)
    if match:
        domain = match.group(1)
        parts = [p for p in domain.split(".")
                 if p.lower() not in {"com", "co", "in", "net", "org", "example", "www"}]
        name = (parts[0] if parts else domain).replace("-", " ").title()

    letters = [c for c in name if c.isalpha()]
    if len(letters) > 4 and all(c.isupper() for c in letters):
        name = name.title()

    return name or fallback


def parse_response(data: dict[str, Any], payload: DocumentPayload) -> VendorResponse:
    # Everything below reads the model's JSON by key. When a model returns the
    # right information in a slightly different shape -- the whole document as a
    # bare list of lines, or a line as a string instead of an object -- the
    # dictionary access raised AttributeError, which is not caught anywhere
    # meaningful and so took down the reading of that supplier's file with a
    # stack trace instead of a sentence. Shape is checked at every level; a
    # malformed line is skipped, a malformed document reads as empty and is
    # reported as "no lines found", which is a thing the buyer can act on.
    if not isinstance(data, dict):
        data = {"lines": data} if isinstance(data, list) else {}

    response = VendorResponse(
        vendor=clean_vendor_name(data.get("vendor"), payload.file),
        file=payload.file,
        document_currency=(data.get("document_currency") or None),
        freight_included=data.get("freight_included"),
        payment_terms_days=_as_int(data.get("payment_terms_days")),
        lead_time_days=_as_float(data.get("lead_time_days")),
        overall_confidence=_as_float(data.get("overall_confidence")) or 0.0,
        extraction_notes=data.get("extraction_notes") or "",
        unresolved_references=_as_list(data.get("unresolved_references")),
    )

    for raw in data.get("lines") or []:
        if not isinstance(raw, dict):
            continue
        source_data = raw.get("source")
        if not isinstance(source_data, dict):
            source_data = {}
        response.lines.append(
            ExtractedLine(
                vendor_sku=(raw.get("vendor_sku") or None),
                description=(raw.get("description") or None),
                quoted_value=_as_float(raw.get("quoted_value")),
                currency=(raw.get("currency") or None),
                unit_text=(raw.get("unit_text") or None),
                quantity=_as_float(raw.get("quantity")),
                lead_time_days=_as_float(raw.get("lead_time_days")),
                confidence=_as_float(raw.get("confidence")) or 0.0,
                notes=raw.get("notes") or "",
                conditions=_as_list(raw.get("conditions")),
                source=SourceRef(
                    file=payload.file,
                    locator=source_data.get("locator") or payload.locator_hint,
                    snippet=source_data.get("snippet") or "",
                ),
            )
        )

    for raw in data.get("questionnaire") or []:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        if not question:
            continue
        response.questionnaire.append({
            "question": question,
            "answer": str(raw.get("answer") or "Unanswered").strip().title(),
            "stated_value": (str(raw.get("stated_value")).strip()
                             if raw.get("stated_value") not in (None, "") else None),
            "evidence": (str(raw.get("evidence")).strip()
                         if raw.get("evidence") not in (None, "") else None),
            "note": (str(raw.get("note")).strip()
                     if raw.get("note") not in (None, "") else None),
        })

    for raw in data.get("terms") or []:
        if not isinstance(raw, dict):
            if isinstance(raw, str) and raw.strip():
                response.terms.append(TermItem(kind="other", text=raw.strip()))
            continue
        response.terms.append(
            TermItem(
                kind=(raw.get("kind") or "other").lower(),
                text=raw.get("text") or "",
                trigger=raw.get("trigger") or None,
                value=_as_float(raw.get("value")),
            )
        )

    _demote_blanket_conditions(response)
    return response


# A condition that lands on nearly every line is a footer, not a qualification
# of any particular price. Attaching it per line would push a whole rate card
# into review and delete an entire supplier from the comparison over one line
# of small print -- while a genuine per-line condition, which is what a buyer
# actually needs to see, would be buried in the noise.
BLANKET_SHARE = 0.6


def _demote_blanket_conditions(response: VendorResponse) -> None:
    """Move document-wide small print off the lines and onto the supplier.

    Nothing is discarded: the text still shows under commercial terms, where a
    disclaimer covering the whole quote belongs. Conditions attached to a
    specific number are left exactly where they are.
    """
    if len(response.lines) < 5:
        return  # too few lines for "nearly every line" to mean anything

    counts: dict[str, int] = {}
    for line in response.lines:
        for condition in set(c.strip() for c in line.conditions if c and c.strip()):
            counts[condition.lower()] = counts.get(condition.lower(), 0) + 1

    threshold = BLANKET_SHARE * len(response.lines)
    blanket = {text for text, count in counts.items() if count >= threshold}
    if not blanket:
        return

    existing = {term.text.strip().lower() for term in response.terms}
    for line in response.lines:
        kept, moved = [], []
        for condition in line.conditions:
            (moved if condition.strip().lower() in blanket else kept).append(condition)
        line.conditions = kept
        for condition in moved:
            key = condition.strip().lower()
            if key not in existing:
                existing.add(key)
                response.terms.append(TermItem(
                    kind="other",
                    text=(f"{condition.strip()} "
                          f"(printed once for the whole quotation, so it is "
                          f"recorded here rather than against each price)"),
                ))


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def _fixture_path(payload: DocumentPayload) -> str:
    stem = os.path.splitext(os.path.basename(payload.file))[0]
    return os.path.join(config.FIXTURE_DIR, f"{stem}.json")


def extract(payload: DocumentPayload) -> VendorResponse:
    """Extract one vendor response from an ingested document."""
    if not payload.has_content:
        raise llm.ExtractionError(f"No readable content in {payload.file}.")

    # Test-only replay path. Never enabled in the demo; see README.
    if config.OFFLINE_FIXTURES:
        path = _fixture_path(payload)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                return parse_response(json.load(handle), payload)
        raise llm.ExtractionError(f"Offline fixtures enabled but {path} is missing.")

    data = llm.generate_json(
        build_prompt(payload),
        images=payload.images or None,
        image_mime=payload.image_mime,
        kind="extract",
    )
    return parse_response(data, payload)


# ---------------------------------------------------------------------------
# last-rung match adjudication
# ---------------------------------------------------------------------------

ADJUDICATION_PROMPT = """A supplier quoted a line that does not obviously map to
any line in the buyer's RFx. Decide which RFx line it corresponds to, or none.

SUPPLIER LINE
  code: {sku}
  description: {description}
  unit: {unit}

CANDIDATE RFx LINES
{candidates}

Rules:
- Match on what the product IS, not on price.
- If you are not confident, return null. A wrong match is far worse than none.
- You must give a reason a buyer can check.

Return JSON: {{"rfx_sku": null, "confidence": 0.0, "reason": ""}}
"""


def adjudicate_match(line: ExtractedLine, rfx_lines: list[RfxLine]) -> MatchResult:
    """Final matching rung. Only called for lines the deterministic rungs missed."""
    candidates = "\n".join(
        f"  {rfx.sku}: {rfx.description} ({rfx.canonical_unit})" for rfx in rfx_lines
    )
    data = llm.generate_json(
        ADJUDICATION_PROMPT.format(
            sku=line.vendor_sku or "(none)",
            description=line.description or "(none)",
            unit=line.unit_text or "(none)",
            candidates=candidates,
        ),
        kind="extract",
    )
    return MatchResult(
        rfx_sku=data.get("rfx_sku") or None,
        basis="llm",
        confidence=_as_float(data.get("confidence")) or 0.0,
        reason=data.get("reason") or "Model adjudication.",
    )
