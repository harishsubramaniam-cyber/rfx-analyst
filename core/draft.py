"""The RFx co-pilot: a buyer talks a request into existence.

Two rules shape everything here.

**The model edits the real object, not a transcript.** Every turn is a manual
function-calling loop whose tools mutate the same `RfxSpec` the comparison
engine consumes. There is no "now parse the conversation into a spec" step,
because that step is where a drafting assistant quietly invents a line item
nobody asked for. What the buyer sees in the draft panel IS what will be sent
and what responses will be compared against -- one object, three views.

**A line the co-pilot proposed is marked as proposed.** Asked for "thirty
corrugated items", a language model will produce thirty plausible ones, and a
buyer skim-reading a tidy table cannot tell which of them they actually asked
for. So every line carries an origin, anything the model proposed lands as
`suggested`, and a suggestion is never sent to a supplier until a person
accepts it. This is the same provenance rule the extraction side follows: the
system never passes its own guess off as somebody's requirement.

**Where that third source is meant to come from.** A replenishment RFx does
not really begin with a buyer listing items from memory: it begins in the
warehouse, with the items that have fallen below their minimum stock level and
the shortfall as the quantity. That is the intended source -- the co-pilot
reads the WMS or ERP, pulls everything under its reorder point, and drafts the
request against real numbers. **That connection is not built here.** There is no
stock tool, the prompt says so explicitly, and until there is, items asked for
this way come from the model's own knowledge of the category and are marked
`suggested` precisely because nothing behind them is a fact. Wiring it up
changes only where `add_line` gets its arguments; everything downstream --
provenance, acceptance, the document, the comparison -- already works the way
it would need to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from google.genai import types

from . import criteria as criteria_module
from . import derive as derive_module
from . import llm, normalize, skus
from .rfx import RfxLine, RfxSpec

SYSTEM_PROMPT = """You are helping a category buyer draft a request to
suppliers (an RFx). You are drafting a document that five companies will price
and that a buyer may award several crore rupees against, so precision matters
more than helpfulness.

You do not write the request in prose. You build it by calling tools. Each
call changes the draft the buyer is watching on screen.

WHAT A COMPLETE REQUEST NEEDS
  * a scope: what is being bought, for where, in which currency, by when
  * line items: each with a code, a description precise enough to price, a
    quantity, and the unit a price should be quoted per
  * questions: whatever the buyer needs suppliers to confirm before award
  * terms: payment, delivery, how long the price must hold, tax treatment

HOW TO WORK
1. Ask what you actually need. Do not interrogate the buyer through a
   checklist -- ask the two or three questions that unblock the next step.
2. If the buyer has a list, a previous order, a BOM or a spreadsheet, ask for
   it and say they can attach it. Reading their real list always beats
   inventing one.
3. Call the tools as the conversation goes. Do not save everything for a big
   final call: the buyer is watching the draft build.
4. Call show_draft whenever you need to know what is already there. Never
   guess at the current state.

ITEMS BELOW THEIR MINIMUM STOCK LEVEL
Most replenishment requests start from the warehouse: the items under their
reorder point, and the shortfall as the quantity. You do NOT have a connection
to the buyer's warehouse or ERP in this build. There is no tool to read stock,
and you must never imply you have read one.

So when the buyer asks for "whatever is below minimum", or for a number of
items in a category without listing them, you may propose lines from your own
knowledge of that category -- and you must:
  * add every one with origin="suggested"
  * say in your reply, plainly, that these are proposed from category
    knowledge and NOT read from their stock system, and that quantities in
    particular are guesses they need to replace
  * offer the alternative: they can attach a stock report, a reorder list or
    a purchase order and you will read the real items and quantities out of it

Never present a proposed item as a stock fact. Never invent a stock level, a
reorder point or an on-hand figure. Never mark your own proposal as "buyer".

DESCRIPTIONS
A description has to be precise enough that two suppliers price the same
thing. "Corrugated box" is not; "5-ply corrugated box 400x300x250 mm, 180 GSM
kraft outer" is. If the buyer's description is too loose to price, say so and
ask the one question that fixes it.

UNITS
The unit is what ONE price covers: per box, per sheet, per roll, per kg, per
metre, per unit. Getting this wrong is the single most common way a quote
comparison goes wrong, so state it on every line.

QUESTIONS
Write each as something a supplier can answer and a buyer can test. Prefer a
number with a direction ("monthly capacity of at least X units") to a vague
ask ("adequate capacity"). Where the buyer's own basket implies a sensible
target, propose that rather than a round number, and say where it came from.

