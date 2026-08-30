"""Page two: read the responses and interrogate them.

Everything from intake through the recommended award. This is the half a buyer
returns to, so it is where the app opens once a comparison exists.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from core import (analyst, assemble, award, criteria as criteria_module,
                  glossary, ingest, pipeline, present, rfxdoc, store, theme)
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
        "Suppliers respond however they choose. Every response is read, "
        "normalised and scored into one comparison you can interrogate in "
        "plain language and defend line by line.", meta),
                unsafe_allow_html=True)
    # Sits above everything, closed, but loud enough to be found. Both pages
    # use words a category buyer has no reason to already know.
    st.markdown(theme.glossary_panel(), unsafe_allow_html=True)

    # ---------------------------------------------------------------------------
    # 1 · intake
    # ---------------------------------------------------------------------------
    st.markdown(theme.eyebrow("01", "Supplier responses",
                              "spreadsheet · pdf · word · email · photo"),
                unsafe_allow_html=True)

    if rfx_module.active().is_drafted and rfx_module.active().lines:
        st.success(
            f"**Responses will be compared against the request you drafted** — "
            f"{len(rfxdoc.sendable_lines(rfx_module.active()))} items, priced in "
            f"{rfx_module.active().currency}. A supplier who skips an item will "
            f"show as not having priced it, rather than the item quietly "
            f"disappearing from the comparison.")

    uploads = st.file_uploader(
        "Drop whatever the suppliers sent",
        type=ingest.SUPPORTED_UPLOAD_TYPES,
        accept_multiple_files=True,
        help="Any format a supplier might reply in: a spreadsheet, a PDF, a Word "
             "document, an email saved as text, or a photo of a printed rate card. "
             "You do not need to tidy them up first. Two responses are enough to "
             "build a comparison.",
    )

    if uploads:
        st.markdown(
            '<div class="rfx-legend" style="margin:.5rem 0 .2rem">'
            + "".join(theme.chip(present.describe_format(f.name), "mute") for f in uploads)
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("Five example responses to this request — a spreadsheet, a "
                   "PDF on letterhead, a Word quotation, a saved email with its "
                   "attachment, and a phone photo of a rate card — are in the "
                   "project's `sample_data` folder if you want something to try.")

    if st.button("Analyse responses", type="primary", disabled=not uploads,
                 help=None if uploads else "Add at least one supplier response above."):
        files = [(io.BytesIO(f.getvalue()), f.name) for f in uploads]

        status = st.status("Reading supplier documents…", expanded=True)

        def _progress(index: int, total: int, filename: str) -> None:
            if filename:
                status.write(f"**{index + 1}/{total}** · {filename}")

        # If the buyer drafted and sent a request, responses are compared against
        # THAT -- not against a spine reverse-engineered from the replies, which
        # would let an item nobody quoted vanish from the comparison entirely.
        drafted = st.session_state["draft"]
        use_drafted = bool(rfxdoc.sendable_lines(drafted))
        if use_drafted:
            rfx_module.set_active(drafted)

        result = pipeline.run(files, db_path=st.session_state["db_path"],
                              progress=_progress,
                              build_spine=not use_drafted,
                              invitations=st.session_state["invitations"] or None)

        for outcome in result.outcomes:
            if outcome.ok and outcome.supporting:
                status.write(f"📎 **{outcome.filename}** — read, but it contains no "
                             f"prices. Treated as a supporting document.")
            elif outcome.ok:
                status.write(f"✓ **{outcome.vendor}** — {outcome.lines_found} lines "
                             f"(read via {outcome.reader})")
                for warning in outcome.warnings:
                    status.write(f"   ↳ {warning}")
            else:
                status.write(f"✗ **{outcome.filename}** — {outcome.error}")

        if result.comparison is None:
            status.update(label="Nothing could be extracted.", state="error")
        else:
            label = f"Read {result.ok_count} of {len(result.outcomes)} documents."
            if result.supporting:
                label += f" {len(result.supporting)} had no prices in them."
            status.update(label=label, state="complete", expanded=False)
            st.session_state["run"] = result
            st.session_state["comparison"] = result.comparison
            st.session_state["spec"] = rfx_module.active()
            st.session_state["criteria_settings"] = {}
            st.session_state["history"] = []
            st.rerun()

    comparison = st.session_state["comparison"]

    if comparison is None:
        if rfx_module.active().is_drafted and rfx_module.active().lines:
            st.info("Add the replies to your request above, then press "
                    "**Analyse responses**. They will be compared against the "
                    "request you drafted, so an item nobody quoted still shows "
                    "as a gap rather than disappearing.")
        else:
            st.info("Add supplier responses above, then press **Analyse "
                    "responses**. Two are enough. No request is needed — the "
                    "item list is built from the replies themselves. If you "
                    "would rather start by writing one, **Draft and send a "
                    "request** is at the top of the page.")
        st.stop()


    # ---------------------------------------------------------------------------
    # 2 · the state of play
    # ---------------------------------------------------------------------------
    all_winners = present.cheapest_by_line(comparison)

    st.markdown(theme.eyebrow("02", "Where things stand"), unsafe_allow_html=True)
    st.markdown(theme.stats(present.headline_stats(comparison, all_winners)),
                unsafe_allow_html=True)

    warnings = assemble.comparability_warnings(comparison)
    if warnings:
        st.markdown("".join(theme.advisory(text) for text in warnings),
                    unsafe_allow_html=True)

    st.markdown(theme.supplier_cards(present.supplier_card_data(comparison)),
                unsafe_allow_html=True)


    # ---------------------------------------------------------------------------
    # 3 · the comparison
    # ---------------------------------------------------------------------------
    st.markdown(theme.eyebrow("03", "Line by line",
                              "click any row to see what each supplier wrote"),
                unsafe_allow_html=True)

    controls = st.columns([2.2, 2.4, 3])
    with controls[0]:
        view = st.radio("View", ["Prices made comparable", "Exactly as the supplier wrote it"],
                        label_visibility="collapsed",
                        help=f"**Prices made comparable** — {glossary.tip('made_comparable')}"
                             f"\n\n**Exactly as the supplier wrote it** — "
                             f"{glossary.tip('as_quoted')}")
    normalized = view.startswith("Prices made")

    with controls[1]:
        shown_vendors = st.multiselect(
            "Suppliers to show", comparison.vendors, default=comparison.vendors,
            help="The grid shows everyone by default. Shortlisting for the award "
                 "happens further down, where you can see what it costs.")
        show_confidence = st.checkbox("Show how clearly we read each number",
                                      value=True,
                                      help=glossary.tip("read_clarity"))

    with controls[2]:
        st.markdown(theme.legend(), unsafe_allow_html=True)

    eligible = [v for v in comparison.vendors if v in (shown_vendors or comparison.vendors)]

    winners = present.cheapest_by_line(comparison, eligible)
    display, statuses = present.grid(comparison, normalized=normalized,
                                     show_confidence=show_confidence)

    hidden = [v for v in comparison.vendors if v not in eligible]
    if hidden:
        display = display.drop(columns=hidden)
        statuses = statuses.drop(columns=hidden)
        st.caption(f"Hidden: {', '.join(hidden)}.")

    present.mark_winners(display, winners)
    present.add_winner_column(display, statuses, comparison, winners, eligible)

    selection = st.dataframe(
        present.style_grid(display, statuses, winners),
        width="stretch", height=600,
        on_select="rerun", selection_mode="single-row", key="comparison_grid",
        column_config={
            "Line": st.column_config.Column(help=glossary.tip("line_item")),
            "Description": st.column_config.Column(
                width="large", help="The item as your request described it."),
            "Qty": st.column_config.Column(
                help="How many of this item your request asked to be priced."),
            "Unit": st.column_config.Column(help=glossary.tip("basis")),
            present.WINNER_COLUMN: st.column_config.Column(
                width="medium",
                help="The cheapest supplier on this item, and how far ahead of the "
                     "next best they are — a win of a few paise is not the same "
                     "fact as a win of a few rupees. Counted only across prices we "
                     "could make comparable, and only across the suppliers shown."),
            **{vendor: st.column_config.Column(
                width="medium",
                help=f"{vendor}'s price for each line, restated on your unit and "
                     f"currency where that was needed. Click any row to see their "
                     f"original wording. {glossary.tip('comparable')}")
               for vendor in display.columns if vendor in comparison.vendors},
        },
    )

    review_reasons = present.review_tag_legend(comparison)
    if review_reasons:
        st.markdown(theme.review_key(review_reasons), unsafe_allow_html=True)

    if show_confidence:
        st.caption(
            "The small figure after each price — ·94% — is how clearly that number "
            "could be read off the supplier's own document. A clean spreadsheet "
            "cell scores high; a figure on a photographed rate card scores lower. "
            "It says nothing about whether the price is a good one."
        )

    counts = pd.Series(winners).value_counts()
    if not counts.empty:
        st.markdown(
            '<div class="rfx-legend" style="margin-top:.5rem">'
            + "".join(theme.chip(f"{vendor} · cheapest on {count} of {len(winners)}", "info")
                      for vendor, count in counts.items())
            + "</div>",
            unsafe_allow_html=True,
        )
        orphaned = rfx_module.active().line_count - len(winners)
        if orphaned:
            st.caption(f"{orphaned} of {rfx_module.active().line_count} lines have no comparable price "
                       "from any shortlisted supplier — see Exceptions.")

    # --- click-through --------------------------------------------------------
    chosen_rows = list(getattr(selection, "selection", {}).get("rows", []) or [])
    if chosen_rows:
        chosen_sku = display.index[chosen_rows[0]]
        line = rfx_module.active().by_sku[chosen_sku]

        st.markdown(
            theme.eyebrow(chosen_sku, "What each supplier actually wrote",
                          f"{line.description}"
                          + (f" · {line.quantity:,} units" if line.quantity else "")
                          + " · "
                          f"price wanted {line.canonical_unit}"),
            unsafe_allow_html=True,
        )
        cards = present.original_quote_cards(comparison, chosen_sku)
        for row_start in range(0, len(cards), 3):
            for column, card in zip(st.columns(3), cards[row_start:row_start + 3]):
                column.markdown(theme.quote_card(card), unsafe_allow_html=True)
    else:
        st.caption("Select a row above to see the original wording from every supplier.")


    # ---------------------------------------------------------------------------
    # 4 · quality and compliance
    # ---------------------------------------------------------------------------
    st.markdown(theme.eyebrow("04", "Quality and compliance",
                              "scored, not gated"),
                unsafe_allow_html=True)

    if not comparison.criteria:
        st.info("No supplier answered a quality questionnaire, so there is nothing "
                "to score here.")
    else:
        # Apply whatever the buyer has changed, then re-score. Their answers never
        # change; only what the buyer decided to require, weight or ignore.
        for criterion in comparison.criteria:
            saved = st.session_state["criteria_settings"].get(criterion.key)
            if saved:
                criterion.requirement = saved["requirement"]
                criterion.threshold = saved["threshold"]
                criterion.weight = saved["weight"]
        assemble.rescore(comparison)

        st.caption(
            "These criteria were read from the suppliers' own answers — nothing here "
            "is a fixed checklist. The score is plain arithmetic: **the weight of "
            "every criterion a supplier satisfies, divided by the total weight**. "
            "Where they gave a figure, the figure is tested against the target; "
            "where they only answered Yes, the Yes counts in full. A supplier is "
            "ranked, not eliminated — nothing removes anyone from the recommendation "
            "unless you mark a criterion **Must have**."
        )

        st.markdown(theme.scorecard_cards(comparison.summaries, len(comparison.criteria)),
                    unsafe_allow_html=True)

        st.markdown("##### What counts, and how much")
        suggestions = [c for c in comparison.criteria
                       if c.suggested_threshold and c.suggested_threshold != c.threshold]
        basket = rfx_module.active().basket_units_per_month
        if suggestions and basket:
            names = ", ".join(f"**{c.label}** → {c.suggested_threshold:,.0f}"
                              for c in suggestions)
            column_note, column_button = st.columns([4, 1])
            column_note.info(
                f"The target on the questionnaire may not be the target you need. "
                f"Your basket needs about "
                f"{basket:,.0f} units a month, so "
                f"we suggest: {names}.")
            if column_button.button("Use suggested", width="stretch"):
                for criterion in suggestions:
                    st.session_state["criteria_settings"][criterion.key] = {
                        "requirement": criterion.requirement,
                        "threshold": criterion.suggested_threshold,
                        "weight": criterion.weight,
                    }
                st.rerun()

        edited = st.data_editor(
            present.criteria_frame(comparison),
            hide_index=True, width="stretch", key="criteria_editor",
            column_config={
                "Criterion": st.column_config.TextColumn(disabled=True, width="large"),
                "Requirement": st.column_config.SelectboxColumn(
                    options=list(criteria_module.REQUIREMENT_LEVELS),
                    help=glossary.tip("must_have")),
                "Weight": st.column_config.NumberColumn(
                    min_value=0.0, max_value=5.0, step=0.5,
                    help="How much this criterion counts towards the score."),
                "key": None,
            },
        )

        thresholds = {c.key: c.threshold for c in comparison.criteria}
        changed = False
        for _, row in edited.iterrows():
            # A cleared weight cell arrives as NaN, and NaN never equals
            # itself -- so comparing it against the stored setting was true
            # every run, which reran the page forever and pushed a NaN into
            # the quality score. An emptied cell means "back to one".
            weight = present.number_or(row["Weight"], 1.0)
            current = {"requirement": row["Requirement"],
                       "threshold": thresholds.get(row["key"]),
                       "weight": weight}
            if st.session_state["criteria_settings"].get(row["key"]) != current:
                st.session_state["criteria_settings"][row["key"]] = current
                changed = True
        if changed:
            st.rerun()

        st.markdown("##### What each supplier actually said")
        answers_display, answers_state = present.questionnaire_frame(comparison)
        st.dataframe(
            present.style_questionnaire(answers_display, answers_state),
            width="stretch",
            column_config={"Weight": st.column_config.Column(width="small")},
        )
        st.markdown(
            '<div class="rfx-legend" style="margin:.35rem 0 .1rem">'
            + theme.chip("meets the criterion", "ok")
            + theme.chip("does not meet it", "stop")
            + theme.chip("not answered", "mute")
            + "</div>",
            unsafe_allow_html=True,
        )
        st.caption("Where a supplier gave a figure it is shown, and the figure "
                   "decides. Where they only answered Yes, the Yes counts in full.")

        try:
            store.write(comparison, path=st.session_state["db_path"])
        except Exception:
            pass


    # ---------------------------------------------------------------------------
    # 5 · recommended award
    # ---------------------------------------------------------------------------
    st.markdown(theme.eyebrow("05", "Recommended award",
                              "our suggestion — you decide"),
                unsafe_allow_html=True)

    award_controls = st.columns([2.4, 2.4, 3])
    with award_controls[0]:
        min_quality = st.slider(
            "Minimum quality score to be shortlisted", 0, 100, 0, step=5,
            help=glossary.tip("quality_score")) / 100.0
    with award_controls[1]:
        min_lines = st.slider(
            "Fewest items worth awarding to one supplier", 1, 10, 1,
            help=glossary.tip("min_lines"))
    with award_controls[2]:
        st.caption("Each item goes to whichever shortlisted supplier is cheapest on "
                   "that item, using only prices we could make comparable. Everyone "
                   "is shortlisted unless they miss a **Must have** you set above, or "
                   "fall below the score you choose here.")

    plan = award.recommend(comparison, min_lines=min_lines, min_quality=min_quality)
    try:
        store.write_award(plan, path=st.session_state["db_path"])
    except Exception:
        pass  # the recommendation still displays even if it cannot be persisted

    if not plan.vendors:
        st.warning("We cannot recommend anyone under these settings. Try lowering "
                   "the minimum quality score, or relaxing a Must have.")
    else:
        symbol = present.SYMBOLS.get(rfx_module.active().currency, "")
        st.markdown(theme.award_headline(plan, symbol), unsafe_allow_html=True)
        st.markdown(theme.stats(present.award_stats(plan)), unsafe_allow_html=True)
        st.markdown(theme.saving_working(plan, symbol), unsafe_allow_html=True)
        st.markdown(theme.allocation_bar(plan), unsafe_allow_html=True)
        st.markdown(theme.award_cards(plan, symbol), unsafe_allow_html=True)

        notes = award.caveats(plan, comparison)
        if notes:
            with st.expander(f"What this recommendation does not account for ({len(notes)})"):
                for note in notes:
                    st.markdown(f"- {note}")

        detail_award, detail_gaps = st.tabs(
            ["Item by item", f"Cannot be recommended ({len(plan.unawardable)})"])
        with detail_award:
            st.dataframe(
                present.award_line_frame(plan), width="stretch",
                hide_index=True, height=380,
                column_config={
                    "Suggested supplier": st.column_config.Column(
                        help="The cheapest shortlisted supplier for this item. It is "
                             "a suggestion from the data, not a decision."),
                    "Next best": st.column_config.Column(
                        help="The runner-up, so you can see how close the decision was."),
                    "Saving": st.column_config.Column(
                        help="What choosing the winner saves against the runner-up."),
                    "Contested": st.column_config.Column(help=glossary.tip("uncontested")),
                },
            )
        with detail_gaps:
            gaps = present.award_gap_frame(plan)
            if gaps.empty:
                st.success("Every item could be recommended to someone.")
            else:
                st.caption("We cannot suggest anyone for these yet. The Needs "
                           "attention tab says exactly what to ask each supplier for.")
                st.dataframe(gaps, width="stretch", hide_index=True)


    # ---------------------------------------------------------------------------
    # 6 · ask the analyst
    # ---------------------------------------------------------------------------
    st.markdown(theme.eyebrow("06", "Ask the analyst",
                              "plain language, real queries"),
                unsafe_allow_html=True)

    st.markdown(theme.ask_banner(), unsafe_allow_html=True)

    st.markdown("###### Start from one of these, or write your own")
    suggestion_columns = st.columns(len(analyst.SUGGESTED_QUESTIONS))
    for column, suggestion in zip(suggestion_columns, analyst.SUGGESTED_QUESTIONS):
        if column.button(suggestion, width="stretch",
                         key=f"suggest_{abs(hash(suggestion))}"):
            st.session_state["analyst_question"] = suggestion
            st.rerun()

    question = st.text_input(
        "Your question",
        value=st.session_state.get("analyst_question", ""),
        placeholder="Which supplier is cheapest per line among those scoring above 85?",
        label_visibility="collapsed",
        help="Ask in ordinary language. The analyst looks the answer up in the data "
             "rather than working it out in its head, and shows you every lookup it "
             "made underneath the answer.",
    )

    if st.button("Ask", type="primary", disabled=not question.strip(),
                 help=None if question.strip() else "Type a question first."):
        with st.spinner("Querying the comparison…"):
            answer = analyst.ask(question, db_path=st.session_state["db_path"])
        st.session_state["history"].insert(0, (question, answer))

    for asked, answer in st.session_state["history"]:
        st.markdown(f"#### {asked}")
        if answer.error:
            st.error(answer.error)
        st.markdown(answer.text)

        for chart in answer.charts:
            if not chart.rows:
                continue
            frame = pd.DataFrame(chart.rows)
            st.markdown(f"**{chart.title}**")
            try:
                if chart.kind == "line":
                    st.line_chart(frame, x=chart.x, y=chart.y, color=chart.series)
                elif chart.kind == "scatter":
                    st.scatter_chart(frame, x=chart.x, y=chart.y, color=chart.series)
                else:
                    st.bar_chart(frame, x=chart.x, y=chart.y, color=chart.series)
            except Exception:
                st.dataframe(frame, width="stretch", hide_index=True)

        if answer.queries:
            with st.expander(f"Show the working — {len(answer.queries)} queries"):
                for index, query in enumerate(answer.queries, start=1):
                    st.markdown(f"**Query {index}** · {query['row_count']} rows")
                    st.code(query["sql"], language="sql")
                    if query["rows"]:
                        st.dataframe(pd.DataFrame(query["rows"]),
                                     width="stretch", hide_index=True)
        if answer.evidence:
            with st.expander(f"Source evidence pulled — {len(answer.evidence)} cells"):
                st.dataframe(pd.DataFrame(answer.evidence),
                             width="stretch", hide_index=True)
        st.divider()


    # ---------------------------------------------------------------------------
    # 4 · tabs
    # ---------------------------------------------------------------------------
    st.markdown(theme.eyebrow("07", "Dig in"), unsafe_allow_html=True)

    tab_exceptions, tab_evidence, tab_terms = st.tabs(
        ["Needs attention", "Evidence", "Commercial terms"]
    )

    with tab_exceptions:
        frame = present.exceptions_frame(comparison)
        if frame.empty:
            st.success("Nothing needs review.")
        else:
            unresolved = int(frame["Status"].str.contains("Unresolved").sum())
            review = int(frame["Status"].str.contains("Needs Review").sum())
            missing = int(frame["Status"].str.contains("Not Quoted").sum())
            unplaced = int(frame["Status"].str.contains("Not on your list").sum())
            st.markdown(
                '<div class="rfx-legend" style="margin-bottom:.7rem">'
                + theme.chip(f"{unresolved} could not work out", "stop")
                + theme.chip(f"{review} need a human", "warn")
                + theme.chip(f"{missing} not priced", "mute")
                + (theme.chip(f"{unplaced} not on your list", "mute")
                   if unplaced else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            st.caption("Every row is a line you cannot safely compare yet, with the "
                       "exact thing needed to fix it.")
            st.dataframe(
                frame, width="stretch", hide_index=True, height=440,
                column_config={
                    "Status": st.column_config.Column(
                        help="Why this line is not in the comparison. Hover the "
                             "coloured labels above the grid for what each one means."),
                    "As quoted": st.column_config.Column(
                        help="Exactly what the supplier wrote, in their own units."),
                    "How clearly we read it": st.column_config.Column(
                        help=glossary.tip("read_clarity")),
                    "Why": st.column_config.Column(
                        help="Our reason, in full. Nothing is excluded silently."),
                    "What we need": st.column_config.Column(
                        help="The single piece of information that would resolve this "
                             "line. Usually one question to the supplier."),
                },
            )

    with tab_evidence:
        st.caption("Any number on the grid, walked back to the words on the page.")
        picker = st.columns(2)
        with picker[0]:
            sku = st.selectbox("Line", [line.sku for line in rfx_module.active().lines],
                               format_func=lambda s: f"{s} — {rfx_module.active().by_sku[s].description}",
                               help=glossary.tip("line_item"))
        with picker[1]:
            vendor = st.selectbox("Supplier", comparison.vendors,
                                  help="Whose response you want to inspect for this line.")

        cell = comparison.cell(sku, vendor)
        if cell is None:
            st.info("No cell for that combination.")
        else:
            head = st.columns(4)
            head[0].metric("What they wrote",
                           present.money(cell.original_value, cell.original_currency),
                           cell.original_unit or "unit not stated",
                           help=glossary.tip("basis"))
            head[1].metric(f"Comparable price ({rfx_module.active().by_sku[sku].canonical_unit})",
                           present.money(cell.canonical_value, cell.canonical_currency),
                           cell.factor or "no conversion needed",
                           help=glossary.tip("conversion"))
            head[2].metric("Status", cell.status,
                           f"matched by {cell.match_basis.replace('_', ' ')}",
                           help=glossary.tip(theme.STATUS_TERM.get(cell.status, "")))
            head[3].metric("How clearly we read it",
                           f"{cell.extraction_confidence:.0%}"
                           if cell.original_value is not None else "—",
                           present.confidence_label(cell.extraction_confidence).split("· ")[-1]
                           if cell.original_value is not None else "nothing quoted",
                           help=glossary.tip("read_clarity"))

            if cell.reason:
                st.info(cell.reason)
            if cell.missing_datum:
                st.error(f"**To resolve this line, ask the supplier for:** {cell.missing_datum}")
            for label in present.flag_legend(cell.flags):
                st.caption(f"⚑ {label}")

            if cell.source_snippet:
                st.markdown(f"**Source — {cell.source_file} · {cell.source_locator}**")
                st.code(cell.source_snippet, language=None, wrap_lines=True)
            else:
                st.caption("No source text — this line was not quoted.")

    with tab_terms:
        st.subheader("What they said about terms")
        rows = []
        for response in comparison.responses:
            for term in response.terms:
                rows.append({"Supplier": response.vendor, "About": term.kind.title(),
                             "In their words": term.text,
                             "Only if": term.trigger or "—"})
        if rows:
            st.dataframe(
                pd.DataFrame(rows), width="stretch", hide_index=True,
                column_config={
                    "About": st.column_config.Column(
                        help="Delivery, payment, how long the price stays valid, tax, "
                             "or a discount."),
                    "In their words": st.column_config.Column(
                        width="large", help="Quoted from their document, unedited."),
                    "Only if": st.column_config.Column(
                        help=glossary.tip("discount")),
                },
            )

