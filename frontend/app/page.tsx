"use client";

import {
  AlertCircle,
  ArrowDownToLine,
  Bell,
  CalendarClock,
  CalendarDays,
  ChevronRight,
  CircleAlert,
  FilePlus2,
  FileSearch,
  Info,
  Landmark,
  Receipt,
  ReceiptText,
  Sun,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type Dashboard, manwon, mmdd, todayKst, won } from "@/lib/api";
import { useOrg } from "@/lib/useOrg";

type DashUnit = Dashboard["units"][number];

/** 은행 내역이 없거나 오래됐거나 입금 검토가 남았으면, 납부일이 지났어도 '미납'으로 단정하지 않는다 (PRD §4) */
const UNSURE_KINDS = ["bank_none", "bank_stale", "review_in"];
const isUnsure = (d: Dashboard) => d.attention.some((a) => UNSURE_KINDS.includes(a.kind));

type Status = "paid" | "due" | "overdue" | "check" | "partial" | "none" | "vacant" | "owner";
const STATUS: Record<Status, { label: string; dot: string; card: string; text: string }> = {
  paid: { label: "입금완료", dot: "bg-emerald-500", card: "border-emerald-100 bg-emerald-50/70", text: "text-emerald-700" },
  due: { label: "납부예정", dot: "bg-amber-400", card: "border-amber-100 bg-amber-50/70", text: "text-amber-700" },
  partial: { label: "일부입금", dot: "bg-amber-500", card: "border-amber-200 bg-amber-50", text: "text-amber-800" },
  overdue: { label: "미납", dot: "bg-red-500", card: "border-red-100 bg-red-50/80", text: "text-red-600" },
  check: { label: "확인필요", dot: "bg-orange-500", card: "border-orange-200 bg-orange-50", text: "text-orange-700" },
  none: { label: "청구 전", dot: "bg-slate-300", card: "border-slate-200 bg-white", text: "text-slate-500" },
  vacant: { label: "공실", dot: "bg-slate-300", card: "border-dashed border-slate-300 bg-slate-50", text: "text-slate-500" },
  owner: { label: "주인세대", dot: "bg-indigo-300", card: "border-indigo-100 bg-indigo-50/60", text: "text-indigo-700" },
};

function statusOf(u: DashUnit, d: Dashboard): Status {
  if (u.status === "owner") return "owner";
  if (u.status === "vacant") return "vacant";
  switch (u.charge_status) {
    case "paid":
    case "waived":
      return "paid";
    case "none":
      return "none";
    case "partial":
    case "open": {
      const overdue = u.due_date != null && u.due_date < d.as_of;
      if (overdue) return isUnsure(d) ? "check" : "overdue";
      return u.charge_status === "partial" ? "partial" : "due";
    }
    default:
      return "none";
  }
}

function dateNote(u: DashUnit, s: Status): string {
  if (s === "paid") return u.paid_on ? `(${mmdd(u.paid_on)})` : "";
  if (s === "overdue" || s === "check") return `(기한 ${mmdd(u.due_date)})`;
  if (s === "due" || s === "partial") return `(${mmdd(u.due_date)})`;
  return "";
}

function greeting(): string {
  const h = Number(new Date().toLocaleString("en-US", { timeZone: "Asia/Seoul", hour: "numeric", hour12: false }));
  if (h >= 5 && h < 11) return "좋은 아침입니다!";
  if (h >= 11 && h < 17) return "좋은 오후입니다!";
  return "좋은 저녁입니다!";
}

