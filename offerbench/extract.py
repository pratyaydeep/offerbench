import logging
from dataclasses import dataclass

from offerbench import config, currency, db, llm_client
from offerbench.models import OfferEntry

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    processed: int  # posts processed (not offer rows -- a post may yield 0..N offers)
    ok: int
    low_confidence: int
    no_data: int
    errors: int


def classify_offer_status(offer: OfferEntry) -> str:
    if offer.organization is None and offer.total_ctc is None:
        return "no_data"
    if offer.confidence < 0.5:
        return "low_confidence"
    return "ok"


def extract_pending(
    force: bool = False,
    limit: int | None = None,
    max_rounds: int = 5,
    cooldown_s: float = 60.0,
    pace_s: float = 1.0,
) -> ExtractResult:
    """Processes pending posts one at a time. Each LLM call tries providers
    from llm_providers.json (or the single LLM_BASE_URL/LLM_API_KEY/
    LLM_MODEL env vars as a fallback) in order, paced `pace_s` seconds apart;
    if every provider fails, waits `cooldown_s` and retries the whole list,
    up to `max_rounds` rounds before giving up on that post and recording it
    as an error.

    A single post can describe multiple distinct offers (comparison posts
    like "Amazon vs Gojek"), so each extraction can produce 0..N rows in
    extracted_offers, one per offer_index -- not exactly one row per post."""
    providers = config.load_llm_providers()
    if not providers:
        raise RuntimeError(
            "No LLM providers configured -- set up llm_providers.json or "
            "LLM_BASE_URL/LLM_API_KEY/LLM_MODEL in .env"
        )

    posts = db.posts_needing_extraction(config.EXTRACTION_VERSION, force=force, limit=limit)
    counts = {"ok": 0, "low_confidence": 0, "no_data": 0, "errors": 0}
    total = len(posts)
    logger.info(
        "extract: %d post(s) to process across %d provider(s): %s",
        total, len(providers), ", ".join(p.label for p in providers),
    )

    for i, post in enumerate(posts, start=1):
        logger.info("[%d/%d] topic_id=%s %r", i, total, post["topic_id"], post["title"][:60])
        try:
            result, provider = llm_client.extract_offer(
                post["title"], post["content"], providers,
                max_rounds=max_rounds, cooldown_s=cooldown_s, pace_s=pace_s,
            )

            if not result.offers:
                db.insert_extraction(
                    post["topic_id"],
                    config.EXTRACTION_VERSION,
                    provider.model,
                    status="no_data",
                    payload={
                        "post_kind": result.post_kind,
                        "years_experience": result.years_experience,
                        "location": result.location,
                    },
                    offer_index=0,
                )
                counts["no_data"] += 1
                logger.info("  -> no_data (no offers found)")
                continue

            for offer_index, offer in enumerate(result.offers):
                status = classify_offer_status(offer)
                payload = offer.model_dump()
                payload["post_kind"] = result.post_kind
                payload["years_experience"] = result.years_experience
                payload["location"] = result.location
                inr_lakhs, usd = currency.normalize_compensation(offer.currency, offer.total_ctc)
                payload["total_ctc_inr_lakhs"] = inr_lakhs
                payload["total_ctc_usd"] = usd
                db.insert_extraction(
                    post["topic_id"],
                    config.EXTRACTION_VERSION,
                    provider.model,
                    status=status,
                    payload=payload,
                    offer_index=offer_index,
                )
                counts[status] += 1
                logger.info(
                    "  -> [%d] %s org=%r role=%r ctc_lakhs=%s",
                    offer_index, status, offer.organization, offer.role_title, inr_lakhs,
                )
        except Exception as e:
            db.insert_extraction(
                post["topic_id"],
                config.EXTRACTION_VERSION,
                providers[0].model,
                status="error",
                payload=None,
                error=str(e),
                offer_index=0,
            )
            counts["errors"] += 1
            logger.info("  -> error (gave up after %d round(s)): %s", max_rounds, e)

    return ExtractResult(
        processed=total,
        ok=counts["ok"],
        low_confidence=counts["low_confidence"],
        no_data=counts["no_data"],
        errors=counts["errors"],
    )
