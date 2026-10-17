"""Vercel Python 함수 진입점 — 모든 요청을 FastAPI 앱으로 (vercel.json 의 rewrites).

로컬·docker 에서는 쓰지 않는다 (uvicorn app.main:app).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
