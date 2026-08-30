"""Who is buying, and what they are buying.

The engine is category-agnostic on purpose -- the item list, the units, the
questionnaire and the currency are all derived or drafted, and none of the code
in `core/` knows what a corrugated box is. But a demo has to be *somebody's*
demo. A screen headed "AI RFx Analyst" is a tool looking for a use; a screen
headed with the buyer's own name and the category they are sourcing is the
thing a procurement person recognises as theirs.

So the identity lives here, in one file, as display text. Change these three
strings and the whole application is a different company sourcing a different
category -- nothing downstream reads them, and the sample documents are
addressed from the same constants, so the fabricated dataset and the interface
can never disagree about who sent what to whom.
"""

from __future__ import annotations

import os

# The buyer running this sourcing event. A group brand with an Indian
# manufacturing operation, which is why the request is priced in rupees and
# delivered to Bengaluru while the company name is not.
COMPANY = os.getenv("RFX_COMPANY", "Wexford Consumer Brands")
COMPANY_LEGAL = os.getenv("RFX_COMPANY_LEGAL",
                          "Wexford Consumer Brands India Pvt Ltd")
COMPANY_UNIT = os.getenv("RFX_COMPANY_UNIT", "Packaging Procurement")

# The category. Named on the masthead so nobody has to read three sections to
# work out what is being bought.
CATEGORY = os.getenv("RFX_CATEGORY", "Corrugated packaging")

# The line under the name. It has to say the category out loud -- a tagline
# that could belong to any procurement tool teaches the reader nothing.
TAGLINE = os.getenv(
    "RFX_TAGLINE",
    "The best corrugated packaging company in India",
)

# Where the goods go. Used on the request document and in the sample quotes.
ADDRESS = os.getenv("RFX_ADDRESS", "Bommasandra Industrial Area, Bengaluru 560099")
CONTACT = os.getenv("RFX_CONTACT", "Claire Whitfield, Category Manager")
CONTACT_EMAIL = os.getenv("RFX_CONTACT_EMAIL",
                          "procurement@wexfordbrands.example")


def kicker() -> str:
    """The small line above the headline."""
    return f"{COMPANY_UNIT} · {CATEGORY}"


def addressed_to() -> str:
    """How a supplier would head their quotation."""
    return f"{COMPANY_LEGAL}, {ADDRESS}"