HOW TO REPLY
Short. Say what you changed, then ask the next thing you need. Never list the
whole draft back at the buyer -- it is on screen next to you.
"""


@dataclass
class DraftTurn:
    """One exchange, kept so the panel can show what changed and why."""
    question: str
    answer: str = ""
    changes: list[str] = field(default_factory=list)
    rounds: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _unit_family(unit_text: str) -> tuple[str, str]:
    """Read a buyer's unit words with the same parser the quotes go through.

    Deliberately the same code path: if "per 100 sheets" means something on the
    response side, it has to mean exactly that on the request side too.
    """
    spec = normalize.parse_unit(unit_text)
    family = spec.family or "discrete"
    noun = spec.noun or (unit_text or "unit").strip().lower()
    noun = re.sub(r"^per\s+", "", noun).strip() or "unit"
    # "Nos", "ea", "pcs" mean "one of them" rather than naming a thing, and a
    # request that says "price per no" reads as a typo to the supplier who has
    # to answer it. Same rule the derived spine uses, so a drafted request and
    # a derived one label the same unit the same way.
    if noun in derive_module._COUNTING_WORDS:
        noun = "unit"
    # A buyer who asks for a price "per 100 sheets" means it. Dropping the
    # hundred and asking for a price "per sheet" changes the request by two
    # orders of magnitude, silently, on the one field where that is hardest
    # to spot.
    if spec.pack > 1:
        label = f"per {spec.pack:,.0f} {noun}"
        if not label.endswith("s"):
            label += "s"
    else:
        label = f"per {noun}"
    return label, family


def _clean_sku(raw: str, existing: set[str]) -> str:
    """A code the buyer will recognise, unique within the request.

    Anything shaped like an item code goes through the same normaliser the
    matcher uses, so a buyer typing "bx 1" and a supplier writing "BX-001" end
    up on the same row rather than two rows that never meet.
    """
    tidy = skus.normalize_sku(raw)
    code = tidy or re.sub(r"[^A-Za-z0-9\-]+", "-", (raw or "").strip()).strip("-").upper()
    if not code:
        code = "ITEM"
    candidate, suffix = code, 2
    while candidate in existing:
        candidate = f"{code}-{suffix}"
        suffix += 1
    return candidate


DECLARATIONS = [
    types.FunctionDeclaration(
        name="set_scope",
        description=("Set or update what this request is for. Call it as soon as "
                     "you know any part; you can call it again to fill in the rest."),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "title": types.Schema(type=types.Type.STRING,
                                      description="e.g. 'Corrugated packaging — annual rate contract'"),
                "reference": types.Schema(type=types.Type.STRING,
                                          description="The buyer's own reference, if they have one."),
                "scope": types.Schema(type=types.Type.STRING,
                                      description="What is being bought, in one or two sentences."),
                "currency": types.Schema(type=types.Type.STRING,
                                         description="ISO code suppliers must quote in: INR, USD, EUR, GBP."),
                "delivery_location": types.Schema(type=types.Type.STRING),
                "starts_at": types.Schema(
                    type=types.Type.STRING,
                    description="When the RFQ opens: 'YYYY-MM-DDTHH:MM'."),
                "ends_at": types.Schema(
                    type=types.Type.STRING,
                    description="When the RFQ closes: 'YYYY-MM-DDTHH:MM'. "
                                "Always give a time, never a bare date."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="add_line",
        description=("Add one item to the request. Call once per item. If the "
                     "buyer did not state this item and you are proposing it, "
                     "you MUST pass origin='suggested'."),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sku": types.Schema(type=types.Type.STRING,
                                    description="Item code. Invent a consistent one if the buyer has none."),
                "description": types.Schema(type=types.Type.STRING,
                                            description="Precise enough that two suppliers price the same thing."),
                "quantity": types.Schema(type=types.Type.NUMBER,
                                         description="How many are being bought over the contract period."),
                "unit": types.Schema(type=types.Type.STRING,
                                     description="What ONE price covers: 'per box', 'per kg', 'per 100 sheets'."),
                "origin": types.Schema(type=types.Type.STRING,
                                       description="'buyer' if they stated it, 'suggested' if you proposed it."),
                "note": types.Schema(type=types.Type.STRING,
                                     description="Anything a supplier needs to know about this line."),
            },
            required=["sku", "description", "unit"],
        ),
    ),
    types.FunctionDeclaration(
        name="revise_line",
        description="Change one existing line. Only the fields you pass are changed.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sku": types.Schema(type=types.Type.STRING),
                "description": types.Schema(type=types.Type.STRING),
                "quantity": types.Schema(type=types.Type.NUMBER),
                "unit": types.Schema(type=types.Type.STRING),
                "note": types.Schema(type=types.Type.STRING),
            },
            required=["sku"],
        ),
    ),
    types.FunctionDeclaration(
        name="remove_line",
        description="Remove one line from the request.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"sku": types.Schema(type=types.Type.STRING)},
            required=["sku"],
        ),
    ),
    types.FunctionDeclaration(
        name="add_question",
        description=("Add one question suppliers must answer. Give a threshold "
                     "and direction whenever the answer is a number, so the "
                     "answers can be scored rather than just read."),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "question": types.Schema(type=types.Type.STRING,
                                         description="As the supplier will read it."),
                "threshold": types.Schema(type=types.Type.NUMBER,
                                          description="The number they must meet, if any."),
                "direction": types.Schema(type=types.Type.STRING,
                                          description="'higher_better' or 'lower_better'."),
                "unit": types.Schema(type=types.Type.STRING,
                                     description="e.g. '%', ' units/month', ' days'."),
                "requirement": types.Schema(type=types.Type.STRING,
                                            description="'Scored' (default) or 'Must have'."),
                "weight": types.Schema(type=types.Type.NUMBER,
                                       description="Relative importance. Default 1."),
            },
            required=["question"],
        ),
    ),
    types.FunctionDeclaration(
        name="remove_question",
        description="Remove one question, by its exact text.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"question": types.Schema(type=types.Type.STRING)},
            required=["question"],
        ),
    ),
    types.FunctionDeclaration(
        name="set_term",
        description="Set one commercial term on the request.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "kind": types.Schema(type=types.Type.STRING,
                                     description="payment | delivery | validity | tax | other"),
                "text": types.Schema(type=types.Type.STRING,
                                     description="The term as suppliers will read it."),
            },
            required=["kind", "text"],
        ),
    ),
    types.FunctionDeclaration(
        name="show_draft",
        description=("Read the request as it currently stands. Call this before "
                     "changing anything you are not certain about."),
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
]


# ---------------------------------------------------------------------------
# the tools, bound to one spec
# ---------------------------------------------------------------------------

def _tools(spec: RfxSpec, changes: list[str]) -> dict[str, Any]:

    def set_scope(title: str = None, reference: str = None, scope: str = None,
                  currency: str = None, delivery_location: str = None,
                  starts_at: str = None, ends_at: str = None) -> dict:
        if title:
            spec.title = title
        if reference:
            spec.reference = reference
        if scope:
            spec.scope = scope
        if currency:
            spec.currency = currency.strip().upper()[:3]
            spec.currency_inferred = False
        if delivery_location:
            spec.delivery_location = delivery_location
        if starts_at:
            spec.starts_at = starts_at.strip()
        if ends_at:
            spec.ends_at = ends_at.strip()
        spec.derived = False
        changes.append("scope updated")
        return {"ok": True, "title": spec.title, "currency": spec.currency}

    def add_line(sku: str, description: str, unit: str,
                 quantity: float = None, origin: str = "buyer",
                 note: str = "") -> dict:
        label, family = _unit_family(unit)
        code = _clean_sku(sku, {line.sku for line in spec.lines})
        origin = "suggested" if str(origin).lower().startswith("sugg") else "buyer"
        spec.lines.append(RfxLine(
            sku=code, description=description.strip(),
            quantity=int(quantity) if quantity else None,
            canonical_unit=label, unit_family=family,
            origin=origin, note=note or "",
        ))
        spec.derived = False
        changes.append(f"added {code}" + (" (suggested)" if origin == "suggested" else ""))
        return {"ok": True, "sku": code, "unit": label, "origin": origin,
                "line_count": len(spec.lines)}

    def revise_line(sku: str, description: str = None, quantity: float = None,
                    unit: str = None, note: str = None) -> dict:
        for index, line in enumerate(spec.lines):
            if line.sku.upper() != sku.strip().upper():
                continue
            label, family = (_unit_family(unit) if unit
                             else (line.canonical_unit, line.unit_family))
            spec.lines[index] = RfxLine(
                sku=line.sku,
                description=description.strip() if description else line.description,
                quantity=int(quantity) if quantity else line.quantity,
                canonical_unit=label, unit_family=family,
                # A suggestion stays a suggestion when the co-pilot revises it:
                # editing its own invention is not the same as a person
                # accepting it. Only a human act clears that flag.
                origin=line.origin,
                note=note if note is not None else line.note,
            )
            changes.append(f"revised {line.sku}")
            return {"ok": True, "sku": line.sku}
        return {"error": f"No line {sku} in this request."}

    def remove_line(sku: str) -> dict:
        before = len(spec.lines)
        spec.lines[:] = [l for l in spec.lines if l.sku.upper() != sku.strip().upper()]
        if len(spec.lines) == before:
            return {"error": f"No line {sku} in this request."}
        changes.append(f"removed {sku}")
        return {"ok": True, "line_count": len(spec.lines)}

    def add_question(question: str, threshold: float = None, direction: str = None,
                     unit: str = None, requirement: str = "Scored",
                     weight: float = 1.0) -> dict:
        text = question.strip()
        for existing in spec.criteria:
            if criteria_module.same_question(existing.question, text):
                return {"error": "That question is already in the request as "
                                 f"'{existing.question}'."}
        kind, read_direction, read_threshold, read_unit = \
            criteria_module.read_question(text)
        criterion = criteria_module.Criterion(
            key=criteria_module._slug(text),
            question=text,
            variants=[text],
            kind=kind,
            direction=(direction or read_direction or "boolean"),
            threshold=threshold if threshold is not None else read_threshold,
            unit=unit if unit is not None else read_unit,
            requirement=("Must have" if str(requirement).lower().startswith("must")
                         else "Scored"),
            weight=float(weight or 1.0),
        )
        spec.criteria.append(criterion)
        spec.derived = False
        changes.append(f"asked: {criterion.label}")
        return {"ok": True, "question": criterion.label,
                "requirement": criterion.requirement}

    def remove_question(question: str) -> dict:
        before = len(spec.criteria)
        spec.criteria[:] = [c for c in spec.criteria
                            if not criteria_module.same_question(c.question, question)]
        if len(spec.criteria) == before:
            return {"error": "No such question in this request."}
        changes.append("removed a question")
        return {"ok": True, "question_count": len(spec.criteria)}

    def set_term(kind: str, text: str) -> dict:
        spec.terms[kind.strip().lower()] = text.strip()
        spec.derived = False
        changes.append(f"{kind.lower()} terms set")
        return {"ok": True, "terms": spec.terms}

    def show_draft() -> dict:
        return {
            "title": spec.title, "reference": spec.reference, "scope": spec.scope,
            "currency": spec.currency, "delivery_location": spec.delivery_location,
            "starts_at": spec.starts_at, "ends_at": spec.ends_at,
            "vendor_category": spec.vendor_category, "notes": spec.notes,
            "terms": spec.terms,
            "line_count": len(spec.lines),
            "lines": [{"sku": l.sku, "description": l.description,
                       "quantity": l.quantity, "unit": l.canonical_unit,
                       "origin": l.origin, "note": l.note} for l in spec.lines],
            "questions": [{"question": c.label, "requirement": c.requirement,
                           "weight": c.weight} for c in spec.criteria],
        }

    return {"set_scope": set_scope, "add_line": add_line,
            "revise_line": revise_line, "remove_line": remove_line,
            "add_question": add_question, "remove_question": remove_question,
            "set_term": set_term, "show_draft": show_draft}


# ---------------------------------------------------------------------------
# one turn of the conversation
# ---------------------------------------------------------------------------

def converse(message: str, spec: RfxSpec,
             history: Optional[list[dict]] = None) -> DraftTurn:
    """Run one buyer turn against the draft. Mutates `spec` in place."""
    turn = DraftTurn(question=message)
    changes: list[str] = []

    try:
        outcome = llm.run_tool_loop(
            system_prompt=SYSTEM_PROMPT,
            user_message=message,
            tools=_tools(spec, changes),
            declarations=DECLARATIONS,
            kind="analyst",
            history=history or [],
            max_rounds=12,
        )
        turn.answer = outcome.text
        turn.rounds = outcome.rounds
    except Exception as exc:
        # Name the actual failure. "Could not reach the model" sends a buyer
        # looking at their network when the real answer is usually an unset key
        # or an exhausted quota, and they cannot tell those apart from a
        # sentence that refuses to say which happened.
        turn.error = f"{type(exc).__name__}: {exc}"
        detail = str(exc)
        if "busy rather than broken" in detail or "503" in detail or "high demand" in detail:
            hint = ("**Google's model is overloaded, not your setup.** It was "
                    "retried three times and then on a second model, and every "
                    "attempt came back busy. This clears on its own, usually "
                    "within a minute — press send again.")
        elif "GEMINI_API_KEY" in detail or "API key" in detail:
            hint = ("No usable API key. Copy `.env.example` to `.env`, put your "
                    "key in it, and restart.")
        elif "quota" in detail.lower() or "429" in detail:
            hint = ("The key is being rate-limited or is out of quota. Wait a "
                    "minute and try again, or use a different key.")
        elif "403" in detail or "permission" in detail.lower():
            hint = ("The key was rejected. Check it is enabled for the Gemini "
                    "API, and press **Run connection check** in the sidebar.")
        else:
            hint = ("Press **Run connection check** in the sidebar to see what "
                    "the model call is actually returning.")
        turn.answer = (
            f"**That turn did not reach the model, so nothing in the draft "
            f"changed.** {hint}\n\n"
            f"You are not stuck: the two example buttons load a complete "
            f"request without the model, and you can edit every line, quantity "
            f"and unit directly in the table on the right.\n\n"
            f"`{turn.error[:300]}`")

    turn.changes = changes
    return turn


# ---------------------------------------------------------------------------
# reading the buyer's own list out of a file they already have
# ---------------------------------------------------------------------------

REQUEST_PROMPT = """You are reading a document a BUYER has handed over while
drafting a request to suppliers. It might be a purchase order, a bill of
materials, last year's contract, or a plain list of what they buy.

