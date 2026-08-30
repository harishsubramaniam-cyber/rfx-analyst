"""Quality and compliance criteria, derived from the responses.

The first version of this was five hardcoded yes/no questions and an AND gate.
It had three faults, and every one of them mattered more than the code:

1. **It punished candour.** A supplier who disclosed "91.8%" against a 95%
   target was eliminated; a supplier who typed "Yes" with no figure and no
   evidence was not. Run that for one cycle and every supplier learns to write
   Yes.

2. **Its thresholds were invented.** "Capacity above 50,000 units/month" was
   nearly three times the buyer's entire annual basket. It removed viable
   suppliers for being smaller than a number nobody derived.

3. **It threw away the only comparable quality data in the set.** 96.4%, 97.1%
   and 91.8% are rankable. Yes / Yes / No is not.

So nothing here is fixed: the criteria are derived from whatever the suppliers
actually answered, and the thresholds are parsed from the questions themselves,
with the buyer free to move them.

The scoring itself is deliberately plain arithmetic:

    score = sum(weight of every criterion satisfied) / sum(weight of all of them)

A criterion is satisfied when the supplier's stated figure clears the target,
or -- where they gave no figure -- when they answered Yes. A bare Yes counts
exactly as much as a Yes with a number behind it. That is a decision about
explainability: a score a buyer can recompute on paper survives a procurement
committee, and one built from evidence multipliers does not.

What was measured and what backs it up are still captured and shown beside
every answer, so a buyer can see that one supplier disclosed 91.8% while
another simply wrote "Yes" -- the score just does not encode the difference.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# how much a claim is worth, depending on what backs it
# ---------------------------------------------------------------------------

EVIDENCE_LABEL = {
    "documented": "documented",
    "quantified": "figure given",
    "asserted": "asserted only",
    "none": "not answered",
}

VERDICTS = ("Yes", "No", "Partial", "Unanswered")

REQUIREMENT_LEVELS = ("Must have", "Scored", "Ignore")


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------

@dataclass
class Criterion:
    """One thing the buyer asked suppliers to confirm."""
    key: str
    question: str                      # the clearest phrasing any supplier used
    variants: list[str] = field(default_factory=list)
    kind: str = "other"                # certification | threshold | capability | other
    direction: str = "boolean"         # higher_better | lower_better | boolean
    threshold: Optional[float] = None
    unit: Optional[str] = None
    # Defaults to "Scored": nothing eliminates a supplier unless the buyer says
    # so. The old build eliminated three of five suppliers by default, on
    # unverified self-reports.
    requirement: str = "Scored"
    weight: float = 1.0
    # What the basket itself implies, offered to the buyer as a better default
    # than whatever round number the questionnaire happened to carry.
    suggested_threshold: Optional[float] = None

    @property
    def label(self) -> str:
        """The criterion as a testable statement, carrying the LIVE target.

        The question a supplier answered says "above 50,000 units". If the
        buyer moves that to 30,000, the row must say 30,000 -- otherwise the
        table is showing one number and scoring against another.
        """
        if self.threshold is None:
            return spell_out(self.question.rstrip("?").strip()) + "?"
        base = spell_out(_strip_target(self.question))
        return f"{base} {self.threshold_label}".strip()

    @property
    def threshold_label(self) -> str:
        if self.threshold is None:
            return "—"
        # Words, not symbols. "≥" is a maths glyph a buyer has to decode mid-row;
        # a criterion has to read as a sentence anyone can check an answer against.
        words = {"higher_better": "greater than",
                 "lower_better": "less than"}.get(self.direction, "")
        number = (f"{self.threshold:,.0f}" if float(self.threshold).is_integer()
                  else f"{self.threshold:,.2f}")
        unit = (self.unit or "").strip()
        # "%" hugs the number; a word does not. Typing a unit into the table
        # strips the leading space it was stored with, which is how you get
        # "30,000units/month".
        if unit and not unit.startswith("%"):
            unit = f" {unit}"
        return f"{words} {number}{unit}".strip()


@dataclass
class Answer:
    """What one supplier said about one criterion."""
    key: str
    verdict: str = "Unanswered"
    stated_text: str = ""
    value: Optional[float] = None
    unit: Optional[str] = None
    evidence: str = "none"
    evidence_text: str = ""
    note: str = ""

    @property
    def evidence_label(self) -> str:
        return EVIDENCE_LABEL.get(self.evidence, self.evidence)


@dataclass
class Scored:
    """One supplier's result on one criterion."""
    criterion: Criterion
    answer: Answer
    score: float = 0.0
    meets: Optional[bool] = None       # None when there is nothing to test against
    shortfall: Optional[float] = None  # how far under the target, as a fraction
    explanation: str = ""


