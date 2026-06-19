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


def test_stops_at_first_already_seen_post(monkeypatch):
    db.upsert_raw_post_list_fields(_node(2))

    pages = {
        0: {"totalNum": 5, "pageInfo": {"hasNextPage": True},
            "edges": [{"node": _node(1)}, {"node": _node(2)}]},
    }

    def fake_list(order_by, tag_slugs, skip, first):
        return pages[skip]

    def fake_detail(topic_id):
        return _detail(topic_id)

    monkeypatch.setattr(leetcode_client, "discuss_post_items", fake_list)
    monkeypatch.setattr(leetcode_client, "discuss_post_detail", fake_detail)

    result = ingest.sync_new_posts(page_size=2, request_delay_s=0)

    assert result.new_posts == 1
    assert db.raw_post_exists("1")
    assert db.raw_post_exists("2")
    assert db.status_counts()["raw_posts"] == 2
