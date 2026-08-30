"""Presentation helpers: turning cells into something a buyer can read fast.

Kept out of app.py so the formatting rules are testable and in one place.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from . import config
from .assemble import Comparison
from .models import FLAG_LABELS
from . import rfx as rfx_module

STATUS_COLOURS = {
    "Confirmed":    ("#e8f5e9", "#1b5e20"),
    "Normalized":   ("#e3f2fd", "#0d47a1"),
    "Needs Review": ("#fff8e1", "#e65100"),
    "Unresolved":   ("#ffebee", "#b71c1c"),
    "Not Quoted":   ("#f5f5f5", "#9e9e9e"),
}

STATUS_ICON = {
    "Confirmed": "●",
    "Normalized": "◆",
    "Needs Review": "▲",
    "Unresolved": "■",
    "Not Quoted": "·",
}

SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def money(value: Optional[float], currency: str = None) -> str:
    if value is None:
        return "—"
    symbol = SYMBOLS.get(currency or config.BASE_CURRENCY, "")
    return f"{symbol}{value:,.2f}"


def confidence_label(value: Optional[float]) -> str:
    """Plain words first, the number second. '82%' alone means little to a buyer."""
    if value is None:
        return "—"
    if value >= 0.95:
        word = "very clear"
    elif value >= 0.85:
        word = "clear"
    elif value >= 0.7:
        word = "readable"
    else:
        word = "hard to read"
    return f"{value:.0%} · {word}"


# Two or three words naming WHY a human is needed, keyed to the flag the
# engine actually set. Not a story -- the grid square has room for a tag, and
# the full sentence is one click away on the row and spelled out in full in
# the Needs attention tab. Anything the engine flags in a way this table does
# not cover falls back to the reason the extraction itself gave.
REVIEW_TAGS: dict[str, tuple[str, str]] = {
    "unquantified_adder": (
        "extra charge",
        "The price carries an additional charge the supplier never put a "
        "number on, so the figure on screen is not the whole cost."),
    "spec_deviation": (
        "different spec",
        "They priced something other than what was specified, so this is not "
        "a like-for-like price."),
    "conditional_price": (
        "has a condition",
        "The price only holds if some condition is met, and the condition is "
        "not one we can check for you."),
    "subject_to_confirmation": (
        "not firm",
        "The supplier marked their rates as indicative rather than firm."),
    "cross_basis": (
        "different basis",
        "They priced on a different basis to the one requested — a weight "
        "against a count, for instance — so the numbers do not line up."),
    "conditional_freight": (
        "delivery conditional",
        "Delivery is only included if a condition is met, so the delivered "
        "cost may be higher than shown."),
}


def review_tag(cell) -> str:
    """The short why, for a cell that needs a human."""
    for flag in cell.flags:
        if flag in REVIEW_TAGS:
            return REVIEW_TAGS[flag][0]
    if cell.missing_datum:
        return f"needs {cell.missing_datum}"
    first = (cell.reason or "").split(".")[0].strip().lower()
    return first[:34] if first else "needs a look"


def review_tag_legend(comparison) -> list[tuple[str, str]]:
    """Only the tags actually on screen, with the full sentence behind each."""
    seen, out = set(), []
    for cell in comparison.cells:
        if cell.status != "Needs Review":
            continue
        for flag in cell.flags:
            if flag in REVIEW_TAGS and flag not in seen:
                seen.add(flag)
                out.append(REVIEW_TAGS[flag])
                break
    return out


def cell_label(cell, normalized: bool = True, show_confidence: bool = False) -> str:
    """What goes in the grid square."""
    if cell.status == "Not Quoted":
        return "not quoted"

    if normalized:
        if cell.canonical_value is None:
            text = (f"no price — needs {cell.missing_datum}"
                    if cell.missing_datum else cell.status.lower())
        else:
            text = money(cell.canonical_value, cell.canonical_currency)
            if cell.status == "Needs Review":
                text += f" ▲ {review_tag(cell)}"
            elif cell.status == "Normalized":
                text += " ◆"
    elif cell.original_value is None:
        text = cell.status.lower()
    else:
        text = money(cell.original_value, cell.original_currency) + (
            f" {cell.original_unit}" if cell.original_unit else ""
        )

    if show_confidence and cell.original_value is not None:
        text += f"  ·{cell.extraction_confidence:.0%}"
    return text


def _unique(labels: list[str]) -> list[str]:
    """Row labels no two of which collide.

    A buyer can type the same item code twice, and two questions can reduce to
    the same wording. pandas' Styler refuses a non-unique index outright, so a
    duplicate did not merely confuse the grid -- it raised, and took the whole
    page with it. Repeats are suffixed so both rows survive and stay visibly
    distinct.
    """
    seen: dict[str, int] = {}
    out = []
    for label in labels:
        if label in seen:
            seen[label] += 1
            out.append(f"{label} ({seen[label]})")
        else:
            seen[label] = 1
            out.append(label)
    return out


def _lookup(frame: pd.DataFrame, row, column):
    """One cell by label, tolerant of a duplicated index.

    `.at` returns a Series rather than a value when the index repeats, and the
    caller then does a dict lookup on it -- "unhashable type: 'Series'" -- which
    takes the whole page down. Two rows can share a label whenever a buyer types
    the same item code or the same question twice, so the styler reads the first
    match instead of assuming uniqueness.
    """
    if column not in frame.columns:
        return ""
    try:
        value = frame.at[row, column]
    except (KeyError, IndexError):
        return ""
    if isinstance(value, pd.Series):
        value = value.iloc[0] if len(value) else ""
    return value


def grid(comparison: Comparison, normalized: bool = True,
         show_confidence: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (display frame, status frame) indexed by SKU with vendors as columns."""
    vendors = comparison.vendors
    display_rows, status_rows = [], []

    for line in rfx_module.active().lines:
        display = {"Line": line.sku, "Description": line.description,
                   "Qty": (f"{line.quantity:,}" if line.quantity else "—"), "Unit": line.canonical_unit.replace("per ", "")}
        status = {"Line": "", "Description": "", "Qty": "", "Unit": ""}
        for vendor in vendors:
            cell = comparison.cell(line.sku, vendor)
            display[vendor] = (cell_label(cell, normalized, show_confidence)
                               if cell else "—")
            status[vendor] = cell.status if cell else "Not Quoted"
        display_rows.append(display)
        status_rows.append(status)

    if not display_rows:
        # No item list, so nothing to lay out. An empty frame has no columns
        # at all, and set_index would raise -- from the sidebar, which runs on
        # every rerun, so it would take both pages down rather than showing an
        # empty grid.
        columns = ["Line", "Description", "Qty", "Unit"] + list(vendors)
        empty = pd.DataFrame(columns=columns).set_index("Line")
        return empty, empty.copy()

    labels = _unique([row["Line"] for row in display_rows])
    frame = pd.DataFrame(display_rows)
    frame["Line"] = labels
    return (frame.set_index("Line"),
            pd.DataFrame(status_rows, index=labels))


