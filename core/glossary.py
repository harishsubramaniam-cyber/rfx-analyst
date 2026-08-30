"""Plain-English definitions for every term the interface uses.

One source of truth, so the tooltip on a stat, the tooltip on a column header
and the glossary panel can never drift apart and start explaining the same
word differently.

House rule for the wording: explain what it means for the buyer's decision,
not what the code does. "Comparable" is not "a boolean flag on the quote row";
it is "prices we can safely put side by side".
"""

from __future__ import annotations

TERMS: dict[str, str] = {
    # --- the request -------------------------------------------------------
    "rfx":
        "The request you sent to suppliers. Every response is compared back to "
        "it — its item list, its units and its currency.",
    "line_item":
        "One product you asked for a price on, identified by its own item code.",

    # --- coverage ----------------------------------------------------------
    "priced":
        "How many of the items in this comparison the supplier actually gave a "
        "price for. Anything missing is a gap you will have to chase them for.",
    "comparable":
        "How many of their prices we can safely put side by side with the other "
        "suppliers. A price only becomes comparable once we are sure what it "
        "covers — one box, one roll, one kilogram — and which currency it is in. "
        "Prices we could not make safe are left out of every ranking rather than "
        "quietly averaged in.",
    "need_attention":
        "Prices that cannot go into the comparison yet: ones we could not work "
        "out, ones carrying a condition, and items nobody priced. Each has a "
        "specific next step listed in the Needs attention tab.",
    "cheapest_on":
        "How many items have a best price we can stand behind. An item counts "
        "only when at least one supplier's price for it could be made "
        "comparable; items nobody priced safely are left out rather than "
        "awarded to whoever happened to send a number.",
    "suppliers_read":
        "How many supplier documents were read successfully. Each may have "
        "arrived in a completely different format.",

    # --- confidence --------------------------------------------------------
    "read_clarity":
        "How clearly the numbers could be read off this supplier's document. A "
        "clean spreadsheet cell scores high; a figure on a photographed rate "
        "card scores lower. A low score does not mean the price is wrong — it "
        "means it is worth a second look before you commit.",

    # --- statuses ----------------------------------------------------------
    "status_confirmed":
        "They priced this exactly the way you asked. Nothing was changed.",
    "status_normalized":
        "They priced it a different way — per 100 pieces, or in another currency "
        "— and we converted it so it lines up. Both their original figure and "
        "the sum we did are shown.",
    "status_review":
        "There is a price, but something about it is not safe to compare yet. "
        "The reason is written next to the number itself — extra charge, "
        "different spec, has a condition, not firm — and spelled out in full "
        "in the key under the grid, on the row itself, and in Needs attention. "
        "The number is shown but kept out of every ranking and out of the "
        "recommended award.",
    "status_unresolved":
        "We will not show a number here, because producing one would mean "
        "guessing. Instead we say exactly what is missing, so you can ask them "
        "for that one thing.",
    "status_not_quoted":
        "This supplier did not mention this item anywhere in their response.",

    "quality_score":
        "Simple arithmetic: add up the weight of every criterion the supplier "
        "satisfies, and divide by the total weight of all of them. Nothing "
        "else goes into it, so you can recompute it on paper. It ranks "
        "suppliers rather than eliminating them — nobody is excluded unless "
        "you mark a criterion as a must-have.",
    "disclosure":
        "How many questions this supplier answered with an actual figure "
        "rather than a bare Yes. It does not change the score — a Yes counts "
        "in full either way — but it tells you how much of the score rests on "
        "the supplier's word alone.",
    "must_have":
        "Mark a criterion as a must-have and any supplier who does not meet it "
        "drops out of the recommendation entirely. Nothing is a must-have by "
        "default, because eliminating a supplier on one unverified self-report "
        "is a decision a person should take deliberately.",
    "target_suggestion":
        "The target the questionnaire itself asked for is often a round number "
        "nobody derived. Where the basket implies a better one — a capacity "
        "target of 1.5x what you actually need to buy — it is offered here.",
    "evidence_level":
        "What stands behind a claim: a certificate number, an attached "
        "third-party report, a stated figure, or nothing at all. It is captured "
        "against every answer and included in the Excel export, but it does not "
        "change the score — a Yes counts the same either way.",

    # --- quality -----------------------------------------------------------
    "passed_quality":
        "Whether this supplier meets every criterion you marked as a must-have. "
        "By default nothing is a must-have, so everyone qualifies and the "
        "quality score is what separates them.",
    "unanswered":
        "The supplier's document does not address this question at all. That is "
        "not the same as answering No, and is usually worth one email.",

    # --- commercial --------------------------------------------------------
    "delivery":
        "Whether getting the goods to you is already inside the price, or "
        "charged on top. If suppliers differ here, the cheapest price on screen "
        "may not be the cheapest once delivery is added.",
    "payment_terms":
        "How long after invoicing you have to pay. Longer is better for your "
        "cash, and is worth real money on a large order.",
    "lead_time":
        "How long after you place the order before the goods arrive.",
    "currency_assumed":
        "Their document never says which currency the prices are in. Where no "
        "currency is stated anywhere, prices are treated as INR by default, and "
        "flagged here so the assumption does not slip through unnoticed. You can "
        "change the default in the .env file.",
    "default_currency":
        "When a supplier's document does not state a currency anywhere, their "
        "prices are assumed to be in INR — the default — and every affected "
        "figure is flagged. Confirm the assumption with the supplier before you "
        "award anything.",
    "item_list":
        "The list of items being compared is built from the responses "
        "themselves: every item code that appears in at least one supplier's "
        "reply becomes a row. So the tool works for any category, and for any "
        "number of suppliers.",
    "discount":
        "A price reduction the supplier offers only if you buy enough. It is "
        "never applied to the prices shown, because it depends on future volumes "
        "nobody can confirm yet.",

    # --- award -------------------------------------------------------------
    "split_award":
        "Suggesting each item to whichever shortlisted supplier is cheapest on "
        "that item, rather than handing the whole basket to one. It usually "
        "costs less, at the price of managing more suppliers. It is a "
        "suggestion from the data — the decision stays yours.",
    "estimated_spend":
        "What you would spend if you followed this recommendation: the suggested "
        "price times the quantity, added up. It excludes delivery and any volume "
        "discount, because no supplier put a number on either.",
    "saving_vs_single":
        "How much less the split costs than giving everything to the best "
        "single supplier. It is measured only across the items every "
        "shortlisted supplier priced comparably — the only basket where both "
        "options can be totalled the same way — so it is a smaller number than "
        "the estimated spend, which covers every recommended item. The full "
        "arithmetic, both totals and the size of that basket are printed under "
        "the recommendation so you can check the sum.",
    "uncontested":
        "An item only one shortlisted supplier could price. They are suggested "
        "because there is no alternative, not because they beat anyone — so it "
        "is the first place to go back to the market.",
    "min_lines":
        "The smallest number of items worth giving any one supplier. Coming out "
        "ahead on two items rarely justifies onboarding a supplier and raising a "
        "PO, so anything below this is moved to the next cheapest supplier and "
        "the extra cost is reported.",

    # --- drafting a request ------------------------------------------------
    "origin_yours":
        "You stated this item — typed to the co-pilot, or edited into the "
        "table. It goes to suppliers exactly as written.",
    "origin_document":
        "Read out of a file you handed over: a purchase order, a bill of "
        "materials, last year's contract. Yours, not a proposal — but check "
        "the quantities, because a past order says what you bought then, not "
        "what you need next.",
    "origin_suggested":
        "Proposed for you rather than stated by you. It is held out of the "
        "document sent to suppliers until you accept it, because nobody "
        "should be asked to price something no person decided to buy. "
        "Accepting is one click, or just edit the line.",
    "quote_reference":
        "One identifier per supplier, carried in the subject line, the "
        "covering note and the request document — RFX-<request>-<supplier>-"
        "<check>. When a reply quotes it, that supplier is identified rather "
        "than guessed from a letterhead, and a mistyped reference matches "
        "nobody instead of matching the wrong company.",
    "charges_note":
        "The instruction telling suppliers that packaging, palletisation, "
        "plates, tooling and any other charge must be quoted as a line with "
        "an amount — not as \"at actuals\" or \"to be advised\". A charge with "
        "no number cannot be compared, and it is where a cheap-looking quote "
        "hides its tail.",
    "terms":
        "The commercial conditions the request is issued on — payment, "
        "delivery, validity, tax — and any instruction about how to quote. "
        "Written one to a line as \"Payment: 45 days from invoice\": the label "
        "before the colon is what the supplier sees in the Terms column of the "
        "request, and a line with no label is sent exactly as you wrote it.",
    "rfx_window":
        "When the request opens and when it closes. A deadline on its own "
        "tells a supplier nothing about how long they have — the same "
        "\"responses due Friday\" is a fortnight or an afternoon depending on "
        "when it was sent, and quoting time is the first thing a salesperson "
        "checks before deciding how much care to take.",
    "vendor_category":
        "Which slice of the category this request is for. It decides which "
        "approved suppliers are recommended, and it is printed on the request "
        "so a supplier can tell at a glance whether it is aimed at them.",
    "vendor_rating":
        "Your own scorecard for a supplier, out of ten — not their claim about "
        "themselves. It is the average of four scores kept from previous "
        "business: quality, delivery, commercial and responsiveness. Every "
        "part is shown beside it, so you can disagree with one score rather "
        "than with the whole number.",
    "recommended_vendors":
        "Who this request is suggested to go to: the approved suppliers in "
        "this category rating 7.0 or better. It decides who gets ASKED, never "
        "who gets awarded — that is settled by the prices they send back, and "
        "a well-rated supplier who quotes badly should lose. It never "
        "shortlists fewer than two, because a request sent to one supplier is "
        "a purchase order with extra steps.",
    "issuer_notes":
        "Anything you want suppliers to read that is not an item, a question "
        "or a term — a plant shutdown, a change of specification coming, how "
        "you want the quote laid out. Sent verbatim with the request.",
    "attachments_out":
        "Files sent with the request: drawings, specifications, a delivery "
        "schedule, artwork. They ride along on every invitation and are listed "
        "on the request document itself, so a supplier can see whether they "
        "received everything.",
    "outbox":
        "Where invitations are written. The mail server is stubbed, so each "
        "one lands as a real .eml file with the request PDF attached — "
        "openable in any mail client. Point it at a real server and nothing "
        "else changes.",

    # --- mechanics ---------------------------------------------------------
    "basis":
        "What a single price actually covers — one box, one sheet, one roll, a "
        "hundred pieces, or a kilogram. Two prices can only be compared when "
        "they cover the same thing. This is where most quote comparisons quietly "
        "go wrong.",
    "fx_date":
        "The day the exchange rates are taken to hold on. The rates themselves "
        "are fixed rather than pulled live, so the same files give the same "
        "answer tomorrow as today — a comparison you cannot reproduce is one "
        "you cannot defend. You can change the date in the sidebar; it is "
        "stamped on every converted price and carried into the export, and you "
        "are warned if it has gone more than a month stale.",
    "conversion":
        "The sum we did to restate a supplier's price on your unit and currency, "
        "shown in full so you can check it. For example ÷ 100 turns a price per "
        "100 pieces into a price per piece.",
    "evidence":
        "The exact words from the supplier's own document that a number was read "
        "from. Every figure on screen can be traced back to one.",
    "audit_trail":
        "The complete record behind every figure: what the supplier wrote, what "
        "we changed, why we changed it, and which part of which document it came "
        "from.",
    "as_quoted":
        "Shows each supplier's price in their own words and their own units, "
        "untouched. Useful for checking, but the columns are not comparable to "
        "each other in this view.",
    "made_comparable":
        "Shows every price restated on your units and currency, so the columns "
        "can be read against each other. The original is always one click away.",
}


