// 우리은행 '보안메일' 거래내역(암호 걸린 HTML) → 글자(.txt)·풀린 HTML(.dec.html)
// 사용: node tools/bank/woori_decrypt.mjs <html 폴더> <출력 폴더> <메일 비밀번호>
// - 브라우저는 오프라인으로 띄움(파일 밖 요청 차단) — 내역이 밖으로 나가지 않음
// - playwright 는 e2e/ 의 것을 씀: (cd e2e && npm ci) 후 실행. 크롬 위치는 PW_CHROMIUM 으로 바꿀 수 있음
// 다음 단계: python tools/bank/woori_to_csv.py out.csv <출력 폴더>/*.txt → 앱 '통장 내역 가져오기'에 CSV 업로드
import fs from "fs";
import path from "path";
import { createRequire } from "module";

const require = createRequire(path.resolve("e2e/package.json"));
const { chromium } = require("playwright");
const [, , inDir, outDir, pw] = process.argv;
if (!inDir || !outDir || !pw) {
  console.error("사용: node tools/bank/woori_decrypt.mjs <html 폴더> <출력 폴더> <메일 비밀번호>");
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
for (const f of fs.readdirSync(inDir).filter((n) => n.endsWith(".html"))) {
  const ctx = await browser.newContext({ offline: true, javaScriptEnabled: true });
  const page = await ctx.newPage();
  await page.route("**/*", (r) => (r.request().url().startsWith("file:") ? r.continue() : r.abort()));
  await page.goto("file://" + path.resolve(inDir, f));
  await page.fill("#password", pw);
  await page.click("#confirm");
  await page.waitForTimeout(3000);
  const texts = [];
  const html = [];
  for (const fr of page.frames()) {
    try { texts.push(await fr.evaluate(() => (document.body ? document.body.innerText : ""))); } catch {}
    try { html.push(await fr.content()); } catch {}
  }
  fs.writeFileSync(path.join(outDir, f + ".txt"), texts.join("\n=====FRAME=====\n"));
  fs.writeFileSync(path.join(outDir, f + ".dec.html"), html.join("\n<!--FRAME-->\n"));
  await ctx.close();
}
await browser.close();
