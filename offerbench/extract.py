import logging
from dataclasses import dataclass

from offerbench import batching, config, currency, db, llm_client
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
    batch_size: int = 10,
    batch_delay_s: float = 5.0,
) -> ExtractResult:
    """LLM calls are one-post-per-call with no natural grouping, so this is
    explicitly batched the same way as the LeetCode detail fetch in
    ingest.py: `batch_size` calls run back-to-back, then `batch_delay_s`
    seconds pass before the next batch.

    A single post can describe multiple distinct offers (comparison posts
    like "Amazon vs Gojek"), so each extraction can produce 0..N rows in
    extracted_offers, one per offer_index -- not exactly one row per post."""
    posts = db.posts_needing_extraction(config.EXTRACTION_VERSION, force=force, limit=limit)
    counts = {"ok": 0, "low_confidence": 0, "no_data": 0, "errors": 0}
    total = len(posts)
    logger.info(
        "extract: %d post(s) to process (model=%s) in batches of %d",
        total, config.LLM_MODEL, batch_size,
    )

    def process_one(post) -> None:
        logger.info("topic_id=%s %r", post["topic_id"], post["title"][:60])
        try:
            result = llm_client.extract_offer(post["title"], post["content"])

            if not result.offers:
                db.insert_extraction(
                    post["topic_id"],
                    config.EXTRACTION_VERSION,
                    config.LLM_MODEL,
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
                return

            for i, offer in enumerate(result.offers):
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
                    config.LLM_MODEL,
                    status=status,
                    payload=payload,
                    offer_index=i,
                )
                counts[status] += 1
                logger.info(
                    "  -> [%d] %s org=%r role=%r ctc_lakhs=%s",
                    i, status, offer.organization, offer.role_title, inr_lakhs,
                )
        except Exception as e:
            db.insert_extraction(
                post["topic_id"],
                config.EXTRACTION_VERSION,
                config.LLM_MODEL,
                status="error",
                payload=None,
                error=str(e),
                offer_index=0,
            )
            counts["errors"] += 1
            logger.info("  -> error: %s", e)

    batching.process_in_batches(posts, process_one, batch_size, batch_delay_s, label="post")

    return ExtractResult(
        processed=total,
        ok=counts["ok"],
        low_confidence=counts["low_confidence"],
        no_data=counts["no_data"],
        errors=counts["errors"],
    )
