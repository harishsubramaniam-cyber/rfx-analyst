"""One request, rendered for the people who have to answer it.

The PDF a supplier opens and the spec the comparison is built from come from
the same `RfxSpec` object, in this file, in one pass. That is not tidiness: it
is the only way to guarantee that the item list being compared is the item list
that was actually sent. Anywhere those two are produced separately, they drift,
and the drift shows up as a supplier "missing" a line nobody ever asked them
for.

Suggested lines are excluded here rather than filtered by the caller. A line
the co-pilot invented and nobody accepted must not reach a supplier, and the
safest place to enforce that is at the point of rendering.
"""

from __future__ import annotations

import io
from typing import Optional

from . import brand
from .rfx import RfxSpec

# ReportLab is imported inside the two functions that need it, not at module
# scope. Rendering a request PDF is one feature; comparing supplier responses
# is the rest of the application, and the second must not fail to import
# because the first one's library is missing. A missing dependency should cost
# you a button, with a sentence saying which package to install -- not the
# whole page and a stack trace.
PDF_HINT = ("The request document needs the `reportlab` package, which is not "
            "installed. Run `pip install -r requirements.txt` (or "
            "`pip install reportlab`) and restart the app. Everything else — "
            "reading responses, the comparison, the analyst — works without it.")

INK_HEX = "#151A22"
RULE_HEX = "#DDE3EA"
SOFT_HEX = "#414B5A"
HEAD_BG_HEX = "#F0F3F7"


class PdfUnavailable(RuntimeError):
    """Raised when the PDF library is absent, carrying what to do about it."""


