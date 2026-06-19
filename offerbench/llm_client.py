from openai import OpenAI

from offerbench import config
from offerbench.models import ExtractedOffer

SYSTEM_PROMPT = """You extract structured compensation data from a single \
LeetCode discuss-forum post.

Rules:
- Only extract values that are explicitly stated or can be directly, \
unambiguously inferred from the text. Never invent or estimate a number \
that isn't grounded in the text. If a field is absent, leave it null.
- If multiple numbers could plausibly fill total_ctc (e.g. ambiguous "CTC" \
vs "in-hand"), prefer the figure most clearly labeled as total annual \
compensation, and note the ambiguity in `notes`.
- Report all monetary fields (total_ctc, fixed_base, variable_bonus, \
stock_rsu, signing_bonus, retirement_benefits) as plain absolute numbers in \
the stated currency's base unit (e.g. plain rupees, plain dollars) — \
convert shorthand like "44.5 LPA" or "12L" or "1.2 Cr" into the absolute \
number yourself (44.5 LPA -> 4450000). Do not report figures still in \
lakhs/crore/k shorthand.
- Set `currency` to your best read of the currency: "INR" or "USD". Assume \
INR if rupee symbols, "LPA", or lakhs/crore shorthand are used without an \
explicit denomination — this is the overwhelmingly common case on this \
forum. Leave `currency` null only if you cannot tell at all.
- `post_kind`: "accepted_offer" if the poster describes an offer they \
received/accepted, "current_comp" if describing their current package, \
"question" if primarily asking for advice without disclosing firm numbers, \
"comparison" if comparing multiple offers, "other" otherwise.
- Set `confidence` (0-1) reflecting your overall certainty across all \
extracted fields. Lower it for vague, sarcastic, meta-question posts, or \
posts that rely heavily on inference.
"""

_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "record_offer",
        "description": "Record the structured compensation data extracted from the post.",
        "parameters": ExtractedOffer.model_json_schema(),
    },
}

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    return _client


def extract_offer(title: str, content: str) -> ExtractedOffer:
    client = _get_client()
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Title: {title}\n\nContent:\n{content}"},
        ],
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "record_offer"}},
    )
    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise RuntimeError("Model did not return a tool call for record_offer")
    return ExtractedOffer.model_validate_json(tool_calls[0].function.arguments)
