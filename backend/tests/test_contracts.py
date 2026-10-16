"""계약서 OCR — PRD §8: 계약 OCR 결과는 관리자 승인 전 원장에 확정되지 않음."""
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Deposit, Lease, Unit
from app.services import ocr
from app.services.contract_extract import extract, korean_number

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x01" * 64

# 표준 주택임대차계약서를 OCR 한 것과 비슷한 글자 (띄어쓰기·줄바꿈이 흐트러진 상태)
CONTRACT_TEXT = """주택 임대차 계약서
임대인과 임차인 쌍방은 아래 표시 주택에 관하여 다음 계약 내용과 같이 임대차계약을 체결한다.
[계약내용] 제1조 (보증금과 차임) 위 부동산의 임대차에 관하여 임대인과 임차인은 합의에 의하여
보증금 및 차임을 아래와 같이 지불하기로 한다.
보증금 금 오백만원정 (₩5,000,000)
계약금 금 오십만원정은 계약시에 지불하고 영수함
잔금 금 사백오십만원정은 2025 년 3 월 1 일에 지불한다
차임 금 사십오만원정 은 매월 1 일에 지불한다 (입금계좌: ○○은행)
제2조 (임대차기간) 임대인은 임차주택을 임대차 목적대로 사용할 수 있는 상태로
20 25년 3월 1일까지 임차인에게 인도하고, 임대차기간은 인도일로부터 2027년 2월 28일까지로 한다.
임차인 성명 홍길동 연락처 010-1234-5678
"""


def _clova(text_lines, status=200, infer="SUCCESS", seen=None):
    def handler(request: httpx.Request):
        if seen is not None:
            seen.append(request)
        fields = [{"inferText": w, "lineBreak": i == len(line) - 1}
                  for line in text_lines for i, w in enumerate(line)]
        return httpx.Response(status, json={"images": [{"inferResult": infer, "message": "x", "fields": fields}]})
    return ocr.ClovaOcr("https://ocr.example/general", "secret-x", transport=httpx.MockTransport(handler))


@pytest.fixture
def with_ocr(monkeypatch):
    lines = [line.split() for line in CONTRACT_TEXT.splitlines() if line.strip()]
    seen: list[httpx.Request] = []
    monkeypatch.setattr(ocr, "get_provider", lambda: _clova(lines, seen=seen))
    return seen


@pytest.fixture
def lease101(client, onboarded):
    org = onboarded["organization_id"]
    c = next(c for c in client.get("/api/v1/contracts", params={"organization_id": org}).json()
             if c["unit_no"] == "101")
    return org, c


def _upload(client, org, lease_id, raw=PNG, name="contract.png"):
    return client.post(f"/api/v1/leases/{lease_id}/documents", params={"organization_id": org},
                       files={"file": (name, raw)})


# ── 추출 ──

@pytest.mark.parametrize("s,n", [("오백만", 5_000_000), ("사십오만", 450_000), ("오천만", 50_000_000),
                                 ("일억이천만", 120_000_000), ("5천만", 50_000_000), ("삼십만오천", 305_000),
                                 ("abc", None)])
def test_korean_number(s, n):
    assert korean_number(s) == n


def test_extract_standard_contract():
    f = extract(CONTRACT_TEXT)
    assert f["deposit"]["value"] == 5_000_000 and "보증금" in f["deposit"]["evidence"]
    assert f["rent"]["value"] == 450_000
    assert f["due_day"]["value"] == 1
    assert (f["start_date"]["value"], f["end_date"]["value"]) == ("2025-03-01", "2027-02-28")
    # 계약금·잔금 금액을 보증금/월세로 잘못 잡지 않음
    assert f["deposit"]["value"] != 500_000


def test_extract_never_guesses():
    f = extract("임대차 계약서 사진이 흐려서 글자가 거의 없음")
    assert all(v == {"value": None, "evidence": None} for v in f.values())


def test_extract_from_until_pattern_and_korean_only_amount():
    f = extract("월세 금 삼십오만원정 매월 25일 지급. 2026년 1월 10일부터 2028년 1월 9일까지 임대한다. 보증금 금 일천만원")
    assert f["rent"]["value"] == 350_000 and f["due_day"]["value"] == 25
    assert f["deposit"]["value"] == 10_000_000
    assert (f["start_date"]["value"], f["end_date"]["value"]) == ("2026-01-10", "2028-01-09")


def test_extracts_no_personal_info():
    f = extract(CONTRACT_TEXT)
    assert set(f) == {"deposit", "rent", "due_day", "start_date", "end_date"}
    assert not any("010-1234" in (v["evidence"] or "") or "홍길동" in (v["evidence"] or "") for v in f.values())


# ── CLOVA 클라이언트 ──

def test_clova_request_and_text_join():
    seen = []
    text = _clova([["보증금", "금"], ["차임"]], seen=seen).read(PNG, "png")
    assert text == "보증금 금\n차임"
    req = seen[0]
    assert req.headers["X-OCR-SECRET"] == "secret-x"
    body = json.loads(req.content)
    assert body["version"] == "V2" and body["images"][0]["format"] == "png" and body["images"][0]["data"]


@pytest.mark.parametrize("kw", [{"status": 401}, {"infer": "FAILURE"}])
def test_clova_errors(kw):
    with pytest.raises(ocr.OcrError):
        _clova([["x"]], **kw).read(PNG, "png")


# ── 업로드 · 검수 ──

