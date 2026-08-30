"""SQLite persistence and the read-only query surface.

Two reasons the normalised comparison lands in a real database rather than
staying in memory:

1. The analyst answers questions by running SQL against it. Real aggregation on
   real rows, instead of an LLM doing arithmetic in its head over a wall of
   pasted JSON -- which is where wrong-but-confident numbers come from.

2. A demo survives a page refresh.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Optional

import pandas as pd

from . import config
from .assemble import Comparison
from . import rfx as rfx_module

# The recommendation table lives in its own constant because two things create
# it: a fresh comparison (empty, so the analyst can query it before the buyer
# has opened the award tab) and write_award (filled, whenever the buyer changes
# an award setting). Before this, a new comparison left the PREVIOUS one's award
# rows in place, and the analyst -- told in its prompt that this table is "the
# buyer's CURRENT recommendation" -- answered "who should get what" with winners
# from a comparison that was no longer on screen.
AWARD_TABLE = """
CREATE TABLE award (
    rfx_sku          TEXT,
    description      TEXT,
    quantity         INTEGER,
    winner           TEXT,
    price            REAL,
    extended         REAL,
    runner_up        TEXT,
    runner_up_price  REAL,
    saving_per_unit  REAL,
    extended_saving  REAL,
    contenders       INTEGER,
    status           TEXT,
    reason           TEXT
);
"""

SCHEMA = """
DROP VIEW  IF EXISTS comparison;
DROP TABLE IF EXISTS award;
DROP TABLE IF EXISTS quotes;
DROP TABLE IF EXISTS questionnaire;
DROP TABLE IF EXISTS terms;
DROP TABLE IF EXISTS vendors;
DROP TABLE IF EXISTS rfx_lines;

CREATE TABLE rfx_lines (
    sku            TEXT PRIMARY KEY,
    description    TEXT,
    quantity       INTEGER,
    canonical_unit TEXT,
    line_no        INTEGER
);

CREATE TABLE vendors (
    vendor               TEXT PRIMARY KEY,
    source_file          TEXT,
    coverage_quoted      INTEGER,
    coverage_total       INTEGER,
    comparable_lines     INTEGER,
    meets_requirements   INTEGER,
    quality_score        REAL,
    hard_failures        TEXT,
    unanswered_criteria  TEXT,
    disclosed_figures    INTEGER,
    freight_included     INTEGER,
    payment_terms_days   INTEGER,
    lead_time_days       REAL,
    document_currency    TEXT,
    currency_assumed     INTEGER,
    overall_confidence   REAL
);

CREATE TABLE questionnaire (
    vendor         TEXT,
    criterion_key  TEXT,
    question       TEXT,
    verdict        TEXT,
    stated_value   TEXT,
    numeric_value  REAL,
    target         REAL,
    direction      TEXT,
    meets          INTEGER,
    evidence       TEXT,
    evidence_text  TEXT,
    note           TEXT,
    score          REAL,
    requirement    TEXT,
    weight         REAL
);

CREATE TABLE terms (
    vendor  TEXT,
    kind    TEXT,
    text    TEXT,
    trigger TEXT,
    value   REAL
);

CREATE TABLE quotes (
    rfx_sku               TEXT,
    vendor                TEXT,
    original_text         TEXT,
    original_value        REAL,
    original_unit         TEXT,
    original_currency     TEXT,
    canonical_value       REAL,
    canonical_unit        TEXT,
    canonical_currency    TEXT,
    factor                TEXT,
    rules                 TEXT,
    status                TEXT,
    reason                TEXT,
    missing_datum         TEXT,
    flags                 TEXT,
    comparable            INTEGER,
    match_basis           TEXT,
    match_confidence      REAL,
    extraction_confidence REAL,
    source_file           TEXT,
    source_locator        TEXT,
    source_snippet        TEXT
);

CREATE VIEW comparison AS
SELECT
    q.rfx_sku,
    r.description        AS rfx_description,
    r.quantity           AS rfx_quantity,
    r.canonical_unit     AS rfx_unit,
    q.vendor,
    q.original_value,
    q.original_unit,
    q.original_currency,
    q.canonical_value,
    q.canonical_currency,
    q.factor,
    q.status,
    q.reason,
    q.missing_datum,
    q.flags,
    q.comparable,
    q.extraction_confidence,
    q.source_locator,
    q.source_snippet,
    v.meets_requirements,
    v.quality_score,
    v.freight_included,
    v.coverage_quoted,
    v.coverage_total,
    (q.canonical_value * r.quantity) AS extended_value
FROM quotes q
JOIN rfx_lines r ON r.sku = q.rfx_sku
JOIN vendors   v ON v.vendor = q.vendor;
""" + AWARD_TABLE


SCHEMA_FOR_PROMPT = """
TABLE rfx_lines(sku, description, quantity, canonical_unit, line_no)
    Every item in the comparison. `quantity` is the volume asked for, and may
    be NULL when no supplier stated one.

