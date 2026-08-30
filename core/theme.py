"""Visual identity for the app.

The look borrows from the documents this thing exists to replace: ledger rules,
tabular figures, mono labels in the margin, status stamped rather than
described. Type is IBM Plex Sans and Plex Mono for anything numeric, with
Spectral carrying the headings — the same pairing as the written design note,
so the prototype and the note read as one piece of work.

Components are rendered as plain HTML rather than by styling Streamlit's own
class names, which change between releases.
"""

from __future__ import annotations

import html
import re
from typing import Iterable, Optional

from . import brand, glossary

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Spectral:wght@500;600&display=swap');

:root {
  --paper:     #F5F7FA;
  --card:      #FFFFFF;
  --ink:       #151A22;
  --ink-soft:  #414B5A;
  --muted:     #6B7688;
  --rule:      #DDE3EA;
  --rule-soft: #EBEFF4;
  --accent:    #22417C;
  --accent-bg: #E9EEF7;
  --ok:        #2C6942;  --ok-bg:   #E6F1E9;
  --warn:      #8A570F;  --warn-bg: #FAF0DE;
  --stop:      #93302B;  --stop-bg: #F8E7E5;
  --sans: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
  --serif: Spectral, Georgia, serif;
}

/* ---------- base ----------
   Deliberately does NOT blanket every div/span: those selectors outrank the
   component classes below and would silently undo the mono labels. */
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp button,
.stApp input, .stApp textarea, .stApp select,
.stApp [data-testid="stMarkdownContainer"] { font-family: var(--sans); }
.stApp { background: var(--paper); }
.block-container { padding-top: 3.1rem; padding-bottom: 5rem; max-width: 1500px; }

h1, h2, h3 { font-family: var(--serif) !important; letter-spacing: -.012em; }
h1 { font-weight: 600 !important; }
h2 { font-weight: 600 !important; font-size: 1.62rem !important; }
h3 { font-weight: 600 !important; font-size: 1.18rem !important; }

/* numbers line up wherever they appear */
[data-testid="stDataFrame"], [data-testid="stMetricValue"] {
  font-variant-numeric: tabular-nums;
}

/* ---------- masthead ---------- */
.rfx-mast { margin-bottom: 1.9rem; }
.rfx-kicker {
  font-family: var(--mono); font-size: .72rem; letter-spacing: .17em;
  text-transform: uppercase; color: var(--accent); margin-bottom: .55rem;
}
.rfx-mast h1 {
  font-family: var(--serif); font-weight: 600; font-size: 2.5rem;
  line-height: 1.08; margin: 0 0 .45rem; color: var(--ink);
}
.rfx-sub { color: var(--ink-soft); font-size: 1.03rem; max-width: 62ch; margin: 0; }
/* the category line carries the identity, so it outranks the page line */
.rfx-tagline { font-family: var(--serif); font-size: 1.15rem; line-height: 1.45;
               color: var(--ink); margin-bottom: .5rem; }
.rfx-pageline { font-size: .93rem; color: var(--muted); }
.rfx-meta {
  margin-top: 1.15rem; padding-top: .85rem; border-top: 2px solid var(--ink);
  display: flex; flex-wrap: wrap; gap: .35rem 2.1rem;
  font-family: var(--mono); font-size: .76rem; color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.rfx-meta b { color: var(--ink); font-weight: 500; }

/* ---------- section eyebrow ---------- */
.rfx-eyebrow {
  display: flex; align-items: baseline; gap: .8rem;
  margin: 2.4rem 0 .9rem; padding-bottom: .5rem;
  border-bottom: 1px solid var(--rule);
}
.rfx-eyebrow .n {
  font-family: var(--mono); font-size: .74rem; letter-spacing: .12em;
  color: var(--accent); text-transform: uppercase;
}
.rfx-eyebrow .t {
  font-family: var(--serif); font-size: 1.45rem; font-weight: 600; color: var(--ink);
}
.rfx-eyebrow .h { font-size: .82rem; color: var(--muted); margin-left: auto; }

/* ---------- stat strip ----------
   Real gaps and per-card borders rather than the hairline trick: with an odd
   number of cards the trick leaves a slab of container colour where the empty
   grid cells are. */
.rfx-stats { display: grid; gap: .6rem; margin: .2rem 0 1.5rem;
             grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); }
.rfx-stat { background: var(--card); border: 1px solid var(--rule);
            padding: .95rem 1.3rem; }
.rfx-stat .v {
  font-family: var(--mono); font-size: 1.62rem; font-weight: 500; line-height: 1.1;
  color: var(--ink); font-variant-numeric: tabular-nums; letter-spacing: -.02em;
}
.rfx-stat .v.accent { color: var(--accent); }
.rfx-stat .v.warn { color: var(--warn); }
.rfx-stat .v.small { font-size: 1.1rem; }
.rfx-stat .l {
  font-family: var(--mono); font-size: .68rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin-top: .4rem;
}

/* ---------- advisory cards ---------- */
.rfx-advisory {
  background: var(--card); border: 1px solid var(--rule);
  border-left: 3px solid var(--warn);
  padding: 1rem 1.25rem; margin-bottom: .7rem;
}
.rfx-advisory.info { border-left-color: var(--accent); }
.rfx-advisory .hd {
  font-weight: 600; color: var(--ink); margin-bottom: .35rem; font-size: 1.01rem;
}
.rfx-advisory p { margin: 0 0 .5rem; color: var(--ink-soft); line-height: 1.6; }
.rfx-advisory p:last-child { margin-bottom: 0; }
.rfx-advisory strong { color: var(--ink); font-weight: 600; }

/* ---------- supplier cards ---------- */
.rfx-suppliers { display: grid; gap: .6rem;
                 grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr)); }
.rfx-supplier { background: var(--card); border: 1px solid var(--rule);
                padding: 1.05rem 1.2rem 1.15rem; }
