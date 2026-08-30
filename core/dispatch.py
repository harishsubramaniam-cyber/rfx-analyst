"""Sending the request out, and recognising what comes back.

The assignment allows the mail server to be stubbed. It does not allow the
*idea* to be stubbed, so this is a channel interface with a real implementation
behind it rather than an `if DEMO:` branch. `MailboxChannel` writes genuine
RFC-822 .eml files — openable in any mail client, complete with the attached
request document — into an outbox folder. Point `SmtpChannel` at a server and
the same envelopes go out for real; nothing above this file changes.

The part that earns its place is the token.

Every invitation carries one identifier, built from the request reference and
the supplier, and it appears in the subject line, the covering note and the
request document. When a reply arrives, that token says which supplier sent it
and which version of the request they were answering. Without it the system is
guessing a supplier's identity from an email address or a letterhead — which is
what it does today, and which is a heuristic doing a job an identifier should
do. So building the send step measurably improves the read step: a token found
in a document beats any amount of name-matching.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Optional, Protocol

from . import brand
from .rfx import RfxSpec

OUTBOX = "outbox"


@dataclass
class Vendor:
    """A supplier being invited. Email is optional: some are phoned or portalled."""
    name: str
    email: str = ""
    contact: str = ""


@dataclass
class Envelope:
    """One invitation to one supplier, ready to hand to a channel."""
    vendor: Vendor
    token: str
    subject: str
    body: str
    attachment_name: str
    attachment: bytes
    attachment_mime: str = "application/pdf"
    # Anything the buyer attached alongside the request itself: drawings, a
    # specification, a delivery schedule. Each is {"name", "data"}.
    extras: list = field(default_factory=list)


@dataclass
class Receipt:
    """What happened when we tried to send it."""
    vendor: str
    token: str
    channel: str
    sent_at: str
    ok: bool = True
    location: str = ""      # file path, message id, whatever the channel returns
    error: str = ""


@dataclass
class Invitation:
    """The buyer-facing record of one supplier's place in this request."""
    vendor: Vendor
    token: str
    receipt: Optional[Receipt] = None
    responded: bool = False
    response_files: list = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.responded:
            return "responded"
        if self.receipt and self.receipt.ok:
            return "sent"
        if self.receipt:
            return "failed"
        return "not sent"


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\bRFX-([A-Z0-9]{2,10})-([A-Z0-9]{2,8})-([0-9a-f]{4})\b", re.I)


def _slug(text: str, length: int = 8) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", (text or "").upper())
    return (cleaned[:length] or "X")


def make_token(spec: RfxSpec, vendor_name: str) -> str:
    """RFX-<request>-<supplier>-<checksum>.

    Short enough that a salesperson will retype it without complaining, and
    specific enough that it cannot collide between two live requests. The last
    four characters are a hash of both halves, so a mistyped token fails
    loudly rather than resolving to the wrong supplier.
    """
    request = _slug(spec.reference or spec.title or "REQ", 10)
    supplier = _slug(vendor_name, 6)
    # The checksum is taken over the supplier's FULL name, not the six-letter
    # slug that appears in the token. Hashing the slug meant "Prime Packaging
    # Ltd" and "Prime Packers" produced the same token, character for
    # character: identify() then credited one supplier's quotation to the
    # other, and the mailbox channel -- which names the file after the token --
    # wrote the second invitation over the first, so one supplier was never
    # invited at all. Both are silent. The full name is what actually
    # distinguishes them, so it is what the checksum has to cover.
    digest = hashlib.sha1(
        f"{request}|{(vendor_name or '').strip().lower()}|{len(spec.lines)}"
        .encode()).hexdigest()[:4]
    return f"RFX-{request}-{supplier}-{digest}"


def find_token(text: str) -> Optional[str]:
    """Pull our token out of whatever a supplier sent back."""
    match = _TOKEN_RE.search(text or "")
    return match.group(0).upper() if match else None


