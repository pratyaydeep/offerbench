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
      "total_ctc": 29.42,
      "fixed_base": 19.17,
      "variable_bonus": null,
      "stock_rsu": 15.0,
      "signing_bonus": 11.5,
      "retirement_benefits": null,
      "confidence": 0.85,
      "notes": null
    },
    {
      "organization": "Gojek",
      "role_title": "Associate Software Engineer",
      "level_grade": null,
      "currency": "INR",
      "total_ctc": 27.22,
      "fixed_base": 22.22,
      "variable_bonus": 2.0,
      "stock_rsu": null,
      "signing_bonus": 3.0,
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
- If currency is INR, report all monetary fields (total_ctc, fixed_base, \
variable_bonus, stock_rsu, signing_bonus, retirement_benefits) as a number \
of LAKHS (1 lakh = 100,000 rupees) — matching how these posts are usually \
already written. "44.5 LPA" -> 44.5, "12L" -> 12, "1.2 Cr" -> 120, an \
absolute figure like "22,22,279" -> 22.22. If currency is USD, report \
monetary fields as plain absolute dollars (no lakhs conversion — lakhs is \
an INR-only concept). Approximate is fine; getting the right order of \
magnitude and roughly the right value matters more than precision.
- Stock/RSU figures are the most common source of unit mistakes — they're \
often phrased awkwardly ("15 lakh vested over 4 years", "$15k RSU/yr"). \
Convert to the SAME unit and SAME total-grant basis as the other fields \
(lakhs for INR, dollars for USD): "15 lakh vested over 4 years" -> \
stock_rsu: 15.0 (total grant value in lakhs — do not divide by the vesting \
period unless the post is explicitly asking for an annualized figure). \
Double-check stock_rsu is the same order of magnitude as fixed_base for \
that same offer; if a post says base is "20L" and stock is "15L", both \
should be reported as ~15-20, not one of them off by 100x or 1000x.
- Stock/RSU is frequently denominated in a DIFFERENT currency than the rest \
of the offer -- common for Indian roles at US-headquartered companies, \
where base/bonus are in INR (LPA) but stock is quoted in USD (e.g. "fixed: \
21 LPA ... stocks: 12k USD vested over 4 years"). When this happens, \
convert the stock figure into the SAME unit as the offer's overall \
`currency` using 1 USD ≈ 94 INR, so stock_rsu stays consistent with \
fixed_base/total_ctc -- never leave it in its original currency's raw \
number if that differs from the offer's `currency` field. Example: offer \
currency is INR, stock is "12k USD" -> 12000 * 94 / 100000 ≈ 11.3 lakhs, so \
stock_rsu: 11.3 (not 12 and not 12000).
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
