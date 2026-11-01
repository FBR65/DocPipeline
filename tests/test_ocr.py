"""B2/E1 — OCR über OpenAI-kompatible Schnittstelle."""

from __future__ import annotations

import json

import httpx
import pytest

from docpipeline.config import Settings
from docpipeline.errors import OcrError
from docpipeline.ocr import OcrClient

PNG = b"\x89PNG\r\n\x1a\nfake"


def _ok(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        },
    )


def _client(settings: Settings, handler, sleeps: list[float] | None = None) -> OcrClient:
    return OcrClient(
        settings,
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
    )


def test_request_is_openai_compatible(settings: Settings) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.url.path.endswith("/chat/completions")
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 8080
        return _ok("Text der Seite")

    client = _client(settings, handler)
    assert client.ocr_page(PNG, page_no=1) == "Text der Seite"

    body = seen[0]
    assert body["model"] == "paddleocr-vl"
    assert body["temperature"] == 0
    part = body["messages"][0]["content"][0]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["messages"][0]["content"][1]["type"] == "text"


def test_code_fences_are_stripped(settings: Settings) -> None:
    client = _client(settings, lambda _r: _ok("```markdown\n# Titel\nText\n```"))
    assert client.ocr_page(PNG, page_no=1) == "# Titel\nText"


def test_retry_on_500_then_success(settings: Settings) -> None:
    settings.ocr_backoff_s = 1.0
    attempts: list[int] = []
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(500, text="kaputt")
        return _ok("dritte Anfrage")

    client = _client(settings, handler, sleeps)
    assert client.ocr_page(PNG, page_no=2) == "dritte Anfrage"
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_retries_exhausted_raises_with_page_and_status(settings: Settings) -> None:
    client = _client(settings, lambda _r: httpx.Response(500, text="kaputt"))
    with pytest.raises(OcrError) as err:
        client.ocr_page(PNG, page_no=4)
    assert err.value.page == 4
    assert err.value.status == 500


def test_timeout_raises_ocr_error(settings: Settings) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("zu langsam")

    client = _client(settings, handler)
    with pytest.raises(OcrError, match="Seite 1"):
        client.ocr_page(PNG, page_no=1)


def test_api_key_not_leaked_in_error(settings: Settings) -> None:
    settings.ocr_api_key = "geheim-123"
    client = _client(settings, lambda _r: httpx.Response(503, text="nope"))
    with pytest.raises(OcrError) as err:
        client.ocr_page(PNG, page_no=3)
    assert "geheim-123" not in str(err.value)


def test_ping_reports_reachability(settings: Settings) -> None:
    assert _client(settings, lambda _r: httpx.Response(200, json={"data": []})).ping() is True
    assert _client(settings, lambda _r: httpx.Response(500)).ping() is False

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kein Server")

    assert _client(settings, boom).ping() is False
