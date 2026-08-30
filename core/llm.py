"""Thin wrapper over the Gemini client.

Three things live here and nothing else:
  * model resolution (so a bad model ID surfaces at startup, not mid-demo)
  * a structured-JSON call, with the raw response kept on failure
  * a manual tool-calling loop, kept manual so every query the analyst runs
    can be logged and shown to the buyer
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from google import genai
from google.genai import types

from . import config

# The SDK logs a warning whenever function declarations reach
# `generate_content`, recommending Chat.send_message and its automatic function
# calling instead. We drive the loop by hand ON PURPOSE -- automatic calling
# would hide which tools ran, and showing the buyer every query behind an
# answer is the entire reason this application is trustworthy. AFC is disabled
# on every call we make (`AutomaticFunctionCallingConfig(disable=True)`), so
# the advice does not apply; some SDK versions log it regardless. Silencing
# just that one line, by exact subject, rather than muting the logger.
class _AfcAdviceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        return not ("automatic function calling" in message
                    and "not recommended" in message)


logging.getLogger("google_genai.models").addFilter(_AfcAdviceFilter())

# Model names are matched as substrings against the live list, and that list
# holds far more than chat models: image generators, music generators, speech,
# embeddings. "3-pro" matched "gemini-3-pro-image-preview" first, and then
# "lyria-3-pro-preview" -- a MUSIC model. Both accept a prompt happily and
# never issue a function call, so the analyst sat in front of a database it
# could not query.
#
# The rule here is an allow-list, not a block-list, because a block-list is a
# list of the surprises you have already had. A model qualifies only if its
# name begins with "gemini-" -- the text families this application is built on
# -- and does not name one of the non-text variants within that family.
_GEMINI_PREFIX = "gemini-"
_NOT_A_CHAT_MODEL = ("vision", "embedding", "embed", "image", "imagen",
                     "tts", "audio", "live", "computer-use", "aqa")


def usable_model(name: str) -> bool:
    """Is this a general text model we can hold a tool-calling conversation with?"""
    lowered = (name or "").lower()
    if not lowered.startswith(_GEMINI_PREFIX):
        return False
    return not any(bad in lowered for bad in _NOT_A_CHAT_MODEL)


_client: Optional[genai.Client] = None
_model_cache: dict[str, str] = {}
_available: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# client + model resolution
# ---------------------------------------------------------------------------

def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.require_api_key())
    return _client


def available_models(refresh: bool = False) -> list[str]:
    global _available
    if _available is None or refresh:
        models = []
        for m in client().models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                models.append(m.name.replace("models/", ""))
        _available = models
    return _available


_VERSION = re.compile(r"gemini-(\d+(?:\.\d+)?)")

# Models the API listed but then refused to serve. See _attempt().
_dead: set[str] = set()


def _version(name: str) -> float:
    """The version number in a model name, for ranking. 0.0 when unnumbered."""
    match = _VERSION.search(name.lower())
    return float(match.group(1)) if match else 0.0


def ranked_models(kind: str) -> list[str]:
    """Every model we could use for this job, best first.

    Ranked rather than looked up in a list of version strings, because that
    list has to be edited every time Google ships a version -- and when it is
    not, the application silently keeps asking for a model that has been
    withdrawn. Newest first, this job's branch of the family before the other,
    and a stable, non-preview build before a preview of the same version.
    """
    family = config.EXTRACT_FAMILY if kind == "extract" else config.ANALYST_FAMILY
    try:
        live = available_models()
    except Exception:
        live = []
    usable = [m for m in live if usable_model(m) and m not in _dead]
    return sorted(
        usable,
        key=lambda m: (family in m.lower(), _version(m), "preview" not in m.lower()),
        reverse=True,
    )


def resolve_model(kind: str) -> str:
    """Pick the best live model for this job.

    Falls back to the pinned value if the list call fails (some keys are not
    permitted to enumerate models), so a restricted key still works.
    """
    if kind in _model_cache:
        return _model_cache[kind]

    pin = config.MODEL_EXTRACT_PIN if kind == "extract" else config.MODEL_ANALYST_PIN
    chosen: Optional[str] = None

    if pin and pin not in _dead:
        chosen = pin
    else:
        ordered = ranked_models(kind)
        chosen = ordered[0] if ordered else None

    if not chosen:
        chosen = "gemini-flash-latest"

    _model_cache[kind] = chosen
    return chosen


# ---------------------------------------------------------------------------
# transient failures
# ---------------------------------------------------------------------------

# Gemini answers a busy moment with 503 UNAVAILABLE ("high demand"), a hammered
# key with 429, and an internal hiccup with 500. None of those mean the request
# was wrong, and all of them clear on their own. Treating them like a real
# error -- which is what a bare call does -- turns a two-second blip into a
# lost drafting turn and a message telling the buyer to check their API key.
_TRANSIENT_PHRASES = (
    "unavailable", "high demand", "overloaded", "try again later",
    "resource_exhausted", "rate limit",
    "internal error", "deadline", "timed out", "timeout",
)

# The status codes are matched as whole numbers, not as substrings. Looking for
# "500" anywhere in the message meant an INVALID_ARGUMENT complaint quoting a
# token count ("...exceeds the maximum of 1500000") read as a transient
# failure: nine attempts across three models, thirteen seconds of backoff, and
# then a message telling the buyer the models were busy rather than the one
# fact they needed -- that the document was too big.
_TRANSIENT_CODES = re.compile(r"(?<!\d)(429|500|503)(?!\d)")


def is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(phrase in text for phrase in _TRANSIENT_PHRASES):
        return True
    return bool(_TRANSIENT_CODES.search(text))


def candidate_models(kind: str) -> list[str]:
    """The model we want, then the ones we would accept instead.

    A 503 is usually specific to one model under load, so the second attempt
    should not be at the same door.
    """
    first = resolve_model(kind)
    others = [m for m in ranked_models(kind) if m != first]
    return [first] + others[:2]


# A model can be listed and still refuse to run. Google withdrew gemini-2.5-pro
# from new keys while continuing to list it, so the application asked for it,
# got a 404 naming a replacement, and stopped -- with the buyer reading a stack
# trace about a model ID. A listing is a claim; only a call is proof. So a
# refusal of the model itself is not an error to report, it is a fact to learn:
# the model is struck off and the next-best one is tried in the same breath.
_MODEL_GONE = (
    "not_found", "is not found", "no longer available", "not supported",
    "does not exist", "deprecated", "permission_denied",
)
_GONE_CODES = re.compile(r"(?<!\d)(400|403|404)(?!\d)")


def is_model_unavailable(exc: Exception) -> bool:
    """Did the API refuse THIS MODEL, rather than fail the request?"""
    text = f"{type(exc).__name__}: {exc}".lower()
    if not _GONE_CODES.search(text):
        return False
    return any(phrase in text for phrase in _MODEL_GONE)


def _attempt(call, kind: str, what: str, max_tries: int = 3):
    """Run one model call, riding out the failures that clear by themselves.

    Backs off between attempts, then moves to the next acceptable model. Only
    a failure that survives all of that is handed back to the caller -- and
    when it does, the message says which models were tried.
    """
    models = candidate_models(kind)
    tried: list[str] = []
    last: Optional[Exception] = None
    index = 0
    while index < len(models):
        model = models[index]
        index += 1
        if model in _dead:
            continue
        tried.append(model)
        for attempt in range(max_tries):
            try:
                return call(model)
            except Exception as exc:
                last = exc
                if is_model_unavailable(exc):
                    # Struck off for the life of the process, and the cached
                    # choice cleared so the next call re-resolves rather than
                    # walking into the same wall.
                    _dead.add(model)
                    _model_cache.pop(kind, None)
                    for replacement in candidate_models(kind):
                        if replacement not in tried and replacement not in models:
                            models.append(replacement)
                    break
                if not is_transient(exc):
                    raise
                if attempt < max_tries - 1:
                    time.sleep(1.5 * (2 ** attempt))     # 1.5s, 3s
        # that model is busy or gone; try the next one

    listed = ", ".join(tried) or "no usable model"
    if last is not None and is_transient(last):
        raise RuntimeError(
            f"{what} failed after retrying on {listed}. The models are busy rather "
            f"than broken \u2014 this usually clears within a minute. Last error: {last}"
        ) from last
    raise RuntimeError(
        f"{what} failed on {listed}. Every model this key can see was either "
        f"withdrawn or refused the request. Last error: {last}"
    ) from last


def doctor() -> dict[str, Any]:
    """Startup self-check. Surfaced in the UI sidebar and by `python -m core.llm`."""
    out: dict[str, Any] = {"api_key_present": bool(config.GEMINI_API_KEY)}
    # Re-resolve from scratch. The first call of the process may have been made
    # while the key was missing or the network down, and the fallback it picked
    # ("gemini-2.5-flash", a guess) was then cached for the life of the server:
    # pressing "Run connection check" after fixing the key reported that guess
    # back as the model in use, for as long as the app stayed up.
    _model_cache.clear()
    try:
        models = available_models(refresh=True)
        out["models_visible"] = len(models)
        out["sample"] = models[:12]
        out["extract_model"] = resolve_model("extract")
        out["analyst_model"] = resolve_model("analyst")
        out["ok"] = True
    except Exception as exc:  # network, auth, proxy...
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["extract_model"] = config.MODEL_EXTRACT_PIN or "gemini-2.5-flash"
        out["analyst_model"] = config.MODEL_ANALYST_PIN or "gemini-2.5-flash"
    return out


# ---------------------------------------------------------------------------
# structured JSON
# ---------------------------------------------------------------------------

class ExtractionError(RuntimeError):
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def generate_json(
    prompt: str,
    images: Optional[list[bytes]] = None,
    image_mime: str = "image/jpeg",
    kind: str = "extract",
    retries: int = 2,
) -> dict[str, Any]:
    """Ask for JSON and insist on getting it.

    On a parse failure the raw text is attached to the exception so the UI can
    show what actually came back rather than a bare stack trace.
    """
    parts: list[Any] = [prompt]
    for blob in images or []:
        parts.append(types.Part.from_bytes(data=blob, mime_type=image_mime))

    last_raw = ""
    for attempt in range(retries + 1):
        try:
            response = _attempt(
                lambda model: client().models.generate_content(
                    model=model,
                    contents=parts,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                    ),
                ),
                kind, "Reading the document")
            last_raw = response.text or ""
            return json.loads(last_raw)
        except json.JSONDecodeError:
            # Occasionally a model fences the JSON despite the mime type.
            cleaned = _strip_fence(last_raw)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                if attempt == retries:
                    raise ExtractionError(
                        "Model did not return valid JSON.", raw=last_raw[:4000]
                    )
                time.sleep(1.0 * (attempt + 1))
        except Exception as exc:
            if attempt == retries:
                raise ExtractionError(f"{type(exc).__name__}: {exc}", raw=last_raw[:4000])
            time.sleep(1.5 * (attempt + 1))
    raise ExtractionError("unreachable")


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


# ---------------------------------------------------------------------------
# tool-calling loop
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    result: Any
    error: Optional[str] = None


@dataclass
class ToolLoopResult:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    rounds: int = 0


def run_tool_loop(
    system_prompt: str,
    user_message: str,
    tools: dict[str, Callable[..., Any]],
    declarations: list[types.FunctionDeclaration],
    kind: str = "analyst",
    max_rounds: int = 8,
    history: Optional[list[dict[str, str]]] = None,
) -> ToolLoopResult:
    """Manual function-calling loop.

    Automatic function calling would be fewer lines, but the whole point of
    this design is that the buyer can see which queries produced the answer.
    So we drive it by hand and keep every call.

    `history` is an optional list of {"role": "user"|"model", "text": ...} from
    earlier turns. The analyst answers one question at a time and passes none;
    the drafting co-pilot is a conversation and passes all of it, because "make
    that one 8,000 instead" only means something after the turn before it.
    """
    contents: list[types.Content] = []
    for turn in history or []:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        role = "model" if turn.get("role") == "model" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_message)])
    )
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    recorded: list[ToolCall] = []

    for round_index in range(max_rounds):
        response = _attempt(
            lambda model: client().models.generate_content(
                model=model, contents=contents, config=cfg),
            kind, "The model call")

        candidate = (response.candidates or [None])[0]
        if candidate is None or not candidate.content:
            return ToolLoopResult(text=response.text or "", calls=recorded,
                                  rounds=round_index + 1)

        contents.append(candidate.content)

        fcalls = [p.function_call for p in (candidate.content.parts or [])
                  if getattr(p, "function_call", None)]

        if not fcalls:
            return ToolLoopResult(text=response.text or "", calls=recorded,
                                  rounds=round_index + 1)

        reply_parts: list[types.Part] = []
        for call in fcalls:
            name = call.name
            args = dict(call.args or {})
            fn = tools.get(name)
            if fn is None:
                payload: dict[str, Any] = {"error": f"unknown tool {name}"}
                recorded.append(ToolCall(name, args, None, payload["error"]))
            else:
                try:
                    value = fn(**args)
                    payload = {"result": value}
                    recorded.append(ToolCall(name, args, value))
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    payload = {"error": message}
                    recorded.append(ToolCall(name, args, None, message))

            reply_parts.append(
                types.Part.from_function_response(name=name, response=payload)
            )

        contents.append(types.Content(role="user", parts=reply_parts))

    return ToolLoopResult(
        text="I ran out of query rounds before reaching a conclusion. "
             "Please narrow the question.",
        calls=recorded,
        rounds=max_rounds,
    )


if __name__ == "__main__":  # python -m core.llm
    import pprint
    pprint.pp(doctor())
