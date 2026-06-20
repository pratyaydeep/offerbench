import logging
import time
from typing import Callable, Sequence, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def process_in_batches(
    items: Sequence[T],
    process_item: Callable[[T], None],
    batch_size: int,
    batch_delay_s: float,
    label: str = "item",
) -> int:
    """Processes items sequentially in groups of `batch_size` (no delay
    between calls within a batch), pausing `batch_delay_s` seconds between
    batches (not after the last one). Returns the number of items processed."""
    total = len(items)
    processed = 0
    for batch_start in range(0, total, batch_size):
        batch = items[batch_start : batch_start + batch_size]
        logger.info(
            "batch %d-%d of %d %s(s)", batch_start + 1, batch_start + len(batch), total, label
        )
        for item in batch:
            process_item(item)
            processed += 1
        if batch_start + batch_size < total:
            logger.info("batch done, pausing %.1fs before next batch", batch_delay_s)
            time.sleep(batch_delay_s)
    return processed
