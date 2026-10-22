from sqlalchemy import select, text

from app.models import Charge, Deposit, Tenant, Unit


def test_sample_onboarding_counts(onboarded):
    assert onboarded["units"] == 10
    assert onboarded["leases"] == 8  # 9 임대호실 중 203 공실
    assert onboarded["vacant"] == 1
    assert onboarded["deposits_total"] == 43_000_000


def test_owner_unit_has_no_lease(onboarded, session):
    owner = session.scalar(select(Unit).where(Unit.unit_no == "401"))
    assert owner.use_type == "owner" and owner.status == "owner"


def test_deposit_is_liability_not_charge(onboarded, session):
    # 보증금은 deposits 에만 있고 청구(매출)로 잡히지 않는다
    assert session.scalar(select(Deposit).limit(1)) is not None
    assert session.scalars(select(Charge)).all() == []


def test_phone_encrypted_at_rest(onboarded, session):
    raw = session.execute(text("select phone from tenants limit 1")).scalar_one()
    assert raw and not raw.startswith("010")
    t = session.scalar(select(Tenant).limit(1))
    assert t.phone.startswith("010-")


def test_csv_preview_reports_bad_rows_without_saving(client, session):
    raw = "호실,용도,임차인,월세,납부일,계약시작\n101,임대,홍길동,450000,,2026-01-01\n102,창고,,,,\n".encode()
    res = client.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw, "text/csv")}).json()
    assert [e["row"] for e in res["errors"]] == [2, 3]
    assert "납부일" in res["errors"][0]["message"]
    assert session.scalars(select(Unit)).all() == []


def test_csv_preview_accepts_cp949(client):
    raw = "호실,용도\n101,임대\n".encode("cp949")
    res = client.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw, "text/csv")}).json()
    assert res["errors"] == [] and res["units"][0]["unit_no"] == "101"


def test_duplicate_unit_no_rejected(client):
    res = client.post("/api/v1/onboarding", json={
        "property": {"name": "x"}, "units": [{"unit_no": "101"}, {"unit_no": "101"}],
    })
    assert res.status_code == 422


def test_future_deposit_received_date_rejected(client):
    # 보증금 받은 날은 '들어온 증거' — 아직 오지 않은 날로 받았다고 적을 수 없다 (받기 전이면 비움)
    from datetime import timedelta

    from app.schemas import today_kst
    future = (today_kst() + timedelta(days=1)).isoformat()
    raw = (f"호실,용도,임차인,보증금,월세,납부일,계약시작,보증금수령일\n"
           f"101,임대,홍길동,1000000,450000,1,2026-01-01,{future}\n").encode()
    res = client.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw, "text/csv")}).json()
    assert res["units"] == [] and "보증금 받은 날" in res["errors"][0]["message"]
    unit = {"unit_no": "101", "tenant_name": "홍길동", "deposit": 1000000, "rent": 450000, "due_day": 1,
            "start_date": "2026-01-01", "deposit_received_on": future}
    assert client.post("/api/v1/onboarding", json={"property": {"name": "x"}, "units": [unit]}).status_code == 422
    today = today_kst().isoformat()
    ok = client.post("/api/v1/onboarding", json={"property": {"name": "x"}, "units": [{**unit, "deposit_received_on": today}]})
    assert ok.status_code in (200, 201), ok.text  # 오늘은 받을 수 있음