export default function Home() {
  const { orgs, orgId, setOrgId, error: orgError } = useOrg();
  const [asOf, setAsOf] = useState(todayKst());
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!orgId) return;
    try {
      setD(await api<Dashboard>(`/api/v1/dashboard?organization_id=${orgId}&as_of=${asOf}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, asOf]);
  useEffect(() => { reload(); }, [reload]);

  async function generateCharges() {
    if (!d) return;
    setBusy(true);
    try {
      await api(`/api/v1/charges/generate?organization_id=${orgId}&period=${d.period}`, { method: "POST" });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (orgs && orgs.length === 0) {
    return (
      <section className="card mx-auto max-w-xl space-y-4 p-8 text-center">
        <Landmark className="mx-auto h-10 w-10 text-blue-600" />
        <h1 className="page-title">ROOMAX에 오신 것을 환영합니다</h1>
        <p className="text-slate-600">호실·계약·납부일을 먼저 등록하면 대시보드에 현황이 나타납니다.</p>
        <a href="/onboarding" className="btn-primary px-5 py-2.5">건물·호실 등록 시작</a>
      </section>
    );
  }

  const warnCount = d?.attention.filter((a) => a.level === "warn").length ?? 0;
  const asOfLabel = new Date(`${asOf}T00:00:00`).toLocaleDateString("ko-KR", {
    year: "numeric", month: "long", day: "numeric", weekday: "short" });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start gap-4">
        <div className="mr-auto">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-[28px]">
            사장님, {greeting()} <Sun className="h-7 w-7 text-amber-400" aria-hidden />
          </h1>
          <p className="page-sub">오늘도 안정적인 임대 운영을 응원합니다.</p>
        </div>
        <div className="flex items-center gap-3">
          {orgs && orgs.length > 1 && (
            <select className="field py-1.5" value={orgId} onChange={(e) => setOrgId(e.target.value)} aria-label="건물">
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          <label className="relative flex items-center gap-2 rounded-xl px-2 py-1.5 text-sm text-slate-600 hover:bg-white" title="기준일 바꾸기">
            <CalendarDays className="h-4 w-4 text-slate-400" />
            <span>{asOfLabel}</span>
            <input type="date" className="absolute inset-0 cursor-pointer opacity-0" value={asOf} aria-label="기준일"
              onChange={(e) => e.target.value && setAsOf(e.target.value)} />
          </label>
          <a href="#alerts" className="relative rounded-full p-2 text-slate-600 hover:bg-white" aria-label={`확인할 알림 ${warnCount}건`}>
            <Bell className="h-6 w-6" />
            {warnCount > 0 && (
              <span className="absolute right-0.5 top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-red-500 px-1 text-[11px] font-bold text-white">
                {warnCount}
              </span>
            )}
          </a>
        </div>
      </header>

      {(error || orgError) && <p className="whitespace-pre-line rounded-xl bg-red-50 p-3 text-sm text-red-800">{error ?? orgError}</p>}
      {!d && !error && !orgError && <p className="text-sm text-slate-500">불러오는 중…</p>}

      {d && <DashboardBody d={d} busy={busy} onGenerate={generateCharges} />}
    </div>
  );
}

function DashboardBody({ d, busy, onGenerate }: { d: Dashboard; busy: boolean; onGenerate: () => void }) {
  const unsure = isUnsure(d);
  const occupied = d.units.filter((u) => u.status === "occupied");
  const paidCount = occupied.filter((u) => u.charge_status === "paid" || u.charge_status === "waived").length;

  return (
    <>
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-5 lg:gap-4">
        <Kpi icon={CalendarDays} tone="blue" label="이번 달 임대수입" value={won(d.money.rent_charged)}
          sub={d.money.charges_ready ? `임대 ${d.counts.occupied}호실 청구 기준` : "이번 달 청구 전"} />
        <Kpi icon={Wallet} tone="green" label="입금 완료" value={won(d.money.rent_received)}
          sub={d.money.bank_covered ? `${paidCount}/${occupied.length} 호실 완납` : "이번 달 은행 내역 없음"} href="/payments" />
        <Kpi icon={AlertCircle} tone={unsure ? "orange" : "red"} label={unsure ? "미납 금액 (확인 전)" : "미납 금액"}
          value={won(d.money.overdue_total)} sub={`${d.money.overdue_count}건 · 납부일 지남`} href="/payments" />
        <Kpi icon={Receipt} tone="violet" label="이번 달 운영비" value={won(d.money.operating_total)}
          sub={d.money.bank_covered ? "전기 · 수도 · 청소 · 수리" : "이번 달 은행 내역 없음"} href="/expenses" />
        <Kpi icon={TrendingUp} tone="noi" label={d.money.complete ? "순운영수익" : "순운영수익 (확정 전)"}
          value={won(d.money.noi)} sub={d.money.bank_covered ? "확인된 입금 − 운영비" : "은행 내역을 가져오면 계산"} href="/expenses" wide />
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <UnitsCard d={d} />
        <div className="space-y-4 xl:col-span-4">
          <FlowChart d={d} />
          <RecentCard d={d} />
        </div>
        <div className="space-y-4 xl:col-span-3">
          <AlertsCard d={d} busy={busy} onGenerate={onGenerate} />
          <QuickActions />
        </div>
      </section>

      <section className="grid items-start gap-4 lg:grid-cols-3">
        <ListCard icon={CalendarClock} title="7일 안 납부 예정" empty="예정된 납부가 없습니다.">
          {d.due_soon.map((x) => (
            <li key={x.unit_no + x.due_date} className="flex items-center justify-between gap-2">
              <span><b className="font-semibold">{x.unit_no}호</b> <span className="text-slate-500">{mmdd(x.due_date)}</span></span>
              <span className="tabular-nums">{won(x.outstanding)}</span>
            </li>
          ))}
        </ListCard>
        <ListCard icon={FileSearch} title="계약 만료 · 보증금 반환" empty="60일 안에 만료되는 계약이 없습니다.">
          {d.lease_endings.map((x) => (
            <li key={x.unit_no} className="space-y-0.5">
              <div className="flex justify-between gap-2">
                <span><b className="font-semibold">{x.unit_no}호</b> {x.tenant_name}</span>
                <span className={`chip ${x.days_left < 0 ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-600"}`}>
                  {x.days_left >= 0 ? `D-${x.days_left}` : `${-x.days_left}일 지남`}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                만료 {x.end_date}{x.deposit_to_return ? ` · 반환할 보증금 ${won(x.deposit_to_return)}` : ""}
              </div>
            </li>
          ))}
        </ListCard>
        <ListCard icon={Landmark} title="세금 일정" empty="120일 안에 일반 일정이 없습니다."
          footnote="일반 법정 일정입니다. 본인 해당 여부(사업자등록·주택 수·공시가격 등)는 확인이 필요하며, 마감이 주말·공휴일이면 다음 영업일입니다.">
          {d.tax_events.map((x) => (
            <li key={x.name + x.end} className="space-y-0.5">
              <div className="flex justify-between gap-2">
                <a href={x.url} target="_blank" rel="noreferrer" className="font-medium underline-offset-2 hover:underline">{x.name}</a>
                <span className={`chip shrink-0 ${x.in_progress ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-600"}`}>
                  {x.in_progress ? `진행 중 D-${x.days_until_end}` : mmdd(x.start)}
                </span>
              </div>
              <div className="text-xs text-slate-500">{x.start} ~ {x.end} · {x.note}</div>
            </li>
          ))}
        </ListCard>
      </section>
    </>
  );
}

