import io
from datetime import datetime, timezone

from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import Transaction
from tests.conftest import SAMPLES


def _upload(client, account_id, name, raw):
    return client.post(f"/api/v1/bank-accounts/{account_id}/import", files={"file": (name, raw)})


def _count(session):
    return session.scalar(select(func.count()).select_from(Transaction))


def test_sample_import_and_reupload_has_no_duplicates(client, onboarded, session):
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    first = _upload(client, onboarded["bank_account_id"], "nov.csv", raw).json()
    assert first["errors"] == []
    assert first["inserted"] == 14 and first["duplicates"] == 0

    second = _upload(client, onboarded["bank_account_id"], "nov.csv", raw).json()
    assert second["inserted"] == 0 and second["duplicates"] == 14
    assert _count(session) == 14


def test_identical_rows_in_one_file_are_both_kept(client, onboarded, session):
    # 은행이 잔액을 안 주는 내역에서 같은 시각·같은 금액·같은 입금자가 2건 → 실제 2건
    raw = ("거래일시,입금자,출금,입금\n"
           "2026-11-15 09:00,임차인D,,450000\n"
           "2026-11-15 09:00,임차인D,,450000\n").encode()
    assert _upload(client, onboarded["bank_account_id"], "a.csv", raw).json()["inserted"] == 2
    assert _upload(client, onboarded["bank_account_id"], "a.csv", raw).json()["duplicates"] == 2
    assert _count(session) == 2


def test_overlapping_files_deduplicate(client, onboarded, session):
    head = "거래일시,적요,출금,입금,잔액\n"
    a = "2026-11-01 09:00:00,이체,,1000,1000\n2026-11-02 09:00:00,이체,,2000,3000\n"
    b = "2026-11-02 09:00:00,이체,,2000,3000\n2026-11-03 09:00:00,이체,500,,2500\n"
    _upload(client, onboarded["bank_account_id"], "a.csv", (head + a).encode())
    res = _upload(client, onboarded["bank_account_id"], "b.csv", (head + b).encode()).json()
    assert res["inserted"] == 1 and res["duplicates"] == 1
    assert _count(session) == 3


def test_bank_ref_used_when_present(client, onboarded, session):
    raw = ("거래고유번호,거래일시,출금,입금\n"
           "T-1,2026-11-01,,1000\n"
           "T-2,2026-11-01,,1000\n").encode()
    assert _upload(client, onboarded["bank_account_id"], "r.csv", raw).json()["inserted"] == 2
    assert _upload(client, onboarded["bank_account_id"], "r.csv", raw).json()["duplicates"] == 2


def test_header_below_bank_preamble_and_kst_to_utc(client, onboarded, session):
    raw = ("조회계좌,123-456\n조회기간,2026-11-01~2026-11-30\n\n"
           "거래일자,거래시간,기재내용,찾으신금액,맡기신금액,거래후잔액\n"
           "2026.11.01,09:00:00,월세,,\"450,000\",\"1,450,000\"\n").encode("cp949")
    res = _upload(client, onboarded["bank_account_id"], "kb.csv", raw).json()
    assert res["inserted"] == 1, res
    tx = session.scalar(select(Transaction))
    occurred = tx.occurred_at if tx.occurred_at.tzinfo else tx.occurred_at.replace(tzinfo=timezone.utc)
    assert occurred == datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)  # KST 09:00 = UTC 00:00
    assert (tx.amount, tx.direction, tx.balance_after) == (450000, "in", 1450000)


def test_xlsx_import(client, onboarded, session):
    wb = Workbook()
    ws = wb.active
    ws.append(["거래일시", "적요", "출금", "입금", "잔액"])
    ws.append([datetime(2026, 11, 5, 10, 15), "한국전력공사", 128300, None, 100000])
    buf = io.BytesIO()
    wb.save(buf)
    res = _upload(client, onboarded["bank_account_id"], "x.xlsx", buf.getvalue()).json()
    assert res["inserted"] == 1 and res["errors"] == []
    assert session.scalar(select(Transaction)).direction == "out"


def test_bad_rows_reported_good_rows_kept(client, onboarded, session):
    raw = ("거래일시,출금,입금\n"
           "2026-11-01,,1000\n"
           "어제,,1000\n"
           "2026-11-02,500,500\n").encode()
    res = _upload(client, onboarded["bank_account_id"], "e.csv", raw).json()
    assert res["inserted"] == 1
    assert [e["row"] for e in res["errors"]] == [3, 4]


def test_missing_header_and_wrong_type(client, onboarded):
    res = _upload(client, onboarded["bank_account_id"], "n.csv", "a,b\n1,2\n".encode()).json()
    assert res["inserted"] == 0 and "헤더" in res["errors"][0]["message"]
    assert _upload(client, onboarded["bank_account_id"], "n.pdf", b"%PDF").status_code == 415