TABLE vendors(vendor, source_file, coverage_quoted, coverage_total,
              comparable_lines, meets_requirements, quality_score,
              hard_failures, unanswered_criteria, disclosed_figures,
              freight_included, payment_terms_days, lead_time_days,
              document_currency, currency_assumed, overall_confidence)
    meets_requirements is 1 unless the supplier fails a criterion the BUYER
    marked as a must-have; by default nothing is a must-have, so it is 1 for
    everyone and quality_score (0..1) is what separates them. Never treat a low
    score as disqualifying on your own -- report it and let the buyer decide.
    freight_included: 1 = included in rates, 0 = extra, NULL = document silent.

TABLE questionnaire(vendor, criterion_key, question, verdict, stated_value,
                    numeric_value, target, direction, meets, evidence,
                    evidence_text, note, score, requirement, weight)
    One row per supplier per quality criterion. The criteria are DERIVED from
    what the suppliers answered, so the question text is their own wording.
    verdict is 'Yes' | 'No' | 'Partial' | 'Unanswered' -- 'Unanswered' is NOT
    'No'. numeric_value is the figure they actually disclosed, if any, and
    `target` is what the question asked for, so you can measure the gap rather
    than just report a fail. `meets` is 1 when the criterion is satisfied.
    score is exactly 1 or 0 -- satisfied or not -- and a supplier's overall
    quality_score is sum(weight where meets) / sum(weight). A bare Yes with no
    figure counts the same as a Yes with one; evidence ('documented' |
    'quantified' | 'asserted' | 'none') is recorded for the buyer's judgement
    but does NOT affect the score. Do not invent a different weighting.

TABLE terms(vendor, kind, text, trigger, value)
    kind in ('freight','payment','validity','discount','tax','other').
    For discounts, `trigger` is the qualifying condition and `value` the percent.

TABLE quotes(rfx_sku, vendor, original_text, original_value, original_unit,
             original_currency, canonical_value, canonical_unit,
             canonical_currency, factor, rules, status, reason, missing_datum,
             flags, comparable, match_basis, match_confidence,
             extraction_confidence, source_file, source_locator, source_snippet)

TABLE award(rfx_sku, description, quantity, winner, price, extended, runner_up,
            runner_up_price, saving_per_unit, extended_saving, contenders,
            status, reason)
    The buyer's CURRENT split-award recommendation, one row per item, reflecting
    whatever filters they have set on screen. status is 'awarded' (contested),
    'single_source' (only one supplier could price it) or 'no_comparable' (it
    cannot be awarded from these responses). Use this when asked who should get
    what, rather than recomputing the minimum yourself.

VIEW comparison
    quotes joined to rfx_lines and vendors, plus
    extended_value = canonical_value * rfx_quantity.

CRITICAL SEMANTICS
  * canonical_value is the price restated on the buyer's unit and currency.
    original_value is what the vendor printed. They differ wherever `factor`
    is not null.
  * comparable = 1 marks the ONLY rows valid for price comparison. Rows with
    status 'Needs Review', 'Unresolved' or 'Not Quoted' have comparable = 0.
    ALWAYS filter `WHERE comparable = 1` when ranking or totalling prices.
  * A vendor missing lines will produce a smaller total. Never compare SUM()
    across vendors without checking coverage_quoted, or restricting to a set
    of SKUs all vendors quoted.
