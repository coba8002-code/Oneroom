import type { Metadata, Viewport } from "next";
import Shell from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "ROOMAX",
  description: "내 건물의 든든한 파트너 — 다가구주택 임대 관리",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#172d4f" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
