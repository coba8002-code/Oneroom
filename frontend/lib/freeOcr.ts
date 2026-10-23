/**
 * 무료 판독 — 사진 속 글자를 이 기기(브라우저) 안에서 읽는다 (Tesseract.js, 한국어+영어).
 * 사진은 기기 밖으로 나가지 않고, 읽은 글자만 서버의 규칙(/vision/parse-text)으로 표로 나눈다.
 * 엔진·한국어 데이터는 우리 주소(/ocr, 빌드 때 scripts/copy-ocr.mjs 가 복사)에서 받는다 — 외부 CDN 을 쓰지 않음.
 * 처음 한 번 약 8MB 를 받아 와서 시간이 걸리고(이후 브라우저 캐시), PDF 는 읽지 못한다.
 */
export async function recognizeText(files: File[], onProgress?: (p: number) => void): Promise<string> {
  const { createWorker } = await import("tesseract.js");
  const worker = await createWorker(["kor", "eng"], 1, {
    workerPath: "/ocr/worker.min.js",
    corePath: "/ocr/core",
    langPath: "/ocr/lang",
    logger: (m: { status: string; progress: number }) => {
      if (m.status === "recognizing text") onProgress?.(m.progress);
    },
  });
  try {
    const parts: string[] = [];
    for (const f of files) {
      if (!f.type.startsWith("image/")) throw new Error("무료 판독은 사진(JPG·PNG)만 읽습니다. PDF 는 캡처해서 올려 주세요");
      const { data } = await worker.recognize(f);
      parts.push(data.text);
    }
    return parts.join("\n");
  } finally {
    await worker.terminate();
  }
}
