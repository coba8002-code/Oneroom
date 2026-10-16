"use client";

import {
  Bell,
  Building2,
  Calculator,
  FileBarChart,
  FileText,
  House,
  Landmark,
  LayoutDashboard,
  Menu,
  MoreHorizontal,
  Receipt,
  Settings,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type NavItem = { href: string | null; label: string; icon: LucideIcon };

// href 가 null 이면 아직 없는 기능 (PRD 2차) — 가짜 화면 대신 '준비 중' 표시
const NAV: NavItem[] = [
  { href: "/", label: "대시보드", icon: LayoutDashboard },
  { href: "/onboarding", label: "건물·호실 등록", icon: Building2 },
  { href: "/contracts", label: "계약 관리", icon: FileText },
  { href: "/payments", label: "임대료 관리", icon: Wallet },
  { href: "/expenses", label: "지출·운영비", icon: Receipt },
  { href: null, label: "알림·메시지", icon: Bell },
  { href: null, label: "세무 관리", icon: Landmark },
  { href: null, label: "전월세 시뮬레이션", icon: Calculator },
  { href: null, label: "보고서", icon: FileBarChart },
  { href: "/settings", label: "설정", icon: Settings },
];

const TABS: NavItem[] = [
  { href: "/", label: "홈", icon: House },
  { href: "/payments", label: "임대료", icon: Wallet },
  { href: "/expenses", label: "운영비", icon: Receipt },
  { href: "/contracts", label: "계약", icon: FileText },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <a href="/" className="flex items-center gap-2.5">
      <span className={`grid place-items-center rounded-xl bg-white/10 ${compact ? "h-8 w-8" : "h-11 w-11"}`}>
        <House className={compact ? "h-5 w-5" : "h-7 w-7"} strokeWidth={2.2} />
      </span>
      <span className="leading-tight">
        <span className={`block font-extrabold tracking-tight ${compact ? "text-lg" : "text-2xl"}`}>ROOMAX</span>
        {!compact && <span className="block text-xs text-slate-300">내 건물의 든든한 파트너</span>}
      </span>
    </a>
  );
}

function NavList({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav className="space-y-1">
      {NAV.map(({ href, label, icon: Icon }) =>
        href ? (
          <a key={label} href={href} onClick={onNavigate}
            className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-[15px] font-medium transition-colors ${
              isActive(pathname, href)
                ? "bg-blue-600 text-white shadow-lg shadow-blue-900/30"
                : "text-slate-200 hover:bg-white/5 hover:text-white"}`}
            aria-current={isActive(pathname, href) ? "page" : undefined}>
            <Icon className="h-[18px] w-[18px]" />
            {label}
          </a>
        ) : (
          <span key={label} className="flex cursor-not-allowed items-center gap-3 rounded-xl px-3.5 py-2.5 text-[15px] text-slate-400/80"
            title="다음 단계에서 만듭니다">
            <Icon className="h-[18px] w-[18px]" />
            {label}
            <span className="ml-auto rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-slate-300">준비 중</span>
          </span>
        ),
      )}
    </nav>
  );
}

function SidebarCard() {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-sky-100 via-blue-50 to-indigo-100 p-4 text-navy-900">
      <p className="relative z-10 text-sm font-semibold leading-snug">행복한 임대관리,<br />오늘도 좋은 하루 되세요.</p>
      <House className="absolute -bottom-3 -right-2 h-20 w-20 text-blue-300/70" strokeWidth={1.5} />
    </div>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [drawer, setDrawer] = useState(false);
  useEffect(() => setDrawer(false), [pathname]);

  return (
    <div className="min-h-screen lg:flex">
      {/* 데스크톱 사이드바 */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-6 bg-gradient-to-b from-navy-800 to-navy-950 px-4 py-6 text-white lg:flex">
        <div className="px-2"><Logo /></div>
        <NavList pathname={pathname} />
        <div className="mt-auto"><SidebarCard /></div>
      </aside>

      {/* 모바일 상단 바 */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur lg:hidden">
        <a href="/" className="flex items-center gap-2 font-extrabold tracking-tight text-navy-800">
          <House className="h-6 w-6 text-blue-600" strokeWidth={2.4} /> ROOMAX
        </a>
        <button type="button" className="rounded-lg p-2 text-slate-600 hover:bg-slate-100" aria-label="메뉴 열기"
          onClick={() => setDrawer(true)}>
          <Menu className="h-5 w-5" />
        </button>
      </header>

      {/* 모바일 메뉴 */}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="메뉴">
          <button type="button" className="absolute inset-0 bg-slate-900/40" aria-label="메뉴 닫기" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col gap-6 bg-gradient-to-b from-navy-800 to-navy-950 px-4 py-5 text-white">
            <div className="flex items-center justify-between px-2">
              <Logo compact />
              <button type="button" className="rounded-lg p-2 hover:bg-white/10" aria-label="메뉴 닫기" onClick={() => setDrawer(false)}>
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavList pathname={pathname} onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 pb-24 pt-5 sm:px-6 lg:px-8 lg:pb-10 lg:pt-8">
        <div className="mx-auto max-w-[1400px]">{children}</div>
      </main>

      {/* 모바일 하단 탭 */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
        aria-label="주요 메뉴">
        {TABS.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href!);
          return (
            <a key={label} href={href!} className={`flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
              active ? "text-blue-600" : "text-slate-500"}`} aria-current={active ? "page" : undefined}>
              <Icon className="h-5 w-5" strokeWidth={active ? 2.4 : 2} />
              {label}
            </a>
          );
        })}
        <button type="button" onClick={() => setDrawer(true)} className="flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-slate-500">
          <MoreHorizontal className="h-5 w-5" />
          더보기
        </button>
      </nav>
    </div>
  );
}