@dataclass
class Scorecard:
    vendor: str
    results: dict[str, Scored] = field(default_factory=dict)
    overall: float = 0.0
    hard_failures: list[str] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)
    disclosed: int = 0                 # answers that came with a real figure

    @property
    def meets_requirements(self) -> bool:
        return not self.hard_failures


# ---------------------------------------------------------------------------
# reading a question
# ---------------------------------------------------------------------------

_UNIT_PATTERNS = [
    (r"%|per\s?cent|percent", "%"),
    (r"units?\s*/\s*month|units? per month|units?/mo|units?\s*pm", " units/month"),
    # "Monthly production capacity above 50,000 units" says the same thing
    # without ever writing "per month".
    (r"month\w*\b[^.?]*\bunits?\b|\bunits?\b[^.?]*\bmonth", " units/month"),
    (r"\bdays?\b", " days"),
    (r"\btonnes?\b|\bmt\b", " t"),
]

_HIGHER = r">|≥|>=|above|greater|at least|minimum|min\.|no less|exceed|over"
_LOWER = r"<|≤|<=|below|less than|under|maximum|max\.|no more|within"

_STOPWORDS = {
    "is", "are", "the", "a", "an", "do", "does", "you", "your", "we", "our",
    "have", "has", "held", "held?", "able", "to", "of", "in", "for", "and",
    "please", "confirm", "state", "provide", "kindly", "with", "on", "at",
    "be", "can", "will", "any", "per", "than", "that", "this", "it",
}


def _number(text: str) -> Optional[float]:
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def read_question(question: str) -> tuple[str, str, Optional[float], Optional[str]]:
    """Infer (kind, direction, threshold, unit) from the question's own words."""
    text = (question or "").strip()
    lowered = text.lower()

    unit = None
    for pattern, label in _UNIT_PATTERNS:
        if re.search(pattern, lowered):
            unit = label
            break

    direction = "boolean"
    if re.search(_LOWER, lowered):
        direction = "lower_better"
    elif re.search(_HIGHER, lowered):
        direction = "higher_better"

    threshold = None
    comparison = re.search(rf"(?:{_HIGHER}|{_LOWER})\s*([\d][\d,]*(?:\.\d+)?)", lowered)
    if comparison:
        threshold = _number(comparison.group(1))
    elif direction != "boolean":
        threshold = _number(lowered)
    else:
        # "Can meet a 30-day delivery SLA" carries a target without a comparator
        embedded = re.search(r"(\d[\d,]*)\s*[- ]?\s*day", lowered)
        if embedded:
            threshold = _number(embedded.group(1))
            direction = "lower_better"
            unit = " days"

    if re.search(r"iso\b|certif|accredit|audit|licen[cs]e|compliance standard", lowered):
        kind = "certification"
    elif threshold is not None:
        kind = "threshold"
    elif re.search(r"can |able|capab|willing|support|offer", lowered):
        kind = "capability"
    else:
        kind = "other"

    return kind, direction, threshold, unit


def _normalise(question: str) -> str:
    """Lowercase, and glue thousands separators back together.

    Without this "50,000" tokenises to {"50", "000"} and drags noise into every
    comparison.
    """
    text = (question or "").lower()
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


_TARGET_PHRASE = re.compile(
    r"\s*(?:is|are|of)?\s*(?:>=|<=|>|<|≥|≤|above|below|greater than|less than|"
    r"under|over|at least|at most|minimum|maximum|no less than|no more than|"
    r"exceeding|exceeds)\s*[\d][\d,]*(?:\.\d+)?\s*"
    r"(?:%|per\s?cent|percent|units?|days?|tonnes?)?", re.I)

_EMBEDDED_TARGET = re.compile(r"\s*\b[\d][\d,]*\s*[- ]?(?:day|hour|week|month)s?\b",
                              re.I)


