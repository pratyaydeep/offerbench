from offerbench import db, ingest, leetcode_client


def _node(topic_id, created_at="2026-06-01T00:00:00Z"):
    return {
        "topicId": str(topic_id),
        "uuid": f"uuid-{topic_id}",
        "slug": f"slug-{topic_id}",
        "title": f"Title {topic_id}",
        "summary": "summary...",
        "author": {"userName": "someuser", "realName": "Some User"},
        "isAnonymous": False,
        "createdAt": created_at,
        "updatedAt": created_at,
        "hitCount": 10,
        "tags": [{"name": "Compensation", "slug": "compensation", "tagType": None}],
    }


def _detail(topic_id):
    return {
        "uuid": f"uuid-{topic_id}",
        "topicId": str(topic_id),
        "title": f"Title {topic_id}",
        "slug": f"slug-{topic_id}",
        "summary": "summary...",
        "content": f"full content for {topic_id}",
        "createdAt": "2026-06-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
    }


def test_full_backfill_on_empty_db(monkeypatch):
    pages = {
        0: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(1)}, {"node": _node(2)}]},
        2: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(3)}, {"node": _node(4)}]},
        4: {"totalNum": 5, "pageInfo": {"hasNextPage": False},
            "edges": [{"node": _node(5)}]},
    }

    def fake_list(order_by, tag_slugs, skip, first):
        return pages[skip]

    def fake_detail(topic_id):
        return _detail(topic_id)

    monkeypatch.setattr(leetcode_client, "discuss_post_items", fake_list)
    monkeypatch.setattr(leetcode_client, "discuss_post_detail", fake_detail)

    result = ingest.sync_new_posts(page_size=2, request_delay_s=0)

    assert result.new_posts == 5
    assert result.detail_fetched == 5
    assert db.status_counts()["raw_posts"] == 5
    assert db.status_counts()["missing_detail"] == 0


def test_fills_historical_gap_instead_of_stopping(monkeypatch):
    # simulate a previous run that only captured post 3, leaving older
    # posts 4 and 5 (below it) never fetched -- a real gap.
    db.upsert_raw_post_list_fields(_node(3))

    pages = {
        0: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(1)}, {"node": _node(2)}]},
        2: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(3)}, {"node": _node(4)}]},
        4: {"totalNum": 5, "pageInfo": {"hasNextPage": False},
            "edges": [{"node": _node(5)}]},
    }

    def fake_list(order_by, tag_slugs, skip, first):
        return pages[skip]

    def fake_detail(topic_id):
        return _detail(topic_id)

    monkeypatch.setattr(leetcode_client, "discuss_post_items", fake_list)
    monkeypatch.setattr(leetcode_client, "discuss_post_detail", fake_detail)

    result = ingest.sync_new_posts(page_size=2, request_delay_s=0)

    # post 3 already existed, so only 1, 2, 4, 5 are newly inserted -- but
    # the walk continued past post 3 instead of stopping there, so the
    # gap (post 4) gets filled.
    assert result.new_posts == 4
    for topic_id in ("1", "2", "3", "4", "5"):
        assert db.raw_post_exists(topic_id)
    assert db.status_counts()["raw_posts"] == 5


def test_limit_still_stops_early(monkeypatch):
    pages = {
        0: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(1)}, {"node": _node(2)}]},
        2: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(3)}, {"node": _node(4)}]},
    }

    def fake_list(order_by, tag_slugs, skip, first):
        return pages[skip]

    def fake_detail(topic_id):
        return _detail(topic_id)

    monkeypatch.setattr(leetcode_client, "discuss_post_items", fake_list)
    monkeypatch.setattr(leetcode_client, "discuss_post_detail", fake_detail)

    result = ingest.sync_new_posts(page_size=2, request_delay_s=0, limit=3)

    assert result.new_posts == 3
    assert db.status_counts()["raw_posts"] == 3
