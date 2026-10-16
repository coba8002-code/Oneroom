import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ROOMAX",
  description: "다가구주택 임대 관리",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <header className="border-b bg-white">
          <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
            <a href="/" className="font-bold tracking-tight">ROOMAX</a>
            <nav className="text-sm text-slate-600">
              <a href="/onboarding" className="hover:text-slate-900">초기 등록</a>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
