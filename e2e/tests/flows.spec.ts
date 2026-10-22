import { api, expect, importBank, noOverflow, SAMPLES, sampleBank, signupAndOnboard, test } from "./helpers";

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
  for (const path of ["/", "/payments", "/expenses", "/units", "/assets", "/vacancy", "/move-out", "/tax", "/reports", "/settings", "/assistant", "/certificate", "/tenant-notices", "/utilities"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await noOverflow(page);
  }
});

test("건물 두 동: 같은 통장을 함께 쓰고, 호실은 '건물 이름 + 호실'로 구분", async ({ page }) => {
  const org = await signupAndOnboard(page);
  await page.goto("/onboarding");
  await page.getByLabel("건물 이름").fill("행복빌라 2동");
  await expect(page.getByLabel("월세 받는 통장")).toHaveValue(/.+/);  // 기본: 기존 통장 함께 쓰기
  await page.locator("input[type=file]").first().setInputFiles(`${SAMPLES}/onboarding_units.csv`);
  await page.getByRole("button", { name: "등록", exact: true }).click();
  await page.getByText("등록 완료").waitFor();
  expect((await api(page, "GET", `/api/v1/bank-accounts?organization_id=${org}`)).length).toBe(1);

  await page.goto("/");
  await expect(page.locator("aside").getByText("행복빌라 외 1동")).toBeVisible();  // 로고 옆 건물 이름
  const labels = (await api(page, "GET", `/api/v1/units?organization_id=${org}`)).map((u: { unit_no: string }) => u.unit_no);
  expect(labels).toContain("행복빌라 101");
  expect(labels).toContain("행복빌라 2동 101");
  await page.goto("/vacancy");
  await expect(page.locator("li.card").filter({ hasText: "행복빌라 2동 203호" })).toBeVisible();

  await page.goto("/onboarding");  // 같은 이름은 거절
  await page.getByLabel("건물 이름").fill("행복빌라 2동");
  await page.locator("input[type=file]").first().setInputFiles(`${SAMPLES}/onboarding_units.csv`);
  await page.getByRole("button", { name: "등록", exact: true }).click();
  await expect(page.getByText(/이미 '행복빌라 2동' 건물이 있습니다/)).toBeVisible();
});

test("월간 보고서: 장부 값 그대로 한 장 요약 → 엑셀 내려받기, 인쇄 화면에서 메뉴 숨김", async ({ page }) => {
  // 샘플 은행 내역(2026-11)을 지난달인 2026-09 로 옮겨 쓴다 — 보고서는 오지 않은 달을 만들지 않으므로
  const org = await signupAndOnboard(page);
  await api(page, "POST", `/api/v1/charges/generate?organization_id=${org}&period=2026-09`);
  await importBank(page, org, sampleBank().replaceAll("2026-11-", "2026-09-"));
  await api(page, "POST", `/api/v1/matching/run?organization_id=${org}`);

  await page.goto("/reports");
  await page.getByLabel("보고서 월").fill("2026-09");
  await expect(page.getByText("2026-09 운영 보고서")).toBeVisible();
  const kpi = (name: string) => page.locator(".card").filter({ has: page.getByText(name, { exact: true }) });
  await expect(kpi("미수(납부일 지남)")).toContainText("1,350,000원");
  await expect(kpi("보증금 잔액(부채)")).toContainText("43,000,000원");
  await expect(page.getByText(/입금 검토 대기 4건/)).toBeVisible();
  await expect(page.getByText(/임차인[A-H]/)).toHaveCount(0);  // 이름 없음

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "엑셀" }).click();
  expect((await download).suggestedFilename()).toBe("roomax-report-2026-09.xlsx");

  await page.getByLabel("보고서 월").fill("2099-01");  // 오지 않은 달 → 안내만, 예전 보고서가 남지 않음
  await expect(page.getByText("아직 오지 않은 달입니다")).toBeVisible();
  await expect(page.getByText(/^\d{4}-\d{2} 운영 보고서$/)).toHaveCount(0);
  await page.getByLabel("보고서 월").fill("2026-09");

  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("button", { name: "인쇄·PDF" })).toBeHidden();
  await expect(page.getByText("2026-09 운영 보고서")).toBeVisible();
});

