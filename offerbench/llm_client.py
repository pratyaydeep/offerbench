import json
import logging
import re
import time

import httpx

from offerbench.config import Provider
from offerbench.models import ExtractionResult

logger = logging.getLogger(__name__)

_JSON_SCHEMA_EXAMPLE = """{
  "post_kind": "comparison",
  "years_experience": 2.0,
  "location": "Bengaluru, India",
  "offers": [
    {
      "organization": "Amazon",
      "role_title": "SDE 1",
      "level_grade": null,
      "currency": "INR",
      "total_ctc": 2942000,
      "fixed_base": 1917000,
      "variable_bonus": null,
      "stock_rsu": 1500000,
      "signing_bonus": 1150000,
      "retirement_benefits": null,
      "confidence": 0.85,
      "notes": null
    },
    {
      "organization": "Gojek",
      "role_title": "Associate Software Engineer",
      "level_grade": null,
      "currency": "INR",
      "total_ctc": 2722279,
      "fixed_base": 2222279,
      "variable_bonus": 200000,
      "stock_rsu": null,
      "signing_bonus": 300000,
      "retirement_benefits": null,
      "confidence": 0.85,
      "notes": null
    }
  ]
}"""

SYSTEM_PROMPT = f"""You extract structured compensation data from a single \
LeetCode discuss-forum post.

Respond with ONLY a single JSON object matching the schema below — no \
markdown code fences, no commentary before or after, just the raw JSON.

Schema (example shown for a comparison post with two offers):
{_JSON_SCHEMA_EXAMPLE}

Most posts describe exactly one offer/company, so `offers` will usually \
have exactly one entry. Some are comparison posts ("Amazon vs Gojek", \
"Offer Evaluation - Oracle vs Adobe") that describe TWO OR MORE distinct \
offers. Output one entry in `offers` per distinct company/offer mentioned \
with its own numbers — never merge two companies' figures into one entry, \
and never drop one of them just because there are multiple. If the post \
genuinely contains no concrete offer (e.g. a pure question with no numbers \
disclosed), `offers` should be an empty list: [].

`post_kind`, `years_experience`, and `location` describe the post/poster as \
a whole (the same person, even when comparing multiple offers) and are set \
once at the top level, not repeated per offer. Any of them may be null if \
not stated.

Rules (apply per offer entry):
- Only extract values that are explicitly stated or can be directly, \
unambiguously inferred from the text. Never invent or estimate a number \
that isn't grounded in the text. If a field is absent, use null.
- If multiple numbers could plausibly fill total_ctc for the same offer \
(e.g. ambiguous "CTC" vs "in-hand"), prefer the figure most clearly labeled \
as total annual compensation, and note the ambiguity in `notes`.
- Report all monetary fields (total_ctc, fixed_base, variable_bonus, \
stock_rsu, signing_bonus, retirement_benefits) as plain absolute numbers in \
the stated currency's base unit (e.g. plain rupees, plain dollars) — \
convert shorthand like "44.5 LPA" or "12L" or "1.2 Cr" into the absolute \
number yourself (44.5 LPA -> 4450000). Do not report figures still in \
lakhs/crore/k shorthand.
- Set `currency` to your best read of the currency: "INR" or "USD". Assume \
INR if rupee symbols, "LPA", or lakhs/crore shorthand are used without an \
explicit denomination — this is the overwhelmingly common case on this \
forum. Use null only if you cannot tell at all.
- Set `confidence` (0-1) per offer, reflecting your certainty for that \
specific offer's fields. Lower it for vague, sarcastic, or heavily-inferred \
figures.

`post_kind`: "accepted_offer" if the poster describes an offer they \
received/accepted, "current_comp" if describing their current package, \
"question" if primarily asking for advice without disclosing firm numbers, \
"comparison" if comparing multiple offers, "other" otherwise.
"""