const KPI_TONE = {
  blue: { card: "bg-blue-50/70 border-blue-100", icon: "bg-white text-blue-600", value: "text-slate-900" },
  green: { card: "bg-emerald-50/70 border-emerald-100", icon: "bg-white text-emerald-600", value: "text-emerald-700" },
  red: { card: "bg-red-50/80 border-red-100", icon: "bg-white text-red-500", value: "text-red-600" },
  orange: { card: "bg-orange-50 border-orange-200", icon: "bg-white text-orange-500", value: "text-orange-700" },
  violet: { card: "bg-violet-50/60 border-violet-100", icon: "bg-white text-violet-600", value: "text-slate-900" },
  noi: { card: "bg-sky-50 border-blue-200 ring-1 ring-blue-100", icon: "bg-white text-emerald-500", value: "text-blue-700" },
} as const;

function Kpi({ icon: Icon, tone, label, value, sub, href, wide }: {
  icon: LucideIcon; tone: keyof typeof KPI_TONE; label: string; value: string; sub: string; href?: string; wide?: boolean;
}) {
  const t = KPI_TONE[tone];
  const body = (
    <div className={`flex h-full items-start gap-2.5 rounded-2xl border p-4 shadow-card ${t.card}`}>
      <span className={`hidden h-10 w-10 shrink-0 place-items-center rounded-full shadow-sm sm:grid ${t.icon}`}>
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-slate-600">{label}</div>
        {/* 5칸일 때도 '2,260,000원' 이 잘리지 않게 화면 폭에 맞춰 크기 조절 */}
        <div className={`mt-0.5 whitespace-nowrap text-xl font-bold tabular-nums tracking-tight sm:text-[22px] lg:text-[clamp(1rem,1.3vw,1.375rem)] ${t.value}`}>{value}</div>
        <div className="mt-0.5 truncate text-xs text-slate-500">{sub}</div>
      </div>
    </div>
  );
  const cls = wide ? "col-span-2 lg:col-span-1" : "";
  return href ? <a href={href} className={`${cls} block transition-opacity hover:opacity-90`}>{body}</a> : <div className={cls}>{body}</div>;
}