"""


def connect(path: Optional[str] = None, read_only: bool = False) -> sqlite3.Connection:
    path = path or config.DB_PATH
    if read_only:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def write(comparison: Comparison, path: Optional[str] = None) -> str:
    path = path or config.DB_PATH
    connection = connect(path)
    try:
        connection.executescript(SCHEMA)

        connection.executemany(
            "INSERT INTO rfx_lines VALUES (?,?,?,?,?)",
            [(line.sku, line.description, line.quantity, line.canonical_unit, index + 1)
             for index, line in enumerate(rfx_module.active().lines)],
        )

        connection.executemany(
            "INSERT INTO vendors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(
                s.vendor, s.file, s.coverage_quoted, s.coverage_total,
                s.comparable_lines, int(s.meets_requirements), s.quality_score,
                ",".join(s.hard_failures), ",".join(s.unanswered),
                s.disclosed_figures,
                None if s.freight_included is None else int(s.freight_included),
                s.payment_terms_days, s.lead_time_days, s.document_currency,
                int(s.currency_assumed), s.overall_confidence,
            ) for s in comparison.summaries],
        )

        connection.executemany(
            "INSERT INTO questionnaire VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(summary.vendor, key, scored.criterion.question, scored.answer.verdict,
              scored.answer.stated_text, scored.answer.value,
              scored.criterion.threshold, scored.criterion.direction,
              None if scored.meets is None else int(scored.meets),
              scored.answer.evidence, scored.answer.evidence_text,
              scored.answer.note, scored.score, scored.criterion.requirement,
              scored.criterion.weight)
             for summary in comparison.summaries
             for key, scored in summary.scorecard.results.items()],
        )

        connection.executemany(
            "INSERT INTO terms VALUES (?,?,?,?,?)",
            [(response.vendor, term.kind, term.text, term.trigger, term.value)
             for response in comparison.responses for term in response.terms],
        )

        rows = [cell.to_row() for cell in comparison.cells]
        if rows:
            columns = list(rows[0].keys())
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO quotes ({','.join(columns)}) VALUES ({placeholders})",
                [tuple(row[column] for column in columns) for row in rows],
            )

        connection.commit()
    finally:
        connection.close()
    return path


# ---------------------------------------------------------------------------
# read-only query surface (this is what the analyst is given)
# ---------------------------------------------------------------------------

# `replace` is deliberately NOT in this list. In SQLite it is both a statement
# keyword and one of the most-used string functions, and a statement can only
# ever begin with it -- which the SELECT/WITH check above already refuses.
# banning the word blocked ordinary questions like
# "SELECT replace(description,'-',' ') ..." with "only read-only queries are
# allowed", which is both wrong and impossible for the buyer to act on.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum)\b",
    re.I,
)


class QueryError(ValueError):
    pass


def run_query(sql: str, path: Optional[str] = None, max_rows: int = 200,
              parameters: tuple = ()) -> dict[str, Any]:
    """Execute one read-only SELECT and return rows as plain data.

    Guarded rather than trusted: the analyst is a language model, and the
    database is the buyer's only source of truth on screen.
    """
    statement = (sql or "").strip().rstrip(";")
    if not statement:
        raise QueryError("Empty query.")
    if ";" in statement:
        raise QueryError("Only a single statement is allowed.")
    if not re.match(r"^(select|with)\b", statement, re.I):
        raise QueryError("Only SELECT (or WITH ... SELECT) queries are allowed.")
    if _FORBIDDEN.search(statement):
        raise QueryError("Only read-only queries are allowed.")

    path = path or config.DB_PATH
    if not os.path.exists(path):
        raise QueryError("No comparison has been built yet.")

    connection = connect(path, read_only=True)
    try:
        cursor = connection.execute(statement, parameters)
        rows = cursor.fetchmany(max_rows + 1)
        columns = [d[0] for d in cursor.description] if cursor.description else []
    finally:
        connection.close()

    truncated = len(rows) > max_rows
    records = [dict(row) for row in rows[:max_rows]]
    return {
        "sql": statement,
        "columns": columns,
        "row_count": len(records),
        "truncated": truncated,
        "rows": records,
    }


def query_frame(sql: str, path: Optional[str] = None) -> pd.DataFrame:
    result = run_query(sql, path=path, max_rows=5000)
    return pd.DataFrame(result["rows"], columns=result["columns"] or None)


def get_evidence(rfx_sku: str, vendor: str, path: Optional[str] = None) -> dict[str, Any]:
    """The audit trail for one cell: what the vendor wrote, and what we did to it."""
    result = run_query(
        "SELECT rfx_sku, vendor, original_text, original_value, original_unit, "
        "original_currency, canonical_value, canonical_unit, canonical_currency, "
        "factor, rules, status, reason, missing_datum, flags, match_basis, "
        "extraction_confidence, source_file, source_locator, source_snippet "
        "FROM quotes WHERE rfx_sku = ? AND vendor = ?",
        path=path,
        parameters=(str(rfx_sku), str(vendor)),
    )
    if not result["rows"]:
        return {"found": False, "rfx_sku": rfx_sku, "vendor": vendor}
    row = result["rows"][0]
    row["found"] = True
    return row


# The evidence lookup used to build its WHERE clause by quote-doubling the two
# values into the SQL string. It was safe from injection, but it ran the result
# back through the same guard the analyst's own SQL goes through -- so an item
# code or supplier name containing a semicolon was refused as "only a single
# statement is allowed", and one containing the word "update" or "create" as
# "only read-only queries are allowed". A buyer clicking a cell to see where a
# number came from got an error about SQL. Bound parameters cannot be read as
# syntax at all, which is the correct answer to both problems.


# ---------------------------------------------------------------------------
# award plan (recomputed whenever the buyer changes the award settings)
# ---------------------------------------------------------------------------

AWARD_SCHEMA = "DROP TABLE IF EXISTS award;\n" + AWARD_TABLE


def write_award(plan, path: Optional[str] = None) -> None:
    """Persist the current recommendation so the analyst can query it too."""
    path = path or config.DB_PATH
    connection = connect(path)
    try:
        connection.executescript(AWARD_SCHEMA)
        connection.executemany(
            "INSERT INTO award VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(a.sku, a.description, a.quantity, a.winner, a.price, a.extended,
              a.runner_up, a.runner_up_price, a.saving_per_unit, a.extended_saving,
              a.contenders, a.status, a.reason) for a in plan.lines],
        )
        connection.commit()
    finally:
        connection.close()
