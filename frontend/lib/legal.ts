/** 약관·처리방침에 들어가는 운영자 정보 — 여기 한 곳만 고치면 두 문서에 함께 반영된다. */
export const LEGAL = {
  service: "ROOMAX",
  operator: "ROOMAX 운영자",            // 상용화 시: 상호(법인명)
  representative: "(상용화 전 기재)",     // 대표자 성명
  businessNo: "(상용화 전 기재)",         // 사업자등록번호
  address: "(상용화 전 기재)",
  privacyOfficer: "운영자 본인",          // 개인정보 보호책임자 — 소상공인은 미지정 시 대표자가 책임자 (개인정보 보호법 제31조)
  contactEmail: "(운영자 연락 이메일 기재)",
  effectiveDate: "2026-10-17",
  version: "1.0",
  privacyVersion: "1.2",  // 1.1: AI 비서 국외 이전 고지 · 1.2: 사진 판독(계약서·통장 캡처) 국외 이전
  privacyEffectiveDate: "2026-10-23",
} as const;