STATUS_PLAIN = {
    "Confirmed": "Priced exactly the way the RFx asked. Nothing was changed.",
    "Normalized": "We converted this so it can be compared. The original is shown above.",
    "Needs Review": "There is a number, but something about it is not safe to compare yet.",
    "Unresolved": "We could not work out a comparable price, and we will not guess one.",
    "Not Quoted": "This supplier did not price this item at all.",
}


def original_quote_cards(comparison: Comparison, sku: str) -> list[dict]:
    """Everything needed to show what each supplier actually wrote for one line."""
    cards = []
    for vendor in comparison.vendors:
        cell = comparison.cell(sku, vendor)
        if cell is None:
            continue
        cards.append({
            "vendor": vendor,
            "status": cell.status,
            "plain": STATUS_PLAIN.get(cell.status, ""),
            "quoted": (money(cell.original_value, cell.original_currency)
                       if cell.original_value is not None else None),
            "unit": cell.original_unit or ("unit not stated" if cell.original_value
                                           is not None else None),
            "currency": cell.original_currency or ("not stated"
                                                   if cell.original_value is not None else None),
            "comparable_price": (money(cell.canonical_value, cell.canonical_currency)
                                 if cell.canonical_value is not None else None),
            "factor": cell.factor,
            "reason": cell.reason,
            "missing": cell.missing_datum,
            "flags": flag_legend(cell.flags),
            "confidence": cell.extraction_confidence,
            "confidence_notes": cell.confidence_notes,
            "confidence_label": confidence_label(cell.extraction_confidence)
            if cell.original_value is not None else "—",
            "snippet": cell.source_snippet,
            "file": cell.source_file,
            "locator": cell.source_locator,
            "match_basis": cell.match_basis.replace("_", " "),
        })
    return cards


WINNER_COLUMN = "Best price"


def add_winner_column(display: pd.DataFrame, status: pd.DataFrame,
                      comparison: Comparison, cheapest: dict[str, str],
                      vendors: Optional[list[str]] = None) -> None:
    """Name the winner on every row, in place, and say by how much.

    The ring around the cheapest cell is easy to miss on a thirty-row grid and
    impossible to read once the vendor columns scroll sideways. A named column
    survives both, and carries the margin -- winning by four paise is a
    different fact from winning by four rupees, and a buyer should not have to
    subtract two numbers to find out which one they are looking at.
    """
    labels = {}
    for sku in display.index:
        winner = cheapest.get(sku)
        if not winner:
            labels[sku] = "no comparable price"
            continue
        offers = sorted(
            cell.canonical_value for vendor in (vendors or comparison.vendors)
            for cell in [comparison.cell(sku, vendor)]
            if cell and cell.comparable and cell.canonical_value is not None
        )
        if len(offers) < 2:
            labels[sku] = f"{winner} · only price"
        else:
            gap = offers[1] - offers[0]
            share = gap / offers[1] if offers[1] else 0
            if share < 0.005:
                # Winning by a rounding error is not winning. Saying "0% cheaper"
                # would let a buyer switch supplier over nothing.
                labels[sku] = f"{winner} · {money(gap)} ahead — too close to call"
            else:
                labels[sku] = f"{winner} · {money(gap)} ({share:.0%}) cheaper"

    display.insert(3, WINNER_COLUMN, pd.Series(labels))
    status.insert(3, WINNER_COLUMN, "")


def mark_winners(display: pd.DataFrame, cheapest: dict[str, str]) -> None:
    """Put a tick in the winning cell itself, in place.

    Colour alone is not an indication: it is lost to a colour-blind reader, to
    a printout, and to anyone scanning a thirty-row grid quickly. The tick
    survives all three, and it sits in the same cell as the number so the eye
    does not have to travel to a legend to learn what green meant.
    """
    for sku, winner in cheapest.items():
        if not winner or winner not in display.columns or sku not in display.index:
            continue
        value = display.at[sku, winner]
        if isinstance(value, str) and not value.startswith("✓"):
            display.at[sku, winner] = f"✓ {value}"