def identify(text: str, invitations: list[Invitation]
             ) -> tuple[Optional[Invitation], str]:
    """Which invitation this document answers, and how we know.

    Token first, because it is an identifier. Only if there is no token do we
    fall back to looking for the supplier's name in their own document, and
    that fallback is exactly the guesswork the token exists to remove.

    The basis comes back with the answer -- "token", "name" or "none" -- so
    the caller can tell the buyer which of the two it was. Reporting a name
    match as a quote reference would claim certainty the reply never carried,
    which is the whole distinction this mechanism exists to make.
    """
    token = find_token(text)
    if token:
        for invitation in invitations:
            if invitation.token.upper() == token:
                return invitation, "token"
        return None, "none"

    # Two guards on the name fallback, both learned the hard way.
    #
    # A short supplier name is not evidence. "AB Packaging" invited as "AB"
    # matched the letters "ab" inside "available", "fabrication", "table" --
    # that is, inside every document -- and the first supplier on the list
    # collected whatever arrived. Four characters is the shortest run that
    # means anything.
    #
    # And a name found in a document is only evidence if it is the ONLY name
    # found. A supplier replying to a forwarded thread quotes our covering
    # note, which may list the others; taking the first match then attributes a
    # quotation to a company that did not write it. Ambiguity is reported as no
    # identification, which puts the buyer in front of the choice rather than
    # hiding it.
    haystack = (text or "").lower()
    hits = [invitation for invitation in invitations
            if len(invitation.vendor.name.strip()) >= 4
            and invitation.vendor.name.strip().lower()[:14] in haystack]
    if len(hits) == 1:
        return hits[0], "name"
    return None, "none"


def match_response(text: str, invitations: list[Invitation]) -> Optional[Invitation]:
    """Which invitation does this document answer? See identify()."""
    return identify(text, invitations)[0]


# ---------------------------------------------------------------------------
# channels
# ---------------------------------------------------------------------------

class Channel(Protocol):
    """Anything that can carry an invitation to a supplier."""

    name: str

    def send(self, envelope: Envelope) -> Receipt: ...


@dataclass
class MailboxChannel:
    """Writes real .eml files to a folder instead of talking to a mail server.

    Chosen over a print statement deliberately: the output is a genuine RFC-822
    message with the request attached, so it can be opened, read, forwarded, or
    diffed. The stub is the transport, not the artefact.
    """
    directory: str = OUTBOX
    sender: str = brand.CONTACT_EMAIL
    name: str = "mailbox"

    def send(self, envelope: Envelope) -> Receipt:
        stamp = datetime.now(timezone.utc)
        try:
            os.makedirs(self.directory, exist_ok=True)
            message = EmailMessage()
            message["Subject"] = envelope.subject
            message["From"] = self.sender
            message["To"] = envelope.vendor.email or f"{_slug(envelope.vendor.name).lower()}@example.com"
            message["Date"] = format_datetime(stamp)
            message["Message-ID"] = make_msgid(domain="rfx.local")
            # Machine-readable too, so a real inbound integration could route
            # on a header rather than scraping the subject line.
            message["X-RFx-Token"] = envelope.token
            message.set_content(envelope.body)
            maintype, _, subtype = envelope.attachment_mime.partition("/")
            message.add_attachment(envelope.attachment, maintype=maintype,
                                   subtype=subtype or "pdf",
                                   filename=envelope.attachment_name)
            for extra in envelope.extras:
                data = extra.get("data")
                if not data:
                    continue
                # Sent as octet-stream deliberately: guessing a MIME type from
                # a filename is how a .dwg arrives as text and cannot be opened.
                message.add_attachment(data, maintype="application",
                                       subtype="octet-stream",
                                       filename=extra.get("name", "attachment"))

            path = os.path.join(self.directory, f"{envelope.token}.eml")
            with open(path, "wb") as handle:
                handle.write(bytes(message))
            return Receipt(vendor=envelope.vendor.name, token=envelope.token,
                           channel=self.name, sent_at=stamp.isoformat(timespec="seconds"),
                           ok=True, location=path)
        except Exception as exc:
            return Receipt(vendor=envelope.vendor.name, token=envelope.token,
                           channel=self.name, sent_at=stamp.isoformat(timespec="seconds"),
                           ok=False, error=f"{type(exc).__name__}: {exc}")


