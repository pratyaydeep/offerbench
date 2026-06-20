from offerbench import db, extract, llm_client
from offerbench.models import ExtractionResult, OfferEntry
from tests.conftest import FAKE_PROVIDER


def _seed_post(topic_id="1", content="Company: Teradata\nCTC: 44.5 LPA"):
    db.upsert_raw_post_list_fields(
        {
            "topicId": topic_id,
            "uuid": f"u{topic_id}",
            "slug": f"slug-{topic_id}",
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
    db.update_raw_post_detail(topic_id, {"content": content})


def test_extract_pending_writes_normalized_row(monkeypatch):
    _seed_post()

    def fake_extract(title, content, providers, **kwargs):
        return (
            ExtractionResult(
                offers=[
                    OfferEntry(
                        organization="Teradata",
                        role_title="SDE2",
                        currency="INR",
                        total_ctc=44.5,
                        confidence=0.9,
                    )
                ]
            ),
            FAKE_PROVIDER,
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


def test_comparison_post_yields_one_row_per_offer(monkeypatch):
    _seed_post(content="Amazon vs Gojek, which should I pick?")

    def fake_extract(title, content, providers, **kwargs):
        return (
            ExtractionResult(
                post_kind="comparison",
                years_experience=2.0,
                offers=[
                    OfferEntry(organization="Amazon", currency="INR", total_ctc=29.42, confidence=0.8),
                    OfferEntry(organization="Gojek", currency="INR", total_ctc=27.22, confidence=0.8),
                ],
            ),
            FAKE_PROVIDER,
        )

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.processed == 1  # one post...
    assert result.ok == 2  # ...but two offer rows

    offers = db.query_current_offers({"include_no_data": True, "sort": "ctc_desc"})
    assert len(offers) == 2
    orgs = {o["organization"] for o in offers}
    assert orgs == {"Amazon", "Gojek"}
    for o in offers:
        assert o["post_kind"] == "comparison"
        assert o["years_experience"] == 2.0


def test_idempotent_without_force(monkeypatch):
    _seed_post()
    call_count = {"n": 0}

    def fake_extract(title, content, providers, **kwargs):
        call_count["n"] += 1
        return ExtractionResult(offers=[OfferEntry(organization="Teradata", confidence=0.9)]), FAKE_PROVIDER

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    extract.extract_pending()
    second = extract.extract_pending()

    assert call_count["n"] == 1
    assert second.processed == 0


def test_force_reextracts(monkeypatch):
    _seed_post()

    def fake_extract(title, content, providers, **kwargs):
        return ExtractionResult(offers=[OfferEntry(organization="Teradata", confidence=0.9)]), FAKE_PROVIDER

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    extract.extract_pending()
    second = extract.extract_pending(force=True)

    assert second.processed == 1


def test_low_confidence_classification(monkeypatch):
    _seed_post()

    def fake_extract(title, content, providers, **kwargs):
        return (
            ExtractionResult(offers=[OfferEntry(organization="Teradata", total_ctc=100, confidence=0.2)]),
            FAKE_PROVIDER,
        )

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.low_confidence == 1


def test_no_data_classification(monkeypatch):
    _seed_post()

    def fake_extract(title, content, providers, **kwargs):
        return ExtractionResult(offers=[]), FAKE_PROVIDER

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.no_data == 1


def test_error_status_on_exception(monkeypatch):
    _seed_post()

    def fake_extract(title, content, providers, **kwargs):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(llm_client, "extract_offer", fake_extract)

    result = extract.extract_pending()
    assert result.errors == 1

    offers = db.query_current_offers({"include_no_data": True})
    assert offers[0]["extraction_status"] == "error"
    assert "provider timeout" in offers[0]["error_message"]
