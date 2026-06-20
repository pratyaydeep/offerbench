import logging
import time
from dataclasses import dataclass

from offerbench import batching, config, db, leetcode_client

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    new_posts: int
    detail_fetched: int


def sync_new_posts(
    page_size: int = 50,
    request_delay_s: float = 1.0,
    limit: int | None = None,
    batch_size: int = 10,
    batch_delay_s: float = 5.0,
) -> SyncResult:
    """Fetch posts tagged `compensation`, newest first. Walks every page of
    the full list — skipping posts already in raw_posts rather than stopping
    at the first one — so any historical gap (e.g. from a previous run that
    was capped by `limit` or interrupted) gets filled in on every call. Only
    `limit` or reaching the true end of the feed (hasNextPage=False) stops
    the walk. List pages are cheap (just metadata), so walking the whole
    ~3000-post list every run is an acceptable cost for guaranteed coverage.

    Seriality: the list-pagination phase below runs to completion first (all
    new post stubs land in raw_posts), and only then does the per-post detail
    fetch begin. Detail fetches have no natural batching (one topicId per
    call), so they're explicitly batched: `batch_size` calls run back-to-back,
    then `batch_delay_s` seconds pass before the next batch."""
    skip = 0
    new_count = 0
    while True:
        page = leetcode_client.discuss_post_items(
            order_by="MOST_RECENT",
            tag_slugs=[config.COMPENSATION_TAG_SLUG],
            skip=skip,
            first=page_size,
        )
        edges = page.get("edges") or []
        if not edges:
            break
        logger.info("list page: skip=%d fetched=%d posts", skip, len(edges))

        hit_limit = False
        for edge in edges:
            node = edge["node"]
            if db.raw_post_exists(node["topicId"]):
                continue
            db.upsert_raw_post_list_fields(node)
            new_count += 1
            logger.info("  new post topic_id=%s %r", node["topicId"], node["title"][:60])
            if limit is not None and new_count >= limit:
                hit_limit = True
                break

        if hit_limit or not page["pageInfo"]["hasNextPage"]:
            break
        skip += page_size
        time.sleep(request_delay_s)

    pending_detail = db.topic_ids_missing_detail()
    logger.info(
        "new_posts=%d, fetching full content for %d post(s) in batches of %d...",
        new_count, len(pending_detail), batch_size,
    )

    def fetch_one_detail(topic_id: str) -> None:
        detail = leetcode_client.discuss_post_detail(topic_id)
        db.update_raw_post_detail(topic_id, detail)

    detail_fetched = batching.process_in_batches(
        pending_detail, fetch_one_detail, batch_size, batch_delay_s, label="post"
    )

    return SyncResult(new_posts=new_count, detail_fetched=detail_fetched)