Pull out the items they want priced. Return JSON:

{
  "title": null,
  "currency": null,
  "lines": [
    {"sku": null, "description": "", "quantity": null, "unit": null, "note": null}
  ]
}

RULES
1. Return only items that are actually in the document. Never pad the list to
   a round number, and never invent a line because a range looks incomplete.
2. `unit` is what ONE price covers, in the document's own words: "per box",
   "per kg", "per 100 sheets". Null if the document does not say.
3. `sku` is the buyer's own code if there is one, else null.
4. `quantity` is a number only. Strip commas and units.
5. If a price appears, IGNORE it. This is what they want to buy, not what
   anyone charged.
6. If the document contains no item list at all, return "lines": [].

DOCUMENT
{document}
"""


def lines_from_document(text: str, spec: RfxSpec) -> dict:
    """Read a buyer's own list into the draft. Real extraction, same as quotes."""
    data = llm.generate_json(
        REQUEST_PROMPT.replace("{document}", text[:120000]), kind="extract")

    existing = {line.sku for line in spec.lines}
    added = 0
    for raw in data.get("lines") or []:
        description = str(raw.get("description") or "").strip()
        if not description:
            continue
        label, family = _unit_family(str(raw.get("unit") or "unit"))
        code = _clean_sku(str(raw.get("sku") or description[:12]), existing)
        existing.add(code)
        quantity = raw.get("quantity")
        spec.lines.append(RfxLine(
            sku=code, description=description,
            quantity=int(quantity) if isinstance(quantity, (int, float)) and quantity else None,
            canonical_unit=label, unit_family=family,
            # Read from the buyer's own document: theirs, not a suggestion.
            origin="document",
            note=str(raw.get("note") or ""),
        ))
        added += 1

    if data.get("currency") and spec.currency_inferred:
        spec.currency = str(data["currency"]).strip().upper()[:3]
        spec.currency_inferred = False
    if data.get("title") and not spec.title:
        spec.title = str(data["title"]).strip()
    if added:
        spec.derived = False
    return {"added": added, "line_count": len(spec.lines)}


# Category-specific on purpose: these are the buyer's own words, and this
# buyer sources packaging. The engine is category-agnostic; the demo is not
# supposed to be, and a starter prompt about IT hardware on a packaging
# company's screen just reads as a stray template.
# The drafting page no longer shows free-text starters: the two buttons there
# load a worked request from examples/ instead, which works with the model
# unreachable. These remain for anyone driving core.draft directly.
OPENING_PROMPTS = [
    "Draft a replenishment request for whatever is below its minimum stock "
    "level — I will correct the list and the quantities.",
    "I need to run an RFx for corrugated packaging — about 30 items, annual "
    "rate contract, delivered to our Bommasandra warehouse.",
    "I have last year's purchase order — can I attach it and start from that?",
]
