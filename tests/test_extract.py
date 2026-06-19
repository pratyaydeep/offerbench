from offerbench import db, extract, llm_client
from offerbench.models import ExtractedOffer


def _seed_post(topic_id="1"):
    db.upsert_raw_post_list_fields(
        {
            "topicId": topic_id,
            "uuid": "u1",
            "slug": "slug-1",
            "title": "Teradata offer",
            "summary": "summary",
            "author": {"userName": "u", "realName": "U"},
            "isAnonymous": False,
            "createdAt": "2026-06-01T00:00:00Z",
            "updatedAt": "2026-06-01T00:00:00Z",
            "hitCount": 1,
            "tags": [],
        }
    )
    db.update_raw_post_detail(topic_id, {"content": "Company: Teradata\nCTC: 44.5 LPA"})


def test_extract_pending_writes_normalized_row(monkeypatch):
    _seed_post()

    def fake_extract(title, content):
        return ExtractedOffer(
            organization="Teradata",
            role_title="SDE2",
            currency="INR",
            total_ctc=4_450_000,
            confidence=0.9,
        )

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.processed == 1
    assert result.ok == 1

    offers = db.query_current_offers({"include_no_data": True})
    assert len(offers) == 1
    row = offers[0]
    assert row["organization"] == "Teradata"
    assert row["extraction_status"] == "ok"
    assert round(row["total_ctc_inr_lakhs"], 1) == 44.5
    assert row["source_url"] == "https://leetcode.com/discuss/post/1/slug-1/"


def test_idempotent_without_force(monkeypatch):
    _seed_post()
    call_count = {"n": 0}

    def fake_extract(title, content):
        call_count["n"] += 1
        return ExtractedOffer(organization="Teradata", confidence=0.9)

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    extract.extract_pending()
    second = extract.extract_pending()

    assert call_count["n"] == 1
    assert second.processed == 0


def test_force_reextracts(monkeypatch):
    _seed_post()

    def fake_extract(title, content):
        return ExtractedOffer(organization="Teradata", confidence=0.9)

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    extract.extract_pending()
    second = extract.extract_pending(force=True)

    assert second.processed == 1


def test_low_confidence_classification(monkeypatch):
    _seed_post()

    def fake_extract(title, content):
        return ExtractedOffer(organization="Teradata", total_ctc=100, confidence=0.2)

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.low_confidence == 1


def test_no_data_classification(monkeypatch):
    _seed_post()

    def fake_extract(title, content):
        return ExtractedOffer(confidence=0.9)

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.no_data == 1


def test_error_status_on_exception(monkeypatch):
    _seed_post()

    def fake_extract(title, content):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.errors == 1

    offers = db.query_current_offers({"include_no_data": True})
    assert offers[0]["extraction_status"] == "error"
    assert "provider timeout" in offers[0]["error_message"]
