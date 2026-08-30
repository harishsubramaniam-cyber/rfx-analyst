"""End-to-end: files in, comparison out, database written."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import assemble, config, derive, dispatch, extract, ingest, store
from . import rfx as rfx_module
from .assemble import Comparison
from .models import DocumentPayload, VendorResponse


@dataclass
class FileOutcome:
    filename: str
    ok: bool
    reader: str = ""
    warnings: list[str] = field(default_factory=list)
    lines_found: int = 0
    vendor: str = ""
    error: str = ""
    supporting: bool = False   # readable, but contains no prices
    token: str = ""            # set ONLY when the reply quoted its reference
    identified_by: str = ""    # "token" | "name" | "" (no invitation matched)


@dataclass
class RunResult:
    comparison: Optional[Comparison]
    outcomes: list[FileOutcome] = field(default_factory=list)
    db_path: Optional[str] = None

    supporting: list[str] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.ok)


def process_one(handle, filename: str,
                invitations: Optional[list] = None
                ) -> tuple[Optional[VendorResponse], FileOutcome]:
    payload: DocumentPayload = ingest.load(handle, filename)

    outcome = FileOutcome(filename=filename, ok=False, reader=payload.reader,
                          warnings=list(payload.warnings))

    if not payload.has_content:
        outcome.error = "No readable content could be extracted from this file."
        return None, outcome

    try:
        response = extract.extract(payload)
    except Exception as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
        return None, outcome

    outcome.ok = True

    # If this request was actually sent, a reply carries the token we put in
    # the invitation. An identifier beats reading a supplier's name off their
    # own letterhead, so when we find one it wins.
    if invitations:
        invitation, basis = dispatch.identify(payload.text or "", invitations)
        if invitation is not None:
            # The token is recorded only when the reply actually quoted one.
            # A name read off a letterhead ties the reply to a supplier just
            # as usefully, but it is a guess, and saying "quote reference"
            # over a guess is exactly the confusion the reference removes.
            outcome.token = invitation.token if basis == "token" else ""
            outcome.identified_by = basis
            invitation.responded = True
            invitation.response_files.append(filename)
            if response.vendor != invitation.vendor.name:
                outcome.warnings.append(
                    f"Identified as {invitation.vendor.name} from the quote "
                    f"reference in their reply."
                    if basis == "token" else
                    f"Read as {invitation.vendor.name} from the supplier name "
                    f"in the document. Their reply did not quote its reference, "
                    f"so this is a match on the letterhead rather than an "
                    f"identification — worth confirming.")
            response.vendor = invitation.vendor.name

    outcome.vendor = response.vendor
    outcome.lines_found = len(response.lines)
    # A certificate or test report is a perfectly valid thing to be handed; it
    # is just not a quotation. Say so instead of showing it as a supplier with
    # nothing priced.
    outcome.supporting = not response.lines
    if response.extraction_notes:
        outcome.warnings.append(response.extraction_notes)
    return response, outcome


def run(
    files: list[tuple[Any, str]],
    db_path: Optional[str] = None,
    adjudicate: Optional[Callable] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
    build_spine: bool = True,
    invitations: Optional[list] = None,
) -> RunResult:
    """Process uploaded files into a persisted comparison.

    `files` is a list of (file-like, filename) pairs.

    With `build_spine` (the default) the item list being compared is assembled
    from the responses themselves, so any category and any number of suppliers
    works. Pass False when a specific request has already been loaded with
    rfx.set_active().
    """
    responses: list[VendorResponse] = []
    outcomes: list[FileOutcome] = []

    # Each run starts from a clean slate: the comparison spine belongs to this
    # set of responses, not to whatever was analysed before it.
    if build_spine:
        rfx_module.reset_active()

    for index, (handle, filename) in enumerate(files):
        if progress:
            progress(index, len(files), filename)
        response, outcome = process_one(handle, filename, invitations=invitations)
        outcomes.append(outcome)
        if response is not None and response.lines:
            responses.append(response)

    if progress:
        progress(len(files), len(files), "")

    supporting = [o.filename for o in outcomes if o.ok and o.supporting]

    if not responses:
        return RunResult(comparison=None, outcomes=outcomes, supporting=supporting)

    if build_spine:
        rfx_module.set_active(derive.derive_spec(responses))

    comparison = assemble.build(responses, adjudicate=adjudicate)
    path = store.write(comparison, path=db_path or config.DB_PATH)
    return RunResult(comparison=comparison, outcomes=outcomes, db_path=path,
                     supporting=supporting)


def run_paths(paths: list[str], **kwargs) -> RunResult:
    handles = []
    try:
        for path in paths:
            handles.append((open(path, "rb"), os.path.basename(path)))
        return run(handles, **kwargs)
    finally:
        for handle, _ in handles:
            handle.close()