.rfx-supplier .nm {
  font-weight: 600; font-size: 1.02rem; color: var(--ink); line-height: 1.25;
  margin-bottom: .15rem;
}
.rfx-supplier .fmt {
  font-family: var(--mono); font-size: .68rem; color: var(--muted);
  text-transform: uppercase; letter-spacing: .08em; margin-bottom: .85rem;
}
.rfx-bar { height: 4px; background: var(--rule-soft); margin: .3rem 0 .1rem; }
.rfx-bar > i { display: block; height: 100%; background: var(--accent); }
.rfx-bar.ok > i { background: var(--ok); }
.rfx-bar.warn > i { background: var(--warn); }
.rfx-supplier .mt {
  display: flex; justify-content: space-between; font-family: var(--mono);
  font-size: .71rem; color: var(--muted); font-variant-numeric: tabular-nums;
}
.rfx-supplier .mt b { color: var(--ink-soft); font-weight: 500; }
.rfx-supplier .facts {
  margin-top: .85rem; padding-top: .7rem; border-top: 1px solid var(--rule-soft);
  font-size: .79rem; color: var(--muted); line-height: 1.75;
}
.rfx-supplier .facts b { color: var(--ink-soft); font-weight: 500; }

/* ---------- help icons and tooltips ----------
   Anything with data-tip grows a bubble on hover or keyboard focus. The
   containers that hold them are set to overflow:visible below, otherwise the
   bubble is clipped by its own card. */
.rfx-tip { position: relative; }
.rfx-tip::after {
  content: attr(data-tip);
  position: absolute; bottom: calc(100% + 9px); left: 50%;
  transform: translateX(-50%);
  width: 17rem; max-width: 60vw;
  background: var(--ink); color: #FFF;
  padding: .65rem .75rem; border-radius: 3px;
  font-family: var(--sans); font-size: .74rem; font-weight: 400;
  line-height: 1.5; letter-spacing: 0; text-transform: none; text-align: left;
  white-space: normal; opacity: 0; visibility: hidden;
  transition: opacity .12s ease; z-index: 9999; pointer-events: none;
  box-shadow: 0 8px 26px -10px rgba(0,0,0,.55);
}
.rfx-tip::before {
  content: ""; position: absolute; bottom: calc(100% + 4px); left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent; border-top-color: var(--ink);
  opacity: 0; visibility: hidden; transition: opacity .12s ease; z-index: 9999;
}
.rfx-tip:hover::after, .rfx-tip:hover::before,
.rfx-tip:focus::after, .rfx-tip:focus::before { opacity: 1; visibility: visible; }

.rfx-help {
  display: inline-flex; align-items: center; justify-content: center;
  width: 14px; height: 14px; margin-left: .4em;
  border: 1px solid var(--muted); border-radius: 50%;
  color: var(--muted); background: transparent;
  font-family: var(--sans); font-size: 9px; font-weight: 700; line-height: 1;
  letter-spacing: 0; text-transform: none; cursor: help;
  vertical-align: middle; flex: none;
}
.rfx-help:hover, .rfx-help:focus {
  border-color: var(--accent); color: var(--accent); background: var(--accent-bg);
  outline: none;
}

/* let bubbles escape their cards */
.rfx-stats, .rfx-stat, .rfx-suppliers, .rfx-supplier,
.rfx-legend, .rfx-eyebrow, .rfx-quote { overflow: visible; }

/* ---------- award allocation ---------- */
.rfx-award-head {
  background: var(--card); border: 1px solid var(--rule);
  border-left: 3px solid var(--ok);
  padding: 1.1rem 1.3rem; margin-bottom: .9rem;
}
.rfx-award-head .lead { font-size: 1.12rem; line-height: 1.5; color: var(--ink); }
.rfx-award-head .lead strong { font-weight: 600; }
.rfx-award-head .sub { font-size: .85rem; color: var(--muted); margin-top: .5rem; }

/* ---------- the assistant half ----------
   Cool, flat, screen-like: a machine you talk to. It is deliberately the
   opposite of the document below it in every dimension a reader notices at a
   glance -- colour temperature, edge, and whether the type has serifs. */
.st-key-ai_panel {
  background: #F2F5F9;
  border: 1px solid var(--rule);
  border-left: 3px solid var(--accent);
  border-radius: 3px;
  padding: 1.2rem 1.4rem .9rem;
}
.st-key-ai_panel .rfx-eyebrow { margin-top: .2rem; }

/* ---------- the RFQ document ----------
   The draft is not another panel of the app: it is the document that goes to
   five companies, and it should look like one. Cream paper, a ruled edge,
   serif headings and a typewriter face on the field labels -- so at a glance
   you can tell what you are LOOKING at from what you are TALKING TO. The AI
   half of the page stays plain and grey; this half reads as a form on a desk. */
