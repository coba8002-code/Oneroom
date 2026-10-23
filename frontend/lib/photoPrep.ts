/**
 * 올린 파일을 판독하기 좋게 고친다 (브라우저 안에서만 — 서버로 보내기 전).
 * - zip 은 풀어서 안의 사진·PDF 만 꺼낸다 (카카오톡으로 받은 묶음 등)
 * - 아주 긴 캡처(통장 내역 전체 화면처럼 세로가 가로보다 훨씬 긴 것)는 위에서부터 겹치게 잘라 여러 장으로
 *   — 그대로 줄이면 글자가 뭉개져 읽을 수 없다. 겹친 부분에서 같은 거래가 두 번 나오면 표에서 하나로 합친다.
 */
const IMAGE = /\.(jpe?g|png|webp|gif)$/i;
const MIME: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif", pdf: "application/pdf" };
const SLICE = 1.6;  // 조각 하나의 세로 = 가로 × 1.6
const OVERLAP = 0.08;

async function unzip(file: File): Promise<File[]> {
  const { unzipSync } = await import("fflate");
  const entries = unzipSync(new Uint8Array(await file.arrayBuffer()), {
    filter: (f) => !f.name.startsWith("__MACOSX/") && (IMAGE.test(f.name) || /\.pdf$/i.test(f.name)),
  });
  return Object.entries(entries).sort(([a], [b]) => a.localeCompare(b)).map(([name, data]) => {
    const ext = name.split(".").pop()!.toLowerCase();
    return new File([data], name.split("/").pop()!, { type: MIME[ext] ?? "application/octet-stream" });
  });
}

async function slice(file: File, tallRatio: number): Promise<File[]> {
  if (!file.type.startsWith("image/")) return [file];
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); } catch { return [file]; }
  const { width, height } = bitmap;
  if (height / width <= tallRatio) return [file];
  const step = Math.round(width * SLICE);
  const out: File[] = [];
  for (let top = 0, n = 1; top < height; top += Math.round(step * (1 - OVERLAP)), n += 1) {
    const h = Math.min(step, height - top);
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = h;
    canvas.getContext("2d")!.drawImage(bitmap, 0, top, width, h, 0, 0, width, h);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
    if (blob) out.push(new File([blob], `${file.name.replace(/\.\w+$/, "")}-${n}.png`, { type: "image/png" }));
    if (top + h >= height) break;
  }
  return out;
}

/** zip 풀기 → 세로가 가로의 tallRatio 배를 넘는 캡처 자르기. 순서는 올린 순서(zip 안은 이름순) 그대로 */
export async function prepareFiles(files: File[], opts: { tallRatio: number }): Promise<File[]> {
  const flat: File[] = [];
  for (const f of files) flat.push(...(/\.zip$/i.test(f.name) || f.type === "application/zip" ? await unzip(f) : [f]));
  const out: File[] = [];
  for (const f of flat) out.push(...(await slice(f, opts.tallRatio)));
  return out;
}

/** 크기 한도(장 수·바이트) 안에서 묶음으로 나눈다 — AI 판독은 한 번에 5장·약 4MB 까지 */
export function batches(files: File[], maxFiles: number, maxBytes: number): File[][] {
  const out: File[][] = [];
  let cur: File[] = [], size = 0;
  for (const f of files) {
    if (cur.length && (cur.length >= maxFiles || size + f.size > maxBytes)) { out.push(cur); cur = []; size = 0; }
    cur.push(f); size += f.size;
  }
  if (cur.length) out.push(cur);
  return out;
}