function CardHead({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="card-title">{title}</h2>
      {action}
    </div>
  );
}

const LEGEND: Status[] = ["paid", "due", "overdue", "vacant"];

function UnitsCard({ d }: { d: Dashboard }) {
  return (
    <div className="card p-4 sm:p-5 xl:col-span-5">
      <CardHead title="호실별 임대 현황" action={<a href="/payments" className="btn-secondary btn-sm">전체 보기</a>} />
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        {LEGEND.map((s) => (
          <span key={s} className="flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-full ${STATUS[s].dot}`} />{STATUS[s].label}
          </span>
        ))}
        <span className="text-slate-400">임대 {d.counts.rental} · 입주 {d.counts.occupied} · 공실 {d.counts.vacant}</span>
      </div>

      {/* 데스크톱: 카드 격자 */}
      <div className="hidden grid-cols-3 gap-2.5 sm:grid">
        {d.units.map((u) => {
          const s = statusOf(u, d);
          const st = STATUS[s];
          return (
            <a key={u.unit_no} href="/payments" className={`group rounded-xl border p-3 transition-shadow hover:shadow-card ${st.card}`}>
              <div className="flex items-center justify-between">
                <span className={`font-bold ${s === "overdue" ? "text-red-600" : "text-slate-900"}`}>{u.unit_no}호</span>
                <ChevronRight className="h-4 w-4 text-slate-400 group-hover:text-slate-600" />
              </div>
              <div className="mt-0.5 text-[13px] text-slate-700">
                {u.status === "occupied" ? manwon(u.rent) : u.floor != null ? `${u.floor}층` : "—"}
              </div>
              <div className={`mt-2 flex items-center gap-1.5 text-[13px] font-semibold ${st.text}`}>
                <span className={`h-2.5 w-2.5 rounded-full ${st.dot}`} />{st.label}
              </div>
              <div className="mt-0.5 h-4 text-xs text-slate-500">{dateNote(u, s)}</div>
            </a>
          );
        })}
      </div>

      {/* 모바일: 목록 */}
      <ul className="divide-y divide-slate-100 sm:hidden">
        {d.units.map((u) => {
          const s = statusOf(u, d);
          const st = STATUS[s];
          return (
            <li key={u.unit_no}>
              <a href="/payments" className="flex items-center gap-3 py-2.5">
                <span className={`h-2.5 w-2.5 rounded-full ${st.dot}`} />
                <span className="w-14 font-bold">{u.unit_no}호</span>
                <span className="flex-1 text-sm text-slate-600">{u.status === "occupied" ? manwon(u.rent) : ""}</span>
                <span className={`chip ${st.card} ${st.text} border`}>{st.label}</span>
                <ChevronRight className="h-4 w-4 text-slate-400" />
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// 검증한 범주 팔레트 (dataviz validate_palette: light 모드 전 항목 PASS)
const BARS = [
  { key: "rent_received", label: "임대수입", color: "#2563eb" },
  { key: "operating_total", label: "운영비", color: "#16a34a" },
  { key: "non_operating_total", label: "기타지출", color: "#8b5cf6" },
] as const;

function FlowChart({ d }: { d: Dashboard }) {
  const values = BARS.map((b) => d.money[b.key]);  // null = 모름 → 막대 없이 '—'
  const max = Math.max(...values.map((v) => v ?? 0), 1);
  return (
    <div className="card p-4 sm:p-5">
      <CardHead title="이번 달 수입·지출 현황" action={<a href="/expenses" className="btn-secondary btn-sm">더보기</a>} />
      <p className="-mt-2 mb-2 text-right text-xs text-slate-400">(단위: 만원)</p>
      <div className="flex h-44 items-end justify-around gap-4 border-b border-slate-200 px-2" role="list" aria-label="이번 달 수입·지출">
        {BARS.map((b, i) => {
          const v = values[i];
          const h = v == null ? 0 : Math.max((v / max) * 100, v > 0 ? 2 : 0);
          return (
            <div key={b.key} role="listitem" aria-label={`${b.label} ${won(v)}`}
              className="group relative flex h-full w-16 flex-col items-center justify-end">
              <span className="mb-1 text-sm font-semibold tabular-nums text-slate-700">{v == null ? "—" : Math.round(v / 10000).toLocaleString("ko-KR")}</span>
              <div className="w-full rounded-t-[4px] transition-opacity group-hover:opacity-85" style={{ height: `${h}%`, background: b.color }} />
              <div className="pointer-events-none absolute -top-8 z-10 hidden whitespace-nowrap rounded-lg bg-slate-900 px-2 py-1 text-xs text-white shadow group-hover:block">
                {b.label} {won(v)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-around text-xs text-slate-600">
        {BARS.map((b) => <span key={b.key} className="w-16 text-center">{b.label}</span>)}
      </div>
      {!d.money.bank_covered && <p className="mt-3 text-xs text-slate-500">이번 달 은행 내역이 아직 없어 수입·지출을 알 수 없습니다.</p>}
      <p className="mt-3 text-[11px] text-slate-400">임대수입 = 확인된 월세 입금 · 기타지출 = 생활비·주인세대 (순운영수익 제외)</p>
    </div>
  );
}

function RecentCard({ d }: { d: Dashboard }) {
  return (
    <div className="card p-4 sm:p-5">
      <CardHead title="최근 거래 내역" action={<a href="/payments" className="btn-secondary btn-sm">더보기</a>} />
      {d.recent_transactions.length === 0 ? (
        <p className="text-sm text-slate-500">은행 거래내역을 가져오면 여기에 보입니다.</p>
      ) : (
        <ul className="space-y-2.5 text-sm">
          {d.recent_transactions.map((t, i) => (
            <li key={i} className="flex items-center gap-3">
              <span className="w-11 shrink-0 tabular-nums text-slate-500">{mmdd(new Date(t.occurred_at).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }))}</span>
              <span className={`min-w-0 flex-1 truncate ${t.confirmed ? "text-slate-800" : "text-slate-400"}`}>{t.label}</span>
              <span className={`shrink-0 font-semibold tabular-nums ${t.direction === "in" ? "text-emerald-600" : "text-red-500"}`}>
                {t.direction === "in" ? "+" : "−"}{t.amount.toLocaleString("ko-KR")}원
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const ALERT_ICON: Record<string, { icon: LucideIcon; tone: string }> = {
  bank_none: { icon: ArrowDownToLine, tone: "bg-amber-50 text-amber-600" },
  bank_stale: { icon: ArrowDownToLine, tone: "bg-amber-50 text-amber-600" },
  charges_missing: { icon: ReceiptText, tone: "bg-amber-50 text-amber-600" },
  review_in: { icon: Wallet, tone: "bg-blue-50 text-blue-600" },
  review_out: { icon: Receipt, tone: "bg-violet-50 text-violet-600" },
  overdue: { icon: CircleAlert, tone: "bg-red-50 text-red-500" },
  deposit_unreceived: { icon: Landmark, tone: "bg-sky-50 text-sky-600" },
  lease_ending: { icon: CalendarClock, tone: "bg-indigo-50 text-indigo-600" },
  vacant: { icon: Info, tone: "bg-slate-100 text-slate-500" },
};

function AlertsCard({ d, busy, onGenerate }: { d: Dashboard; busy: boolean; onGenerate: () => void }) {
  return (
    <div id="alerts" className="card scroll-mt-20 p-4 sm:p-5">
      <CardHead title="오늘의 알림" />
      {d.attention.length === 0 ? (
        <p className="text-sm text-slate-500">확인할 것이 없습니다.</p>
      ) : (
        <ul className="space-y-3">
          {d.attention.map((a, i) => {
            const { icon: Icon, tone } = ALERT_ICON[a.kind] ?? { icon: Info, tone: "bg-slate-100 text-slate-500" };
            return (
              <li key={i} className="flex gap-3">
                <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${tone}`}><Icon className="h-[18px] w-[18px]" /></span>
                <div className="min-w-0 flex-1 text-sm leading-snug">
                  <p className={a.level === "warn" ? "text-slate-900" : "text-slate-600"}>{a.message}</p>
                  {a.kind === "charges_missing" ? (
                    <button type="button" className="btn-primary btn-sm mt-1.5" disabled={busy} onClick={onGenerate}>
                      {d.period} 청구 생성
                    </button>
                  ) : (
                    <a href={a.href} className="mt-0.5 inline-block text-xs font-semibold text-blue-600 hover:underline">바로가기</a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const QUICK = [
  { href: "/contracts", label: "계약서 등록", icon: FilePlus2, tone: "bg-blue-50 text-blue-600" },
  { href: "/payments", label: "거래내역 불러오기", icon: ArrowDownToLine, tone: "bg-emerald-50 text-emerald-600" },
  { href: "/expenses", label: "지출 등록", icon: Receipt, tone: "bg-rose-50 text-rose-500" },
  { href: "/onboarding", label: "호실 등록", icon: Landmark, tone: "bg-violet-50 text-violet-600" },
];

function QuickActions() {
  return (
    <div className="card p-4 sm:p-5">
      <CardHead title="빠른 기능" />
      <div className="grid grid-cols-4 gap-2">
        {QUICK.map(({ href, label, icon: Icon, tone }) => (
          <a key={label} href={href} className="flex flex-col items-center gap-1.5 rounded-xl p-1.5 text-center text-[11px] font-medium text-slate-700 hover:bg-slate-50">
            <span className={`grid h-11 w-11 place-items-center rounded-xl ${tone}`}><Icon className="h-5 w-5" /></span>
            <span className="leading-tight">{label}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

function ListCard({ icon: Icon, title, empty, footnote, children }: {
  icon: LucideIcon; title: string; empty: string; footnote?: string; children: React.ReactNode[];
}) {
  return (
    <div className="card p-4 sm:p-5">
      <h2 className="card-title mb-3 flex items-center gap-2"><Icon className="h-4 w-4 text-slate-400" />{title}</h2>
      <div className="text-sm">
        {children.length === 0 ? <p className="text-slate-500">{empty}</p> : <ul className="space-y-2.5">{children}</ul>}
        {footnote && <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">{footnote}</p>}
      </div>
    </div>
  );
}
