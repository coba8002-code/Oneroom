import { expect, test as base, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const SAMPLES = resolve(__dirname, "../../samples");

/** 콘솔 오류·페이지 오류가 하나라도 있으면 실패 (4xx 응답 로그는 화면이 처리하는 정상 흐름이라 제외) */
export const test = base.extend<{ errors: string[] }>({
  errors: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error" && !/status of 4\d\d/.test(m.text())) errors.push(m.text()); });
    page.on("dialog", (d) => d.accept());
    await use(errors);
    expect(errors, "브라우저 오류").toEqual([]);
  }, { auto: true }],  // 모든 테스트에 적용
});
export { expect };

let n = 0;
/** 새 사업장으로 가입하고 샘플 호실(9 임대 + 주인 1)을 등록. organization_id 를 돌려준다 */
export async function signupAndOnboard(page: Page): Promise<string> {
  const email = `owner${Date.now()}${n++}@e2e.test`;
  await page.goto("/signup");
  await page.getByLabel("이름", { exact: true }).fill("김대표");
  await page.getByLabel("사업장 이름").fill("행복빌라 임대");
  await page.getByLabel("이메일 (로그인 아이디)").fill(email);
  await page.getByLabel("비밀번호", { exact: true }).fill("happy-villa-2026");
  await page.getByLabel("비밀번호 확인").fill("happy-villa-2026");
  await page.getByLabel("아래 내용에 모두 동의").check();
  await page.getByRole("button", { name: /가입하고 시작하기/ }).click();
  await page.waitForURL(/\/onboarding/);
  await page.getByLabel("건물 이름").fill("행복빌라");
  await page.locator("input[type=file]").first().setInputFiles(`${SAMPLES}/onboarding_units.csv`);
  await expect(page.getByRole("button", { name: "등록", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "등록", exact: true }).click();
  await page.getByText("등록 완료").waitFor();
  return (await (await page.request.get("/api/v1/auth/me")).json()).organization.id;
}

export async function api(page: Page, method: "GET" | "POST" | "PUT" | "DELETE", path: string, data?: unknown) {
  const res = await page.request.fetch(path, { method, data });
  expect(res.status(), `${method} ${path}: ${await res.text()}`).toBeLessThan(300);
  return res.status() === 204 ? null : res.json();
}

export async function importBank(page: Page, org: string, csv: string) {
  const acct = (await api(page, "GET", `/api/v1/bank-accounts?organization_id=${org}`))[0].id;
  const res = await page.request.post(`/api/v1/bank-accounts/${acct}/import?organization_id=${org}`, {
    multipart: { file: { name: "s.csv", mimeType: "text/csv", buffer: Buffer.from(csv) } } });
  expect(res.ok()).toBeTruthy();
  return { acct, result: await res.json() };
}

export const sampleBank = () => readFileSync(`${SAMPLES}/bank_transactions_sample.csv`, "utf8");

/** 가로 스크롤이 생기지 않는지 (휴대폰 폭) */
export async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
}
