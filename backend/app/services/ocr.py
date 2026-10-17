"""클라우드 OCR — NAVER CLOVA OCR (General).

이미지를 보내고 **글자만** 돌려받는다. 계약 내용 판단은 여기서 하지 않는다
(contract_extract 가 후보를 뽑고, 관리자가 검수해서 확정).
설정(ROOMAX_CLOVA_OCR_URL · ROOMAX_CLOVA_OCR_SECRET)이 없으면 get_provider() 는 None.
"""
from __future__ import annotations

import base64
import time
import uuid

import httpx

from app.config import settings


class OcrError(Exception):
    pass


class ClovaOcr:
    name = "clova"

    def __init__(self, url: str, secret: str, transport: httpx.BaseTransport | None = None,
                 timeout: float = 30.0):
        self.url = url
        self.secret = secret
        self._client = httpx.Client(transport=transport, timeout=timeout)

    def read(self, raw: bytes, fmt: str) -> str:
        body = {
            "version": "V2",
            "requestId": uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
            "lang": "ko",
            "images": [{"format": fmt, "name": "contract", "data": base64.b64encode(raw).decode()}],
        }
        try:
            res = self._client.post(self.url, json=body, headers={"X-OCR-SECRET": self.secret})
        except httpx.HTTPError as e:
            raise OcrError(f"OCR 서버에 연결하지 못했습니다 ({type(e).__name__})") from e
        if res.status_code != 200:
            raise OcrError(f"OCR 요청 실패 (HTTP {res.status_code})")
        try:
            images = res.json()["images"]
        except (ValueError, KeyError) as e:
            raise OcrError("OCR 응답 형식을 읽을 수 없습니다") from e

        pages = []
        for image in images:
            if image.get("inferResult") != "SUCCESS":
                raise OcrError(f"OCR 인식 실패: {image.get('message') or image.get('inferResult')}")
            words = []
            for f in image.get("fields", []):
                words.append(f.get("inferText", ""))
                words.append("\n" if f.get("lineBreak") else " ")
            pages.append("".join(words).strip())
        return "\n\n".join(pages)


def get_provider() -> ClovaOcr | None:
    if settings.clova_ocr_url and settings.clova_ocr_secret:
        return ClovaOcr(settings.clova_ocr_url, settings.clova_ocr_secret)
    return None