def _strip_target(question: str) -> str:
    """Remove the target the question carries, leaving the thing being measured."""
    text = _TARGET_PHRASE.sub(" ", question or "")
    text = _EMBEDDED_TARGET.sub(" ", text)
    text = re.sub(r"\b(?:able to commit to|can you meet|do you meet|is your|"
                  r"are your|can meet|committed to)\b", "", text, flags=re.I)
    text = re.sub(r"\s*\ba\b\s*", " ", text)
    text = re.sub(r"[?,:;]+\s*$", "", text.strip())
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—")
    return text[:1].upper() + text[1:] if text else question


def _tokens(question: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _normalise(question))
    # A single digit is kept. "Rejection rate below 2%" and "below 5%" are
    # different questions, and dropping the digit made them one -- so a
    # supplier was scored against a target nobody had asked them about, and
    # could be excluded from the award for missing it.
    return {w for w in words
            if w not in _STOPWORDS and (len(w) > 1 or w.isdigit())}


def _words(question: str) -> set[str]:
    """Content words only -- no digits, no units. Used for acronyms."""
    return {w for w in _tokens(question) if not w.isdigit() and w not in
            {"units", "unit", "days", "day", "month", "monthly"}}


def _acronyms(question: str) -> set[str]:
    """'On-time delivery performance' also travels as 'OTD'.

    Built from the question itself rather than a lookup table, so it works for
    whatever shorthand a category happens to use.
    """
    # No stopword filter here: "ON-time delivery" is where the O in OTD comes
    # from. Precision comes from requiring a 3+ letter exact match instead.
    words = [w for w in re.findall(r"[a-z]+", _normalise(question)) if len(w) >= 2]
    if len(words) < 3:
        return set()
    # three letters minimum, so two-letter coincidences cannot merge anything
    found = set()
    for size in (3, 4):
        for start in range(0, len(words) - size + 1):
            found.add("".join(w[0] for w in words[start:start + size]))
    return found


# Display only. Where every supplier used the same shorthand there is nothing
# in the responses to expand it from, and a row heading of "OTD >95%" asks the
# buyer to decode jargon mid-decision. This never touches matching, scoring or
# the stored text -- an unknown acronym simply stays as it was written.
_SPELLED_OUT = {
    "OTD": "on-time delivery",
    "DIFOT": "delivery in full on time",
    "SLA": "service level",
    "MOQ": "minimum order quantity",
    "TAT": "turnaround time",
    "QC": "quality control",
    "QA": "quality assurance",
    "COA": "certificate of analysis",
    "NCR": "non-conformance report",
    "PPM": "defects per million",
    "FOB": "free on board",
    "CIF": "cost, insurance and freight",
    "EXW": "ex works",
    "LT": "lead time",
}


def spell_out(text: str) -> str:
    """Replace standalone shorthand with the words it stands for."""
    def swap(match: re.Match) -> str:
        return _SPELLED_OUT.get(match.group(0), match.group(0))
    return re.sub(r"\b[A-Z]{2,5}\b", swap, text or "")


def _slug(question: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", (question or "").lower())
             if w not in _STOPWORDS][:4]
    return "_".join(words) or "criterion"