# Order shown in the glossary panel, grouped so it reads like an explanation
# rather than a dictionary.
GLOSSARY_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("The basics", [
        ("Request (RFx)", "rfx"),
        ("Line item", "line_item"),
        ("The item list", "item_list"),
        ("Basis", "basis"),
        ("Default currency", "default_currency"),
    ]),
    ("How complete each response is", [
        ("Priced", "priced"),
        ("Comparable", "comparable"),
        ("Need attention", "need_attention"),
        ("Items with a best price", "cheapest_on"),
        ("Read clarity", "read_clarity"),
    ]),
    ("What each status means", [
        ("As the RFx asked", "status_confirmed"),
        ("We converted it", "status_normalized"),
        ("Needs a human", "status_review"),
        ("Could not work it out", "status_unresolved"),
        ("Not priced", "status_not_quoted"),
    ]),
    ("Quality and commercial terms", [
        ("Quality score", "quality_score"),
        ("Figures disclosed", "disclosure"),
        ("Must-have", "must_have"),
        ("Suggested target", "target_suggestion"),
        ("Not answered", "unanswered"),
        ("Delivery", "delivery"),
        ("Payment terms", "payment_terms"),
        ("Lead time", "lead_time"),
        ("Discount", "discount"),
        ("Currency assumed", "currency_assumed"),
    ]),
    ("Recommending an award", [
        ("Split award", "split_award"),
        ("Estimated spend", "estimated_spend"),
        ("Saved vs one supplier", "saving_vs_single"),
        ("Uncontested line", "uncontested"),
        ("Minimum lines per supplier", "min_lines"),
    ]),
    ("Checking our working", [
        ("Evidence", "evidence"),
        ("Conversion", "conversion"),
        ("Exchange rate date", "fx_date"),
        ("Audit trail", "audit_trail"),
    ]),
]


