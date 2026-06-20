from unittest.mock import MagicMock

import pytest

from offerbench import llm_client
from offerbench.config import Provider
from offerbench.models import ExtractionResult

_PROVIDER = Provider(label="test", base_url="https://example.test/v1", api_key="key", model="test-model")


class _FakeStreamCtx:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.iter_lines = lambda: iter(self._lines)
        return resp

    def __exit__(self, *args):
        return False


def _patch_stream(monkeypatch, lines_by_call):
    """lines_by_call: list of line-lists, one per successive stream() call."""
    fake_client = MagicMock()
    fake_client.stream.side_effect = [_FakeStreamCtx(lines) for lines in lines_by_call]
    monkeypatch.setattr(llm_client, "_get_http_client", lambda: fake_client)


def test_stream_content_reassembles_deltas(monkeypatch):
    lines = [
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":"{\\"a\\":"}}]}',
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":"1}"}}]}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, [lines])
    result = llm_client._stream_content(_PROVIDER, [{"role": "user", "content": "hi"}])
    assert result == '{"a":1}'


def test_stream_content_raises_on_embedded_error(monkeypatch):
    # Observed on both NVIDIA build and OpenRouter: HTTP 200, but a
    # mid-stream {"error": ...} event when the upstream provider drops.
    lines = [
        'data: {"id":"x","choices":[],"error":{"code":502,"message":"Network connection lost.","metadata":{"error_type":"provider_unavailable"}}}',
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":""},"finish_reason":"error"}]}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, [lines])
    with pytest.raises(RuntimeError, match="Network connection lost"):
        llm_client._stream_content(_PROVIDER, [{"role": "user", "content": "hi"}])


def test_stream_content_raises_on_finish_reason_error(monkeypatch):
    lines = [
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":""},"finish_reason":"error"}]}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, [lines])
    with pytest.raises(RuntimeError, match="finish_reason=error"):
        llm_client._stream_content(_PROVIDER, [{"role": "user", "content": "hi"}])


def test_extract_offer_fails_over_to_next_provider(monkeypatch):
    providers = [
        Provider(label="bad", base_url="https://bad.test/v1", api_key="k", model="bad-model"),
        Provider(label="good", base_url="https://good.test/v1", api_key="k", model="good-model"),
    ]
    good_payload = '{"post_kind":"other","years_experience":null,"location":null,"offers":[]}'

    call_log = []

    def fake_try_provider(provider, title, content):
        call_log.append(provider.label)
        if provider.label == "bad":
            raise RuntimeError("simulated failure")
        return ExtractionResult.model_validate_json(good_payload)

    monkeypatch.setattr(llm_client, "_try_provider", fake_try_provider)

    result, used = llm_client.extract_offer(
        "title", "content", providers, max_rounds=2, cooldown_s=0, pace_s=0
    )
    assert used.label == "good"
    assert result.offers == []
    assert call_log == ["bad", "good"]


def test_extract_offer_gives_up_after_max_rounds(monkeypatch):
    providers = [Provider(label="always-bad", base_url="https://bad.test/v1", api_key="k", model="m")]
    call_log = []

    def fake_try_provider(provider, title, content):
        call_log.append(provider.label)
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(llm_client, "_try_provider", fake_try_provider)

    with pytest.raises(RuntimeError, match="All providers failed after 2 round"):
        llm_client.extract_offer("title", "content", providers, max_rounds=2, cooldown_s=0, pace_s=0)

    assert call_log == ["always-bad", "always-bad"]
