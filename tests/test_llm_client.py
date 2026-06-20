from unittest.mock import MagicMock

import pytest

from offerbench import llm_client


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


def _patch_stream(monkeypatch, lines):
    fake_client = MagicMock()
    fake_client.stream.return_value = _FakeStreamCtx(lines)
    monkeypatch.setattr(llm_client, "_get_http_client", lambda: fake_client)


def test_stream_content_reassembles_deltas(monkeypatch):
    lines = [
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":"{\\"a\\":"}}]}',
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":"1}"}}]}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    result = llm_client._stream_content([{"role": "user", "content": "hi"}])
    assert result == '{"a":1}'


def test_stream_content_raises_on_embedded_error(monkeypatch):
    # Observed on both NVIDIA build and OpenRouter: HTTP 200, but a
    # mid-stream {"error": ...} event when the upstream provider drops.
    lines = [
        'data: {"id":"x","choices":[],"error":{"code":502,"message":"Network connection lost.","metadata":{"error_type":"provider_unavailable"}}}',
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":""},"finish_reason":"error"}]}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    with pytest.raises(RuntimeError, match="Network connection lost"):
        llm_client._stream_content([{"role": "user", "content": "hi"}])


def test_stream_content_raises_on_finish_reason_error(monkeypatch):
    lines = [
        'data: {"id":"x","choices":[{"index":0,"delta":{"content":""},"finish_reason":"error"}]}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    with pytest.raises(RuntimeError, match="finish_reason=error"):
        llm_client._stream_content([{"role": "user", "content": "hi"}])
