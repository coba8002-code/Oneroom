// 무료 판독(Tesseract.js) 엔진·한국어 데이터를 public/ocr 로 복사 — 외부 CDN 없이 우리 주소에서 받게 한다
// (CDN 이 막힌 망에서도 동작, 사진·글자가 제3자 서버를 거치지 않음). npm 패키지에서 꺼내므로 저장소에는 넣지 않는다.
import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const pkgDir = (name) => dirname(require.resolve(`${name}/package.json`));
const out = join(process.cwd(), "public", "ocr");
mkdirSync(join(out, "core"), { recursive: true });
mkdirSync(join(out, "lang"), { recursive: true });

cpSync(join(pkgDir("tesseract.js"), "dist", "worker.min.js"), join(out, "worker.min.js"));
for (const f of ["tesseract-core-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js"]) {
  cpSync(join(pkgDir("tesseract.js-core"), f), join(out, "core", f));
}
for (const lang of ["kor", "eng"]) {
  cpSync(join(pkgDir(`@tesseract.js-data/${lang}`), "4.0.0_best_int", `${lang}.traineddata.gz`), join(out, "lang", `${lang}.traineddata.gz`));
}
console.log("ocr assets → public/ocr");
