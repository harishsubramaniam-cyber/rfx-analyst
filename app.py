"""AI RFx Analyst -- the shell.

This file holds only what both pages share: session state, the sidebar, and
the page switcher. The two pages themselves are in views/.

Reading order for anyone reviewing this: the interesting decisions live in
core/draft.py (why the co-pilot edits the real object), core/normalize.py (what
we refuse to convert), core/match.py (how vendor lines are tied to RFx lines)
and core/analyst.py (why the analyst queries a database instead of reading
pasted JSON). Presentation is here and in core/theme.py.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from core import (assemble, config, glossary, llm, present, rfxdoc, store, theme)
from core import rfx as rfx_module
from views import compare_page, draft_page

st.set_page_config(page_title="AI RFx Analyst", page_icon="◧", layout="wide")
st.markdown(theme.CSS, unsafe_allow_html=True)

for key, default in (("run", None), ("comparison", None), ("history", []),
                     ("spec", None), ("criteria_settings", {}),
                     ("analyst_question", ""), ("fx_date", config.FX_DATE),
                     ("draft", None), ("draft_history", []), ("draft_open", False),
                     ("invitations", []), ("invite_text", ""),
                     ("chosen_vendors", set()), ("vendor_category_seen", None),
                     ("vendor_rows", None)):
    st.session_state.setdefault(key, default)

# The comparison database belongs to this browser session too -- see
# config.new_session_db_path(). Set before anything can read it, and only once:
# a fresh path on a rerun would orphan the comparison already written.
if "db_path" not in st.session_state:
    st.session_state["db_path"] = config.new_session_db_path()

# The rate date belongs to this browser session too, for the same reason the
# item list does: one server, several buyers, no shared state between them.
config.FX_DATE = st.session_state["fx_date"]

# The request being drafted also belongs to this browser session.
if st.session_state["draft"] is None:
    st.session_state["draft"] = rfx_module.RfxSpec(derived=False)

# The comparison spine belongs to this browser session, not to the process, so
# two people using the same server never see each other's item list.
if st.session_state["spec"] is not None:
    rfx_module.set_active(st.session_state["spec"])
else:
    rfx_module.reset_active()


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    spec = rfx_module.active()
    if spec.lines:
        st.markdown(
            f'<div class="rfx-kicker">This comparison</div>'
            f'<div class="rfx-meta" style="border:none;padding:0;margin:0;'
            f'flex-direction:column;gap:.2rem">'
            f"<span><b>{spec.line_count}</b> items being compared</span>"
            f"<span>priced in <b>{spec.currency}</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.caption("The item list is built from the responses themselves, so any "
                   "category works.")
    else:
        st.markdown('<div class="rfx-kicker">This comparison</div>',
                    unsafe_allow_html=True)
        st.caption("Add supplier responses to begin.")

    st.divider()
    st.markdown('<div class="rfx-kicker">Model</div>', unsafe_allow_html=True)
    if st.button("Run connection check", width="stretch"):
        st.session_state["doctor"] = llm.doctor()

    report = st.session_state.get("doctor")
    if report and report.get("ok"):
        st.markdown(theme.chip("connected", "ok"), unsafe_allow_html=True)
        st.caption(f"reading · `{report['extract_model']}`")
        st.caption(f"analysis · `{report['analyst_model']}`")
    elif report:
        st.markdown(theme.chip("cannot reach model", "stop"), unsafe_allow_html=True)
        st.caption(report.get("error", ""))
    else:
        st.caption("Not checked yet.")

    st.divider()
    st.markdown('<div class="rfx-kicker">Currency</div>', unsafe_allow_html=True)
    st.info(f"**Default currency: {config.BASE_CURRENCY}.** When a supplier's "
            f"document does not state a currency anywhere, their prices are "
            f"assumed to be {config.BASE_CURRENCY} and every affected figure is "
            f"flagged. Confirm before award.")
    chosen = st.date_input(
        "Exchange rate date",
        value=date.fromisoformat(st.session_state["fx_date"]),
        help="The date these rates are taken to hold on. The rates themselves "
             "are fixed on purpose — a comparison has to give the same answer "
             "tomorrow as it does today, or nobody can defend the award. This "
             "date is stamped on every converted price and carried into the "
             "audit export, so it is always clear which day's rate a number "
             "rests on. Set the rate values in your .env file.",
    )
    # st.date_input returns None when the field is emptied, and this runs in
    # the shell -- an exception here takes both pages down, not just the
    # sidebar. An empty date simply means "leave the rate date alone".
    if chosen is not None and chosen.isoformat() != st.session_state["fx_date"]:
        st.session_state["fx_date"] = chosen.isoformat()
        config.FX_DATE = chosen.isoformat()
        if st.session_state["comparison"] is not None:
            # Rebuild from the responses already read: restamping the date must
            # never mean asking the model to read the documents again.
            rebuilt = assemble.build(st.session_state["comparison"].responses)
            st.session_state["comparison"] = rebuilt
            try:
                store.write(rebuilt, path=st.session_state["db_path"])
            except Exception:
                pass  # the screen is still correct; the analyst reconnects later
        st.rerun()

    rate_bits = " · ".join(
        f"{code} {value:g}" for code, value in config.FX_TO_BASE.items()
        if code != config.BASE_CURRENCY)
    st.caption(f"Rates held at {rate_bits} {config.BASE_CURRENCY}, dated "
               f"{config.FX_DATE}.")

    age = (date.today() - chosen).days if chosen is not None else 0
    if age > 30:
        st.warning(f"These rates are dated {age} days ago. Converted prices are "
                   f"still shown, and every one of them carries that date — but "
                   f"confirm the rate before you award anything.")
    elif age < 0:
        st.caption("Dated in the future — a forward or budget rate. That is fine, "
                   "as long as the suppliers know it.")
    if config.OFFLINE_FIXTURES:
        st.warning("Replaying recorded test extractions, not reading live.")

    if st.session_state["comparison"] is not None:
        st.divider()
        st.markdown('<div class="rfx-kicker">Download</div>', unsafe_allow_html=True)
        buffer = io.BytesIO()
        current = st.session_state["comparison"]
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            present.export_frame(current).to_excel(
                writer, sheet_name="Audit trail", index=False)
            present.grid(current, normalized=True)[0].to_excel(
                writer, sheet_name="Comparable")
            present.grid(current, normalized=False)[0].to_excel(
                writer, sheet_name="As quoted")
            present.exceptions_frame(current).to_excel(
                writer, sheet_name="Needs attention", index=False)
            present.questionnaire_frame(current)[0].to_excel(
                writer, sheet_name="Quality")
            present.vendor_frame(current).to_excel(writer, sheet_name="Suppliers")
        st.download_button(
            "Comparison as Excel", buffer.getvalue(),
            file_name="rfx_comparison.xlsx", width="stretch",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help=glossary.tip("audit_trail"))





# ---------------------------------------------------------------------------
# the two pages
#
# Drafting a request and comparing the replies are two jobs done on different
# days, and stacking them on one scroll meant the page opened on work most
# visits did not need. They are two pages with a switcher across the top. The
# session state behind them is shared and unconditional, so a request drafted
# on the first page is already active on the second -- switching costs nothing
# and loses nothing.
# ---------------------------------------------------------------------------
draft_ready = bool(rfxdoc.sendable_lines(st.session_state["draft"]))
compare_ready = st.session_state["comparison"] is not None

pages = [
    st.Page(draft_page.render, title="Draft and send a request", icon=":material/edit_note:",
            url_path="request", default=not compare_ready),
    st.Page(compare_page.render, title="AI-Powered Bid Analysis", icon=":material/table_view:",
            url_path="compare", default=compare_ready),
]

st.navigation(pages, position="top").run()