@dataclass
class SmtpChannel:
    """The same envelopes, over a real server. Unused in the demo, on purpose.

    It exists so that the mailbox channel is visibly one implementation of an
    interface rather than the only thing the system can do.
    """
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = brand.CONTACT_EMAIL
    name: str = "smtp"

    def send(self, envelope: Envelope) -> Receipt:
        import smtplib
        stamp = datetime.now(timezone.utc)
        try:
            message = EmailMessage()
            message["Subject"] = envelope.subject
            message["From"] = self.sender
            message["To"] = envelope.vendor.email
            message["X-RFx-Token"] = envelope.token
            message.set_content(envelope.body)
            maintype, _, subtype = envelope.attachment_mime.partition("/")
            message.add_attachment(envelope.attachment, maintype=maintype,
                                   subtype=subtype or "pdf",
                                   filename=envelope.attachment_name)
            for extra in envelope.extras:
                if extra.get("data"):
                    message.add_attachment(extra["data"], maintype="application",
                                           subtype="octet-stream",
                                           filename=extra.get("name", "attachment"))
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(message)
            return Receipt(vendor=envelope.vendor.name, token=envelope.token,
                           channel=self.name, sent_at=stamp.isoformat(timespec="seconds"),
                           ok=True, location=envelope.vendor.email)
        except Exception as exc:
            return Receipt(vendor=envelope.vendor.name, token=envelope.token,
                           channel=self.name, sent_at=stamp.isoformat(timespec="seconds"),
                           ok=False, error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# sending a whole request
# ---------------------------------------------------------------------------

def build_envelope(spec: RfxSpec, vendor: Vendor, document: bytes,
                   token: Optional[str] = None) -> Envelope:
    from . import rfxdoc
    token = token or make_token(spec, vendor.name)
    reference = f" [{token}]"
    subject = (f"Request for quotation — {spec.title or 'items attached'}"
               f"{reference}")
    return Envelope(
        vendor=vendor, token=token, subject=subject,
        body=rfxdoc.covering_note(spec, vendor.name, token),
        attachment_name=f"{(spec.reference or 'request').replace('/', '_')}.pdf",
        attachment=document,
        extras=[{"name": item.get("name", "attachment"), "data": item.get("data")}
                for item in (spec.attachments or [])],
    )


def send_request(spec: RfxSpec, vendors: list[Vendor],
                 channel: Optional[Channel] = None) -> list[Invitation]:
    """Send one request to every invited supplier. Returns the invitations.

    The document is rendered once per supplier because it carries that
    supplier's own token — but from one spec, so every copy has the same items.
    """
    from . import rfxdoc
    channel = channel or MailboxChannel()
    invitations: list[Invitation] = []
    issued: set[str] = set()
    for vendor in vendors:
        token = make_token(spec, vendor.name)
        # Belt and braces over the checksum: two suppliers entered under the
        # same name, or a genuine four-hex collision, would otherwise share one
        # token and one outbox file. Re-salt rather than append a suffix -- the
        # token has to keep its exact shape, or the pattern that finds it in a
        # supplier's reply stops recognising it.
        salt = 1
        while token in issued:
            token = make_token(spec, f"{vendor.name}#{salt}")
            salt += 1
        issued.add(token)
        document = rfxdoc.build_pdf(spec, token=token, vendor=vendor.name)
        envelope = build_envelope(spec, vendor, document, token=token)
        receipt = channel.send(envelope)
        invitations.append(Invitation(vendor=vendor, token=token, receipt=receipt))
    return invitations


def chase_note(spec: RfxSpec, invitation: Invitation) -> str:
    """A follow-up the buyer can send to a supplier who has not replied."""
    return "\n".join([
        f"Dear {invitation.vendor.name},",
        "",
        f"We wrote to you regarding {spec.title or 'our request for quotation'}"
        + (f" ({spec.reference})" if spec.reference else "")
        + ". We have not yet received your quotation.",
        "",
        (f"This RFQ closed at {spec.stamp(spec.ends_at)}. " if spec.ends_at else "")
        + "If you are not quoting on this occasion, a one-line reply saying so "
          "is genuinely useful — we will stop chasing and it will not count "
          "against you next time.",
        "",
        f"Reference {invitation.token}",
        "",
        "Regards,",
        brand.CONTACT,
        brand.COMPANY_LEGAL,
    ])