def style_grid(display: pd.DataFrame, status: pd.DataFrame, cheapest: dict[str, str]):
    """Colour by status; stamp the cheapest comparable price on each line."""
    def _style(frame: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
        for sku in frame.index:
            for column in frame.columns:
                if column == WINNER_COLUMN:
                    won = bool(cheapest.get(sku))
                    styles.at[sku, column] = (
                        "background-color:#dcecdf;color:#164a2c;font-weight:600;"
                        "border-left:3px solid #2C6942;"
                        if won else "background-color:#eef0f3;color:#6b7688;")
                    continue
                if column in {"Description", "Qty", "Unit"}:
                    continue
                state = _lookup(status, sku, column)
                background, colour = STATUS_COLOURS.get(state, ("", ""))
                rule = f"background-color:{background};color:{colour};" if background else ""
                if cheapest.get(sku) == column:
                    # The winner is stated four ways -- tick, weight, a solid
                    # green field and a heavy outline -- because this is the one
                    # cell on the row a buyer acts on.
                    rule = ("background-color:#C8E2CE;color:#123D24;font-weight:700;"
                            "box-shadow:inset 0 0 0 2px #2C6942;")
                styles.at[sku, column] = rule
        return styles

    return display.style.apply(_style, axis=None)


def cheapest_by_line(comparison: Comparison, vendors: Optional[list[str]] = None) -> dict[str, str]:
    """Winner per line among comparable cells only."""
    allowed = set(vendors or comparison.vendors)
    winners: dict[str, str] = {}
    for line in rfx_module.active().lines:
        best_vendor, best_value = None, None
        for vendor in comparison.vendors:
            if vendor not in allowed:
                continue
            cell = comparison.cell(line.sku, vendor)
            if cell and cell.comparable:
                if best_value is None or cell.canonical_value < best_value:
                    best_vendor, best_value = vendor, cell.canonical_value
        if best_vendor:
            winners[line.sku] = best_vendor
    return winners


def exceptions_frame(comparison: Comparison) -> pd.DataFrame:
    """Everything that needs a human. Ordered by how badly it needs one."""
    order = {"Unresolved": 0, "Needs Review": 1, "Not Quoted": 2}
    rows = []
    for cell in comparison.cells:
        if cell.status in order:
            rows.append({
                "Sev": order[cell.status],
                "Status": f"{STATUS_ICON[cell.status]} {cell.status}",
                "Line": cell.rfx_sku,
                # Looked up, not indexed. These rows walk the cells rather
                # than the item list, so a cell can name a line the active
                # request does not carry -- and a KeyError here happens in
                # the sidebar export, taking both pages down with it.
                "Item": getattr(rfx_module.active().by_sku.get(cell.rfx_sku),
                                "description", cell.rfx_sku),
                "Vendor": cell.vendor,
                "As quoted": (money(cell.original_value, cell.original_currency)
                              + (f" {cell.original_unit}" if cell.original_unit else "")
                              if cell.original_value is not None else "—"),
                "How clearly we read it": (confidence_label(cell.extraction_confidence)
                                           if cell.original_value is not None else "—"),
                "Why": cell.reason,
                "What we need": cell.missing_datum or "—",
            })

    # Lines the supplier priced that answer nothing on the item list. They
    # belong here rather than nowhere: the buyer either wants them added to
    # the request, or wants to know the supplier is quoting something else.
    for summary in comparison.summaries:
        for extra in summary.unplaced:
            rows.append({
                "Sev": 3,
                "Status": ("◇ Second price"
                           if extra.get("why", "").startswith("a second")
                           else "◇ Not on your list"),
                "Line": extra.get("code") or "—",
                "Item": extra.get("description") or "—",
                "Vendor": summary.vendor,
                "As quoted": (money(extra.get("value"), extra.get("currency"))
                              + (f" {extra['unit']}" if extra.get("unit") else "")
                              if extra.get("value") is not None else "—"),
                "How clearly we read it": "—",
                "Why": (f"Read from their quote, but it is {extra['why']} — "
                        f"only one price per item can go in the grid."
                        if extra.get("why", "").startswith("a second")
                        else "Read from their quote, but it does not match any "
                             "item on your request."),
                "What we need": ("Confirm which of the two prices applies."
                                 if extra.get("why", "").startswith("a second")
                                 else "Add it to your request, or confirm they "
                                      "are quoting something you did not ask for."),
            })

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return (frame.sort_values(["Sev", "Line", "Vendor"])
                 .drop(columns=["Sev"]).reset_index(drop=True))


VERDICT_MARK = {"Yes": "✓", "No": "✗", "Partial": "~", "Unanswered": "—"}

ANSWER_COLOURS = {
    "Yes":        ("#e6f1e9", "#1d5233"),
    "No":         ("#f8e7e5", "#8d2f2a"),
    "Partial":    ("#faf0de", "#7d4f0d"),
    "Unanswered": ("#eef0f3", "#6b7688"),
}


def _answer_state(scored) -> str:
    if scored is None or scored.answer.verdict == "Unanswered":
        return "Unanswered"
    if scored.meets:
        return "Yes"
    return "Partial" if scored.answer.verdict == "Partial" else "No"


def questionnaire_frame(comparison: Comparison) -> tuple[pd.DataFrame, pd.DataFrame]:
    """What each supplier said, and whether it satisfies the criterion.

    Returns (display, state). The state frame drives the colour: green where
    the criterion is satisfied, red where it is not, grey where the supplier
    never answered.
    """
    display_rows, state_rows = [], []
    for criterion in comparison.criteria:
        display = {"Criterion": criterion.label,
                   "Weight": f"{criterion.weight:g}"}
        state = {"Criterion": "", "Weight": ""}
        for summary in comparison.summaries:
            scored = summary.scorecard.results.get(criterion.key)
            situation = _answer_state(scored)
            if situation == "Unanswered":
                display[summary.vendor] = "— not answered"
            else:
                answer = scored.answer
                shown = (answer.stated_text if answer.value is not None
                         else answer.verdict)
                backing = answer.evidence_label
                display[summary.vendor] = (
                    f"{VERDICT_MARK[situation]} {shown}"
                    + (f"  ({backing})" if backing and answer.evidence != "none" else ""))
            state[summary.vendor] = situation
        display_rows.append(display)
        state_rows.append(state)

    score = {"Criterion": "QUALITY SCORE", "Weight": ""}
    blank = {"Criterion": "", "Weight": ""}
    for summary in comparison.summaries:
        score[summary.vendor] = f"{summary.quality_score * 100:.0f}"
        blank[summary.vendor] = ""
    display_rows.append(score)
    state_rows.append(blank)

    index = _unique([row["Criterion"] for row in display_rows])
    frame = pd.DataFrame(display_rows)
    frame["Criterion"] = index
    return (frame.set_index("Criterion"),
            pd.DataFrame(state_rows, index=index))


def style_questionnaire(display: pd.DataFrame, state: pd.DataFrame):
    """Green satisfied, red not, grey unanswered."""
    def _style(frame: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
        for row in frame.index:
            for column in frame.columns:
                if column == "Weight":
                    continue
                situation = _lookup(state, row, column)
                colours = ANSWER_COLOURS.get(situation)
                if colours:
                    styles.at[row, column] = (
                        f"background-color:{colours[0]};color:{colours[1]};")
            if row == "QUALITY SCORE":
                for column in frame.columns:
                    styles.at[row, column] += "font-weight:700;border-top:2px solid #151A22;"
        return styles

    return display.style.apply(_style, axis=None)


def criteria_frame(comparison: Comparison) -> pd.DataFrame:
    """The editable control table.

    Deliberately two columns wide. The target and its direction are derived and
    shown where they are actually useful -- next to each supplier's answer in
    the scorecard below -- rather than repeated here as read-only clutter.
    """
    return pd.DataFrame([{
        "Criterion": c.label,
        "Requirement": c.requirement,
        "Weight": c.weight,
        "key": c.key,
    } for c in comparison.criteria])


def scorecard_frame(comparison: Comparison) -> pd.DataFrame:
    rows = []
    for summary in sorted(comparison.summaries, key=lambda s: -s.quality_score):
        rows.append({
            "Supplier": summary.vendor,
            "Quality score": f"{summary.quality_score * 100:.0f}",
            "Figures disclosed": f"{summary.disclosed_figures}/{len(comparison.criteria)}",
            "Not answered": len(summary.unanswered) or "—",
            "Misses a must-have": ", ".join(summary.hard_failures) or "no",
        })
    return pd.DataFrame(rows)


def vendor_frame(comparison: Comparison) -> pd.DataFrame:
    rows = []
    for summary in comparison.summaries:
        freight = {True: "Included", False: "Extra", None: "Not stated"}[summary.freight_included]
        rows.append({
            "Vendor": summary.vendor,
            "Document": summary.file,
            "Lines quoted": summary.coverage_label,
            "Comparable": f"{summary.comparable_lines}/{summary.coverage_total}",
            "Quality score": f"{summary.quality_score * 100:.0f}",
            "Freight": freight,
            "Payment": f"{summary.payment_terms_days} days" if summary.payment_terms_days else "—",
            "Lead time": f"{summary.lead_time_days:g} days" if summary.lead_time_days else "—",
            "Currency": summary.document_currency or "not stated (assumed INR)",
            "Extraction conf.": f"{summary.overall_confidence:.0%}",
        })
    return pd.DataFrame(rows).set_index("Vendor")


FORMAT_NAMES = {
    "xlsx": "Spreadsheet", "xlsm": "Spreadsheet", "xls": "Spreadsheet",
    "csv": "Spreadsheet", "pdf": "PDF document", "docx": "Word document",
    "txt": "Email / plain text", "eml": "Email", "md": "Plain text",
    "jpg": "Photograph", "jpeg": "Photograph", "png": "Scanned image",
    "webp": "Photograph", "tif": "Scanned image", "tiff": "Scanned image",
}


def describe_format(filename: str) -> str:
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return FORMAT_NAMES.get(extension, extension.upper() or "Unknown format")


def supplier_card_data(comparison: Comparison) -> list[dict]:
    cards = []
    for summary in comparison.summaries:
        freight = {True: "included", False: "charged extra",
                   None: "not stated"}[summary.freight_included]
        cards.append({
            "vendor": summary.vendor,
            "format": describe_format(summary.file),
            "quoted": summary.coverage_quoted,
            "comparable": summary.comparable_lines,
            "total": summary.coverage_total,
            "cleared": summary.meets_requirements,
            "quality_score": summary.quality_score,
            "confidence": summary.overall_confidence,
            "freight": freight,
            "payment": (f"{summary.payment_terms_days} days"
                        if summary.payment_terms_days else "not stated"),
            "lead": (f"{summary.lead_time_days:g} days"
                     if summary.lead_time_days else "not stated"),
            "currency": summary.document_currency or "not stated",
        })
    return cards


def headline_stats(comparison: Comparison,
                   winners: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """The numbers a buyer should see before anything else.

    Returns (value, label, tone, glossary key) -- the last so each one can
    explain itself.

    Deliberately no "leading supplier" tile. Whoever wins the most lines is
    not the supplier a buyer should award to, and a name at the top of the
    page reads like a verdict before anyone has looked at coverage, quality or
    what the split costs. Who wins each line is shown line by line, where the
    evidence for it is.
    """
    cells = comparison.cells
    comparable = sum(1 for cell in cells if cell.comparable)
    attention = sum(1 for cell in cells
                    if cell.status in ("Unresolved", "Needs Review", "Not Quoted"))
    contested = sum(1 for sku in winners if winners.get(sku))

    return [
        (str(len(comparison.summaries)), "suppliers read", "accent", "suppliers_read"),
        (f"{comparable}/{len(cells)}", "prices comparable", "", "comparable"),
        (str(attention), "need attention", "warn" if attention else "", "need_attention"),
        (f"{contested}/{rfx_module.active().line_count}", "items with a best price",
         "accent", "cheapest_on"),
    ]


def award_vendor_frame(plan) -> pd.DataFrame:
    total_lines = sum(v.line_count for v in plan.vendors) or 1
    rows = []
    for entry in plan.vendors:
        rows.append({
            "Supplier": entry.vendor,
            "Items suggested": entry.line_count,
            "Share of lines": f"{entry.line_count / total_lines:.0%}",
            "Of which uncontested": len(entry.single_source_lines) or "—",
            "Spend": (money(entry.extended_total) if entry.extended_total is not None
                      else "—"),
            "Items": ", ".join(entry.lines),
        })
    return pd.DataFrame(rows)


def award_line_frame(plan) -> pd.DataFrame:
    rows = []
    for line in plan.lines:
        if line.status == "no_comparable":
            continue
        rows.append({
            "Line": line.sku,
            "Item": line.description,
            "Suggested supplier": line.winner,
            "Price": money(line.price),
            "Qty": f"{line.quantity:,}" if line.quantity else "—",
            "Spend": money(line.extended) if line.extended is not None else "—",
            "Next best": line.runner_up or "— only one price",
            "Saving": (money(line.extended_saving) if line.extended_saving is not None
                       else (money(line.saving_per_unit) + " per unit"
                             if line.saving_per_unit else "—")),
            "Contested": "yes" if line.status == "awarded" else "no",
        })
    return pd.DataFrame(rows)


def award_gap_frame(plan) -> pd.DataFrame:
    rows = [{"Line": line.sku, "Item": line.description, "Why": line.reason}
            for line in plan.unawardable]
    return pd.DataFrame(rows)


def _first_name(vendor: Optional[str]) -> str:
    """'Shakti Packaging Industries Pvt Ltd' -> 'Shakti'. Stat labels are narrow."""
    if not vendor:
        return "one supplier"
    return vendor.split()[0]


def saving_stat(plan) -> tuple[str, str, str]:
    """(value, label, tone) for the split-versus-one-supplier tile.

    Never a bare dash. When there is no saving to state, the tile says why,
    because "—" reads as a broken number rather than as an answer.
    """
    if plan.saving_vs_single is None or plan.best_single_vendor is None:
        if plan.supplier_count < 2:
            return "n/a", "one supplier — nothing to split", ""
        return "n/a", "no split saving to show yet", "warn"

    share = (plan.saving_vs_single / plan.best_single_total
             if plan.best_single_total else 0.0)
    label = (f"less than {_first_name(plan.best_single_vendor)} alone, "
             f"on the {plan.common_basket} items all of them priced")
    if plan.saving_vs_single <= 0:
        return (money(0), f"{_first_name(plan.best_single_vendor)} alone is no "
                          f"more expensive on those {plan.common_basket} items", "warn")
    symbol = SYMBOLS.get(config.BASE_CURRENCY, "")
    return (f"{symbol}{plan.saving_vs_single:,.0f} · {share:.1%}", label, "accent")


def award_stats(plan) -> list[tuple[str, str, str, str]]:
    spend = money(plan.total_extended) if plan.total_extended is not None else "—"
    value, label, tone = saving_stat(plan)
    return [
        (str(plan.supplier_count), "suppliers recommended", "accent", "split_award"),
        (f"{plan.awarded_lines}/{len(plan.lines)}", "items we can recommend on",
         "", "comparable"),
        (spend, "estimated spend if you agree", "", "estimated_spend"),
        (value, label, tone, "saving_vs_single"),
    ]


def flag_legend(flags: list[str]) -> list[str]:
    return [FLAG_LABELS.get(flag, flag) for flag in flags]


def export_frame(comparison: Comparison) -> pd.DataFrame:
    """Full audit export: the original, the canonical, and everything between."""
    frame = comparison.frame()
    if frame.empty:
        return frame
    lines = rfx_module.active().lines
    descriptions = {line.sku: line.description for line in lines}
    quantities = {line.sku: line.quantity for line in lines}
    frame.insert(1, "description", frame["rfx_sku"].map(descriptions))
    frame.insert(2, "rfx_quantity", frame["rfx_sku"].map(quantities))
    return frame


# ---------------------------------------------------------------------------
# drafting a request
# ---------------------------------------------------------------------------

ORIGIN_WORDS = {
    "buyer": "yours",
    "document": "your file",
    # Proposed from category knowledge, because the stock system this should
    # read is not connected. Called "suggested" rather than "from stock"
    # precisely so nobody reads it as a fact from a system of record.
    "suggested": "suggested",
    "derived": "from replies",
}


def draft_lines_frame(spec) -> pd.DataFrame:
    """The draft item list, editable.

    Origin is still tracked on every line -- it is what keeps a suggested item
    out of the document until a person accepts it -- but it is no longer a
    column here. In a table a buyer is editing, a locked column they cannot
    change is furniture, and the one fact it carried is said far more loudly
    by the banner underneath: "N of these were proposed for you".
    """
    return pd.DataFrame([{
        "Item": line.sku,
        "Description": line.description,
        "Quantity": line.quantity,
        "Price per": line.canonical_unit.replace("per ", ""),
    } for line in spec.lines])


def _lines_signature(lines: list) -> list[tuple]:
    """Everything about the items the buyer can see or change."""
    return [(l.sku, l.description, l.quantity, l.canonical_unit, l.origin)
            for l in lines]


def apply_draft_edits(spec, edited: pd.DataFrame) -> bool:
    """Push table edits back onto the spec, in place.

    Editing a suggested line makes it the buyer's: they read it and kept it,
    which is exactly the act of accepting it. Rows added by hand are the
    buyer's from the start; rows deleted in the table are deleted here.

    Returns True when the request actually changed. The edits are normalised
    on the way in -- a stray space trimmed, "per box" read as "box", a blank
    row dropped -- so an edit that normalises to what was already there leaves
    the table differing from the request while the request stands still. A
    caller that reruns on *that* difference redraws the same table, replays
    the same edit, and spins for ever.
    """
    from . import rfx as rfx_module
    from .draft import _clean_sku, _unit_family

    by_sku = {line.sku: line for line in spec.lines}
    rebuilt = []
    for _, row in edited.iterrows():
        code = str(row.get("Item") or "").strip()
        original = by_sku.get(code)
        if original is None:
            # A row typed straight into the table. Theirs, not a suggestion.
            description = str(row.get("Description") or "").strip()
            if not description and not code:
                continue
            label, family = _unit_family(str(row.get("Price per") or "unit"))
            quantity = row.get("Quantity")
            rebuilt.append(rfx_module.RfxLine(
                sku=_clean_sku(code or description[:12],
                               {line.sku for line in rebuilt}),
                description=description,
                quantity=int(quantity) if quantity and not pd.isna(quantity) else None,
                canonical_unit=label, unit_family=family,
                origin="buyer", note=""))
            continue
        unit_text = str(row.get("Price per") or original.canonical_unit)
        label, family = _unit_family(unit_text)
        quantity = row.get("Quantity")
        description = str(row.get("Description") or original.description).strip()
        touched = (description != original.description
                   or label != original.canonical_unit
                   or (quantity or None) != original.quantity)
        # Two lines sharing a code cannot be told apart by anything
        # downstream -- the grid indexes on it, and a duplicate label turns
        # every lookup into a Series and takes the page down.
        code = _clean_sku(str(row.get("Item") or original.sku).strip(),
                          {line.sku for line in rebuilt})
        rebuilt.append(rfx_module.RfxLine(
            sku=code,
            description=description,
            quantity=int(quantity) if quantity and not pd.isna(quantity) else None,
            canonical_unit=label,
            unit_family=family,
            origin=("buyer" if (original.origin == "suggested" and touched)
                    else original.origin),
            note=original.note,
        ))
    before = _lines_signature(spec.lines)
    spec.lines[:] = rebuilt
    return _lines_signature(spec.lines) != before


def accept_suggestions(spec) -> int:
    """Turn every suggested line into the buyer's own. Deliberate, and one click."""
    from . import rfx as rfx_module
    count = 0
    for index, line in enumerate(spec.lines):
        if line.origin == "suggested":
            spec.lines[index] = rfx_module.RfxLine(
                sku=line.sku, description=line.description, quantity=line.quantity,
                canonical_unit=line.canonical_unit, unit_family=line.unit_family,
                origin="buyer", note=line.note)
            count += 1
    return count


def drop_suggestions(spec) -> int:
    count = len(spec.suggested_lines)
    spec.lines[:] = [line for line in spec.lines if line.origin != "suggested"]
    return count


def draft_receipt(spec, changes: Optional[list] = None) -> str:
    """A plain-English account of the request that now exists.

    Read off the spec itself rather than from what the co-pilot says it did.
    A model reporting its own work is the one witness you cannot cross-examine
    -- it will happily say "added twelve items" having added nine -- so this
    counts the object the document will actually be built from. If the two
    ever disagree, this is the one that is true.
    """
    # "Generated" has to be earned. A turn that produced no items, no
    # questions and no terms has generated nothing, and announcing otherwise
    # over an empty document is the kind of small untruth that costs a buyer
    # their trust in everything else on the page.
    produced = bool(spec.lines or spec.criteria or spec.terms)
    lines = ["**The draft RFQ has been generated.**" if produced else
             "**No request was generated from that.** Nothing was added — try "
             "saying what you are buying, roughly how many, and by when.", ""]

    # Two trailing spaces is a markdown hard break. Without them the title,
    # the reference and the scope run together into one paragraph.
    if spec.title:
        lines.append(f"**{spec.title}**  ")
    if spec.reference:
        lines.append(f"Your reference `{spec.reference}`  ")
    if spec.scope:
        lines.append(f"_{spec.scope}_")
    if spec.title or spec.reference or spec.scope:
        lines.append("")

    lines.append("Here is exactly what it contains:" if produced
                 else "The request stands as it was:")
    lines.append("")

    suggested = len(spec.suggested_lines)
    accepted = spec.line_count - suggested
    if spec.line_count:
        item_note = f"**{spec.line_count} item{'' if spec.line_count == 1 else 's'}**"
        priced = sum(1 for line in spec.lines if line.quantity)
        if priced == spec.line_count:
            item_note += ", each with a quantity"
        elif priced:
            item_note += f", {priced} of them with a quantity"
        if suggested and accepted:
            item_note += (f" — {accepted} stated by you, {suggested} proposed "
                          f"for you and awaiting your acceptance")
        elif suggested:
            item_note += " — all proposed for you, awaiting your acceptance"
        lines.append(f"- {item_note}")
    else:
        lines.append("- **No items yet** — add them on the **Items** tab, or tell "
                     "me what you are buying")

    lines.append(f"- **{len(spec.criteria)} question"
                 f"{'' if len(spec.criteria) == 1 else 's'}** for suppliers to answer"
                 if spec.criteria else
                 "- **No questions yet** — add them on the **Questions** tab")

    lines.append(f"- **{len(spec.terms)} term"
                 f"{'' if len(spec.terms) == 1 else 's'}** (payment, delivery, "
                 f"validity and the like)"
                 if spec.terms else
                 "- **No terms yet** — add them on the **Terms** tab")

    lines.append(f"- Suppliers must quote in **{spec.currency}**")

    if spec.starts_at and spec.ends_at:
        window = spec.window_days
        span = f", {window} days to quote" if window is not None and window >= 0 else ""
        lines.append(f"- Open **{spec.stamp(spec.starts_at)}** → close "
                     f"**{spec.stamp(spec.ends_at)}**{span}")
    else:
        lines.append("- **Dates not set yet** — required before you can send")

    if spec.delivery_location:
        lines.append(f"- Delivered to **{spec.delivery_location}**")
    if spec.vendor_category:
        lines.append(f"- Vendor category **{spec.vendor_category}**")
    else:
        lines.append("- **Vendor category not set yet** — required before you can send")
    if spec.notes:
        lines.append("- A note to suppliers is included")
    if spec.attachments:
        lines.append(f"- **{len(spec.attachments)} supporting file"
                     f"{'' if len(spec.attachments) == 1 else 's'}** attached")

    if changes:
        lines += ["", "What I changed on this turn:"]
        lines += [f"- {change}" for change in changes]

    outstanding = []
    if suggested:
        outstanding.append("accept the proposed items")
    if not (spec.starts_at and spec.ends_at):
        outstanding.append("set the open and close dates")
    if not spec.vendor_category:
        outstanding.append("choose a vendor category")
    lines += ["", (
        "**Everything below is editable** — change any of it by hand, or tell me "
        "what to change and I will edit the draft."
        if not outstanding else
        "**Before you can send it:** " + ", ".join(outstanding)
        + ". Everything below is editable by hand too.")]

    return "\n".join(lines)


CRITERIA_COLUMNS = ["S. No.", "Question", "Target", "Unit", "Direction",
                    "Requirement", "Weight"]


def draft_criteria_frame(spec) -> pd.DataFrame:
    """The questions, editable.

    The question is shown as the buyer wrote it, not as the label with the
    live target appended -- editing "capacity greater than 50,000 units/month"
    would mean re-parsing the target back out of a string we just built, and
    round-tripping a derived label is how a target quietly changes by itself.
    Target and direction get their own columns instead.

    The columns are declared rather than inferred from the rows. A request with
    no questions yet used to produce a frame with no columns at all, which the
    editor drew as a blank rectangle with no headings and nowhere to type -- so
    the one buyer who most needed to add a question was the one who could not.
    Empty or full, the table now carries its headings and an empty first row.

    "S. No." is display only: it is renumbered from the row order on every
    redraw, so deleting the second of five questions leaves 1-4 rather than a
    gap, and nothing downstream reads it.
    """
    frame = pd.DataFrame([{
        "S. No.": index,
        "Question": criterion.question,
        "Target": criterion.threshold,
        "Unit": (criterion.unit or "").strip(),
        "Direction": ("at least" if criterion.direction == "higher_better"
                      else "at most" if criterion.direction == "lower_better"
                      else "yes / no"),
        "Requirement": criterion.requirement,
        "Weight": float(criterion.weight),
    } for index, criterion in enumerate(spec.criteria, start=1)],
        columns=CRITERIA_COLUMNS)
    if frame.empty:
        # One empty row rather than none. A dynamic editor does offer a trailing
        # blank line, but an entirely empty table reads as "nothing to do here"
        # -- and typing the first question is exactly what this tab is for.
        frame.loc[0] = {"S. No.": 1, "Question": "", "Target": None, "Unit": "",
                        "Direction": "yes / no", "Requirement": "Scored",
                        "Weight": 1.0}
        # Assigning into an empty frame leaves an Index, not a RangeIndex, and
        # a dynamic editor refuses to hide a non-range index -- which puts a
        # stray index column back beside the serial number we just added.
        frame = frame.reset_index(drop=True)
    return frame.astype({"Question": "object", "Unit": "object",
                         "Direction": "object", "Requirement": "object"})


DIRECTION_WORDS = {"at least": "higher_better", "at most": "lower_better",
                   "yes / no": "boolean"}


def blank_questions(edited: pd.DataFrame) -> int:
    """Rows carrying a target or a unit but no question text.

    A row with a threshold and no question is not a half-finished criterion,
    it is a number with nothing to test. Counted so the interface can say so
    rather than dropping the row silently and leaving the buyer to wonder
    where their edit went.
    """
    count = 0
    for _, row in edited.iterrows():
        if str(row.get("Question") or "").strip():
            continue
        if any(row.get(field) not in (None, "", 0)
               and not pd.isna(row.get(field))
               for field in ("Target", "Unit")):
            count += 1
    return count


def _cell(row, column):
    """One cell, with pandas' several flavours of empty collapsed to None."""
    value = row.get(column)
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # arrays and the like are never the empty we mean
    return value


def number_or(value, fallback: float) -> float:
    """A number out of an editable cell, with an emptied cell meaning the
    fallback.

    NaN never equals itself, so letting one through turns any "has this
    changed?" test into a permanent yes -- and a permanent yes on a Streamlit
    page is a rerun loop.
    """
    if value is None:
        return float(fallback)
    try:
        if pd.isna(value):
            return float(fallback)
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _criteria_signature(criteria: list) -> list[tuple]:
    """Everything about the questions the buyer can see or change.

    Used to decide whether an edit actually altered the request. Comparing the
    edited table against the table we drew is the obvious test and the wrong
    one: this function normalises, so a weight of 0.5 typed into a column that
    holds 0.5 already, or a target typed on a row with no question, produces an
    edited frame that differs from the drawn frame while the request itself is
    unchanged. Rerunning on that difference redraws the same frame, replays the
    same edit, and the page spins forever.
    """
    return [(c.key, c.question, c.direction, c.threshold,
             (c.unit or "").strip() or None, c.requirement, c.weight)
            for c in criteria]


def apply_criteria_edits(spec, edited: pd.DataFrame) -> bool:
    """Push question edits back onto the spec, in place, including new rows.

    Returns True when the request actually changed, so the caller knows whether
    a rerun is warranted. See _criteria_signature for why that matters.
    """
    from . import criteria as criteria_module

    before = _criteria_signature(spec.criteria)
    by_position = {index: criterion
                   for index, criterion in enumerate(spec.criteria, start=1)}

    rebuilt, used_keys = [], set()
    for _, row in edited.iterrows():
        text = str(row.get("Question") or "").strip()
        if not text:
            # A row with a target but no question is a number with nothing to
            # test, so it never becomes a criterion. It is counted by
            # blank_questions() and reported on screen, rather than dropped in
            # silence leaving the buyer to wonder where their edit went.
            continue
        # Which criterion this row *is*, by the serial number it was drawn
        # with -- not by its text. Matching on text loses the accumulated
        # phrasings the moment a buyer corrects a typo, and those variants are
        # what tie a supplier's own wording to this question.
        serial = _cell(row, "S. No.")
        previous = by_position.get(int(serial)) if serial is not None else None
        if previous is None:
            previous = next((c for c in spec.criteria if c.question == text), None)

        threshold = _cell(row, "Target")
        weight = _cell(row, "Weight")
        unit = _cell(row, "Unit")
        requirement = str(row.get("Requirement") or "").strip()
        if requirement not in criteria_module.REQUIREMENT_LEVELS:
            requirement = "Scored"

        key = previous.key if previous else criteria_module._slug(text)
        if key in used_keys:
            # Two questions that slug to the same key would silently overwrite
            # each other's score. Keep both, distinctly.
            suffix = 2
            while f"{key}_{suffix}" in used_keys:
                suffix += 1
            key = f"{key}_{suffix}"
        used_keys.add(key)

        variants = list(previous.variants) if previous else []
        if text not in variants:
            variants.append(text)

        rebuilt.append(criteria_module.Criterion(
            key=key,
            question=text,
            variants=variants,
            kind=(previous.kind if previous else criteria_module.read_question(text)[0]),
            direction=DIRECTION_WORDS.get(str(row.get("Direction") or "").strip(),
                                          "boolean"),
            threshold=float(threshold) if threshold is not None else None,
            unit=(str(unit).strip() or None) if unit is not None else None,
            requirement=requirement,
            # A weight of zero is a real answer -- "ask it, but do not let it
            # move the score" -- and the column offers it. Only an absent
            # weight falls back to one.
            weight=float(weight) if weight is not None else 1.0,
            suggested_threshold=(previous.suggested_threshold if previous else None),
        ))

    spec.criteria[:] = rebuilt
    return _criteria_signature(spec.criteria) != before


def draft_terms_frame(spec) -> pd.DataFrame:
    return pd.DataFrame([{"Term": kind.title(), "What suppliers are told": text}
                         for kind, text in spec.terms.items()])


def apply_terms_edits(spec, edited: pd.DataFrame) -> None:
    terms = {}
    for _, row in edited.iterrows():
        kind = str(row.get("Term") or "").strip().lower()
        text = str(row.get("What suppliers are told") or "").strip()
        if kind and text:
            terms[kind] = text
    spec.terms.clear()
    spec.terms.update(terms)


# --- terms as text ---------------------------------------------------------
# A two-column table was the wrong shape for the way terms are actually
# written. They arrive as a block a buyer already has -- pasted out of last
# year's request, or typed straight through -- and a grid made that four
# clicks per line. So the tab is a textbox, one term to a line, and the
# `Payment: 45 days` shape is parsed back into the same dict the request
# document renders from. Nothing downstream changes.

# Long enough for "Packaging, palletisation and handling", short enough that a
# sentence with a colon in the middle of it is not mistaken for a label.
_TERM_LABEL_MAX = 60


def draft_terms_text(spec) -> str:
    """The terms as the buyer edits them: one `Kind: text` line each.

    This has to survive a round trip -- what the box shows, saved unchanged,
    must leave the terms exactly as they were -- so three shapes are handled
    rather than assumed away. A term whose text runs to several lines is
    written with its continuations indented, and the parser rejoins them. A
    term with no text at all is not written, because a bare "Payment:" carries
    nothing and comes back as a note. And a label that itself contains a colon
    cannot be written as a label at all, since the parser would split it in the
    wrong place -- so its text goes out unlabelled, intact.
    """
    lines = []
    for kind, text in spec.terms.items():
        body = (text or "").strip()
        if not body:
            continue
        body = "\n  ".join(body.splitlines())
        lines.append(body if ":" in kind else f"{kind.title()}: {body}")
    return "\n".join(lines)


def apply_terms_text(spec, text: str) -> None:
    """Parse the textbox back into terms, in the order they were typed.

    A line reading `Payment: 45 days from invoice` becomes the payment term.
    A line with no label is still kept -- a buyer mid-sentence should not lose
    what they typed because they have not decided what to call it yet -- as a
    numbered note, which is exactly how the request document prints an
    unlabelled term today.
    """
    terms: dict[str, str] = {}
    unlabelled = 0
    last_key = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # An indented line continues the term above it, which is how a term
        # whose text runs to several lines survives being written out and read
        # back. Without this a two-line charges clause returns as two terms.
        if last_key is not None and raw[:1] in (" ", "\t"):
            terms[last_key] = f"{terms[last_key]}\n{line}"
            continue
        label, sep, rest = line.partition(":")
        label, rest = label.strip(), rest.strip()
        if sep and rest and label and len(label) <= _TERM_LABEL_MAX:
            key = label.lower()
        else:
            unlabelled += 1
            key, rest = f"note {unlabelled}", line
        # A repeated label would otherwise silently overwrite the line above it.
        if key in terms:
            suffix = 2
            while f"{key} ({suffix})" in terms:
                suffix += 1
            key = f"{key} ({suffix})"
        terms[key] = rest
        last_key = key
    spec.terms.clear()
    spec.terms.update(terms)


def parse_vendor_list(text: str) -> list:
    """'Name <email>' per line, tolerantly. A missing email is not an error."""
    from .dispatch import Vendor
    vendors = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        email = ""
        if "<" in line and ">" in line:
            name, _, rest = line.partition("<")
            email = rest.split(">")[0].strip()
            line = name.strip()
        elif "," in line:
            name, _, rest = line.partition(",")
            email, line = rest.strip(), name.strip()
        if line:
            vendors.append(Vendor(name=line, email=email))
    return vendors


def invitation_frame(invitations: list) -> pd.DataFrame:
    return pd.DataFrame([{
        "Supplier": invitation.vendor.name,
        "Sent to": invitation.vendor.email or "—",
        "Quote reference": invitation.token,
        "Status": invitation.status,
        "Written to": (invitation.receipt.location if invitation.receipt else "—"),
    } for invitation in invitations])


# ---------------------------------------------------------------------------
# vendors and attachments on a draft
# ---------------------------------------------------------------------------

def directory_frame(category, selected: Optional[set] = None) -> pd.DataFrame:
    """The approved list for one category, best rated first.

    The four scores are shown beside the rating rather than behind it. A
    headline out of ten that cannot be taken apart is a number a buyer either
    swallows whole or ignores; one that shows its parts can be argued with,
    which is the only way it improves.
    """
    selected = selected if selected is not None else set()
    return pd.DataFrame([{
        "Ask": vendor.name in selected,
        "Supplier": vendor.name,
        "Rating": vendor.rating,
        "Quality": vendor.scores.get("quality"),
        "Delivery": vendor.scores.get("delivery"),
        "Commercial": vendor.scores.get("commercial"),
        "Responsiveness": vendor.scores.get("responsiveness"),
        "Where": vendor.location,
        "Email": vendor.email,
        "Why": vendor.why() + ((" " + vendor.note) if vendor.note else ""),
    } for vendor in category.ranked()])


def selected_vendors(edited: pd.DataFrame) -> list:
    """The suppliers ticked in the table, as dispatch Vendors."""
    from .dispatch import Vendor
    out = []
    for _, row in edited.iterrows():
        if not bool(row.get("Ask")):
            continue
        name = str(row.get("Supplier") or "").strip()
        if name:
            out.append(Vendor(name=name, email=str(row.get("Email") or "").strip()))
    return out


def attachment_frame(spec) -> pd.DataFrame:
    return pd.DataFrame([{
        "File": item.get("name", ""),
        "What it is": item.get("note", ""),
        "Size": f"{item.get('size', 0) / 1024:,.0f} KB",
    } for item in spec.attachments])


def apply_attachment_edits(spec, edited: pd.DataFrame) -> bool:
    """Keep the notes the buyer typed, and drop rows they deleted.

    Matched by filename: the bytes live on the spec and are never round-tripped
    through the table, because a data editor is no place to carry a file.
    """
    keep, notes = [], {}
    for _, row in edited.iterrows():
        name = str(row.get("File") or "").strip()
        if name:
            keep.append(name)
            notes[name] = str(row.get("What it is") or "").strip()
    before = [(item["name"], item.get("note", "")) for item in spec.attachments]
    spec.attachments[:] = [
        {**item, "note": notes.get(item["name"], item.get("note", ""))}
        for item in spec.attachments if item["name"] in keep
    ]
    # Same reason as the item table: the File column is disabled, so every row
    # a buyer adds is discarded by construction, and a note is stripped on the
    # way in. Reruns must follow the request, not the table.
    return before != [(item["name"], item.get("note", "")) for item in spec.attachments]