_http_client: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        # NVIDIA build has been observed to have long gaps both before the
        # first chunk and mid-stream -- generous headroom here since this
        # is a per-read timeout, not a cap on total stream duration.
        _http_client = httpx.Client(timeout=180.0)
    return _http_client


def _extract_json_object(raw: str) -> str:
    """Strips markdown code fences and surrounding chatter some models add
    even when told not to, leaving just the JSON object body."""
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


def _stream_content(provider: Provider, messages: list[dict]) -> str:
    """Streams the completion via a raw SSE POST rather than the openai
    SDK's typed chunk model, because some providers (observed on both
    NVIDIA build and OpenRouter) inject a mid-stream {"error": {...}} event
    under HTTP 200 when the upstream provider drops the connection. Parsing
    raw lets us catch that and raise it with the real message, instead of
    it silently looking like an empty response."""
    client = _get_http_client()
    payload = {"model": provider.model, "messages": messages, "stream": True}
    parts: list[str] = []
    with client.stream(
        "POST",
        f"{provider.base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[len("data: ") :]
            if data == "[DONE]":
                break
            obj = json.loads(data)
            if obj.get("error"):
                err = obj["error"]
                raise RuntimeError(
                    f"Provider error mid-stream: {err.get('message')} (code={err.get('code')})"
                )
            choices = obj.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            if choice.get("finish_reason") == "error":
                raise RuntimeError("Provider reported finish_reason=error mid-stream")
            delta = (choice.get("delta") or {}).get("content")
            if delta:
                parts.append(delta)
    return "".join(parts)


def _try_provider(provider: Provider, title: str, content: str) -> ExtractionResult:
    """One provider, up to 2 attempts: an initial call, plus one retry where
    the model is asked to correct its own malformed JSON. Any transient
    error (connection/timeout/mid-stream provider error/empty response)
    raises immediately -- that's the caller's signal to move to the next
    provider, not something worth retrying on the same one."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Title: {title}\n\nContent:\n{content}"},
    ]

    raw = _stream_content(provider, messages)
    if not raw:
        raise RuntimeError("Model returned an empty response")

    json_str = _extract_json_object(raw)
    try:
        return ExtractionResult.model_validate_json(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        logger.info("    [%s] invalid JSON, asking model to correct: %s", provider.label, e)
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That was not valid JSON matching the schema ({e}). "
                    "Respond with ONLY the corrected JSON object, nothing else."
                ),
            }
        )
        raw = _stream_content(provider, messages)
        if not raw:
            raise RuntimeError("Model returned an empty response on correction retry")
        return ExtractionResult.model_validate_json(_extract_json_object(raw))


def extract_offer(
    title: str,
    content: str,
    providers: list[Provider],
    max_rounds: int = 5,
    cooldown_s: float = 60.0,
    pace_s: float = 1.0,
) -> tuple[ExtractionResult, Provider]:
    """Tries each provider in order; on failure, paces `pace_s` seconds and
    moves to the next. If every provider in the list fails (one full
    "round"), waits `cooldown_s` before starting the list over again, up to
    `max_rounds` total rounds before giving up entirely. Returns the result
    together with whichever provider actually produced it."""
    if not providers:
        raise RuntimeError("No LLM providers configured")

    last_error: Exception | None = None
    for round_num in range(1, max_rounds + 1):
        for provider in providers:
            try:
                result = _try_provider(provider, title, content)
                logger.info("  [%s] ok", provider.label)
                time.sleep(pace_s)  # pace every call, success or failure
                return result, provider
            except Exception as e:
                last_error = e
                logger.info("  [%s] failed: %s", provider.label, e)
            time.sleep(pace_s)

        if round_num < max_rounds:
            logger.info(
                "  round %d/%d: all %d provider(s) failed, cooling down %.0fs",
                round_num, max_rounds, len(providers), cooldown_s,
            )
            time.sleep(cooldown_s)

    raise RuntimeError(
        f"All providers failed after {max_rounds} round(s): {last_error}"
    )
