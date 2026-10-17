"""파일 보관소 — 로컬 디스크(서버 1대·docker) 또는 Supabase Storage(서버리스·Vercel).

  ROOMAX_STORAGE=local     (기본) ROOMAX_UPLOAD_DIR 아래에 저장
  ROOMAX_STORAGE=supabase  ROOMAX_SUPABASE_URL · ROOMAX_SUPABASE_SERVICE_KEY · ROOMAX_SUPABASE_BUCKET(기본 roomax)

보관 영역은 둘: uploads(계약서, 이미 암호화된 바이트), backups(복구 직전 안전 백업·정기 백업, 비밀번호로 암호화). 여기서는 바이트를 그대로 보관만 한다 — 암호화는 부르는 쪽 책임.
버킷은 반드시 비공개(private)로 만들 것. 서비스 키는 서버에만 둔다(화면 코드·로그에 금지).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from app.config import settings

KEY_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")


def _check(key: str) -> str:
    if not KEY_RE.match(key) or ".." in key.split("/"):
        raise ValueError("잘못된 파일 이름")
    return key


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, keys: list[str]) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def move(self, src: str, dst: str) -> None: ...


@dataclass
class LocalStore:
    root: Path

    def _path(self, key: str) -> Path:
        p = (self.root / _check(key)).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("잘못된 파일 경로")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, keys: list[str]) -> None:
        for k in keys:
            self._path(k).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        """prefix 로 시작하는 키 (한 단계 폴더 안에서). 예: 'backups/pre-restore-<org>-'"""
        folder, _, start = prefix.rpartition("/")
        d = self.root / folder if folder else self.root
        if not d.exists():
            return []
        return sorted(f"{folder}/{p.name}" if folder else p.name
                      for p in d.iterdir() if p.is_file() and p.name.startswith(start))

    def move(self, src: str, dst: str) -> None:
        d = self._path(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        self._path(src).replace(d)


@dataclass
class SupabaseStore:
    """Supabase Storage REST API (비공개 버킷, 서비스 키). area 가 버킷 안 폴더 (uploads | backups)."""
    url: str
    key: str
    bucket: str
    area: str
    transport: httpx.BaseTransport | None = None  # 테스트용

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=f"{self.url.rstrip('/')}/storage/v1", timeout=60, transport=self.transport,
                            headers={"Authorization": f"Bearer {self.key}", "apikey": self.key})

    def put(self, key: str, data: bytes) -> None:
        with self._client() as c:
            r = c.post(f"/object/{self.bucket}/{self.area}/{_check(key)}", content=data,
                       headers={"x-upsert": "true", "content-type": "application/octet-stream"})
            r.raise_for_status()

    def get(self, key: str) -> bytes:
        with self._client() as c:
            r = c.get(f"/object/{self.bucket}/{self.area}/{_check(key)}")
            if r.status_code in (400, 404):
                raise FileNotFoundError(key)
            r.raise_for_status()
            return r.content

    def delete(self, keys: list[str]) -> None:
        if keys:
            with self._client() as c:
                c.request("DELETE", f"/object/{self.bucket}", json={"prefixes": [f"{self.area}/{_check(k)}" for k in keys]}).raise_for_status()

    def list(self, prefix: str) -> list[str]:
        folder, _, start = prefix.rpartition("/")
        with self._client() as c:
            r = c.post(f"/object/list/{self.bucket}",
                       json={"prefix": f"{self.area}/{folder}".rstrip("/"), "search": start, "limit": 1000, "offset": 0,
                             "sortBy": {"column": "name", "order": "asc"}})
            r.raise_for_status()
            names = [o["name"] for o in r.json() if o.get("id") and o["name"].startswith(start)]
        return sorted(f"{folder}/{n}" if folder else n for n in names)

    # 서버리스는 요청·응답이 약 4.5MB 로 막혀 있어, 큰 백업 파일은 브라우저가 Storage 와 직접 주고받는다.
    # 서명된 주소는 짧게만 유효하고 그 파일 하나에만 쓸 수 있다. 백업 파일은 이미 비밀번호로 암호화돼 있다.
    def signed_download_url(self, key: str, expires: int, download_name: str) -> str:
        with self._client() as c:
            r = c.post(f"/object/sign/{self.bucket}/{self.area}/{_check(key)}", json={"expiresIn": expires})
            r.raise_for_status()
            signed = r.json().get("signedURL") or r.json()["signedUrl"]
        return f"{self.url.rstrip('/')}/storage/v1{signed}&download={download_name}"

    def signed_upload_url(self, key: str) -> str:
        with self._client() as c:
            r = c.post(f"/object/upload/sign/{self.bucket}/{self.area}/{_check(key)}")
            r.raise_for_status()
        return f"{self.url.rstrip('/')}/storage/v1{r.json()['url']}"

    def move(self, src: str, dst: str) -> None:
        with self._client() as c:
            c.post("/object/move", json={"bucketId": self.bucket, "sourceKey": f"{self.area}/{_check(src)}",
                                         "destinationKey": f"{self.area}/{_check(dst)}"}).raise_for_status()


AREAS = ("uploads", "backups")


@lru_cache(maxsize=4)
def store(area: str) -> BlobStore:
    """uploads = 계약서 파일, backups = 안전 백업·정기 백업. 로컬은 ROOMAX_UPLOAD_DIR·ROOMAX_BACKUP_DIR 그대로."""
    if area not in AREAS:
        raise ValueError(area)
    if settings.storage == "supabase":
        if not (settings.supabase_url and settings.supabase_service_key):
            raise RuntimeError("ROOMAX_STORAGE=supabase 인데 ROOMAX_SUPABASE_URL·ROOMAX_SUPABASE_SERVICE_KEY 가 없습니다")
        return SupabaseStore(settings.supabase_url, settings.supabase_service_key, settings.supabase_bucket, area)
    return LocalStore(Path(settings.upload_dir if area == "uploads" else settings.backup_dir).resolve())


def direct_transfer() -> bool:
    """큰 파일(백업)을 브라우저가 Storage 와 직접 주고받는가 — Supabase 보관소일 때."""
    return settings.storage == "supabase"
