import logging
import time
from dataclasses import dataclass

from offerbench import config, db, leetcode_client

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    new_posts: int
    detail_fetched: int


def sync_new_posts(
    page_size: int = 50, request_delay_s: float = 1.0, limit: int | None = None
) -> SyncResult:
    """Incrementally fetch posts tagged `compensation`, newest first, stopping
    at the first already-seen topic_id. On an empty DB this naturally walks
    every page (full backfill) since nothing is ever "already seen".

    `limit` caps how many new posts are fetched in this call — useful for
    testing the pipeline on a handful of posts before running a full sync."""
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

        stop = False
        for edge in edges:
            node = edge["node"]
            if db.raw_post_exists(node["topicId"]):
                stop = True
                break
            db.upsert_raw_post_list_fields(node)
            new_count += 1
            logger.info("  new post topic_id=%s %r", node["topicId"], node["title"][:60])
            if limit is not None and new_count >= limit:
                stop = True
                break

        if stop or not page["pageInfo"]["hasNextPage"]:
            break
        skip += page_size
        time.sleep(request_delay_s)

    logger.info("new_posts=%d, fetching full content...", new_count)

    pending_detail = db.topic_ids_missing_detail()
    detail_fetched = 0
    for i, topic_id in enumerate(pending_detail, start=1):
        logger.info("[%d/%d] fetching content for topic_id=%s", i, len(pending_detail), topic_id)
        detail = leetcode_client.discuss_post_detail(topic_id)
        db.update_raw_post_detail(topic_id, detail)
        detail_fetched += 1
        time.sleep(request_delay_s)

    return SyncResult(new_posts=new_count, detail_fetched=detail_fetched)