test("임차인 링크: 만들기 → 임차인 화면(로그인 없음) → 수리 요청 → 관리자 확인 → 링크 끄기", async ({ page, browser }) => {
  const org = await signupAndOnboard(page);
  await api(page, "POST", `/api/v1/charges/generate?organization_id=${org}&period=2026-11`);
  await page.goto("/units");
  const unit = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "101호" }) });
  await unit.getByRole("button", { name: "임차인 링크" }).click();
  await unit.getByRole("button", { name: "링크 만들기" }).click();
  const url = await unit.getByLabel(/임차인 링크/).inputValue();
  expect(url).toMatch(/\/t\/[\w-]{40,}$/);

  // 임차인: 로그인 없는 새 브라우저, 휴대폰 폭
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const tenant = await ctx.newPage();
  const errors: string[] = [];
  tenant.on("pageerror", (e) => errors.push(e.message));
  tenant.on("console", (m) => { if (m.type() === "error" && !/status of 4\d\d/.test(m.text())) errors.push(m.text()); });
  await tenant.goto(url);
  await expect(tenant.getByRole("heading", { name: "101호" })).toBeVisible();
  await expect(tenant.getByText("매월 1일 · 월세 450,000원")).toBeVisible();
  await expect(tenant.getByText("입금 확인 전").first()).toBeVisible();  // '미납'이라고 쓰지 않음
  await expect(tenant.getByText(/임차인[A-H]|미납/)).toHaveCount(0);  // 이름·독촉 표현 없음
  await expect(tenant.getByRole("link", { name: /대시보드|로그인/ })).toHaveCount(0);  // 관리자 메뉴 없음
  await noOverflow(tenant);
  await tenant.getByLabel("어디가 어떻게 고장 났나요?").fill("보일러 온수가 안 나와요");
  await tenant.getByRole("button", { name: "수리 요청 보내기" }).click();
  await expect(tenant.getByText("집주인에게 보냈습니다.")).toBeVisible();
  await expect(tenant.locator("li").filter({ hasText: "보일러 온수가 안 나와요" }).getByText("처리 중")).toBeVisible();

  // 관리자: 홈 알림과 수리 목록
  await page.goto("/");
  await expect(page.getByText(/임차인 수리 요청 1건 \(101\)/)).toBeVisible();
  await page.goto("/assets?tab=repairs");
  await expect(page.locator("li.card").filter({ hasText: "보일러 온수가 안 나와요" }).getByText("임차인 요청")).toBeVisible();

  // 링크 끄기 → 임차인 화면은 안내만
  await page.goto("/units");
  await unit.getByRole("button", { name: "임차인 링크" }).click();
  await unit.getByRole("button", { name: "링크 끄기" }).click();
  await expect(unit.getByText("링크를 껐습니다.")).toBeVisible();
  await tenant.reload();
  await expect(tenant.getByText(/링크가 만료되었거나/)).toBeVisible();
  expect(errors, "임차인 화면 오류").toEqual([]);
  await ctx.close();
});

test("월세 납부 확인서: 확정된 월세 입금만 → 인쇄 화면", async ({ page }) => {
  const org = await signupAndOnboard(page);
  await api(page, "POST", `/api/v1/charges/generate?organization_id=${org}&period=2026-09`);
  await importBank(page, org, sampleBank().replaceAll("2026-11-", "2026-09-"));
  await api(page, "POST", `/api/v1/matching/run?organization_id=${org}`);

  await page.goto("/units");
  const unit = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "101호" }) });
  await unit.getByRole("link", { name: "납부 확인서" }).click();
  await page.getByLabel("연도 (입금일 기준)").selectOption("2026");
  const paper = page.locator("article");
  await expect(paper.getByText("임차인A")).toBeVisible();
  await expect(paper.locator("tbody tr").filter({ hasText: "2026-09-01" })).toContainText("450,000원");
  await expect(paper.locator("tfoot")).toContainText("합계 (1건)");
  await expect(paper).not.toContainText("010-");  // 연락처 없음
  await expect(page.getByText(/검토 대기 4건은 넣지 않았습니다/)).toBeVisible();  // 화면 경고 (인쇄에는 없음)
  await page.getByLabel(/임대인 이름/).fill("김대표");
  await expect(paper.getByText("김대표")).toBeVisible();

  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("button", { name: "인쇄·PDF" })).toBeHidden();
  await expect(page.getByText(/검토 대기 4건/)).toBeHidden();
  await expect(paper.getByText("월세 납부 확인서")).toBeVisible();
});

