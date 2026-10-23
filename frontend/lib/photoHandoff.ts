// 다른 화면(임대료 관리·첫 설정)에서 고른 통장 캡처를 '사진으로 넣기'로 넘긴다.
// 화면 이동(클라이언트 라우팅) 동안 메모리에만 두고, 새로고침하면 사라진다(사진은 어디에도 저장하지 않음).
let pending: { files: File[]; accountId?: string } | null = null;

export const SHEET_RE = /\.(csv|xlsx|xls)$/i;

/** 통장 파일 칸에서 고른 것 중 CSV·엑셀이 아닌 것(사진·zip·PDF)이 있으면 넘길 준비 */
export function handOffBankPhotos(files: File[], accountId?: string): boolean {
  const photos = files.filter((f) => !SHEET_RE.test(f.name));
  if (!photos.length) return false;
  pending = { files: photos, accountId };
  return true;
}

export function takeBankPhotos(): { files: File[]; accountId?: string } | null {
  const p = pending;
  pending = null;
  return p;
}
