/**
 * 사진을 서버 한도 안으로 줄인다 — 서버리스(Vercel)는 한 번에 받는 요청이 약 4.5MB까지라
 * 휴대폰 사진(3~8MB)은 그대로 못 올린다. 글자 인식에 충분한 크기(긴 변 2400px, JPEG 85%)로 다시 저장.
 * 이미 작거나 사진이 아니면(PDF 등) 그대로 돌려준다.
 */
const TARGET_BYTES = 3.5 * 1024 * 1024;
const MAX_SIDE = 2400;

export async function shrinkImage(file: File): Promise<File> {
  if (!/^image\/(jpeg|png|heic|heif|webp)$/.test(file.type) || file.size <= TARGET_BYTES) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    for (const quality of [0.85, 0.7, 0.55]) {
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", quality));
      if (blob && blob.size <= TARGET_BYTES) {
        return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
      }
    }
  } catch {
    /* 줄이지 못하면 원본 — 서버가 크기 안내를 돌려준다 */
  }
  return file;
}
