from dataclasses import dataclass

from offerbench import config, currency, db, llm_client
from offerbench.models import ExtractedOffer


@dataclass
class ExtractResult:
    processed: int
    ok: int
    low_confidence: int
    no_data: int
    errors: int


def classify_status(result: ExtractedOffer) -> str:
    if result.organization is None and result.total_ctc is None:
        return "no_data"
    if result.confidence < 0.5:
        return "low_confidence"
    return "ok"


def extract_pending(force: bool = False, limit: int | None = None) -> ExtractResult:
    posts = db.posts_needing_extraction(config.EXTRACTION_VERSION, force=force, limit=limit)
    counts = {"ok": 0, "low_confidence": 0, "no_data": 0, "errors": 0}

    for post in posts:
        try:
            result = llm_client.extract_offer(post["title"], post["content"])
            status = classify_status(result)
            payload = result.model_dump()
            inr_lakhs, usd = currency.normalize_compensation(result.currency, result.total_ctc)
            payload["total_ctc_inr_lakhs"] = inr_lakhs
            payload["total_ctc_usd"] = usd
            db.insert_extraction(
                post["topic_id"],
                config.EXTRACTION_VERSION,
                config.LLM_MODEL,
                status=status,
                payload=payload,
            )
            counts[status] += 1
        except Exception as e:
            db.insert_extraction(
                post["topic_id"],
                config.EXTRACTION_VERSION,
                config.LLM_MODEL,
                status="error",
                payload=None,
                error=str(e),
            )
            counts["errors"] += 1

    return ExtractResult(
        processed=len(posts),
        ok=counts["ok"],
        low_confidence=counts["low_confidence"],
        no_data=counts["no_data"],
        errors=counts["errors"],
    )