# The drafting page's own vocabulary. It shares a file with the comparison's
# terms so a word can never be defined twice, but it does NOT share the panel:
# "comparable" and "read clarity" mean nothing on a page where no supplier has
# replied yet, and a help panel full of terms that are not on screen teaches
# people to stop opening it.
DRAFT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Writing the request", [
        ("Line item", "line_item"),
        ("Price per (basis)", "basis"),
        ("Quote currency", "default_currency"),
        ("Open and close dates", "rfx_window"),
        ("Notes to suppliers", "issuer_notes"),
        ("Terms", "terms"),
        ("Charges must carry an amount", "charges_note"),
    ]),
    ("Where each line came from", [
        ("Yours", "origin_yours"),
        ("From your file", "origin_document"),
        ("Suggested", "origin_suggested"),
    ]),
    ("The questions you ask", [
        ("Must-have", "must_have"),
        ("Suggested target", "target_suggestion"),
    ]),
    ("Choosing who to ask", [
        ("Vendor category", "vendor_category"),
        ("Vendor rating", "vendor_rating"),
        ("Recommended suppliers", "recommended_vendors"),
    ]),
    ("Sending it", [
        ("Attachments", "attachments_out"),
        ("Quote reference", "quote_reference"),
        ("Outbox", "outbox"),
    ]),
]


def tip(key: str) -> str:
    """The definition, or an empty string if we have not written one."""
    return TERMS.get(key, "")