def pdf_available() -> bool:
    """Can we render a request document on this machine?"""
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def _reportlab():
    """Import ReportLab, or explain what is missing in one sentence."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (KeepTogether, Paragraph,
                                        SimpleDocTemplate, Spacer, Table,
                                        TableStyle)
    except ImportError as exc:
        raise PdfUnavailable(PDF_HINT) from exc
    return dict(colors=colors, A4=A4, ParagraphStyle=ParagraphStyle,
                getSampleStyleSheet=getSampleStyleSheet, mm=mm,
                KeepTogether=KeepTogether, Paragraph=Paragraph,
                SimpleDocTemplate=SimpleDocTemplate, Spacer=Spacer,
                Table=Table, TableStyle=TableStyle)


def esc(value) -> str:
    """Buyer's text, safe to hand to ReportLab.

    A ReportLab Paragraph is parsed as mini-HTML, so any text a person typed is
    markup until it is escaped. "Grade A<B" ends the parse with an unclosed tag
    and raises, which means one ordinary description -- or a term, or a
    question, or a supplier name with an ampersand -- took down Preview and
    Send together, with a stack trace and no clue which line caused it. The
    bold and italic runs this file adds itself are added AFTER escaping, so
    they still render; nothing typed by a person is ever read as a tag.
    """
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def sendable_lines(spec: RfxSpec) -> list:
    """Only lines a person stands behind. Suggestions do not go out."""
    return [line for line in spec.lines if line.origin != "suggested"]


def _styles(rl: dict) -> dict:
    ParagraphStyle = rl["ParagraphStyle"]
    colors = rl["colors"]
    INK = colors.HexColor(INK_HEX)
    SOFT = colors.HexColor(SOFT_HEX)
    base = rl["getSampleStyleSheet"]()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=15, leading=19, textColor=INK, alignment=0,
                                spaceAfter=2),
        "kicker": ParagraphStyle("k", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=7.5, leading=10,
                                 textColor=colors.HexColor("#6B7688"),
                                 spaceAfter=10),
        "h": ParagraphStyle("h", parent=base["Normal"], fontName="Helvetica-Bold",
                            fontSize=9.5, leading=13, textColor=INK,
                            spaceBefore=12, spaceAfter=5),
        "body": ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.5, leading=12.5, textColor=SOFT),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontName="Helvetica",
                               fontSize=7.6, leading=10),
        "cellb": ParagraphStyle("cb", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=7.6, leading=10),
    }


def _table(rl: dict, rows: list[list], widths: list[float]):
    colors = rl["colors"]
    INK = colors.HexColor(INK_HEX)
    RULE = colors.HexColor(RULE_HEX)
    HEAD_BG = colors.HexColor(HEAD_BG_HEX)
    table = rl["Table"](rows, colWidths=widths, repeatRows=1)
    table.setStyle(rl["TableStyle"]([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_pdf(spec: RfxSpec, token: Optional[str] = None,
              vendor: Optional[str] = None) -> bytes:
    """The request document itself. Returns PDF bytes.

    Raises PdfUnavailable, carrying an installation hint, when ReportLab is
    not present.
    """
    rl = _reportlab()
    Paragraph, Spacer, KeepTogether = rl["Paragraph"], rl["Spacer"], rl["KeepTogether"]
    mm = rl["mm"]
    style = _styles(rl)
    buffer = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buffer, pagesize=rl["A4"],
        leftMargin=17 * mm, rightMargin=17 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=spec.title or "Request for quotation",
    )

    story: list = []
    story.append(Paragraph(esc(spec.title or "Request for quotation"), style["title"]))

    kicker = [brand.COMPANY_LEGAL.upper(), "REQUEST FOR QUOTATION"]
    if spec.reference:
        kicker.append(spec.reference)
    if token:
        # The one string that ties a reply back to this request and this
        # supplier without anyone guessing from a letterhead.
        kicker.append(f"quote reference {token}")
    story.append(Paragraph(esc("  ·  ".join(kicker)), style["kicker"]))

    facts = []
    if vendor:
        facts.append(["Addressed to", vendor])
    facts.append(["From", f"{brand.COMPANY_LEGAL}, {brand.ADDRESS}"])
    facts.append(["Contact", f"{brand.CONTACT} · {brand.CONTACT_EMAIL}"])
    if spec.scope:
        facts.append(["Scope", spec.scope])
    if spec.vendor_category:
        facts.append(["Category", spec.vendor_category])
    facts.append(["Quote in", spec.currency])
    if spec.delivery_location:
        facts.append(["Deliver to", spec.delivery_location])
    # Both ends of the window, each with its time. A deadline with no start
    # tells a supplier nothing about how long they have; a date with no clock
    # is read as midnight at one end of the table and as start of business at
    # the other.
    if spec.starts_at:
        facts.append(["RFQ starts", spec.stamp(spec.starts_at)])
    if spec.ends_at:
        facts.append(["RFQ ends", spec.stamp(spec.ends_at)
                      + (f" — {spec.window_days} days to quote"
                         if spec.window_days is not None else "")])
    if facts:
        story.append(_table(
            rl,
            [[Paragraph(f"<b>{esc(k)}</b>", style["cell"]),
              Paragraph(esc(v), style["cell"])]
             for k, v in facts],
            [32 * mm, 144 * mm]))

    lines = sendable_lines(spec)
    story.append(Paragraph(f"Items to be priced ({len(lines)})", style["h"]))
    story.append(Paragraph(
        f"Please quote a price for every item, in <b>{esc(spec.currency)}</b>, per the "
        f"unit stated. If you cannot supply an item, say so rather than leaving "
        f"it blank. If you must quote on a different basis, quote it and state "
        f"the basis clearly — do not convert it yourself.", style["body"]))
    story.append(Spacer(1, 4))

    header = [Paragraph(esc(t), style["cellb"])
              for t in ("Item", "Description", "Quantity", "Price per", "Your rate")]
    rows = [header]
    for line in lines:
        rows.append([
            Paragraph(esc(line.sku), style["cell"]),
            Paragraph(esc(line.description)
                      + (f"<br/><i>{esc(line.note)}</i>" if line.note else ""),
                      style["cell"]),
            Paragraph(f"{line.quantity:,}" if line.quantity else "—", style["cell"]),
            Paragraph(esc((line.canonical_unit or "").replace("per ", "")), style["cell"]),
            Paragraph("", style["cell"]),
        ])
    story.append(_table(rl, rows, [20 * mm, 84 * mm, 20 * mm, 22 * mm, 30 * mm]))

    if spec.criteria:
        block = [Paragraph(f"Questions ({len(spec.criteria)})", style["h"]),
                 Paragraph("Answer every question. Where a figure is asked for, "
                           "give the figure and say what supports it — a "
                           "certificate number, an audit, a measured result. "
                           "An unanswered question is not the same as a no, and "
                           "will be followed up.", style["body"]),
                 Spacer(1, 4)]
        rows = [[Paragraph(esc(t), style["cellb"])
                 for t in ("#", "Question", "Required", "Your answer")]]
        for index, criterion in enumerate(spec.criteria, start=1):
            rows.append([
                Paragraph(str(index), style["cell"]),
                Paragraph(esc(criterion.label), style["cell"]),
                Paragraph("Must have" if criterion.requirement == "Must have"
                          else "Scored", style["cell"]),
                Paragraph("", style["cell"]),
            ])
        block.append(_table(rl, rows, [8 * mm, 104 * mm, 22 * mm, 42 * mm]))
        story.append(KeepTogether(block))

    if spec.terms:
        story.append(Paragraph("Terms", style["h"]))
        rows = [[Paragraph(esc(t), style["cellb"]) for t in ("Term", "Requested")]]
        for kind, text in spec.terms.items():
            rows.append([Paragraph(esc(str(kind).title()), style["cell"]),
                         Paragraph(esc(text), style["cell"])])
        story.append(_table(rl, rows, [32 * mm, 144 * mm]))

    if spec.notes:
        story.append(Paragraph("Notes from the buyer", style["h"]))
        for paragraph in [p for p in spec.notes.split("\n") if p.strip()]:
            story.append(Paragraph(esc(paragraph.strip()), style["body"]))

    if spec.attachments:
        story.append(Paragraph(f"Enclosed ({len(spec.attachments)})", style["h"]))
        rows = [[Paragraph(esc(t), style["cellb"]) for t in ("File", "What it is")]]
        for item in spec.attachments:
            rows.append([Paragraph(esc(item.get("name", "")), style["cell"]),
                         Paragraph(esc(item.get("note", "") or "—"), style["cell"])])
        story.append(_table(rl, rows, [64 * mm, 112 * mm]))

    story.append(Paragraph("How to reply", style["h"]))
    story.append(Paragraph(
        "Reply in whatever format suits you — your own quotation template, a "
        "spreadsheet, a PDF, or the body of an email. You do not need to use "
        "this layout. Please keep your item references visible so each price "
        "can be matched to the request"
        + (f", and quote reference <b>{esc(token)}</b> in your reply." if token else "."),
        style["body"]))

    doc.build(story)
    return buffer.getvalue()


def covering_note(spec: RfxSpec, vendor: str, token: str,
                  sender: str = "") -> str:
    """The message body. Plain text: it has to survive any mail client."""
    lines = sendable_lines(spec)
    parts = [
        f"Dear {vendor},",
        "",
        f"We are inviting quotations for {spec.scope or spec.title or 'the items below'}.",
        "",
        f"  Request        {spec.title or 'Request for quotation'}"
        + (f" ({spec.reference})" if spec.reference else ""),
        f"  Items          {len(lines)}",
        f"  Quote in       {spec.currency}",
    ]
    if spec.delivery_location:
        parts.append(f"  Deliver to     {spec.delivery_location}")
    if spec.starts_at:
        parts.append(f"  RFQ starts     {spec.stamp(spec.starts_at)}")
    if spec.ends_at:
        parts.append(f"  RFQ ends       {spec.stamp(spec.ends_at)}")
    if spec.attachments:
        parts.append(f"  Enclosed       {len(spec.attachments)} supporting "
                     f"file{'' if len(spec.attachments) == 1 else 's'}")
    parts += [
        f"  Reference      {token}",
        "",
        "The full item list and our questions are in the attached document.",
        "",
        "Please reply in whatever format suits you — your own template is fine. "
        "Keep the reference above in your reply so we can match your prices to "
        "this request.",
        "",
        "Regards,",
        sender or brand.CONTACT,
        brand.COMPANY_LEGAL,
    ]
    return "\n".join(parts)
