import type { Metadata } from "next";

// 링크 자체가 비밀 — 검색에 올리지 않고, 다른 사이트로 주소를 넘기지 않는다
export const metadata: Metadata = {
  title: "우리 집 — ROOMAX",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function TenantLayout({ children }: { children: React.ReactNode }) {
  return children;
}
