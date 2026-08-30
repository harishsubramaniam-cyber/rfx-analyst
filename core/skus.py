"""Item-code and dimension parsing.

Lives on its own so both the matcher and the RFx builder can use it without
importing each other.
"""

from __future__ import annotations

import re
from typing import Optional

# Two letters minimum, and the code must stand as its own token. A one-letter
# prefix is not a code, it is a coincidence: the old pattern read the "x" in
# "400 x 300 x 250 mm" as a prefix and invented the item code X-300 out of a
# description that had no code in it at all. Those phantoms then became rows
# in their own right, so two suppliers describing the same box never met.
_SKU_PATTERN = re.compile(r"\b([A-Z]{2,5})[\s_\-]{0,2}(\d{1,6})\b")
_SEPARATED = re.compile(r"\b([A-Z]{2,5})[_\-](\d{1,6})\b")
_DIM_PATTERN = re.compile(r"(\d{2,5})\s*[x×*]\s*(\d{2,5})(?:\s*[x×*]\s*(\d{2,5}))?", re.I)

# Words that sit next to a number in ordinary prose and are not item codes.
# Without this, "Delivery in 15 days" yields IN-015, "ISO 9001 certified"
# yields ISO-9001 and "Corrugated Box 400 x 300" yields BOX-400 -- and because
# an invented code takes the matcher's top rung at 0.97 confidence, it puts a
# price on the wrong row with more certainty than any honest match.
_NOT_A_PREFIX = {
    # units and quantities
    "MM", "CM", "KG", "GSM", "PLY", "PCS", "NOS", "QTY", "EA", "PC", "LTR",
    "MTR", "SQ", "CBM", "TON", "TONNE", "GM", "ML", "INCH", "FT",
    # money and commercial furniture
    "RS", "INR", "USD", "EUR", "GBP", "GST", "HSN", "MOQ", "NET", "VAT",
    "TOTAL", "AMT", "PRICE", "RATE", "COST", "QTY",
    # standards, which look exactly like codes and are not items
    "ISO", "IS", "EN", "DIN", "ASTM", "BS", "IEC", "ANSI", "JIS", "SAE",
    # ordinary words that precede numbers
    "IN", "FOR", "PER", "NO", "REF", "TYPE", "SIZE", "GRADE", "CLASS",
    "MODEL", "ITEM", "LINE", "ROW", "SL", "SR", "CAT", "BOX", "SET", "PACK",
    "DAYS", "DAY", "WEEK", "MONTH", "YEAR", "VALID", "WITHIN", "UPTO",
}


def normalize_sku(raw: Optional[str]) -> Optional[str]:
    """'bx 1', 'BX001', 'Bx-01' all become 'BX-001'.

    Returns None when the text carries no item code, which is a real and
    common answer -- plenty of suppliers quote by description alone. Inventing
    one is worse than admitting there is none, because a fabricated code looks
    exactly like a real one to everything downstream.

    Two shapes count as a code. Either the whole string is one -- a cell
    holding "CP-001" or "BX 004" -- or, when it is embedded in a sentence, it
    carries a hyphen or underscore, as "our ref BX-001" does. A bare
    letters-space-digits run inside prose is not a code; that is just English
    with a number in it.
    """
    if not raw:
        return None
    text = str(raw).upper().strip()

    whole = _SKU_PATTERN.fullmatch(text)
    if whole and whole.group(1) not in _NOT_A_PREFIX:
        return f"{whole.group(1)}-{int(whole.group(2)):03d}"

    for match in _SEPARATED.finditer(text):
        prefix, digits = match.group(1), match.group(2)
        if prefix in _NOT_A_PREFIX:
            continue
        return f"{prefix}-{int(digits):03d}"
    return None


def dimension_signature(text: Optional[str]) -> Optional[tuple[int, ...]]:
    if not text:
        return None
    match = _DIM_PATTERN.search(text)
    if not match:
        return None
    dims = [int(group) for group in match.groups() if group]
    return tuple(sorted(dims, reverse=True))