def same_question(a: str, b: str) -> bool:
    """Two suppliers phrasing the same requirement differently.

    Real responses are far terser than a questionnaire template. A photographed
    rate card writes "Capacity" and "OTD >95%" where a covering letter writes
    "Monthly production capacity above 50,000 units?" and "On-time delivery
    performance above 95%?". All four rungs below exist because of cases like
    those; none of them names a specific question, so they carry over to any
    category.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False

    # A standard's number IS the question: ISO 9001 and ISO 14001 share every
    # word and are not remotely the same requirement. Where both sides name
    # numbers and none of them agree, they are different questions -- so this
    # guard sits ahead of every rung below.
    da, db = {t for t in ta if t.isdigit()}, {t for t in tb if t.isdigit()}
    numbers_conflict = bool(da and db and not (da & db))
    if numbers_conflict:
        return False

    # 1. a shared distinctive token pair: "iso"+"9001", "rejection"+"rate"
    distinctive = (ta & tb) - {"yes", "no", "months", "month"}
    if len(distinctive) >= 2 and len(distinctive) / max(1, len(ta | tb)) >= 0.3:
        return True

    # 2. one phrasing is a shorthand of the other -- "Capacity" inside
    #    "Monthly production capacity above 50,000 units"
    wa, wb = _words(a), _words(b)
    if wa and wb:
        shorter, longer = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
        if shorter <= longer:
            return True

    # 3. an acronym of one appears in the other: OTD -> on-time delivery
    if (ta & _acronyms(b)) or (tb & _acronyms(a)):
        return True

    # 4. same measurable target, same unit, and a shared WORD -- a shared
    #    number alone is not enough, or "payment terms 30 days" would merge
    #    with "can you meet a 30-day SLA"
    shared_words = (_words(a) & _words(b)) - {"delivery", "quality", "monthly"}
    ka, kb = read_question(a), read_question(b)
    if (ka[2] is not None and ka[2] == kb[2] and ka[3] == kb[3]
            and (shared_words or (ta & _acronyms(b)) or (tb & _acronyms(a)))):
        return True

    jaccard = len(ta & tb) / len(ta | tb)
    if jaccard >= 0.5:
        return True

    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.82


# ---------------------------------------------------------------------------
# reading an answer
# ---------------------------------------------------------------------------

_DOCUMENTED = re.compile(
    r"certificate\s*(no|number|#)|cert(?:ificate)?\s*[a-z]*[-/]?\d|enclos|attach|"
    r"annexure|report\b|audited|third[- ]party|sgs|intertek|bureau veritas|"
    r"valid (?:to|until|till)", re.I)


def read_answer(question_key: str, raw: dict) -> Answer:
    """Turn one supplier's raw answer into a scored-ready Answer."""
    verdict = str(raw.get("answer") or "Unanswered").strip().title()
    if verdict not in VERDICTS:
        verdict = "Unanswered" if not verdict else "Partial"

    stated = str(raw.get("stated_value") or "").strip()
    evidence_text = str(raw.get("evidence") or "").strip()
    note = str(raw.get("note") or "").strip()

    value = _number(stated) if stated else None
    unit = None
    if stated:
        for pattern, label in _UNIT_PATTERNS:
            if re.search(pattern, stated.lower()):
                unit = label
                break

    if verdict == "Unanswered":
        evidence = "none"
    elif evidence_text and _DOCUMENTED.search(evidence_text):
        evidence = "documented"
    elif value is not None:
        evidence = "quantified"
    else:
        evidence = "asserted"

    return Answer(key=question_key, verdict=verdict, stated_text=stated or verdict,
                  value=value, unit=unit, evidence=evidence,
                  evidence_text=evidence_text, note=note)


# ---------------------------------------------------------------------------
# deriving the criteria set
# ---------------------------------------------------------------------------

def _phrasing_rank(text: str) -> tuple[int, int]:
    """How readable one phrasing of the same question is, versus another.

    Suppliers write the same criterion as "OTD >95%" on a rate card and as
    "On-time delivery performance above 95%?" in a covering letter. The row
    heading has to be the sentence, not the shorthand -- so spelled-out words
    earn a point each and every bare acronym loses one. Length alone would not
    do it: "OTD >95% confirmed" is longer than "on-time delivery above 95".
    """
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    spelled = sum(1 for w in words if not (w.isupper() and 2 <= len(w) <= 5))
    acronyms = sum(1 for w in words if w.isupper() and 2 <= len(w) <= 5)
    return (spelled - acronyms, len(text))


def derive_criteria(responses) -> tuple[list[Criterion], dict[str, dict[str, Answer]]]:
    """Build the criteria set from whatever the suppliers actually answered.

    Returns (criteria, {vendor: {criterion_key: Answer}}).
    """
    criteria: list[Criterion] = []
    answers: dict[str, dict[str, Answer]] = {}

    for response in responses:
        answers.setdefault(response.vendor, {})
        for raw in (response.questionnaire or []):
            question = str(raw.get("question") or "").strip()
            if not question:
                continue

            match = next((c for c in criteria
                          if same_question(c.question, question)
                          or any(same_question(v, question) for v in c.variants)), None)

            if match is None:
                kind, direction, threshold, unit = read_question(question)
                match = Criterion(key=_slug(question), question=question,
                                  variants=[question], kind=kind, direction=direction,
                                  threshold=threshold, unit=unit)
                # keys must stay unique even when two questions slug the same
                existing = {c.key for c in criteria}
                if match.key in existing:
                    match.key = f"{match.key}_{len(criteria) + 1}"
                criteria.append(match)
            else:
                if question not in match.variants:
                    match.variants.append(question)
                # prefer the phrasing that carries the target
                if match.threshold is None:
                    _, direction, threshold, unit = read_question(question)
                    if threshold is not None:
                        match.direction, match.threshold, match.unit = (
                            direction, threshold, unit)
                if _phrasing_rank(question) > _phrasing_rank(match.question):
                    match.question = question

            answers[response.vendor][match.key] = read_answer(match.key, raw)

    return criteria, answers