test("임차인 공지·연락처: 공지 올리기·연락처 저장 → 임차인 화면에 보임 → 지우면 사라짐", async ({ page, browser }) => {
  const org = await signupAndOnboard(page);
  await page.goto("/tenant-notices");
  await page.getByLabel("제목").fill("12/20(토) 물탱크 청소");
  await page.getByLabel("내용 (선택)").fill("10~12시 단수됩니다");
  await page.getByRole("button", { name: "공지 올리기" }).click();
  await expect(page.getByText("공지를 올렸습니다.")).toBeVisible();
  await page.getByLabel("보낼 곳").selectOption({ label: "102호만" });
  await page.getByLabel("제목").fill("102호 보일러 점검 방문");
  await page.getByRole("button", { name: "공지 올리기" }).click();
  await expect(page.getByText("공지 2건")).toBeVisible();
  await page.getByLabel("전화번호").fill("010-1234-5678");
  await page.getByLabel("안내 (선택)").fill("평일 9~18시");
  await page.getByRole("button", { name: "연락처 저장" }).click();
  await expect(page.getByText("연락처를 저장했습니다.")).toBeVisible();

  const lease = (await api(page, "GET", `/api/v1/leases?organization_id=${org}`)).find((x: { unit_no: string }) => x.unit_no === "101");
  const { path } = await api(page, "POST", `/api/v1/leases/${lease.lease_id}/tenant-link`, { days: 90 });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const tenant = await ctx.newPage();
  await tenant.goto(path);
  const notices = tenant.locator("section[aria-labelledby=notices]");
  await expect(notices.getByText("12/20(토) 물탱크 청소")).toBeVisible();
  await expect(notices.getByText("102호 보일러 점검 방문")).toHaveCount(0);  // 다른 호실 공지는 안 보임
  await expect(tenant.getByRole("link", { name: "010-1234-5678" })).toHaveAttribute("href", "tel:01012345678");
  await noOverflow(tenant);

  await page.locator("li").filter({ hasText: "12/20(토) 물탱크 청소" }).getByRole("button", { name: /지우기/ }).click();
  await expect(page.getByText("공지를 지웠습니다.")).toBeVisible();
  await tenant.reload();
  await expect(tenant.getByRole("heading", { name: "101호" })).toBeVisible();
  await expect(tenant.locator("section[aria-labelledby=notices]")).toHaveCount(0);
  await ctx.close();
});

test("홈 화면 앱(PWA): 설치 정보 · 연결이 끊기면 안내 화면 · 장부 응답은 저장하지 않음", async ({ page, errors }) => {
  await signupAndOnboard(page);
  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest).toMatchObject({ short_name: "ROOMAX", display: "standalone", start_url: "/" });
  for (const icon of manifest.icons) expect((await page.request.get(icon.src)).ok()).toBeTruthy();

  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();  // 이제 서비스 워커가 이 화면을 맡는다
  await expect(page.getByRole("heading", { name: /사장님/ })).toBeVisible();

  // 연결 끊김 흉내: 이 화면 요청을 끊는다 (서비스 워커 요청도 가로챔 — playwright.config 의 실험 옵션)
  await page.context().route("**/payments", (r) => r.abort("internetdisconnected"));
  await page.goto("/payments").catch(() => {});  // 화면 이동 실패 → 안내 화면
  await expect(page.getByRole("heading", { name: "인터넷에 연결되어 있지 않습니다" })).toBeVisible();
  await page.context().unroute("**/payments");
  errors.splice(0);  // 일부러 끊은 요청의 'Failed to load resource' 는 오류가 아님

  const cached = await page.evaluate(async () => {
    const urls: string[] = [];
    for (const key of await caches.keys()) for (const r of await (await caches.open(key)).keys()) urls.push(new URL(r.url).pathname);
    return urls;
  });
  expect(cached.sort()).toEqual(["/icons/icon-192.png", "/offline.html"]);  // API·화면 HTML 없음
});

test("공과금: 항목별 처리 방식 → 수도 고지서 → 나눈 결과 → 청구 → 임차인 화면", async ({ page }) => {
  const org = await signupAndOnboard(page);
  await page.goto("/utilities");
  const water = page.locator("[data-item=water]");
  await water.getByLabel("수도 처리 방식").selectOption({ label: "나눠서 청구" });
  await water.getByLabel("수도 나누는 방법").selectOption({ label: "호실 수로 똑같이" });
  await water.getByLabel("수도 공실 몫").selectOption({ label: "몫을 나눈 뒤 집주인이 부담" });
  await water.getByLabel("수도 주인세대 몫").selectOption({ label: "빼고 나눔" });
  await water.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("수도 처리 방식을 저장했습니다.")).toBeVisible();
  const elec = page.locator("[data-item=electricity]");
  await elec.getByLabel("전기 처리 방식").selectOption({ label: "월세·관리비에 포함 (따로 청구 안 함)" });
  await elec.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("전기 처리 방식을 저장했습니다.")).toBeVisible();

  await page.getByLabel("청구 월").fill("2026-11");
  await page.getByLabel("고지서 금액 (원)").fill("90000");
  await page.getByRole("button", { name: "고지서 넣기" }).click();
  const bill = page.locator("[data-bill=water]");
  await expect(bill.locator("tr").filter({ hasText: "101호" })).toContainText("10,000원");
  await expect(bill.locator("tr").filter({ hasText: "203호" })).toContainText("집주인 부담");  // 공실 몫
  await expect(bill.getByText(/임차인 청구 합 80,000원 · 집주인 부담 10,000원/)).toBeVisible();
  await bill.getByRole("button", { name: "청구하기" }).click();
  await expect(bill.getByText("청구함")).toBeVisible();

  const lease = (await api(page, "GET", `/api/v1/leases?organization_id=${org}`)).find((x: { unit_no: string }) => x.unit_no === "101");
  const { path } = await api(page, "POST", `/api/v1/leases/${lease.lease_id}/tenant-link`, { days: 90 });
  await page.goto(path);
  await expect(page.getByText("2026-11 수도")).toBeVisible();
});