.st-key-rfq_doc {
  background: #FCFBF7;
  border: 1px solid #DED8C8;
  border-top: 3px solid var(--ink);
  padding: 1.5rem 1.7rem 1.2rem;
  box-shadow: 0 1px 0 #EFEADC, 0 14px 28px -26px rgba(0,0,0,.35);
}
.st-key-rfq_doc h1, .st-key-rfq_doc h2, .st-key-rfq_doc h3,
.st-key-rfq_doc h4, .st-key-rfq_doc strong, .st-key-rfq_doc b {
  font-family: var(--serif) !important;
}
/* field labels in the margin voice, like a printed form */
.st-key-rfq_doc label p,
.st-key-rfq_doc [data-testid="stWidgetLabel"] p {
  font-family: var(--mono) !important; font-size: .72rem !important;
  letter-spacing: .09em; text-transform: uppercase; color: var(--muted) !important;
}
.st-key-rfq_doc [data-testid="stMarkdownContainer"] p { color: var(--ink-soft); }
.st-key-rfq_doc input, .st-key-rfq_doc textarea {
  background: #FFFDF8 !important; border-color: #DED8C8 !important;
}
.st-key-rfq_doc [data-baseweb="tab-list"] { border-bottom: 1px solid #DED8C8; }
.st-key-rfq_doc [data-baseweb="tab"] { font-family: var(--mono); font-size: .78rem; }
.st-key-rfq_doc .rfx-eyebrow { border-bottom-color: #DED8C8; }
.st-key-rfq_doc [data-testid="stDataFrame"] { background: #FFFDF8; }

/* ---------- the split-vs-one-supplier working ---------- */
.rfx-working {
  background: var(--card); border: 1px solid var(--rule);
  padding: .9rem 1.1rem; margin: .2rem 0 .9rem;
}
.rfx-working .hd {
  font-size: .72rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--muted); margin-bottom: .6rem;
}
.rfx-working table { width: 100%; border-collapse: collapse; }
.rfx-working td {
  padding: .3rem 0; font-size: .88rem; color: var(--ink-soft);
  border-bottom: 1px solid var(--rule);
}
.rfx-working td.n {
  text-align: right; font-family: var(--mono); color: var(--ink);
  white-space: nowrap; padding-left: 1rem;
}
.rfx-working tr.total td { border-bottom: none; border-top: 2px solid var(--ink);
                           font-weight: 600; color: var(--ink); padding-top: .45rem; }
.rfx-working .foot { font-size: .8rem; color: var(--muted); margin-top: .6rem;
                     line-height: 1.55; }

.rfx-allocation { display: flex; height: 30px; margin: .2rem 0 .5rem;
                  border: 1px solid var(--rule); overflow: hidden; }
.rfx-allocation > span {
  display: flex; align-items: center; justify-content: center;
  font-family: var(--mono); font-size: .7rem; color: #FFF; overflow: hidden;
  white-space: nowrap;
}
.rfx-alloc-key { display: flex; flex-wrap: wrap; gap: .35rem 1.1rem;
                 font-size: .78rem; color: var(--ink-soft); margin-bottom: 1.2rem; }
.rfx-alloc-key span { display: inline-flex; align-items: center; gap: .4em; }
.rfx-alloc-key i { width: 10px; height: 10px; flex: none; }

.rfx-award-cards { display: grid; gap: .6rem;
                   grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }
.rfx-award-card { background: var(--card); border: 1px solid var(--rule);
                  border-top: 3px solid var(--accent); padding: .95rem 1.1rem; }
.rfx-award-card .nm { font-weight: 600; color: var(--ink); line-height: 1.3; }
.rfx-award-card .big {
  font-family: var(--mono); font-size: 1.75rem; line-height: 1.15; color: var(--ink);
  font-variant-numeric: tabular-nums; margin-top: .5rem; letter-spacing: -.02em;
}
.rfx-award-card .sm { font-family: var(--mono); font-size: .68rem;
                      letter-spacing: .09em; text-transform: uppercase;
                      color: var(--muted); margin-top: .2rem; }
.rfx-award-card .foot { margin-top: .7rem; padding-top: .6rem;
                        border-top: 1px solid var(--rule-soft);
                        font-size: .78rem; color: var(--ink-soft); }
.rfx-award-card .items { font-family: var(--mono); font-size: .67rem;
                         color: var(--muted); margin-top: .45rem;
                         line-height: 1.5; word-break: break-word; }

/* ---------- quality scorecards ---------- */
.rfx-scores { display: grid; gap: .6rem; margin-bottom: 1rem;
              grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }
.rfx-score { background: var(--card); border: 1px solid var(--rule);
             padding: .95rem 1.1rem; overflow: visible; }
.rfx-score .nm { font-weight: 600; color: var(--ink); line-height: 1.3;
                 min-height: 2.6em; }
.rfx-score .big { font-family: var(--mono); font-size: 1.9rem; line-height: 1.1;
                  font-variant-numeric: tabular-nums; letter-spacing: -.02em;
                  margin-top: .45rem; }
.rfx-score .big.good { color: var(--ok); }
.rfx-score .big.mid  { color: var(--warn); }
.rfx-score .big.poor { color: var(--stop); }
.rfx-score .sm { font-family: var(--mono); font-size: .66rem; letter-spacing: .09em;
                 text-transform: uppercase; color: var(--muted); margin-top: .15rem; }
.rfx-score .facts { margin-top: .75rem; padding-top: .6rem;
                    border-top: 1px solid var(--rule-soft);
                    font-size: .78rem; color: var(--ink-soft); line-height: 1.7; }
.rfx-score .facts b { font-weight: 600; color: var(--ink); }

/* ---------- ask the analyst ---------- */
.rfx-ask {
  display: flex; align-items: flex-start; gap: 1.05rem;
  background: var(--ink); color: #FFF;
  padding: 1.25rem 1.4rem; margin: .3rem 0 1.4rem;
}
.rfx-ask .ico {
  width: 42px; height: 42px; border-radius: 50%; flex: none;
  background: #FFF; color: var(--ink);
  display: flex; align-items: center; justify-content: center;
  font-family: var(--sans); font-weight: 700; font-size: 1.25rem;
}
.rfx-ask .txt { display: flex; flex-direction: column; gap: .3rem; }
.rfx-ask .txt b { font-size: 1.1rem; font-weight: 600; }
.rfx-ask .txt i { font-style: normal; font-size: .87rem; line-height: 1.55;
                  color: #C6CEDA; max-width: 82ch; }

/* ---------- chips ---------- */
.rfx-chip {
  display: inline-flex; align-items: center; gap: .4em;
  font-family: var(--mono); font-size: .68rem; letter-spacing: .04em;
  text-transform: uppercase; padding: .2em .55em; border-radius: 2px;
  white-space: nowrap; font-weight: 500;
}
.rfx-chip::before { content:""; width:.44em; height:.44em; border-radius:50%;
                    background: currentColor; }
.rfx-chip.ok   { color: var(--ok);     background: var(--ok-bg); }
.rfx-chip.warn { color: var(--warn);   background: var(--warn-bg); }
.rfx-chip.stop { color: var(--stop);   background: var(--stop-bg); }
.rfx-chip.info { color: var(--accent); background: var(--accent-bg); }
.rfx-chip.mute { color: var(--muted);  background: var(--rule-soft); }

.rfx-legend { display: flex; flex-wrap: wrap; gap: .4rem .55rem; align-items: center; }

/* ---------- quote cards (click-through) ---------- */
.rfx-quote { background: var(--card); border: 1px solid var(--rule);
             border-top: 3px solid var(--rule); padding: 1rem 1.1rem 1.1rem;
             height: 100%; }
.rfx-quote.ok   { border-top-color: var(--ok); }
.rfx-quote.warn { border-top-color: var(--warn); }
.rfx-quote.stop { border-top-color: var(--stop); }
.rfx-quote.info { border-top-color: var(--accent); }
.rfx-quote.mute { border-top-color: var(--rule); }
.rfx-quote .nm { font-weight: 600; color: var(--ink); margin-bottom: .55rem; }
.rfx-quote .lbl {
  font-family: var(--mono); font-size: .66rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin: .8rem 0 .3rem;
}
.rfx-quote blockquote {
  margin: 0; padding: .6rem .75rem; background: var(--paper);
  border-left: 2px solid var(--rule); font-family: var(--mono);
  font-size: .76rem; line-height: 1.55; color: var(--ink-soft);
  white-space: pre-wrap; word-break: break-word;
}
.rfx-kv { display: flex; justify-content: space-between; gap: 1rem;
          padding: .25rem 0; border-bottom: 1px dotted var(--rule-soft);
          font-size: .82rem; }
.rfx-kv:last-of-type { border-bottom: none; }
.rfx-kv span { color: var(--muted); }
.rfx-kv b { color: var(--ink); font-weight: 600; font-family: var(--mono);
            font-variant-numeric: tabular-nums; }
.rfx-quote .why { font-size: .8rem; color: var(--muted); line-height: 1.55;
                  margin-top: .6rem; }
.rfx-quote .ask { margin-top: .6rem; padding: .5rem .65rem; background: var(--warn-bg);
                  color: var(--warn); font-size: .78rem; line-height: 1.5; }
.rfx-quote .src { margin-top: .7rem; font-family: var(--mono); font-size: .66rem;
                  color: var(--muted); word-break: break-all; }

/* ---------- glossary panel ----------
   A real <details> element rather than Streamlit's expander: it needs a
   distinct, deliberately prominent treatment, and this way the open/closed
   state costs no rerun. */
.rfx-gl-wrap {
  border: 1px solid var(--accent); background: var(--accent-bg);
  margin: .5rem 0 1.9rem;
}
.rfx-gl-wrap > summary {
  list-style: none; cursor: pointer; display: flex; align-items: center;
  gap: .95rem; padding: 1rem 1.25rem;
}
.rfx-gl-wrap > summary::-webkit-details-marker { display: none; }
.rfx-gl-wrap > summary:focus-visible { outline: 2px solid var(--accent);
                                       outline-offset: -3px; }
.rfx-gl-wrap .ico {
  width: 36px; height: 36px; border-radius: 50%; background: var(--accent);
  color: #FFF; display: flex; align-items: center; justify-content: center;
  font-family: var(--sans); font-weight: 700; font-size: 1.05rem; flex: none;
}
.rfx-gl-wrap .txt { display: flex; flex-direction: column; gap: .1rem; min-width: 0; }
.rfx-gl-wrap .txt b { font-size: 1.06rem; font-weight: 600; color: var(--ink); }
.rfx-gl-wrap .txt i { font-style: normal; font-size: .83rem; color: var(--ink-soft);
                      line-height: 1.45; }
.rfx-gl-wrap .tog {
  margin-left: auto; flex: none; display: inline-flex; align-items: center;
  gap: .5em; font-family: var(--mono); font-size: .7rem; letter-spacing: .09em;
  text-transform: uppercase; font-weight: 500;
  color: var(--accent); background: var(--card);
  border: 1px solid var(--accent); border-radius: 2px; padding: .38em .75em;
  transition: background .12s, color .12s;
}
.rfx-gl-wrap .tog::before { content: "Expand"; }
.rfx-gl-wrap[open] .tog::before { content: "Collapse"; }
.rfx-gl-wrap .tog::after { content: "\\25BE"; font-size: .9em;
                           transition: transform .16s ease; }
.rfx-gl-wrap[open] .tog::after { transform: rotate(180deg); }
.rfx-gl-wrap > summary:hover .tog { background: var(--accent); color: #FFF; }
.rfx-gl-body {
  background: var(--card); border-top: 1px solid var(--accent);
  padding: 1.35rem 1.25rem 1.45rem;
}
.rfx-gl-hint { font-size: .8rem; color: var(--muted); margin: 0 0 1.1rem; }

.rfx-glossary { display: grid; gap: 1.5rem;
                grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr)); }
.rfx-gl-group h4 {
  font-family: var(--mono); font-size: .7rem; letter-spacing: .11em;
  text-transform: uppercase; color: var(--accent);
  margin: 0 0 .6rem; padding-bottom: .4rem; border-bottom: 1px solid var(--rule);
}
.rfx-gl-row { padding: .5rem 0; border-bottom: 1px solid var(--rule-soft); }
.rfx-gl-row:last-child { border-bottom: none; }
.rfx-gl-row .t { font-weight: 600; font-size: .87rem; color: var(--ink); }
.rfx-gl-row .d { font-size: .82rem; color: var(--ink-soft); line-height: 1.55;
                 margin-top: .15rem; }

/* ---------- streamlit widget tuning ---------- */
[data-testid="stSidebar"] { background: var(--card); border-right: 1px solid var(--rule); }
[data-testid="stSidebar"] .block-container { padding-top: 2rem; }

.stTabs [data-baseweb="tab-list"] { gap: .3rem; border-bottom: 1px solid var(--rule); }
.stTabs [data-baseweb="tab"] {
  font-family: var(--mono) !important; font-size: .78rem !important;
  letter-spacing: .05em; text-transform: uppercase; padding: .55rem .9rem;
}

div[data-testid="stFileUploaderDropzone"] {
  background: var(--card); border: 1px dashed var(--rule);
}

button[kind="primary"] {
  background: var(--accent) !important; border-color: var(--accent) !important;
  font-weight: 600 !important; letter-spacing: .01em;
}

/* A disabled action should look inert, not like dark text on a pale slab.
   Streamlit's default leaves the label at full contrast, which reads as a
   broken button rather than an unavailable one. */
.stButton button:disabled, .stButton button[disabled],
.stDownloadButton button:disabled, button[kind="primary"]:disabled {
  background: var(--rule-soft) !important;
  border: 1px solid var(--rule) !important;
  color: var(--muted) !important;
  cursor: not-allowed !important;
  opacity: 1 !important;
  box-shadow: none !important;
}
.stButton button:disabled *, .stDownloadButton button:disabled *,
button[kind="primary"]:disabled * { color: var(--muted) !important; }
.stButton button:disabled:hover { background: var(--rule-soft) !important;
                                  border-color: var(--rule) !important; }

/* the host's Deploy control is noise in a procurement tool */
[data-testid="stAppDeployButton"], .stAppDeployButton,
[data-testid="stToolbarActions"] { display: none !important; }

[data-testid="stDataFrame"] { border: 1px solid var(--rule); }

code { font-family: var(--mono) !important; }
</style>
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _md(text: str) -> str:
    """Minimal markdown -> html for the strings we author ourselves."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped, flags=re.S)
    paragraphs = [p.strip() for p in escaped.split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)


def help_icon(term_key: str) -> str:
    """A small '?' that explains one term on hover or keyboard focus."""
    text = glossary.tip(term_key)
    if not text:
        return ""
    return (f'<span class="rfx-help rfx-tip" tabindex="0" role="note" '
            f'aria-label="{html.escape(text)}" '
            f'data-tip="{html.escape(text)}">?</span>')


def chip(label: str, tone: str = "mute", term_key: str = "") -> str:
    text = glossary.tip(term_key) if term_key else ""
    if text:
        return (f'<span class="rfx-chip rfx-tip {tone}" tabindex="0" '
                f'aria-label="{html.escape(label)}: {html.escape(text)}" '
                f'data-tip="{html.escape(text)}" style="cursor:help">'
                f"{html.escape(label)}</span>")
    return f'<span class="rfx-chip {tone}">{html.escape(label)}</span>'


STATUS_TONE = {
    "Confirmed": "ok",
    "Normalized": "info",
    "Needs Review": "warn",
    "Unresolved": "stop",
    "Not Quoted": "mute",
}

STATUS_TERM = {
    "Confirmed": "status_confirmed",
    "Normalized": "status_normalized",
    "Needs Review": "status_review",
    "Unresolved": "status_unresolved",
    "Not Quoted": "status_not_quoted",
}


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------

def masthead(page_line: str, meta: list[tuple[str, str]]) -> str:
    """The buyer's own name and category, then what this page does.

    Both pages carry the same headline on purpose: they are two halves of one
    sourcing event, and a masthead that changes identity between them would
    read as two different tools. Only `page_line` differs.
    """
    items = "".join(
        f"<span><b>{html.escape(value)}</b> {html.escape(label)}</span>"
        for value, label in meta
    )
    return (
        f'<div class="rfx-mast">'
        f'<div class="rfx-kicker">{html.escape(brand.kicker())}</div>'
        f"<h1>{html.escape(brand.COMPANY)}</h1>"
        f'<p class="rfx-sub rfx-tagline">{html.escape(brand.TAGLINE)}</p>'
        f'<p class="rfx-sub rfx-pageline">{html.escape(page_line)}</p>'
        f'<div class="rfx-meta">{items}</div>'
        f"</div>"
    )


def eyebrow(number: str, title: str, hint: str = "", term_key: str = "") -> str:
    tail = f'<span class="h">{html.escape(hint)}</span>' if hint else ""
    return (f'<div class="rfx-eyebrow"><span class="n">{html.escape(number)}</span>'
            f'<span class="t">{html.escape(title)}{help_icon(term_key)}</span>'
            f"{tail}</div>")


def stats(items: Iterable[tuple[str, str, str, str]]) -> str:
    """items: (value, label, tone, term_key); tone is '', 'accent' or 'warn'."""
    cells = "".join(
        f'<div class="rfx-stat">'
        f'<div class="v {tone}{" small" if len(value) > 9 else ""}">{html.escape(value)}</div>'
        f'<div class="l">{html.escape(label)}{help_icon(term_key)}</div></div>'
        for value, label, tone, term_key in items
    )
    return f'<div class="rfx-stats">{cells}</div>'


def glossary_panel(open_by_default: bool = False,
                   groups: Optional[list] = None,
                   blurb: str = "") -> str:
    """Every term on THIS page, for anyone who would rather read than hover.

    Deliberately loud: these pages are full of words a buyer has no reason to
    already know, and a thin grey bar labelled "glossary" gets ignored. But
    each page gets its own set — a panel listing terms that are not on screen
    is worse than no panel, because it teaches people to stop opening it.
    """
    groups = groups if groups is not None else glossary.GLOSSARY_GROUPS
    blocks = []
    for heading, entries in groups:
        rows = "".join(
            f'<div class="rfx-gl-row"><div class="t">{html.escape(label)}</div>'
            f'<div class="d">{html.escape(glossary.tip(key))}</div></div>'
            for label, key in entries
        )
        blocks.append(f'<div class="rfx-gl-group"><h4>{html.escape(heading)}</h4>'
                      f"{rows}</div>")

    term_count = sum(len(entries) for _, entries in groups)

    return (
        f'<details class="rfx-gl-wrap"{" open" if open_by_default else ""}>'
        f"<summary>"
        f'<span class="ico">?</span>'
        f'<span class="txt"><b>Help &amp; Guidance</b>'
        f"<i>{html.escape(blurb) if blurb else 'Plain-English definitions for every term on this page — comparable, read clarity, could not work it out, and the rest.'}</i></span>"
        f'<span class="tog"></span>'
        f"</summary>"
        f'<div class="rfx-gl-body">'
        f'<p class="rfx-gl-hint">{term_count} terms. You can also hover the '
        f"<b>?</b> beside any label on the page for the same explanation in place."
        f"</p>"
        f'<div class="rfx-glossary">{"".join(blocks)}</div>'
        f"</div></details>"
    )


def advisory(body: str, tone: str = "warn") -> str:
    """`body` is our own markdown: first paragraph becomes the heading."""
    parts = [p.strip() for p in body.split("\n\n") if p.strip()]
    heading = re.sub(r"\*\*(.+?)\*\*", r"\1", parts[0]) if parts else ""
    rest = "\n\n".join(parts[1:])
    return (f'<div class="rfx-advisory {tone}">'
            f'<div class="hd">{html.escape(heading)}</div>'
            f"{_md(rest)}</div>")


def supplier_cards(cards: list[dict]) -> str:
    blocks = []
    for card in cards:
        coverage_pct = round(100 * card["quoted"] / max(card["total"], 1))
        comparable_pct = round(100 * card["comparable"] / max(card["total"], 1))
        cover_tone = "ok" if coverage_pct == 100 else "warn"
        cleared = (chip("passed quality", "ok", "passed_quality") if card["cleared"]
                   else chip("not passed", "stop", "passed_quality"))
        currency_help = help_icon("currency_assumed") if card["currency"] == "not stated" else ""
        blocks.append(
            f'<div class="rfx-supplier">'
            f'<div class="nm">{html.escape(card["vendor"])}</div>'
            f'<div class="fmt">{html.escape(card["format"])}</div>'
            f"{cleared}"
            f'<div class="mt" style="margin-top:.85rem">'
            f'<span>priced{help_icon("priced")}</span>'
            f'<b>{card["quoted"]}/{card["total"]}</b></div>'
            f'<div class="rfx-bar {cover_tone}"><i style="width:{coverage_pct}%"></i></div>'
            f'<div class="mt" style="margin-top:.6rem">'
            f'<span>comparable{help_icon("comparable")}</span>'
            f'<b>{card["comparable"]}/{card["total"]}</b></div>'
            f'<div class="rfx-bar"><i style="width:{comparable_pct}%"></i></div>'
            f'<div class="mt" style="margin-top:.6rem">'
            f'<span>read clarity{help_icon("read_clarity")}</span>'
            f'<b>{card["confidence"]:.0%}</b></div>'
            f'<div class="rfx-bar ok"><i style="width:{card["confidence"] * 100:.0f}%"></i></div>'
            f'<div class="facts">'
            f'Delivery{help_icon("delivery")} <b>{html.escape(card["freight"])}</b><br>'
            f'Payment{help_icon("payment_terms")} <b>{html.escape(card["payment"])}</b><br>'
            f'Lead time{help_icon("lead_time")} <b>{html.escape(card["lead"])}</b><br>'
            f'Currency{currency_help} <b>{html.escape(card["currency"])}</b>'
            f"</div></div>"
        )
    return f'<div class="rfx-suppliers">{"".join(blocks)}</div>'


def quote_card(card: dict) -> str:
    tone = STATUS_TONE.get(card["status"], "mute")
    out = [f'<div class="rfx-quote {tone}">',
           f'<div class="nm">{html.escape(card["vendor"])}</div>',
           chip(card["status"], tone, STATUS_TERM.get(card["status"], ""))]

    label = f'<div class="lbl">Their exact words{help_icon("evidence")}</div>'
    if card["snippet"]:
        out.append(label)
        out.append(f"<blockquote>{html.escape(card['snippet'])}</blockquote>")
    else:
        out.append(label)
        out.append("<blockquote>— nothing written for this item —</blockquote>")

    if card["quoted"]:
        out.append('<div class="lbl">The numbers</div>')
        out.append(f'<div class="rfx-kv"><span>they wrote{help_icon("basis")}</span>'
                   f'<b>{html.escape(card["quoted"])} {html.escape(card["unit"] or "")}</b></div>')
        out.append(f'<div class="rfx-kv"><span>currency</span>'
                   f'<b>{html.escape(card["currency"] or "—")}</b></div>')
        out.append(f'<div class="rfx-kv">'
                   f'<span>comparable price{help_icon("comparable")}</span>'
                   f'<b>{html.escape(card["comparable_price"] or "cannot work out")}</b></div>')
        out.append(f'<div class="rfx-kv">'
                   f'<span>read clarity{help_icon("read_clarity")}</span>'
                   f'<b>{html.escape(card["confidence_label"])}</b></div>')
        if card.get("confidence_notes"):
            # A score with no reason behind it is just a number to distrust.
            out.append('<div class="why">Marked down because: '
                       + "; ".join(html.escape(n) for n in card["confidence_notes"])
                       + ".</div>")
        if card["factor"]:
            out.append(f'<div class="why">How we got there{help_icon("conversion")}: '
                       f'{html.escape(card["factor"])}</div>')

    if card["plain"]:
        out.append(f'<div class="why">{html.escape(card["plain"])}</div>')
    if card["missing"]:
        out.append(f'<div class="ask"><strong>Ask them for:</strong> '
                   f'{html.escape(card["missing"])}</div>')
    for flag in card["flags"]:
        out.append(f'<div class="why">⚑ {html.escape(flag)}</div>')
    if card["file"]:
        out.append(f'<div class="src">{html.escape(card["file"])} · '
                   f'{html.escape(card["locator"] or "")}</div>')

    out.append("</div>")
    return "".join(out)


ALLOCATION_COLOURS = ["#22417C", "#2C6942", "#8A570F", "#5B3A78", "#1F6C74",
                      "#93302B", "#4A5568"]


def ask_banner() -> str:
    """A loud front door for the analyst -- it is the point of the whole app."""
    return (
        '<div class="rfx-ask">'
        '<div class="ico">?</div>'
        '<div class="txt">'
        '<b>Ask anything about these responses, in plain language.</b>'
        '<i>The analyst does not read the table on screen. It writes real '
        'queries against the extracted data, so the arithmetic is done by the '
        'database and not guessed — and it shows you every query it ran '
        'underneath its answer.</i>'
        "</div></div>"
    )


def award_headline(plan, currency_symbol: str = "₹") -> str:
    lead = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(plan.headline()))

    bits: list[str] = []
    if plan.total_extended is not None:
        bits.append(f"Estimated spend {currency_symbol}{plan.total_extended:,.0f}")
    if plan.saving_vs_single is not None and plan.best_single_vendor:
        bits.append(
            f"about {currency_symbol}{plan.saving_vs_single:,.0f} less than giving "
            f"everything to {plan.best_single_vendor}, judged on the "
            f"{plan.common_basket} items all shortlisted suppliers priced"
        )
    sub = " · ".join(bits)

    return (f'<div class="rfx-award-head">'
            f'<div class="lead">We suggest awarding {lead}</div>'
            + (f'<div class="sub">{html.escape(sub)}</div>' if sub else "")
            + "</div>")


def review_key(reasons: list[tuple[str, str]]) -> str:
    """Why the ▲ prices need a human, in full, under the grid.

    Only the reasons actually present are listed: a fixed key would teach the
    buyer to skip it.
    """
    if not reasons:
        return ""
    rows = "".join(
        f'<div class="rfx-gl-row"><div class="t">▲ {html.escape(tag)}</div>'
        f'<div class="d">{html.escape(text)}</div></div>'
        for tag, text in reasons
    )
    return (f'<div class="rfx-working" style="margin-top:.6rem">'
            f'<div class="hd">Why some prices need a human</div>'
            f'<div class="rfx-glossary">{rows}</div>'
            f'<div class="foot">These prices are shown but held out of every '
            f'ranking and out of the recommended award. Click the row to read '
            f"the supplier's own wording, or open <b>Needs attention</b> for "
            f'the full list and what to ask for.</div></div>')


def saving_working(plan, currency_symbol: str = "₹") -> str:
    """The split-versus-one-supplier arithmetic, written out.

    A saving figure on its own invites the wrong reading -- buyers compare it
    against total spend, which is a different basket. So both totals, the
    basket they are measured on, and what is excluded are all on screen.
    """
    if plan.saving_vs_single is None or not plan.best_single_vendor:
        if plan.supplier_count < 2:
            body = ("Only one supplier is shortlisted, so there is nothing to "
                    "split and nothing to compare a split against.")
        elif not plan.common_basket:
            body = ("No single item was priced comparably by every shortlisted "
                    "supplier, so a like-for-like basket cannot be built. Chase "
                    "the gaps in <b>Needs attention</b> and this will fill in.")
        else:
            body = ("Quantities are missing for the shared items, so the two "
                    "baskets cannot be totalled.")
        return (f'<div class="rfx-working"><div class="hd">Split versus one '
                f'supplier</div><div class="foot">{body}</div></div>')

    def cash(value: float) -> str:
        return f"{currency_symbol}{value:,.0f}"

    total_lines = len(plan.lines)
    outside = total_lines - plan.common_basket
    share = (plan.saving_vs_single / plan.best_single_total
             if plan.best_single_total else 0.0)
    best = html.escape(plan.best_single_vendor)

    if not plan.common_quantities_known:
        rows_note = ("No supplier stated a quantity for some of these items, so "
                     "both totals are sums of unit prices rather than money. "
                     "The percentage is still right; the rupee figure is not a "
                     "spend. ")
    else:
        rows_note = ""

    rows = (
        f'<tr><td>All {plan.common_basket} shared items to {best} alone — the '
        f'cheapest any one supplier could do the whole basket for</td>'
        f'<td class="n">{cash(plan.best_single_total)}</td></tr>'
        f'<tr><td>The same {plan.common_basket} items split across suppliers, '
        f'each to whoever is cheapest on it</td>'
        f'<td class="n">{cash(plan.split_on_common)}</td></tr>'
        f'<tr class="total"><td>What splitting saves</td>'
        f'<td class="n">{cash(plan.saving_vs_single)} &nbsp;({share:.1%})</td></tr>'
    )

    foot = rows_note + (
        f"Measured only on the <b>{plan.common_basket} of {total_lines} items "
        f"every shortlisted supplier priced comparably</b> — the only basket "
        f"where the two options can be priced the same way."
    )
    if outside > 0:
        foot += (f" The other {outside} sit outside this sum because at least one "
                 f"supplier did not price them, so no single-supplier total exists "
                 f"for them. That is also why this saving is smaller than the "
                 f"estimated spend above, which covers every item recommended.")
    if plan.dropped_for_size:
        names = [html.escape(v) for v in plan.dropped_for_size]
        dropped = (names[0] if len(names) == 1
                   else " and ".join([", ".join(names[:-1]), names[-1]]))
        verb = "won" if len(names) == 1 else "each won"
        foot += (f" This is the split we actually recommend, not the theoretical "
                 f"cheapest: {dropped} {verb} too few items to be worth onboarding "
                 f"at your minimum of {plan.min_lines}, so those items moved to "
                 f"the next cheapest supplier and the saving above already "
                 f"carries that cost.")
    foot += (" Delivery charges and volume discounts are in neither total, "
             "because no supplier put a firm number on them.")

    return (f'<div class="rfx-working">'
            f'<div class="hd">Split versus one supplier — the working</div>'
            f'<table>{rows}</table>'
            f'<div class="foot">{foot}</div></div>')


def allocation_bar(plan) -> str:
    total = sum(v.line_count for v in plan.vendors)
    if not total:
        return ""
    segments, keys = [], []
    for index, entry in enumerate(plan.vendors):
        colour = ALLOCATION_COLOURS[index % len(ALLOCATION_COLOURS)]
        width = 100 * entry.line_count / total
        label = str(entry.line_count) if width > 5 else ""
        segments.append(f'<span style="width:{width:.4f}%;background:{colour}">{label}</span>')
        keys.append(f'<span><i style="background:{colour}"></i>'
                    f"{html.escape(entry.vendor)} — {entry.line_count} of {total} items</span>")
    return (f'<div class="rfx-allocation">{"".join(segments)}</div>'
            f'<div class="rfx-alloc-key">{"".join(keys)}</div>')


def award_cards(plan, currency_symbol: str = "₹") -> str:
    total = sum(v.line_count for v in plan.vendors) or 1
    blocks = []
    for index, entry in enumerate(plan.vendors):
        colour = ALLOCATION_COLOURS[index % len(ALLOCATION_COLOURS)]
        spend = (f"{currency_symbol}{entry.extended_total:,.0f}"
                 if entry.extended_total is not None else "spend not calculable")
        uncontested = (f"{len(entry.single_source_lines)} uncontested"
                       f"{help_icon('uncontested')}"
                       if entry.single_source_lines else "all contested")
        items = ", ".join(entry.lines)
        blocks.append(
            f'<div class="rfx-award-card" style="border-top-color:{colour}">'
            f'<div class="nm">{html.escape(entry.vendor)}</div>'
            f'<div class="big">{entry.line_count}</div>'
            f'<div class="sm">{"item" if entry.line_count == 1 else "items"} · '
            f"{entry.line_count / total:.0%} of the basket</div>"
            f'<div class="foot">{html.escape(spend)}<br>{uncontested}</div>'
            f'<div class="items">{html.escape(items)}</div>'
            f"</div>"
        )
    return f'<div class="rfx-award-cards">{"".join(blocks)}</div>'


def scorecard_cards(summaries, criteria_count: int) -> str:
    blocks = []
    for summary in sorted(summaries, key=lambda s: -s.quality_score):
        pct = summary.quality_score * 100
        tone = "good" if pct >= 80 else "mid" if pct >= 55 else "poor"
        answered = criteria_count - len(summary.unanswered)
        fails = (chip(f"misses {len(summary.hard_failures)} must-have", "stop")
                 if summary.hard_failures else "")
        blocks.append(
            f'<div class="rfx-score">'
            f'<div class="nm">{html.escape(summary.vendor)}</div>'
            f'<div class="big {tone}">{pct:.0f}</div>'
            f'<div class="sm">quality score{help_icon("quality_score")}</div>'
            f'{fails}'
            f'<div class="facts">'
            f'Answered <b>{answered}/{criteria_count}</b><br>'
            f'Gave a figure on <b>{summary.disclosed_figures}</b>'
            f'{help_icon("disclosure")}<br>'
            f'Read clarity <b>{summary.overall_confidence:.0%}</b>'
            f"</div></div>"
        )
    return f'<div class="rfx-scores">{"".join(blocks)}</div>'


def legend() -> str:
    """The status vocabulary. Every chip explains itself on hover."""
    return ('<div class="rfx-legend">'
            + chip("✓ cheapest on this line", "ok", "cheapest_on")
            + chip("as the RFx asked", "ok", "status_confirmed")
            + chip("we converted it", "info", "status_normalized")
            + chip("needs a human", "warn", "status_review")
            + chip("could not work it out", "stop", "status_unresolved")
            + chip("not priced", "mute", "status_not_quoted")
            + "</div>")


def draft_head(spec) -> str:
    """The request as it currently stands, above the editable tables."""
    title = html.escape(spec.title or "Untitled request")
    bits = []
    if spec.reference:
        bits.append(f"<span><b>{html.escape(spec.reference)}</b> reference</span>")
    bits.append(f"<span><b>{html.escape(spec.currency)}</b> quote currency</span>")
    bits.append(f"<span><b>{len(spec.lines)}</b> items</span>")
    if spec.criteria:
        bits.append(f"<span><b>{len(spec.criteria)}</b> questions</span>")
    if spec.delivery_location:
        bits.append(f"<span>deliver to <b>{html.escape(spec.delivery_location)}</b></span>")
    if spec.ends_at:
        bits.append(f"<span>closes <b>{html.escape(spec.stamp(spec.ends_at))}</b></span>")

    scope = (f'<div class="rfx-sub" style="font-size:.86rem;margin-top:.4rem">'
             f'{html.escape(spec.scope)}</div>' if spec.scope else "")

    return (f'<div class="rfx-award-head" style="border-left-color:var(--accent)">'
            f'<div class="lead" style="font-size:1.02rem"><strong>{title}</strong></div>'
            f'{scope}'
            f'<div class="rfx-meta" style="margin-top:.7rem;padding-top:.6rem">'
            f'{"".join(bits)}</div></div>')


def sources_note() -> str:
    """Where the items in a draft come from, and which source is not wired yet.

    The third row is the honest one. A buyer who asks for "thirty corrugated
    items" gets thirty from the model's own knowledge of the category, and the
    interface has to say so rather than let a tidy table imply a system of
    record stands behind it.
    """
    rows = [
        ("You say it",
         "Typed to the co-pilot, or edited straight into the table. The table "
         "and the conversation write to the same request, so you are never "
         "stuck in a chat to change a quantity.",
         "yours", "ok"),
        ("A file you already have",
         "A purchase order, a bill of materials, last year's contract. Read "
         "with the same readers the supplier quotes go through, and told "
         "explicitly never to pad a list to a round number.",
         "your file", "ok"),
        ("Items below their minimum stock level",
         "<b>Intended:</b> the co-pilot reads your warehouse system, finds "
         "every item under its reorder point, and drafts the request for the "
         "shortfall — which is how a replenishment RFx actually starts. "
         "<b>In this build that connection does not exist</b>, so items asked "
         "for this way come from the model's own knowledge of the category. "
         "They are marked <i>suggested</i>, kept out of the document sent to "
         "suppliers, and need a person to accept them.",
         "suggested", "warn"),
    ]
    body = "".join(
        f'<div class="rfx-gl-row">'
        f'<div class="t">{html.escape(name)}<br>'
        f'<span class="rfx-chip {tone}" style="margin-top:.3rem">{html.escape(tag)}</span>'
        f'</div>'
        f'<div class="d">{text}</div></div>'
        for name, text, tag, tone in rows
    )
    return (f'<details class="rfx-gl-wrap" style="margin-top:.8rem">'
            f'<summary><span class="ico">◧</span>'
            f'<span class="txt"><b>Where these items come from</b>'
            f'<i>Three sources, and one of them is not connected in this '
            f'build — worth knowing before you send anything.</i></span>'
            f'<span class="tog"></span></summary>'
            f'<div class="rfx-gl-body"><div class="rfx-glossary">{body}</div>'
            f'</div></details>')
