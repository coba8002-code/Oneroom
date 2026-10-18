"""건물 여러 동 — 호실 표시를 '건물 이름 + 호실'로 구분, 건물 이름 중복 금지, 계좌 함께 쓰기."""
from tests.conftest import SAMPLES


def _onboard(client, name, **extra):
    raw = (SAMPLES / "onboarding_units.csv").read_bytes()
    units = client.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw, "text/csv")}).json()["units"]
    return client.post("/api/v1/onboarding", json={"property": {"name": name, "address": "어딘가"}, "units": units, **extra})


def test_single_building_keeps_plain_unit_numbers(client, onboarded):
    units = client.get("/api/v1/units", params={"organization_id": onboarded["organization_id"]}).json()
    assert "101" in [u["unit_no"] for u in units]


def test_second_building_prefixes_every_label(client, onboarded):
    org = onboarded["organization_id"]
    res = _onboard(client, "  행복빌라   2동 ", bank_account_id=onboarded["bank_account_id"])
    assert res.status_code == 201, res.text
    assert res.json()["bank_account_id"] == onboarded["bank_account_id"]  # 같은 통장을 함께 씀
    assert len(client.get("/api/v1/bank-accounts", params={"organization_id": org}).json()) == 1

    labels = [u["unit_no"] for u in client.get("/api/v1/units", params={"organization_id": org}).json()]
    assert "테스트 다가구 101" in labels and "행복빌라 2동 101" in labels and "101" not in labels

    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    dash = client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": "2026-11-30"}).json()
    names = [u["unit_no"] for u in dash["units"]]
    assert len(names) == len(set(names)) == 20  # 두 동 10실씩, 겹치는 이름 없음
    leases = [x["unit_no"] for x in client.get("/api/v1/leases", params={"organization_id": org}).json()]
    assert len(leases) == len(set(leases))


def test_duplicate_building_name_and_foreign_account_rejected(client, make_client, onboarded):
    assert _onboard(client, "테스트  다가구").status_code == 409  # 공백만 다른 같은 이름
    _, other = make_client(email="other@example.com", org_name="남의 사업장")
    res = _onboard(client, "새 건물", bank_account_id=other["organization"]["id"])  # 남의 것·없는 계좌
    assert res.status_code == 409 and "계좌" in res.json()["detail"]


def test_me_lists_building_names_for_logo(client, onboarded):
    assert client.get("/api/v1/auth/me").json()["buildings"] == ["테스트 다가구"]
