"""OCR-Client für OpenAI-kompatible Schnittstellen (B2, E1)."""

from __future__ import annotations

import base64
import re
import time
from typing import Any, Protocol, runtime_checkable

import httpx

from docpipeline.config import Settings
from docpipeline.errors import OcrError

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\n(?P<body>.*?)\n?```$", re.DOTALL)
_RETRYABLE_CLIENT_STATUS = frozenset({408, 409, 425, 429})
_HTTP_ERROR = 400
_HTTP_SERVER_ERROR = 500


@runtime_checkable
class OcrClientProto(Protocol):
    model: str

    def ocr_page(self, image: bytes, page_no: int = 1) -> str: ...

    def ping(self) -> bool: ...


def strip_fences(text: str) -> str:
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group("body").strip() if match else stripped


class OcrClient:
    """Schickt je Seite ein PNG an ``{base_url}/chat/completions``."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = None,
    ) -> None:
        self._settings = settings
        self.model = settings.ocr_model
        self._sleep = sleep if sleep is not None else time.sleep
        self._client = httpx.Client(
            base_url=settings.ocr_base_url.rstrip("/") + "/",
            timeout=settings.ocr_timeout_s,
            transport=transport,
            headers=self._headers(settings),
        )

    @staticmethod
    def _headers(settings: Settings) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.ocr_api_key:
            headers["Authorization"] = f"Bearer {settings.ocr_api_key}"
        return headers

    def payload(self, image: bytes) -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        return {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                        {"type": "text", "text": self._settings.ocr_prompt},
                    ],
                }
            ],
        }

    def ocr_page(self, image: bytes, page_no: int = 1) -> str:
        payload = self.payload(image)
        retries = max(self._settings.ocr_retries, 1)
        status: int | None = None
        for attempt in range(retries):
            status = None
            try:
                response = self._client.post("chat/completions", json=payload)
            except httpx.HTTPError:
                status = None
            else:
                if response.status_code < _HTTP_ERROR:
                    return strip_fences(self._content(response))
                status = response.status_code
                if status < _HTTP_SERVER_ERROR and status not in _RETRYABLE_CLIENT_STATUS:
                    break
            if attempt + 1 < retries:
                self._sleep(self._settings.ocr_backoff_s * (2**attempt))
        raise OcrError(
            f"OCR fehlgeschlagen für Seite {page_no} (Status: {status or 'keine Antwort'})",
            page=page_no,
            status=status,
        )

    @staticmethod
    def _content(response: httpx.Response) -> str:
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OcrError("OCR-Antwort ohne Textfeld", page=0) from exc
        if not isinstance(content, str):
            raise OcrError("OCR-Antwort enthält keinen Text", page=0)
        return content

    def ping(self) -> bool:
        try:
            response = self._client.get("models")
        except httpx.HTTPError:
            return False
        return response.status_code < _HTTP_ERROR

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OcrClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
