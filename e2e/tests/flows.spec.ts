import { api, expect, importBank, noOverflow, sampleBank, signupAndOnboard, test } from "./helpers";

// 날짜가 고정된 샘플(2026-11 은행 내역)로 돌린다 — 화면은 '기준일'을 바꿔 그 날짜로 본다

test("핵심 흐름: 가입 → 호실 등록 → 청구 → 은행 내역 → 매칭 → 홈·임대료", async ({ page }) => {
  const org = await signupAndOnboard(page);
  await api(page, "POST", `/api/v1/charges/generate?organization_id=${org}&period=2026-11`);
  const { result } = await importBank(page, org, sampleBank());
  expect(result.inserted).toBeGreaterThan(0);
  const again = await importBank(page, org, sampleBank());
  expect(again.result.inserted).toBe(0);  // 같은 파일을 다시 올려도 중복 없음
  const m = await api(page, "POST", `/api/v1/matching/run?organization_id=${org}`);
  expect(m.auto_confirmed).toBeGreaterThan(0);

  await page.goto("/");
  await page.getByLabel("기준일").fill("2026-11-30");
  await expect(page.getByText(/입금 검토 대기 \d+건/)).toBeVisible();
  await expect(page.getByText("미납 금액 (확인 전)")).toBeVisible();  // 검토 대기가 있으면 '미납' 단정 안 함

  await page.goto("/payments");
  await expect(page.getByRole("heading", { name: /검토 대기 [1-9]/ })).toBeVisible();
});

test("입금 알림: 연결 주소 → 폰이 보낸 알림 → 오늘 납부일 '입금 확인'", async ({ page, playwright }) => {
  const org = await signupAndOnboard(page);
  await api(page, "POST", `/api/v1/charges/generate?organization_id=${org}&period=2026-11`);
  await page.goto("/settings#bank-alerts");
  const card = page.locator("#bank-alerts");
  await card.getByRole("button", { name: "연결 주소 만들기" }).click();
  const url = await card.getByLabel("연결 주소").inputValue();
  expect(url).toMatch(/\/api\/v1\/bank-alerts\/hook\/[\w-]{20,}$/);

  const phone = await playwright.request.newContext();  // 로그인 없이 (휴대폰 자동화 앱처럼)
  const sent = await phone.post(url, { data: { text: "[KB국민] 입금 450,000원 임차인B 잔액12,876,500" } });
  expect(await sent.json()).toEqual({ ok: true, status: "created" });
  expect((await phone.post(url.replace(/hook\/.+$/, "hook/wrong"), { data: { text: "입금 1원" } })).status()).toBe(404);

  await page.goto("/");
  await page.getByLabel("기준일").fill("2026-11-05");
  const due = page.locator("section[aria-labelledby=due-today]");
  await expect(due.getByRole("heading")).toContainText("1/1 입금 확인");
  const row = due.locator("li").filter({ hasText: "102호" });
  await expect(row.getByText("입금 확인", { exact: true })).toBeVisible();
  await expect(row).toContainText(/\d{2}:\d{2} 알림/);  // 입금 시각 + 출처
});

test("정기 점검: 추가 → 했음 기록 → 다음 예정일 이동 → 되돌리기", async ({ page }) => {
  await signupAndOnboard(page);
  await page.goto("/assets?tab=routine");
  await page.getByRole("button", { name: "할 일 추가" }).click();
  await page.getByRole("button", { name: "소화기 점검 (압력·위치)" }).click();
  await page.getByLabel(/주기/).fill("6");
  await page.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("추가했습니다.")).toBeVisible();
  const card = page.locator("li.card").filter({ hasText: "소화기 점검" });
  await expect(card.getByText("예정일 없음")).toBeVisible();  // 모르면 비움

  await card.getByRole("button", { name: "했음 기록" }).click();
  await card.getByLabel(/비용/).fill("30000");
  await card.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText(/다음 예정일을 6개월 뒤로/)).toBeVisible();
  await expect(card.getByText(/마지막 \d{4}-\d{2}-\d{2} \(1회, 비용 30,000원\)/)).toBeVisible();

  await card.getByRole("button", { name: /기록 1/ }).click();
  await card.getByRole("button", { name: "지우기", exact: true }).first().click();
  await expect(page.getByText("예정일을 되돌렸습니다")).toBeVisible();
  await expect(card.getByText("예정일 없음")).toBeVisible();
});

test("공실: 계약 종료 → 놓친 월세 → 모집 조건 → 광고 문구", async ({ page }) => {
  const org = await signupAndOnboard(page);
  const lease = (await api(page, "GET", `/api/v1/leases?organization_id=${org}`)).find((x: { unit_no: string }) => x.unit_no === "102");
  await api(page, "POST", `/api/v1/leases/${lease.lease_id}/end?organization_id=${org}`, { ended_on: "2026-09-20", reason: "퇴거" });

  await page.goto("/vacancy");
  const card = page.locator("li.card").filter({ hasText: "102호" });
  await expect(card.getByText(/공실 시작 2026-09-20 · 직전 월세 450,000원/)).toBeVisible();
  await card.getByRole("button", { name: "모집 조건·광고·기록" }).click();
  await card.getByLabel("보증금 (원)").fill("5000000");
  await card.getByLabel("월세 (원)").fill("460000");
  await card.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("모집 조건을 저장했습니다.")).toBeVisible();
  await expect(card.locator("pre")).toContainText("보증금 500만원 / 월세 46만원");
  await expect(card.locator("pre")).not.toContainText("옵션:");  // 자산대장에 옵션이 없으면 지어내지 않음
});

test("AI 비서: 키가 없으면 '연결 안 됨' 안내만, 질문 칸은 잠김", async ({ page }) => {
  await signupAndOnboard(page);
  await page.goto("/assistant");
  await expect(page.getByText("아직 연결되지 않았습니다.")).toBeVisible();
  await expect(page.getByLabel("질문")).toBeDisabled();
});

test("휴대폰 폭(390px)에서 주요 화면이 가로로 넘치지 않음", async ({ page }) => {
  await signupAndOnboard(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/", "/payments", "/expenses", "/units", "/assets", "/vacancy", "/move-out", "/tax", "/settings", "/assistant"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await noOverflow(page);
  }
});
