"""Page one: draft a request, and send it to suppliers.

Kept as its own page rather than a section on a long scroll. The two halves of
this application are two different jobs done on different days -- writing a
request in the morning, comparing what came back a fortnight later -- and
stacking them made the page open on work most visits do not need. The switcher
at the top holds the whole flow together; the state behind both pages is one
object, so nothing is lost crossing between them.
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from core import (brand, criteria as criteria_module, dispatch,
                  draft as draft_module, examples, glossary, ingest,
                  present, rfxdoc, theme, vendors as vendors_module)
from core import rfx as rfx_module


def render() -> None:
    comparison = st.session_state["comparison"]
    meta: list[tuple[str, str]] = []
    if comparison:
        meta = [(str(len(comparison.summaries)), "suppliers"),
                (str(len({present.describe_format(item.file)
                          for item in comparison.summaries})),
                 "different formats")]
    st.markdown(theme.masthead(
        "Write the request by talking to it — scope, items, questions, "
        "terms — then send it to suppliers.", meta),
                unsafe_allow_html=True)
    # Sits above everything, closed, but loud enough to be found. Both pages
    # use words a category buyer has no reason to already know.
    st.markdown(theme.glossary_panel(
        groups=glossary.DRAFT_GROUPS,
        blurb="What the words on this page mean — basis, suggested lines, "
              "must-have questions, and the quote reference that goes out "
              "with each invitation."),
        unsafe_allow_html=True)



    # ---------------------------------------------------------------------------
    # Nothing on this page is required. A buyer who already has five quotes in
    # hand can go straight to the other page and compare them -- the item list
    # is derived from the replies when no request exists.
    # ---------------------------------------------------------------------------
    draft_spec: rfx_module.RfxSpec = st.session_state["draft"]
    vendor_categories = vendors_module.categories()

    # Resolve the recommendation before anything is drawn, so the tab label
    # counts the suppliers actually ticked rather than lagging a rerun behind
    # its own contents.
    chosen_category = vendors_module.category(draft_spec.vendor_category or "")
    if chosen_category is not None and \
            st.session_state["vendor_category_seen"] != chosen_category.key:
        picked, _ = vendors_module.recommend(chosen_category)
        st.session_state["chosen_vendors"] = {v.name for v in picked}
        st.session_state["vendor_category_seen"] = chosen_category.key
    elif chosen_category is None:
        st.session_state["chosen_vendors"] = set()
        st.session_state["vendor_category_seen"] = None
        # The ticked rows belong to the category that produced them. Left
        # behind, they are the previous category's suppliers wearing this
        # one's label.
        st.session_state["vendor_rows"] = None

    # The assistant half gets its own container so the page reads as two
    # different kinds of thing: a machine you talk to, and a document you
    # fill in. Same information architecture as the request itself --
    # what was said, and what stands.
    with st.container(key="ai_panel"):
        st.markdown(
            theme.eyebrow("01", "Ask for what you need",
                          "talk to the co-pilot, or start from a document"),
            unsafe_allow_html=True)
        st.caption(
            "Talk the request into existence: scope, items, questions, terms. The "
            "co-pilot edits the document below by calling tools — it never "
            "writes a document you then have to re-key. Anything it proposes rather "
            "than hears from you is marked **suggested** and is not sent to a "
            "supplier until you accept it."
        )

        for entry in st.session_state["draft_history"]:
            with st.chat_message("user" if entry["role"] == "user" else "assistant"):
                st.markdown(entry["text"])
                for change in entry.get("changes") or []:
                    st.caption(f"↳ {change}")

        if not st.session_state["draft_history"]:
            st.markdown("**Start from a worked example:**")
            st.caption(
                "These two load a real request from `examples/` — they do not "
                "call the model, so they work with the API down and give a demo "
                "somewhere to begin. Everything you type after that goes to the "
                "co-pilot as normal."
            )

            if st.button("Draft a replenishment request for whatever is below "
                         "its minimum stock level",
                         key="seed_replenishment", width="stretch"):
                result = examples.seed_replenishment(draft_spec)
                st.session_state["draft_history"].append({
                    "role": "model",
                    "text": (
                        f"After going through the existing stock levels, the "
                        f"following items need replenishment.\n\n"
                        f"`{' · '.join(result['skus'])}`\n\n"
                        f"That is **{result['lines']} of your "
                        f"{result['total_available']} items** below their "
                        f"reorder point, with the {result['questions']} "
                        f"standard supplier quality questions added.\n\n"
                        f"**Check the quantities, then accept the lines to send "
                        f"the request.** They are held as *suggested* until you "
                        f"do — the stock figures behind this draft are "
                        f"simulated, because the warehouse connection is not "
                        f"built in this version, and a supplier should never be "
                        f"asked to price something nobody has checked. Accept "
                        f"them on the **Items** tab or in **Send it to "
                        f"suppliers** below.\n\n"
                        f"Tell me what to change and I will edit the draft."),
                    "changes": [f"{result['lines']} items added (suggested)",
                                f"{result['questions']} questions added"],
                })
                st.session_state["spec"] = draft_spec
                st.rerun()

            if st.button("I need to run an RFx for corrugated packaging — the "
                         "full annual list",
                         key="seed_full", width="stretch"):
                result = examples.seed_full_request(draft_spec)
                st.session_state["draft_history"].append({
                    "role": "model",
                    "text": (
                        f"Loaded the **full annual request**: all "
                        f"{result['lines']} items, the "
                        f"{result['questions']} supplier quality questions, and "
                        f"the terms.\n\n"
                        f"I have also added a note telling suppliers that "
                        f"**packaging, palletisation, plates, tooling and any "
                        f"other charge must be quoted as a line with an amount** "
                        f"— not as \"at actuals\" or \"to be advised\". That one "
                        f"instruction is what stops a cheap-looking quote "
                        f"arriving with an invisible tail of charges.\n\n"
                        f"These lines are yours, not suggestions, so they are "
                        f"ready to send."),
                    "changes": [f"{result['lines']} items added",
                                f"{result['questions']} questions added",
                                f"{result['notes']} notes on charges added"],
                })
                st.session_state["spec"] = draft_spec
                st.rerun()

        # An inline box rather than st.chat_input, which pins itself to the very
        # bottom of the window -- a long way from the two buttons it belongs with,
        # and easy to miss entirely. This is the path that actually exercises the
        # co-pilot, so it sits where the eye already is.
        st.markdown("**Or describe the request in your own words**")
        st.caption(
            "This one goes to the co-pilot: it reads what you wrote and builds "
            "the request by calling tools, item by item. Say what you are buying, "
            "roughly how many, where it is delivered and by when — and anything "
            "you want suppliers asked."
        )
        own_words = st.text_area(
            "Your request", height=110, key="draft_free_text",
            label_visibility="collapsed",
            placeholder="e.g. I need 12 lines of 5-ply export cartons for a new "
                        "line, about 4,000 each a year, delivered to Bengaluru, "
                        "quotes back within a fortnight. Ask them about ISO 9001 "
                        "and their on-time delivery.")
        if st.button("Generate the RFQ from this", type="primary", width="stretch",
                     disabled=not own_words.strip(), key="draft_free_go"):
            st.session_state["draft_pending"] = own_words.strip()
            st.rerun()

        pending = st.session_state.pop("draft_pending", None)
        if pending:
            st.session_state["draft_open"] = True
            history = [{"role": e["role"], "text": e["text"]}
                       for e in st.session_state["draft_history"]]
            with st.spinner("Drafting…"):
                turn = draft_module.converse(pending, draft_spec, history=history)
            st.session_state["draft_history"].append(
                {"role": "user", "text": pending, "changes": []})
            # The co-pilot's own words first, then a receipt counted off the
            # request itself. A buyer who has just typed a paragraph and
            # watched a spinner needs to see what they got, in a form they can
            # check against the document below -- not only the model's account
            # of what it believes it did.
            if turn.error:
                body = turn.answer
            else:
                body = (turn.answer.strip() + "\n\n---\n\n"
                        + present.draft_receipt(draft_spec, turn.changes))
            st.session_state["draft_history"].append(
                {"role": "model", "text": body, "changes": []})
            st.session_state["spec"] = draft_spec
            st.rerun()

        st.markdown("**Or start from a document you already have**")
        st.caption(
            "A purchase order, a bill of materials, last year's contract. The "
            "items are read out of it by the model — real extraction, nothing "
            "seeded — and the questions, terms and charge instructions are "
            "filled in from your standing template, so what you get is a "
            "request, not just a list. There is a sample PO from last year in "
            "`examples/` if you want to try it."
        )
        attached = st.file_uploader(
            "Attach a purchase order, BOM or price list",
            type=ingest.SUPPORTED_UPLOAD_TYPES, key="draft_attachment",
            help="Reading your real list always beats the co-pilot proposing "
                 "one. Items read from your own document are marked as yours, "
                 "not as suggestions.")
        if attached is not None and st.button("Build a request from this document",
                                              type="primary",
                                              width="stretch"):
            with st.spinner(f"Reading {attached.name}…"):
                try:
                    payload = ingest.load(io.BytesIO(attached.getvalue()), attached.name)
                    result = draft_module.lines_from_document(payload.text, draft_spec)
                    if result["added"]:
                        rest = examples.complete_from_document(draft_spec)
                        st.session_state["draft_history"].append({
                            "role": "model",
                            "text": (
                                f"Read **{result['added']} items** out of "
                                f"`{attached.name}` — those are yours, not "
                                f"suggestions.\n\nI have added your standard "
                                f"**{rest['questions']} quality questions** and "
                                f"the terms, including the note that every "
                                f"charge must be quoted with an amount rather "
                                f"than \"at actuals\".\n\nCheck the quantities: "
                                f"a purchase order tells you what you bought "
                                f"last time, not what you need next year."),
                            "changes": [f"{result['added']} items read from the document",
                                        f"{rest['questions']} questions added",
                                        f"{rest['terms']} terms added"],
                        })
                    else:
                        st.session_state["draft_history"].append({
                            "role": "model",
                            "text": (f"I read `{attached.name}` but found no item "
                                     f"list in it. Nothing was added — a document "
                                     f"with no items is better reported than "
                                     f"padded out with guesses."),
                            "changes": [],
                        })
                    st.session_state["spec"] = draft_spec
                    st.rerun()
                except Exception as exc:
                    st.error(
                        f"Could not read that document: {exc}\n\n"
                        f"Reading a file needs the model. The two example "
                        f"buttons above do not, if you need a draft right now.")


        # The draft sits BELOW the conversation rather than beside it. Side by
        # side, seven tabs and a thirty-row table were squeezed into half the
        # window while the chat column sat mostly empty -- and the draft is the
        # thing being built, so it gets the full width and the reading order
        # follows the work: ask for it, then look at what you have.
        # The document is ALWAYS on screen, empty or not. Hiding it until the
        # co-pilot had produced something made the assistant look compulsory,
        # and a buyer who would rather type thirty lines themselves -- which on
        # a category they know is genuinely faster -- had nowhere to type them.

    # One keyed container so the whole document can be styled as a
    # document: see .st-key-rfq_doc in core/theme.py.
    with st.container(key="rfq_doc"):
        st.markdown(theme.eyebrow("02", "RFQ Document",
                                  "scope · items · questions · notes · files · terms"),
                    unsafe_allow_html=True)

        st.markdown(theme.draft_head(draft_spec), unsafe_allow_html=True)

        # Everything below is editable by hand. The co-pilot is a faster way to
        # write a request, not the only way -- a buyer who knows their category
        # will always be quicker correcting a quantity in a table than
        # describing the correction in a sentence, and being unable to reach
        # the model must never mean being unable to change your own request.
        if draft_spec.lines or draft_spec.title:
            st.caption(
                "**Everything here is editable.** Type into any cell, add a row "
                "at the bottom, or tick a row and press delete. Your edits and "
                "the co-pilot write to the same request, so you can switch "
                "between them freely.")
        else:
            st.caption(
                "**This is the request, and it is empty. Fill it in here.** "
                "Give it a title and dates on this tab, type your items on "
                "**Items**, your questions on **Questions** — nothing above "
                "needs to happen first. The co-pilot is a faster way to write "
                "the same document, not a gate in front of it.")

        # Suppliers live inside Scope, under the vendor category that decides
        # them, rather than in a tab of their own. Who you ask follows from what
        # you are buying, and a tab hides that dependency behind a click.
        details, items, questions, notes_tab, files_tab, terms_tab = st.tabs(
            [f"Scope and suppliers ({len(st.session_state['chosen_vendors'])})",
             f"Items ({len(draft_spec.lines)})",
             f"Questions ({len(draft_spec.criteria)})",
             "Notes", f"Files ({len(draft_spec.attachments)})",
             f"Terms ({len(draft_spec.terms)})"])

        with details:
            st.caption(
                "Fields marked **\\***  are required before the request can go "
                "out. Everything else can wait.")
            with st.form("draft_scope", border=False):
                title = st.text_input("Title", value=draft_spec.title,
                                      placeholder="Corrugated packaging — annual rate contract")
                reference = st.text_input("Your reference", value=draft_spec.reference,
                                          placeholder="RFX/CORR/2026-0830")
                scope_text = st.text_area(
                    "Scope", value=draft_spec.scope, height=80,
                    help="One or two sentences telling a supplier what this is for.")
                columns = st.columns(2)
                currencies = ["INR", "USD", "EUR", "GBP"]
                current = (draft_spec.currency if draft_spec.currency in currencies
                           else currencies[0])
                currency = columns[0].selectbox(
                    "Suppliers must quote in", currencies,
                    index=currencies.index(current),
                    help="Anyone quoting in something else is converted, with "
                         "the rate and its date printed beside the number.")
                # One field per end of the window, each with its clock. The
                # free-text "responses due" that used to sit here said the
                # same thing in a form nothing could check, and two ways of
                # stating a deadline is one way too many.
                # Left empty until a person fills them in, rather than
                # pre-filled with today at nine. A default date is a date
                # nobody chose, and it is indistinguishable on screen from one
                # somebody did -- which is precisely what a mandatory field is
                # supposed to prevent.
                opening = st.columns(2)
                # Read defensively. These strings can come from the co-pilot,
                # and a model that writes "9 Sep 2026, 09:00" instead of an ISO
                # timestamp must not take the whole page down -- the form that
                # would fix the field is on the page it just broke.
                def _moment(value):
                    try:
                        return datetime.fromisoformat(value) if value else None
                    except ValueError:
                        return None

                start_default = _moment(draft_spec.starts_at)
                end_default = _moment(draft_spec.ends_at)
                if (draft_spec.starts_at and start_default is None) or \
                        (draft_spec.ends_at and end_default is None):
                    st.warning(
                        "The request's dates were not saved in a form we can "
                        "read, so the fields below are blank. Set them again "
                        "and save.")
                start_date = opening[0].date_input(
                    "RFQ start date \\*",
                    value=start_default.date() if start_default else None,
                    help=glossary.tip("rfx_window"))
                start_time = opening[1].time_input(
                    "RFQ start time \\*",
                    value=start_default.time() if start_default else None,
                    step=1800)

                closing = st.columns(2)
                end_date = closing[0].date_input(
                    "RFQ end date \\*",
                    value=end_default.date() if end_default else None,
                    help=glossary.tip("rfx_window"))
                end_time = closing[1].time_input(
                    "RFQ end time \\*",
                    value=end_default.time() if end_default else None, step=1800,
                    help="A date with no time is read as midnight by the "
                         "supplier and as start of business by the buyer. "
                         "Somebody loses a bid to that gap every year.")

                category_names = ["—"] + [c.name for c in vendor_categories]
                current_category = (draft_spec.vendor_category
                                    if draft_spec.vendor_category in category_names
                                    else "—")
                picked_category = st.selectbox(
                    "Vendor category \\*", category_names,
                    index=category_names.index(current_category),
                    help=glossary.tip("vendor_category"))

                where = st.text_input("Deliver to", value=draft_spec.delivery_location,
                                      placeholder=brand.ADDRESS)
                if st.form_submit_button("Save scope", width="stretch"):
                    # Checked before anything is written. A half-saved scope
                    # that reports itself as saved is worse than a refusal,
                    # because the gap then has to be noticed twice.
                    blocking = []
                    if not (start_date and start_time):
                        blocking.append("**RFQ start date and time**")
                    if not (end_date and end_time):
                        blocking.append("**RFQ end date and time**")
                    if picked_category == "—":
                        blocking.append("**Vendor category**")

                    if blocking:
                        st.error(
                            "Not saved — " + ", ".join(blocking)
                            + (" is" if len(blocking) == 1 else " are")
                            + " required. A request with no closing time cannot "
                              "be chased or closed, and without a category "
                              "there is no approved supplier list to draw on.")
                    else:
                        draft_spec.title = title.strip()
                        draft_spec.reference = reference.strip()
                        draft_spec.scope = scope_text.strip()
                        draft_spec.currency = currency
                        draft_spec.currency_inferred = False
                        draft_spec.delivery_location = where.strip()
                        draft_spec.starts_at = datetime.combine(
                            start_date, start_time).isoformat(timespec="minutes")
                        draft_spec.ends_at = datetime.combine(
                            end_date, end_time).isoformat(timespec="minutes")
                        draft_spec.vendor_category = (
                            "" if picked_category == "—" else picked_category)
                        draft_spec.derived = False
                        st.session_state["spec"] = draft_spec
                        st.rerun()

            outstanding_scope = rfx_module.missing_scope(draft_spec)
            if outstanding_scope:
                st.warning(
                    "**Still to fill in: " + ", ".join(outstanding_scope)
                    + ".** The request cannot be sent until "
                    + ("this is" if len(outstanding_scope) == 1 else "these are")
                    + " set.")

            span = draft_spec.window_days
            if span is not None:
                st.caption(
                    f"**{draft_spec.stamp(draft_spec.starts_at)}** → "
                    f"**{draft_spec.stamp(draft_spec.ends_at)}**")
                if span < 0:
                    st.error("The request closes before it opens. Suppliers "
                             "will read that as a mistake, and they will be right.")
                elif span < 5:
                    st.warning(
                        f"**{span} day{'' if span == 1 else 's'} to quote.** "
                        f"Thirty items priced properly is a day's work for an "
                        f"estimator. A window this short gets you fast prices "
                        f"rather than keen ones, and the suppliers who take "
                        f"most care are the likeliest to decline.")
                else:
                    st.caption(f"Suppliers have **{span} days** to respond.")

            st.divider()
            st.markdown(
                f"**Who this goes to**{theme.help_icon('recommended_vendors')} — "
                f"the approved list for "
                f"{(draft_spec.vendor_category or 'a category you have not set yet').lower()}, "
                f"rated out of ten{theme.help_icon('vendor_rating')}.",
                unsafe_allow_html=True)

            if chosen_category is None:
                st.info("Choose a **vendor category** above and the approved "
                        "suppliers for it appear here, rated, with the ones "
                        "worth asking already ticked.")
            else:
                st.caption(chosen_category.covers)
                _, reason = vendors_module.recommend(chosen_category)
                st.info(reason)
                directory = present.directory_frame(
                    chosen_category, st.session_state["chosen_vendors"])
                edited_vendors = st.data_editor(
                    directory, width="stretch", hide_index=True, height=250,
                    num_rows="dynamic", key="draft_vendor_editor",
                    column_config={
                        "Ask": st.column_config.CheckboxColumn(
                            width="small",
                            help="Tick to invite. Untick to leave them out — "
                                 "your call, not the rating's."),
                        "Supplier": st.column_config.TextColumn(width="medium"),
                        "Rating": st.column_config.NumberColumn(
                            format="%.1f", disabled=True, width="small",
                            help=glossary.tip("vendor_rating")),
                        "Quality": st.column_config.NumberColumn(
                            format="%.1f", width="small", min_value=0.0,
                            max_value=10.0),
                        "Delivery": st.column_config.NumberColumn(
                            format="%.1f", width="small", min_value=0.0,
                            max_value=10.0),
                        "Commercial": st.column_config.NumberColumn(
                            format="%.1f", width="small", min_value=0.0,
                            max_value=10.0),
                        "Responsiveness": st.column_config.NumberColumn(
                            format="%.1f", width="small", min_value=0.0,
                            max_value=10.0),
                        "Why": st.column_config.TextColumn(width="large"),
                    },
                )
                ticked = {str(row["Supplier"]).strip()
                          for _, row in edited_vendors.iterrows()
                          if bool(row.get("Ask")) and str(row.get("Supplier") or "").strip()}
                if ticked != st.session_state["chosen_vendors"]:
                    st.session_state["chosen_vendors"] = ticked
                    st.rerun()

                st.session_state["vendor_rows"] = edited_vendors
                # One is the hard floor -- a request addressed to nobody is a
                # document, not a request -- but two is the number that makes
                # the exercise worth running, so both are said, differently.
                if not ticked:
                    st.error(
                        "**At least one supplier is required.** Tick the ones "
                        "you want to ask, or add a supplier who is not on the "
                        "approved list in the send section below.")
                elif len(ticked) < 2:
                    st.warning(
                        "Fewer than two suppliers selected. A request to one "
                        "supplier is a purchase order with extra steps — you "
                        "will have no way of knowing whether the price is any "
                        "good.")


        with items:
            if draft_spec.lines:
                frame = present.draft_lines_frame(draft_spec)
                edited = st.data_editor(
                    frame, width="stretch", hide_index=True, height=300,
                    num_rows="dynamic", key="draft_lines_editor",
                    column_config={
                        "Item": st.column_config.TextColumn(width="small"),
                        "Description": st.column_config.TextColumn(width="large"),
                        "Quantity": st.column_config.NumberColumn(format="%d"),
                        "Price per": st.column_config.TextColumn(
                            width="small",
                            help="What one price covers: box, sheet, roll, kg, "
                                 "unit. Getting this wrong is the single most "
                                 "common way a comparison goes wrong."),
                    },
                )
                # Rerun on what changed in the request, never on how the
                # table differs from it -- see apply_draft_edits.
                if present.apply_draft_edits(draft_spec, edited):
                    st.session_state["spec"] = draft_spec
                    st.rerun()

                pending_suggestions = draft_spec.suggested_lines
                if pending_suggestions:
                    st.warning(
                        f"**{len(pending_suggestions)} of these items were "
                        f"proposed for you, not stated by you.** They are held "
                        f"out of the request document until you accept them — a "
                        f"supplier should never be asked to price something "
                        f"nobody decided to buy.\n\n"
                        f"These came from the co-pilot's own knowledge of the "
                        f"category, because **the warehouse system is not "
                        f"connected in this build**. Connected, this list would "
                        f"be the items actually below their minimum stock "
                        f"level, with the shortfall as the quantity.")
                    accept, drop = st.columns(2)
                    if accept.button("Accept all suggestions",
                                     width="stretch"):
                        present.accept_suggestions(draft_spec)
                        st.rerun()
                    if drop.button("Remove all suggestions",
                                   width="stretch"):
                        present.drop_suggestions(draft_spec)
                        st.rerun()
            else:
                st.info("No items yet. Use one of the buttons above, attach a "
                        "document, tell the co-pilot what you are buying — or "
                        "just type the first row in below.")
                blank = pd.DataFrame([{"Item": "", "Description": "",
                                       "Quantity": None, "Price per": "box"}])
                typed = st.data_editor(blank, width="stretch",
                                       hide_index=True, num_rows="dynamic",
                                       key="draft_lines_blank")
                if st.button("Add these items", width="stretch",
                             disabled=not any(str(v).strip()
                                              for v in typed["Description"])):
                    present.apply_draft_edits(draft_spec, typed)
                    st.session_state["spec"] = draft_spec
                    st.rerun()

            st.markdown(theme.sources_note(), unsafe_allow_html=True)

        with questions:
            st.caption(
                "What suppliers must confirm. **Type your questions straight "
                "into the table** — one per row, and a new row appears at the "
                "bottom as you fill the last one. A **target** with a direction "
                "is scored against the figure they give; leave it blank for a "
                "yes/no question. **Must have** removes anyone who fails it "
                "from the recommendation — nothing is a must-have by default.")
            criteria_frame = present.draft_criteria_frame(draft_spec)
            edited_criteria = st.data_editor(
                criteria_frame, width="stretch", hide_index=True,
                num_rows="dynamic", height=260, key="draft_criteria_editor",
                column_config={
                    "S. No.": st.column_config.NumberColumn(
                        format="%d", disabled=True, width="small",
                        help="Renumbered from the row order every time this "
                             "table is drawn, so deleting a question closes "
                             "the gap instead of leaving one."),
                    "Question": st.column_config.TextColumn(
                        width="large", required=True,
                        help="Required. Every row needs the question a supplier "
                             "will actually read; a target on its own tests "
                             "nothing."),
                    "Target": st.column_config.NumberColumn(
                        help="The number they must meet. Blank for yes/no."),
                    "Unit": st.column_config.TextColumn(
                        width="small", help="e.g. %, days, units/month"),
                    "Direction": st.column_config.SelectboxColumn(
                        options=list(present.DIRECTION_WORDS), width="small"),
                    "Requirement": st.column_config.SelectboxColumn(
                        options=list(criteria_module.REQUIREMENT_LEVELS),
                        width="medium", help=glossary.tip("must_have")),
                    "Weight": st.column_config.NumberColumn(
                        min_value=0.0, step=0.5, width="small",
                        help="Relative importance in the quality score."),
                },
            )
            stray = present.blank_questions(edited_criteria)
            if stray:
                st.warning(
                    f"**{stray} row{'' if stray == 1 else 's'} carr"
                    f"{'ies' if stray == 1 else 'y'} a target but no question.** "
                    f"A threshold with nothing to test is not a half-finished "
                    f"criterion — type the question a supplier will read, or "
                    f"delete the row. Nothing blank is kept.")

            # Applied every run, and rerun only when the request actually
            # changed. Comparing the edited table against the drawn table
            # instead is the obvious test and the wrong one: the edits are
            # normalised on the way in, so a weight of 0 or a target typed on a
            # row with no question leaves a frame that differs from the one we
            # drew while the request is unchanged -- and rerunning on that
            # redraws the same frame, replays the same edit, forever.
            if present.apply_criteria_edits(draft_spec, edited_criteria):
                st.session_state["spec"] = draft_spec
                st.rerun()

        with notes_tab:
            st.markdown(f"**Notes to suppliers**{theme.help_icon('issuer_notes')}",
                        unsafe_allow_html=True)
            note_text = st.text_area(
                "Notes", value=draft_spec.notes, height=200,
                label_visibility="collapsed",
                placeholder="Anything that is not an item, a question or a "
                            "term. A plant shutdown, a specification change "
                            "coming, how you want the quote laid out, who to "
                            "contact with questions.")
            if st.button("Save notes", width="stretch", key="save_notes"):
                draft_spec.notes = note_text.strip()
                st.session_state["spec"] = draft_spec
                st.rerun()
            st.caption("Sent verbatim, printed on the request under **Notes "
                       "from the buyer**.")

        with files_tab:
            st.markdown(
                f"**Supporting files**{theme.help_icon('attachments_out')}",
                unsafe_allow_html=True)
            new_files = st.file_uploader(
                "Attach drawings, specifications, a delivery schedule",
                accept_multiple_files=True, key="draft_attachment_files",
                help="They ride along on every invitation and are listed on "
                     "the request itself, so a supplier can tell whether they "
                     "received everything.")
            if new_files and st.button("Attach these files", width="stretch"):
                have = {item["name"] for item in draft_spec.attachments}
                added = 0
                for upload in new_files:
                    if upload.name in have:
                        continue
                    draft_spec.attachments.append({
                        "name": upload.name,
                        "data": upload.getvalue(),
                        "size": len(upload.getvalue()),
                        "note": "",
                    })
                    added += 1
                st.session_state["spec"] = draft_spec
                st.toast(f"Attached {added} file{'' if added == 1 else 's'}.")
                st.rerun()

            if draft_spec.attachments:
                files_frame = present.attachment_frame(draft_spec)
                edited_files = st.data_editor(
                    files_frame, width="stretch", hide_index=True,
                    num_rows="dynamic", key="draft_files_editor",
                    column_config={
                        "File": st.column_config.TextColumn(
                            disabled=True, width="medium"),
                        "What it is": st.column_config.TextColumn(
                            width="large",
                            help="Printed beside the filename on the request. "
                                 "A drawing named for the item it belongs to beats "
                                 "'attachment 3'."),
                        "Size": st.column_config.TextColumn(
                            disabled=True, width="small"),
                    },
                )
                if present.apply_attachment_edits(draft_spec, edited_files):
                    st.session_state["spec"] = draft_spec
                    st.rerun()
            else:
                st.caption("Nothing attached. The request stands on its own — "
                           "attach a drawing or a specification if an item "
                           "cannot be priced from its description alone.")

        with terms_tab:
            st.markdown(f"**Terms**{theme.help_icon('terms')}",
                        unsafe_allow_html=True)
            st.caption(
                "The commercial terms and any instruction about how to quote — "
                "**one to a line, written as `Payment: 45 days from invoice`**. "
                "The label before the colon is what the request document prints "
                "in its Terms column; a line with no label is kept as written. "
                "The **charges** line is the one that stops a cheap-looking "
                "quote arriving with an invisible tail of extras.")
            # Deliberately unkeyed. A keyed text area identifies itself by its
            # key alone, so it keeps showing whatever was last typed into it
            # and ignores the `value` -- which would mean a term the co-pilot
            # added never appeared in the box, and was then wiped by the next
            # save. Without a key the value is part of the widget's identity,
            # so the box follows the request. The Notes box works the same way.
            terms_text = st.text_area(
                "Terms", value=present.draft_terms_text(draft_spec), height=240,
                label_visibility="collapsed",
                placeholder="Payment: 45 days from receipt of invoice\n"
                            "Delivery: DDP Bengaluru, freight included in the "
                            "unit rate\n"
                            "Validity: Quoted rates to remain firm for 90 days\n"
                            "Charges: Packaging, palletisation, plates and "
                            "tooling must each be quoted as a line with an "
                            "amount — not \"at actuals\" or \"to be advised\"")
            if st.button("Save terms", width="stretch", key="save_terms"):
                present.apply_terms_text(draft_spec, terms_text)
                st.session_state["spec"] = draft_spec
                st.rerun()
            st.caption(
                f"{len(draft_spec.terms)} term"
                f"{'' if len(draft_spec.terms) == 1 else 's'} saved, printed on "
                f"the request under **Terms**.")

        # --- sending it ------------------------------------------------------
        sendable = rfxdoc.sendable_lines(draft_spec)

    st.markdown(theme.eyebrow("03", "Send it to suppliers",
                              "the transport is stubbed; the artefact is not"),
                unsafe_allow_html=True)

    if not rfxdoc.pdf_available():
        st.warning(rfxdoc.PDF_HINT)
    elif not sendable:
        # There are two quite different reasons nothing can be sent, and they
        # need different words. An empty request needs items. A request whose
        # items are all still suggestions needs one decision -- and the old
        # one-line caption gave no hint that the decision existed, or where to
        # make it, so the page read as though half of it were missing.
        pending = draft_spec.suggested_lines
        if pending:
            st.warning(
                f"**Nothing can be sent yet: all {len(pending)} items are still "
                f"marked *suggested*.**\n\n"
                f"They were proposed for you rather than stated by you — the "
                f"stock figures behind this draft are simulated, because the "
                f"warehouse connection is not built in this version. A supplier "
                f"should never be asked to price something nobody has checked, "
                f"so the request document leaves them out until you accept "
                f"them.\n\n"
                f"Check the list and the quantities on the **Items** tab, then "
                f"accept them here or there. The preview and the send button "
                f"appear as soon as you do.")
            accept_here, edit_first = st.columns([1, 1])
            if accept_here.button(
                    f"Accept all {len(pending)} items and continue",
                    type="primary", width="stretch", key="accept_from_send"):
                present.accept_suggestions(draft_spec)
                st.session_state["spec"] = draft_spec
                st.rerun()
            edit_first.caption(
                "Or open **Items** above to change a quantity or delete a line "
                "before accepting.")
        else:
            st.caption("Add at least one item you have accepted, then invite "
                       "suppliers.")
    elif sendable:
        st.caption(
            "The mail server is stubbed — every invitation is written to the "
            "`outbox` folder as a real .eml file you can open, with the request "
            "PDF attached. Each carries a quote reference unique to that "
            "supplier, so when their reply comes back we know who sent it and "
            "which version they answered, instead of guessing from a letterhead."
        )
        chosen = st.session_state["chosen_vendors"]
        rows = st.session_state.get("vendor_rows")
        vendors = (present.selected_vendors(rows) if rows is not None
                   else present.parse_vendor_list(st.session_state["invite_text"]))

        if chosen:
            st.markdown(
                '<div class="rfx-legend" style="margin:.2rem 0 .6rem">'
                + "".join(theme.chip(v.name, "ok") for v in vendors)
                + "</div>", unsafe_allow_html=True)
            st.caption("Chosen on the **Suppliers** tab. Change who is asked "
                       "there, or add anyone not on the approved list below.")
        else:
            st.caption("Pick suppliers on the **Suppliers** tab, or type them "
                       "in below.")

        extra_text = st.text_area(
            "Anyone else — one per line, `Name <email>`",
            value=st.session_state["invite_text"], height=80, key="invite_box",
            placeholder="A supplier not on the approved list yet",
            help="Approved suppliers come from the directory with a rating "
                 "behind them. Anyone added here has neither, which is worth "
                 "knowing before you compare their quote against the rest.")
        st.session_state["invite_text"] = extra_text
        known = {v.name for v in vendors}
        vendors = vendors + [v for v in present.parse_vendor_list(extra_text)
                             if v.name not in known]

        if draft_spec.attachments:
            st.caption(f"{len(draft_spec.attachments)} supporting "
                       f"file{'' if len(draft_spec.attachments) == 1 else 's'} "
                       f"will be attached to every invitation.")

        # The same rule the scope form enforces, applied once more at the last
        # possible moment -- the supplier count is not knowable inside that
        # form, and a request can lose its only supplier after the scope was
        # saved. What is outstanding is named, so the button being dead is
        # never a mystery.
        outstanding = rfx_module.missing_mandatory(draft_spec, len(vendors))
        if outstanding:
            st.error(
                "**Cannot send yet — " + ", ".join(outstanding) + ".** "
                + ("Set it on the **Scope and suppliers** tab."
                   if len(outstanding) == 1
                   else "Set them on the **Scope and suppliers** tab."))

        preview, send = st.columns([1, 1])
        with preview:
            st.download_button(
                "Preview the request document",
                data=rfxdoc.build_pdf(draft_spec),
                file_name=f"{(draft_spec.reference or 'request').replace('/', '_')}.pdf",
                mime="application/pdf", width="stretch",
                help="Generates the exact PDF copy a supplier will see, so you "
                     "can read your request the way they will.")
        with send:
            if st.button(f"Send to {len(vendors)} supplier"
                         f"{'' if len(vendors) == 1 else 's'}",
                         type="primary", disabled=bool(outstanding),
                         width="stretch",
                         help=("Blocked: " + ", ".join(outstanding))
                              if outstanding else None):
                with st.spinner("Writing invitations…"):
                    invitations = dispatch.send_request(draft_spec, vendors)
                st.session_state["invitations"] = invitations
                draft_spec.invited = vendors
                st.session_state["spec"] = draft_spec
                rfx_module.set_active(draft_spec)
                st.rerun()

    if st.session_state["invitations"]:
        st.dataframe(present.invitation_frame(st.session_state["invitations"]),
                     width="stretch", hide_index=True,
                     column_config={
                         "Quote reference": st.column_config.Column(
                             help="Carried in the subject line, the covering "
                                  "note and the request document. When a reply "
                                  "quotes it, that supplier is identified "
                                  "rather than guessed."),
                     })
        st.success(
            "**Invitations written.** When the replies come in, switch to "
            "**AI-Powered Bid Analysis** at the top of the page and drop them in. "
            "They will be compared against this request, and any reply quoting "
            "its reference identifies its supplier automatically.")

        waiting = [i for i in st.session_state["invitations"] if not i.responded]
        if waiting:
            with st.expander(f"Chase the {len(waiting)} who have not replied"):
                for invitation in waiting:
                    st.code(dispatch.chase_note(draft_spec, invitation),
                            language=None, wrap_lines=True)