def suggest_threshold(criterion: Criterion, basket_units_per_month: Optional[float]) -> Optional[float]:
    """A capacity target should come from the basket, not from a round number."""
    # Compared stripped. The unit is stored with a leading space so the label
    # reads "30,000 units/month", but a buyer who retypes it in the questions
    # table saves it without one -- and matching on the raw string meant the
    # basket-derived suggestion silently stopped being offered after any edit.
    if (criterion.unit or "").strip() != "units/month" or basket_units_per_month is None:
        return None
    # enough headroom to absorb the whole basket plus a margin, rounded to
    # something a buyer would actually write down
    target = basket_units_per_month * 1.5
    step = 1000 if target < 20000 else 5000
    return round(target / step) * step


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def score_answer(criterion: Criterion, answer: Answer) -> Scored:
    """Satisfied or not. One point or none, later multiplied by the weight.

    Where the supplier gave a figure AND the criterion has a target, the figure
    decides -- it is harder evidence than their own yes/no. Otherwise the
    answer decides, and a Yes with no figure counts in full.
    """
    result = Scored(criterion=criterion, answer=answer)

    if answer.verdict == "Unanswered":
        result.meets = False
        result.score = 0.0
        result.explanation = "Did not address this question at all."
        return result

    if criterion.threshold is not None and answer.value is not None:
        if criterion.direction == "lower_better":
            result.meets = answer.value <= criterion.threshold
        else:
            result.meets = answer.value >= criterion.threshold
        verb = "meets" if result.meets else "does not meet"
        result.explanation = (f"Stated {answer.stated_text}, which {verb} the "
                              f"target of {criterion.threshold_label}.")
        if not result.meets and criterion.threshold:
            result.shortfall = abs(answer.value - criterion.threshold) / criterion.threshold
    elif answer.verdict == "Yes":
        result.meets = True
        result.explanation = "Answered Yes."
    elif answer.verdict == "Partial":
        result.meets = False
        result.explanation = "Answered only in part."
    else:
        result.meets = False
        result.explanation = ("Answered No." if not answer.note
                              else f"Answered No — {answer.note}")

    result.score = 1.0 if result.meets else 0.0
    return result


def build_scorecard(vendor: str, criteria: list[Criterion],
                    answers: dict[str, Answer]) -> Scorecard:
    card = Scorecard(vendor=vendor)
    weighted, total_weight = 0.0, 0.0

    for criterion in criteria:
        answer = answers.get(criterion.key) or Answer(key=criterion.key)
        scored = score_answer(criterion, answer)
        card.results[criterion.key] = scored

        if answer.verdict == "Unanswered":
            card.unanswered.append(criterion.key)
        if answer.value is not None:
            card.disclosed += 1

        if criterion.requirement == "Ignore":
            continue
        if criterion.requirement == "Must have" and (scored.meets is not True):
            card.hard_failures.append(criterion.key)

        # weight x satisfied, over the total weight in play
        weighted += scored.score * criterion.weight
        total_weight += criterion.weight

    card.overall = round(weighted / total_weight, 4) if total_weight else 0.0
    return card


def score_all(criteria: list[Criterion],
              answers: dict[str, dict[str, Answer]]) -> dict[str, Scorecard]:
    return {vendor: build_scorecard(vendor, criteria, vendor_answers)
            for vendor, vendor_answers in answers.items()}


def rank(scorecards: dict[str, Scorecard]) -> list[Scorecard]:
    return sorted(scorecards.values(), key=lambda c: (-c.overall, c.vendor))
