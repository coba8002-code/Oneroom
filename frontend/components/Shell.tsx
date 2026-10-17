"use client";

import {
  Bell,
  LogOut,
  MailWarning,
  Building2,
  Calculator,
  ClipboardCheck,
  DoorOpen,
  FileText,
  House,
  Landmark,
  LayoutDashboard,
  Package,
  Menu,
  MoreHorizontal,
  Receipt,
  Settings,
  Wallet,
  X,
  type LucideIcon,
  DoorClosed,
  Bot,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, AUTH_PAGES, type Me, ROLE_LABEL } from "@/lib/api";
import { MeContext } from "@/lib/me";

type NavItem = { href: string | null; label: string; icon: LucideIcon };

// href 가 null 이면 아직 없는 기능 (PRD 2차) — 가짜 화면 대신 '준비 중' 표시
const NAV: NavItem[] = [
  { href: "/", label: "대시보드", icon: LayoutDashboard },
  { href: "/onboarding", label: "건물·호실 등록", icon: Building2 },
  { href: "/units", label: "호실·계약", icon: DoorOpen },
  { href: "/contracts", label: "계약 관리", icon: FileText },
  { href: "/move-out", label: "입주·퇴실", icon: ClipboardCheck },
  { href: "/payments", label: "임대료 관리", icon: Wallet },
  { href: "/expenses", label: "지출·운영비", icon: Receipt },
  { href: "/notifications", label: "알림·메시지", icon: Bell },
  { href: "/vacancy", label: "공실 관리", icon: DoorClosed },
  { href: "/assets", label: "자산·수리", icon: Package },
  { href: "/tax", label: "세무 준비", icon: Landmark },
  { href: "/simulate", label: "전월세 시뮬레이션", icon: Calculator },
  { href: "/assistant", label: "AI 비서", icon: Bot },
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

function UserBox({ me, dark = true }: { me: Me; dark?: boolean }) {
  async function logout() {
    await fetch(`${API_BASE}/api/v1/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {});
    window.location.href = "/login";
  }
  return (
    <div className={`flex items-center gap-3 rounded-2xl p-3 ${dark ? "bg-white/5" : "bg-slate-50"}`}>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-blue-500 text-sm font-bold text-white">
        {(me.user.name ?? me.user.email).slice(0, 1)}
      </span>
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-sm font-semibold">{me.user.name ?? me.user.email}</div>
        <div className={`truncate text-xs ${dark ? "text-slate-300" : "text-slate-500"}`}>
          {me.organization.name} · {ROLE_LABEL[me.user.role]}
        </div>
      </div>
      <button type="button" onClick={logout} title="로그아웃" aria-label="로그아웃"
        className={`rounded-lg p-1.5 ${dark ? "text-slate-300 hover:bg-white/10" : "text-slate-500 hover:bg-white"}`}>
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );
}

/** 이메일 미확인 안내. 쓰는 데 제한은 없지만, 확인해야 비밀번호를 잊었을 때 되찾을 수 있다. */
function VerifyBanner({ email }: { email: string }) {
  const [state, setState] = useState<"idle" | "busy" | "sent" | "error">("idle");
  const [msg, setMsg] = useState("");
  async function resend() {
    setState("busy");
    const res = await fetch(`${API_BASE}/api/v1/auth/verify-email/send`, { method: "POST", credentials: "include" }).catch(() => null);
    if (res?.ok) { setState("sent"); return; }
    setState("error");
    setMsg(res ? (await res.json().catch(() => ({}))).detail ?? "보내지 못했습니다" : "서버에 연결할 수 없습니다");
  }
  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status">
      <MailWarning className="h-5 w-5 shrink-0 text-amber-600" />
      <span className="min-w-0 flex-1">
        이메일 주소 확인이 아직입니다. <b className="break-all">{email}</b> 로 보낸 메일의 링크를 눌러 주세요.
        <span className="block text-xs text-amber-800">확인해 두어야 비밀번호를 잊었을 때 되찾을 수 있습니다.</span>
      </span>
      {state === "sent" ? <span className="text-xs font-semibold text-emerald-700">새 확인 메일을 보냈습니다</span> : (
        <button type="button" className="btn-secondary btn-sm whitespace-nowrap" disabled={state === "busy"} onClick={resend}>확인 메일 다시 보내기</button>
      )}
      {state === "error" && <span className="w-full text-xs text-red-700">{msg}</span>}
    </div>
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
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => setDrawer(false), [pathname]);
  const authPage = AUTH_PAGES.includes(pathname);

  const reload = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/v1/auth/me`, { credentials: "include" }).catch(() => null);
    if (res?.ok) {
      setMe(await res.json());
    } else if (res?.status === 401 && !AUTH_PAGES.includes(window.location.pathname)) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
  }, []);
  useEffect(() => { reload(); }, [reload, pathname]);

  // 가입·로그인·약관 화면은 메뉴 없이
  if (authPage) return <MeContext.Provider value={{ me, reload }}>{children}</MeContext.Provider>;
  // 로그인 확인 전에는 업무 화면을 그리지 않는다 (남의 화면이 잠깐 보이는 일 방지)
  if (!me) return <div className="grid min-h-screen place-items-center text-sm text-slate-400">불러오는 중…</div>;

  return (
    <MeContext.Provider value={{ me, reload }}>
    <div className="min-h-screen lg:flex">
      {/* 데스크톱 사이드바 */}
      <aside className="sticky top-0 hidden h-screen print:!hidden w-64 shrink-0 flex-col gap-6 bg-gradient-to-b from-navy-800 to-navy-950 px-4 py-6 text-white lg:flex">
        <div className="px-2"><Logo /></div>
        <NavList pathname={pathname} />
        <div className="mt-auto space-y-3"><SidebarCard /><UserBox me={me} /></div>
      </aside>

      {/* 모바일 상단 바 */}
      <header className="sticky top-0 z-30 flex items-center justify-between print:hidden border-b border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur lg:hidden">
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
            <div className="mt-auto"><UserBox me={me} /></div>
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 pb-24 pt-5 sm:px-6 lg:px-8 lg:pb-10 lg:pt-8">
        <div className="mx-auto max-w-[1400px]">
          {!me.user.email_verified && me.mail_enabled !== false && <VerifyBanner email={me.user.email} />}
          {children}
        </div>
      </main>

      {/* 모바일 하단 탭 */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 print:hidden border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
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
    </MeContext.Provider>
  );
}