test("관리비 분리: 섞인 월세를 '월세 + 관리비'로 나눠 적기 → 한 번 입금에 둘 다 완납 → 확인서는 월세만", async ({ page }) => {
  const org = await signupAndOnboard(page);
  await page.goto("/units");
  const unit = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "101호" }) });
  await expect(unit).toContainText("관리비 따로 안 적음");
  await unit.getByRole("button", { name: "월세·관리비" }).click();
  await unit.getByLabel("정액 관리비 (원)").fill("50000");
  await unit.getByRole("button", { name: /450,000원에서 나누기 → 월세 400,000원/ }).click();
  await expect(unit.getByLabel("월세 (원)")).toHaveValue("400000");
  await unit.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("101호 월세·관리비를 고쳤습니다.", { exact: false })).toBeVisible();
  await expect(unit).toContainText("월세 400,000원 · 관리비 50,000원");

  await api(page, "POST", `/api/v1/charges/generate?organization_id=${org}&period=2026-11`);
  await importBank(page, org, sampleBank());  // 임차인A 450,000 = 월세 400,000 + 관리비 50,000
  await api(page, "POST", `/api/v1/matching/run?organization_id=${org}`);
  const rows = await api(page, "GET", `/api/v1/charges?organization_id=${org}&period=2026-11`);
  const of101 = rows.filter((c: { unit_no: string }) => c.unit_no === "101").map((c: { kind: string; status: string }) => `${c.kind}:${c.status}`);
  expect(of101.sort()).toEqual(["mgmt:paid", "rent:paid"]);

  await unit.getByRole("link", { name: "납부 확인서" }).click();
  await page.getByLabel("연도 (입금일 기준)").selectOption("2026");
  const paper = page.locator("article");
  await expect(paper.locator("tbody tr").filter({ hasText: "2026-11-01" })).toContainText("400,000원");
  await expect(paper).toContainText("관리비 월 50,000원 별도");
});

test("임대사업자: 건물 전체 등록 → 챙길 일(보증·부기등기) → 보증 넣기 → 경고 사라짐 · 홈 알림", async ({ page }) => {
  await signupAndOnboard(page);
  await page.goto("/rental-business");
  await expect(page.getByText(/아직 등록 임대주택이 없습니다/)).toBeVisible();
  await expect(page.getByText(/확인 필요 — 증액 상한 5%/)).toBeVisible();
  await page.getByRole("button", { name: "등록 임대주택 추가" }).click();
  await page.getByLabel("주택 유형").selectOption({ label: "다가구주택" });
  await page.getByLabel("임대 유형").selectOption({ label: "장기일반민간임대주택" });
  await expect(page.getByLabel("임대의무기간 (년, 모르면 비움)")).toHaveValue("10");  // 제안값 — 고칠 수 있음
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByText("등록 임대주택을 추가했습니다.")).toBeVisible();

  const card = page.locator("section.card").filter({ hasText: "장기일반민간임대주택" }).last();
  await expect(card.getByText("보증 기록 없음")).toBeVisible();
  await expect(page.getByText(/유효한 임대보증금 보증 기록이 없습니다/)).toBeVisible();
  await expect(page.getByText(/부기등기\(등록 임대주택임을 등기부에 표시\) 기록이 없습니다/)).toBeVisible();

  await page.goto("/");
  await expect(page.getByText(/\[임대사업자\].*보증 기록이 없습니다/)).toBeVisible();

  await page.goto("/rental-business");
  await card.getByLabel("보증기관").selectOption({ label: "주택도시보증공사(HUG)" });
  await card.getByRole("button", { name: "보증 넣기" }).click();
  await expect(page.getByText("보증 기록을 넣었습니다.")).toBeVisible();
  await expect(card.getByText("보증 가입")).toBeVisible();
  await expect(page.getByText(/유효한 임대보증금 보증 기록이 없습니다/)).toHaveCount(0);
  await page.setViewportSize({ width: 375, height: 800 });
  await noOverflow(page);
});
