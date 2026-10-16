"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Dashboard, kst, todayKst, won } from "@/lib/api";
import { useOrg } from "@/lib/useOrg";

const field = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm";
const primary = "rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50";

type DashUnit = Dashboard["units"][number];

/** 납부일이 그 달에 없으면 말일 (서버 규칙과 같음) */
function dueDateOf(period: string, dueDay: number): string {
  const [y, m] = period.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return `${period}-${String(Math.min(dueDay, last)).padStart(2, "0")}`;
}

/** 은행 내역이 없거나 오래됐거나 입금 검토가 남았으면, 납부일이 지났어도 '미수'로 단정하지 않는다 (PRD §4) */
const UNSURE_KINDS = ["bank_none", "bank_stale", "review_in"];
const isUnsure = (d: Dashboard) => d.attention.some((a) => UNSURE_KINDS.includes(a.kind));

function unitBadge(u: DashUnit, d: Dashboard): { label: string; tone: string } {
  if (u.status === "owner") return { label: "주인세대", tone: "bg-slate-100 text-slate-600 border-slate-200" };
  if (u.status === "vacant") return { label: "공실", tone: "bg-white text-slate-400 border-dashed border-slate-300" };
  switch (u.charge_status) {
    case "paid":
    case "waived":
      return { label: "완납", tone: "bg-emerald-50 text-emerald-800 border-emerald-200" };
    case "partial":
      return { label: "일부 입금", tone: "bg-amber-50 text-amber-900 border-amber-300" };
    case "open": {
      const overdue = u.due_day != null && dueDateOf(d.period, u.due_day) < d.as_of;
      if (!overdue) return { label: "납부 예정", tone: "bg-white text-slate-700 border-slate-200" };
      return isUnsure(d)
        ? { label: "확인 필요", tone: "bg-amber-50 text-amber-900 border-amber-300" }
        : { label: "미수", tone: "bg-red-50 text-red-800 border-red-200" };
    }
    case "none":
      return { label: "청구 전", tone: "bg-white text-slate-500 border-slate-200" };
    default:
      return { label: "—", tone: "bg-white text-slate-500 border-slate-200" };
  }
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
      <section className="space-y-4">
        <h1 className="text-xl font-semibold">ROOMAX</h1>
        <p className="text-slate-600">호실·계약·납부일을 먼저 등록하면 홈에 현황이 나타납니다.</p>
        <a href="/onboarding" className={`${primary} inline-block px-4 py-2`}>초기 등록 시작</a>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-xl font-semibold">홈</h1>
        {orgs && orgs.length > 1 && (
          <select className={field} value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-600">
          기준일
          <input type="date" className={field} value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
        </label>
      </div>

      {(error || orgError) && (
        <p className="whitespace-pre-line rounded-md bg-red-50 p-3 text-sm text-red-800">{error ?? orgError}</p>
      )}
      {!d && !error && !orgError && <p className="text-sm text-slate-500">불러오는 중…</p>}

      {d && (
        <>
          {d.attention.length > 0 && (
            <section className="space-y-2">
              <h2 className="font-semibold">확인 필요</h2>
              <ul className="space-y-1.5">
                {d.attention.map((a, i) => (
                  <li key={i} className={`flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm ${
                    a.level === "warn" ? "border-amber-300 bg-amber-50 text-amber-950" : "border-slate-200 bg-white text-slate-700"}`}>
                    <span className="flex-1">{a.message}</span>
                    {a.kind === "charges_missing" ? (
                      <button type="button" className={primary} disabled={busy} onClick={generateCharges}>
                        {d.period} 청구 생성
                      </button>
                    ) : (
                      <a href={a.href} className="text-xs font-medium underline underline-offset-2">바로가기</a>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="space-y-2">
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="font-semibold">{d.period} 수지</h2>
              {!d.money.complete && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900">확정 전 수치</span>
              )}
              <span className="ml-auto text-xs text-slate-500">은행 내역 최신: {kst(d.bank_data_as_of)}</span>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              <Tile label="청구" value={won(d.money.rent_charged)} />
              <Tile label="확인된 입금" value={won(d.money.rent_received)} />
              <Tile label={`미수 ${d.money.overdue_count}건${d.money.overdue_count && isUnsure(d) ? " · 확인 전" : ""}`}
                value={won(d.money.overdue_total)}
                tone={d.money.overdue_count ? (isUnsure(d) ? "text-amber-800" : "text-red-700") : undefined} />
              <Tile label="운영비" value={won(d.money.operating_total)} href="/expenses" />
              <Tile label="순운영수익" value={won(d.money.noi)} strong href="/expenses" />
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="font-semibold">
              호실 <span className="text-sm font-normal text-slate-500">
                임대 {d.counts.rental} · 입주 {d.counts.occupied} · 공실 {d.counts.vacant}
                {d.counts.owner ? ` · 주인세대 ${d.counts.owner}` : ""}
              </span>
            </h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {d.units.map((u) => {
                const b = unitBadge(u, d);
                return (
                  <div key={u.unit_no} className={`rounded-lg border p-3 ${b.tone}`}>
                    <div className="flex items-baseline justify-between">
                      <span className="text-base font-semibold">{u.unit_no}</span>
                      <span className="text-xs font-medium">{b.label}</span>
                    </div>
                    {u.status === "occupied" ? (
                      <div className="mt-1 space-y-0.5 text-xs">
                        <div className="truncate text-slate-600">{u.tenant_name}</div>
                        <div className="tabular-nums">{won(u.rent)} · 매월 {u.due_day}일</div>
                        {(u.charge_status === "open" || u.charge_status === "partial") && (
                          <div className="tabular-nums font-medium">남은 금액 {won(u.outstanding)}</div>
                        )}
                      </div>
                    ) : (
                      <div className="mt-1 text-xs text-slate-400">{u.floor != null ? `${u.floor}층` : ""}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <div className="grid gap-6 lg:grid-cols-3">
            <ListCard title="7일 안 납부 예정" empty="없습니다.">
              {d.due_soon.map((x) => (
                <li key={x.unit_no + x.due_date} className="flex justify-between gap-2">
                  <span>{x.unit_no} <span className="text-slate-500">{x.due_date}</span></span>
                  <span className="tabular-nums">{won(x.outstanding)}</span>
                </li>
              ))}
            </ListCard>

            <ListCard title="계약 만료 · 보증금 반환" empty="60일 안에 만료되는 계약이 없습니다.">
              {d.lease_endings.map((x) => (
                <li key={x.unit_no} className="space-y-0.5">
                  <div className="flex justify-between gap-2">
                    <span>{x.unit_no} {x.tenant_name}</span>
                    <span className={x.days_left < 0 ? "text-red-700" : "text-slate-500"}>
                      {x.days_left >= 0 ? `D-${x.days_left}` : `${-x.days_left}일 지남`}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500">
                    만료 {x.end_date}{x.deposit_to_return ? ` · 반환 예정 보증금 ${won(x.deposit_to_return)}` : ""}
                  </div>
                </li>
              ))}
            </ListCard>

            <ListCard title="세금 일정" empty="120일 안에 일반 일정이 없습니다."
              footnote="일반 법정 일정입니다. 본인 해당 여부(사업자등록·주택 수·공시가격 등)는 확인이 필요하며, 마감이 주말·공휴일이면 다음 영업일입니다.">
              {d.tax_events.map((x) => (
                <li key={x.name + x.end} className="space-y-0.5">
                  <div className="flex justify-between gap-2">
                    <a href={x.url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">{x.name}</a>
                    <span className={x.in_progress ? "shrink-0 font-medium text-amber-800" : "shrink-0 text-slate-500"}>
                      {x.in_progress ? `진행 중 · D-${x.days_until_end}` : x.start.slice(5).replace("-", "/")}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500">
                    {x.start} ~ {x.end} · {x.note}
                  </div>
                </li>
              ))}
            </ListCard>
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, strong, tone, href }: {
  label: string; value: string; strong?: boolean; tone?: string; href?: string;
}) {
  const body = (
    <div className={`h-full rounded-md p-3 ${strong ? "bg-slate-900 text-white" : "border bg-white"}`}>
      <div className={`text-xs ${strong ? "text-slate-300" : "text-slate-500"}`}>{label}</div>
      <div className={`mt-0.5 font-semibold tabular-nums ${tone ?? ""}`}>{value}</div>
    </div>
  );
  return href ? <a href={href} className="block hover:opacity-90">{body}</a> : body;
}

function ListCard({ title, empty, footnote, children }: {
  title: string; empty: string; footnote?: string; children: React.ReactNode[];
}) {
  return (
    <section className="space-y-2">
      <h2 className="font-semibold">{title}</h2>
      <div className="rounded-lg border bg-white p-3 text-sm">
        {children.length === 0 ? <p className="text-slate-500">{empty}</p> : <ul className="space-y-2">{children}</ul>}
        {footnote && <p className="mt-3 border-t pt-2 text-xs text-slate-500">{footnote}</p>}
      </div>
    </section>
  );
}
