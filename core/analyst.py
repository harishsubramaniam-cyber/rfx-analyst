"""The AI analyst.

Deliberately NOT "paste the whole comparison into the prompt and ask nicely".
At five vendors and thirty lines that means asking a language model to do
several hundred arithmetic operations in its head, and it will get some of them
quietly wrong. On a screen a buyer is about to commit ₹4 crore against, quietly
wrong is the worst possible failure.

Instead the model is given the database and three tools. It writes SQL, the
database does the arithmetic, and the model explains the result. Every query it
ran is kept and shown underneath the answer, so the buyer can check the working
rather than trust the tone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from google.genai import types

from . import config, llm, store

# "five supplier responses" used to be written into this prompt. It stopped
# being true the moment the comparison was made generic: the analyst was told a
# number the database did not contain, and a model told the shape of its data up
# front will trust that over counting. Ask the database how many there are.
SYSTEM_PROMPT = """You are a procurement analyst helping a category buyer
interrogate the supplier responses to an RFx. The buyer may award a contract
worth a great deal of money based on what you say.

You do not know how many suppliers, items or questions there are, or what
category this is. Count them with a query before you say. Never state a
number of suppliers or lines you have not counted.

You do NOT have the data in front of you. You have a SQLite database and tools
to query it. Query first, then answer. Never estimate a number you could have
computed.

DATABASE SCHEMA
{schema}

HOW TO WORK
1. Plan what you need, then call run_query. Use several small queries rather
   than one enormous one; you can see the results before deciding what next.
2. Filter with `comparable = 1` for any price ranking, comparison or total.
   Rows that are not comparable exist for a reason and must not be silently
   averaged in.
3. When a number matters, call get_evidence to see the vendor's verbatim text,
   and quote it.
4. To show a chart, call make_chart with a query that returns exactly the
   columns you want plotted.

HOW TO ANSWER
* Lead with the answer. The buyer is busy.
* Use a markdown table when comparing more than two things.
* State the number of lines behind every claim. "Cheapest on 24 of 30
  comparable lines" is useful; "cheapest" is not. The figures in that sentence
  must come from a query you ran.
* Name every exclusion. If lines were dropped because they were Unresolved or
  Not Quoted, say which and why. Never let an exclusion pass unmentioned --
  a total that silently covers a smaller basket is a lie with a decimal point.
* Distinguish "answered No" from "did not answer". They are different risks.
* If the data cannot support a conclusion, say exactly that, and say what
  would be needed. This is a correct and valuable answer, not a failure.
* Never apply a conditional discount as if it were certain. Mention it as a
  contingency with its trigger.
* Do not recommend an award unless the data supports one. When you do, give
  the reasoning and the risks in the same breath.
"""


@dataclass
class ChartSpec:
    title: str
    kind: str
    sql: str
    x: str
    y: str
    series: Optional[str] = None
    rows: list[dict] = field(default_factory=list)


@dataclass
class AnalystAnswer:
    text: str
    queries: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    rounds: int = 0
    error: Optional[str] = None


DECLARATIONS = [
    types.FunctionDeclaration(
        name="run_query",
        description=(
            "Run one read-only SQL SELECT against the comparison database and "
            "get the rows back. This is how you do arithmetic: never compute a "
            "sum, average, ranking or count yourself."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sql": types.Schema(
                    type=types.Type.STRING,
                    description="A single SELECT or WITH...SELECT statement.",
                )
            },
            required=["sql"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_evidence",
        description=(
            "Fetch the full audit trail for one vendor's quote on one RFx line: "
            "the verbatim source text, the conversion applied, and the status."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "rfx_sku": types.Schema(type=types.Type.STRING, description="the item code exactly as it appears in the comparison"),
                "vendor": types.Schema(type=types.Type.STRING, description="Vendor name."),
            },
            required=["rfx_sku", "vendor"],
        ),
    ),
    types.FunctionDeclaration(
        name="make_chart",
        description=(
            "Render a chart for the buyer from a query. Use when a comparison is "
            "easier to see than to read. Returns the rows so you can describe them."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "title": types.Schema(type=types.Type.STRING),
                "kind": types.Schema(type=types.Type.STRING,
                                     description="bar | line | scatter"),
                "sql": types.Schema(type=types.Type.STRING,
                                    description="SELECT returning the columns to plot."),
                "x": types.Schema(type=types.Type.STRING, description="Column for the x axis."),
                "y": types.Schema(type=types.Type.STRING, description="Column for the y axis."),
                "series": types.Schema(type=types.Type.STRING,
                                       description="Optional column to split series by."),
            },
            required=["title", "kind", "sql", "x", "y"],
        ),
    ),
]


def ask(question: str, db_path: Optional[str] = None) -> AnalystAnswer:
    """Answer one buyer question against the built comparison."""
    path = db_path or config.DB_PATH
    answer = AnalystAnswer(text="")

    def _run_query(sql: str) -> dict[str, Any]:
        result = store.run_query(sql, path=path)
        answer.queries.append(result)
        return result

    def _get_evidence(rfx_sku: str, vendor: str) -> dict[str, Any]:
        result = store.get_evidence(rfx_sku, vendor, path=path)
        answer.evidence.append(result)
        return result

    def _make_chart(title: str, kind: str, sql: str, x: str, y: str,
                    series: Optional[str] = None) -> dict[str, Any]:
        result = store.run_query(sql, path=path, max_rows=400)
        answer.queries.append(result)
        spec = ChartSpec(title=title, kind=kind, sql=result["sql"], x=x, y=y,
                         series=series, rows=result["rows"])
        answer.charts.append(spec)
        return {"rendered": True, "row_count": result["row_count"], "rows": result["rows"]}

    tools = {
        "run_query": _run_query,
        "get_evidence": _get_evidence,
        "make_chart": _make_chart,
    }

    try:
        outcome = llm.run_tool_loop(
            system_prompt=SYSTEM_PROMPT.format(schema=store.SCHEMA_FOR_PROMPT),
            user_message=question,
            tools=tools,
            declarations=DECLARATIONS,
            kind="analyst",
        )
        answer.text = outcome.text
        answer.rounds = outcome.rounds
    except Exception as exc:
        answer.error = f"{type(exc).__name__}: {exc}"
        answer.text = (
            "I could not complete the analysis because the model call failed. "
            "The comparison data itself is unaffected — the grid above is still valid."
        )

    return answer


SUGGESTED_QUESTIONS = [
    "Which supplier is cheapest per line, but only among suppliers who cleared "
    "the quality questionnaire?",
    "If we split the award line by line to the cheapest compliant supplier, what "
    "do we spend, and how does that compare to giving the whole basket to one?",
    "Where do the suppliers disagree most on price, and is the disagreement real "
    "or a units problem?",
    "Which lines can we not compare at all, and what exactly do I need to ask "
    "each supplier to fix that?",
    "What would change if we ignored the quality questionnaire entirely?",
]