def test_upload_without_ocr_stores_encrypted_and_waits(client, lease101):
    org, c = lease101
    res = _upload(client, org, c["lease_id"])
    assert res.status_code == 201, res.text
    doc = res.json()
    assert doc["ocr_status"] == "not_configured" and doc["fields"] is None and "직접 입력" in doc["ocr_error"]
    stored = list(Path(settings.upload_dir).glob("*.bin"))
    assert stored and all(PNG not in p.read_bytes() for p in stored)  # 디스크에는 암호문만
    back = client.get(f"/api/v1/documents/{doc['id']}/file", params={"organization_id": org})
    assert back.content == PNG and back.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/settings/ocr").json() == {"configured": False, "provider": None}


def test_ocr_fields_are_candidates_until_verified(client, lease101, session, with_ocr):
    org, c = lease101
    doc = _upload(client, org, c["lease_id"], JPG, "c.jpg").json()
    assert doc["ocr_status"] == "done" and doc["ocr_provider"] == "clova"
    assert doc["fields"]["rent"]["value"] == 450_000
    assert json.loads(with_ocr[0].content)["images"][0]["format"] == "jpg"
    # 아직 원장 그대로 (샘플 101: 2025-03-01 ~ 2027-02-28, 월세 450,000)
    lease = session.scalar(select(Lease).join(Unit).where(Unit.unit_no == "101"))
    assert doc["current"]["rent"] == 450_000 and lease.end_date.isoformat() == "2027-02-28"
    assert session.scalar(select(AuditLog).where(AuditLog.action == "ocr.send")) is not None


def test_verify_applies_to_ledger_and_only_future_charges(client, lease101, session):
    org, c = lease101
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    doc = _upload(client, org, c["lease_id"]).json()
    res = client.post(f"/api/v1/documents/{doc['id']}/verify", params={"organization_id": org}, json={
        "deposit": 5_000_000, "rent": 470_000, "due_day": 3, "start_date": "2025-03-01", "end_date": "2027-02-28"})
    assert res.status_code == 200, res.text
    assert res.json()["verified_fields"]["changed"] == ["rent", "due_day"]

    nov = {x["unit_no"]: x for x in client.get("/api/v1/charges", params={"organization_id": org, "period": "2026-11"}).json()}
    assert nov["101"]["amount"] == 450_000  # 이미 만든 청구는 그대로
    dec = client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-12"}).json()
    c101 = next(x for x in dec["charges"] if x["unit_no"] == "101")
    assert (c101["amount"], c101["due_date"]) == (470_000, "2026-12-03")

    log = session.scalar(select(AuditLog).where(AuditLog.action == "document.verify"))
    assert log.detail["before"]["rent"] == 450_000 and log.detail["after"]["rent"] == 470_000
    again = client.post(f"/api/v1/documents/{doc['id']}/verify", params={"organization_id": org}, json={
        "deposit": 5_000_000, "rent": 1, "due_day": 3, "start_date": "2025-03-01"})
    assert again.status_code == 409


def test_received_deposit_cannot_be_changed_by_document(client, lease101):
    org, c = lease101  # 샘플은 보증금 수령일이 있음
    doc = _upload(client, org, c["lease_id"]).json()
    res = client.post(f"/api/v1/documents/{doc['id']}/verify", params={"organization_id": org}, json={
        "deposit": 7_000_000, "rent": 450_000, "due_day": 1, "start_date": "2025-03-01", "end_date": "2027-02-28"})
    assert res.status_code == 409 and "이미" in res.json()["detail"]


def test_unreceived_deposit_updated(client, session):
    res = client.post("/api/v1/onboarding", json={"property": {"name": "x"}, "units": [
        {"unit_no": "101", "tenant_name": "새임차인", "rent": 400000, "due_day": 10, "start_date": "2026-12-01",
         "deposit": 3_000_000}]}).json()
    org = res["organization_id"]
    lease_id = client.get("/api/v1/contracts", params={"organization_id": org}).json()[0]["lease_id"]
    doc = _upload(client, org, lease_id).json()
    client.post(f"/api/v1/documents/{doc['id']}/verify", params={"organization_id": org}, json={
        "deposit": 5_000_000, "rent": 400000, "due_day": 10, "start_date": "2026-12-01", "end_date": "2028-11-30"})
    dep = session.scalar(select(Deposit))
    session.refresh(dep)
    assert dep.amount == 5_000_000 and dep.received_at is None


def test_upload_guards(client, lease101, onboarded):
    org, c = lease101
    assert _upload(client, org, c["lease_id"], b"GIF89a....", "x.gif").status_code == 415
    assert _upload(client, org, c["lease_id"]).status_code == 201
    assert _upload(client, org, c["lease_id"]).status_code == 409  # 같은 파일 다시
    other = "00000000-0000-0000-0000-000000000000"
    assert _upload(client, other, c["lease_id"], JPG).status_code == 404
    doc_id = client.get("/api/v1/contracts", params={"organization_id": org}).json()[0]["documents"][0]["id"]
    assert client.get(f"/api/v1/documents/{doc_id}/file", params={"organization_id": other}).status_code == 404


def test_failed_ocr_then_retry(client, lease101, monkeypatch):
    org, c = lease101
    monkeypatch.setattr(ocr, "get_provider", lambda: _clova([["x"]], status=500))
    doc = _upload(client, org, c["lease_id"]).json()
    assert doc["ocr_status"] == "failed" and "HTTP 500" in doc["ocr_error"]
    monkeypatch.setattr(ocr, "get_provider", lambda: _clova([["차임", "금", "사십오만원", "매월", "1일"]]))
    retried = client.post(f"/api/v1/documents/{doc['id']}/ocr", params={"organization_id": org}).json()
    assert retried["ocr_status"] == "done" and retried["fields"]["rent"]["value"] == 450_000
