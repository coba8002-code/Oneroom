"use client";

import { Download, Printer } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiFetch, kst, todayKst, won } from "@/lib/api";

interface Report {
  period: string; as_of: string; month_closed: boolean; generated_at: string; notice: string;
  status: { bank_covered: boolean; bank_data_as_of: string | null; charges_ready: boolean; unconfirmed_in: number;
    unconfirmed_out: number; pending_review_in: number; complete: boolean };
  occupancy: { rental_units: number; leased_in_month: number };
  money: { rent_charged: number | null; rent_received: number | null; operating: Record<string, number | null>;
    operating_total: number | null; noi: number | null; excluded: Record<string, number | null>;
    deposit_in: number | null; deposit_out: number | null };
  charges: { unit_no: string; due_date: string; amount: number; paid: number; status: string }[];
  overdue: { total: number; items: { unit_no: string; period: string; due_date: string; outstanding: number; days_past_due: number }[] };
  deposits_liability: number;
  vacancies: { unit_no: string; vacant_since: string | null; days_vacant: number | null; missed_rent: number | null; asking_rent: number | null }[];
  routines_done: { done_on: string; title: string; unit_no: string | null; cost: number | null }[];
  routines_overdue: { title: string; unit_no: string | null; next_due_on: string }[];
  repairs: { unit_no: string | null; fixture_name: string | null; reported_on: string; completed_on: string | null; status: string; cost: number | null }[];
  lease_endings: { unit_no: string; end_date: string; stage: string; notice_until: string; notice_sent_on: string | null; deposit_to_return: number | null }[];
}

const STATUS: Record<string, string> = { paid: "완납", partial: "일부", open: "미입금", waived: "면제" };
const lastMonth = () => {
  const [y, m] = todayKst().split("-").map(Number);
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
};

export default function ReportsPage() {
  const [period, setPeriod] = useState(lastMonth());
  const [r, setR] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const latest = useRef(0);  // 월을 빨리 바꿀 때 늦게 온 예전 응답이 화면을 덮지 않게
  const load = useCallback(async () => {
    const ticket = ++latest.current;
    setErr(null); setR(null);
    try {
      const x = await api<Report>(`/api/v1/reports/monthly-summary?period=${period}`);
      if (ticket === latest.current) setR(x);
    } catch (e) { if (ticket === latest.current) setErr((e as Error).message); }
  }, [period]);
  useEffect(() => { load(); }, [load]);

  async function excel() {
    try {
      const res = await apiFetch(`/api/v1/reports/monthly-summary/export.xlsx?period=${period}`);
      if (!res.ok) throw new Error("내려받지 못했습니다");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await res.blob()); a.download = `roomax-report-${period}.xlsx`; a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setErr((e as Error).message); }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <h1 className="page-title">월간 운영 보고서</h1>
          <p className="page-sub">한 달을 한 장으로. 인쇄하거나 PDF로 저장해 보관·공유하세요 (임차인 이름·연락처는 넣지 않습니다).</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-slate-600">월 <input type="month" className="field ml-1" aria-label="보고서 월" value={period}
            max={todayKst().slice(0, 7)} onChange={(e) => e.target.value && setPeriod(e.target.value)} /></label>
          <button type="button" className="btn-secondary" onClick={() => window.print()} disabled={!r}><Printer className="h-4 w-4" />인쇄·PDF</button>
          <button type="button" className="btn-secondary" onClick={excel} disabled={!r}><Download className="h-4 w-4" />엑셀</button>
        </div>
      </header>
      {err && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800" role="status">{err}</p>}
      {!r ? (!err && <p className="text-sm text-slate-400">불러오는 중…</p>) : <ReportBody r={r} />}
    </div>
  );
}

function Money({ v }: { v: number | null | undefined }) {
  return <span className="tabular-nums">{won(v)}</span>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card break-inside-avoid p-4 print:border print:shadow-none">
      <h2 className="card-title mb-2">{title}</h2>
      <div className="text-sm">{children}</div>
    </section>
  );
}

function ReportBody({ r }: { r: Report }) {
  const st = r.status;
  const warn: string[] = [];
  if (!st.bank_covered) warn.push("이 달의 은행 내역이 없어 입금·운영비·순운영수익을 비워 두었습니다.");
  if (st.unconfirmed_in + st.unconfirmed_out > 0) warn.push(`이 달 미확정 거래 ${st.unconfirmed_in + st.unconfirmed_out}건 — 확정 전이라 금액이 바뀔 수 있습니다.`);
  if (st.pending_review_in > 0) warn.push(`입금 검토 대기 ${st.pending_review_in}건 — 미수 중 일부는 실제로 낸 돈일 수 있습니다.`);
  if (!r.month_closed) warn.push(`진행 중인 달입니다 (${r.as_of} 기준).`);

  return (
    <article className="space-y-4 print:space-y-3">
      <div className="card p-4 print:border print:shadow-none">
        <p className="text-lg font-bold">{r.period} 운영 보고서</p>
        <p className="text-xs text-slate-500">기준일 {r.as_of} · 은행 내역 {st.bank_data_as_of ? `${kst(st.bank_data_as_of)}까지` : "없음"} · 작성 {kst(r.generated_at)}</p>
        {warn.length > 0 && <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-amber-800">{warn.map((w) => <li key={w}>{w}</li>)}</ul>}
        <p className="mt-1 text-xs text-slate-500">{r.notice}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 print:grid-cols-3">
        {([["월세 청구", r.money.rent_charged], ["월세 입금(확정)", r.money.rent_received], ["미수(납부일 지남)", r.overdue.total],
          ["운영비", r.money.operating_total], ["순운영수익", r.money.noi], ["보증금 잔액(부채)", r.deposits_liability]] as [string, number | null][]).map(([k, v]) => (
          <div key={k} className="card p-3 print:border print:shadow-none">
            <p className="text-xs text-slate-500">{k}</p><p className="text-lg font-bold"><Money v={v} /></p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0 print:grid-cols-2">
        <Section title={`청구·입금 (임대 ${r.occupancy.rental_units}실 중 그 달 계약 ${r.occupancy.leased_in_month}실)`}>
          {r.charges.length === 0 ? <p className="text-slate-500">이 달 청구가 없습니다.</p> : (
            <table className="w-full tabular-nums"><thead className="text-xs text-slate-500"><tr className="text-right">
              <th className="text-left">호실</th><th>납부일</th><th>청구</th><th>입금</th><th>상태</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{r.charges.map((c) => (
                <tr key={c.unit_no + c.due_date} className="text-right"><td className="py-1 text-left">{c.unit_no}호</td><td>{c.due_date.slice(5)}</td>
                  <td>{won(c.amount)}</td><td>{won(c.paid)}</td><td>{STATUS[c.status] ?? c.status}</td></tr>))}</tbody></table>
          )}
        </Section>
        <Section title="운영비 (공용) · 제외 항목">
          <table className="w-full tabular-nums"><tbody className="divide-y divide-slate-100">
            {Object.entries(r.money.operating).map(([k, v]) => <tr key={k}><td className="py-1">{k}</td><td className="text-right"><Money v={v} /></td></tr>)}
            <tr className="font-semibold"><td className="py-1">합계</td><td className="text-right"><Money v={r.money.operating_total} /></td></tr>
            {Object.entries(r.money.excluded).map(([k, v]) => <tr key={k} className="text-slate-500"><td className="py-1">제외 — {k}</td><td className="text-right"><Money v={v} /></td></tr>)}
            <tr className="text-slate-500"><td className="py-1">보증금 받음 / 돌려줌</td><td className="text-right"><Money v={r.money.deposit_in} /> / <Money v={r.money.deposit_out} /></td></tr>
          </tbody></table>
          <p className="mt-1 text-xs text-slate-500">생활비·주인세대 비용은 순운영수익에 넣지 않습니다. 보증금은 수입이 아니라 부채입니다.</p>
        </Section>
        <Section title="미수 (기준일에 납부일이 지난 것)">
          {r.overdue.items.length === 0 ? <p className="text-slate-500">없습니다.</p> : (
            <ul className="divide-y divide-slate-100">{r.overdue.items.map((i) => (
              <li key={i.unit_no + i.period} className="flex justify-between py-1 tabular-nums"><span>{i.unit_no}호 {i.period} ({i.days_past_due}일 지남)</span><span>{won(i.outstanding)}</span></li>))}</ul>
          )}
        </Section>
        <Section title="공실">
          {r.vacancies.length === 0 ? <p className="text-slate-500">없습니다.</p> : (
            <ul className="divide-y divide-slate-100">{r.vacancies.map((v) => (
              <li key={v.unit_no} className="flex justify-between gap-2 py-1 tabular-nums"><span>{v.unit_no}호 {v.days_vacant != null ? `${v.days_vacant}일째` : "(시작일 모름)"}</span>
                <span className="text-right">놓친 월세 {won(v.missed_rent)} · 모집 {won(v.asking_rent)}</span></li>))}</ul>
          )}
        </Section>
        <Section title="정기 점검 · 수리">
          {r.routines_done.length + r.routines_overdue.length + r.repairs.length === 0 ? <p className="text-slate-500">기록이 없습니다.</p> : (
            <ul className="divide-y divide-slate-100">
              {r.routines_done.map((d, i) => <li key={`d${i}`} className="flex justify-between gap-2 py-1"><span>✓ {d.done_on.slice(5)} {d.title} ({d.unit_no ? `${d.unit_no}호` : "공용"})</span><Money v={d.cost} /></li>)}
              {r.routines_overdue.map((t, i) => <li key={`o${i}`} className="py-1 text-red-700">! {t.title} ({t.unit_no ? `${t.unit_no}호` : "공용"}) — 예정일 {t.next_due_on} 지남</li>)}
              {r.repairs.map((x, i) => <li key={`r${i}`} className="flex justify-between gap-2 py-1"><span>수리 {x.reported_on.slice(5)} {x.fixture_name ?? ""} ({x.unit_no ? `${x.unit_no}호` : "공용"}) · {x.status === "done" ? `완료 ${x.completed_on?.slice(5)}` : "진행 중"}</span><Money v={x.cost} /></li>)}
            </ul>
          )}
          <p className="mt-1 text-xs text-slate-500">점검·수리 비용은 기록용 — 결산에는 은행 출금 분류만 들어갑니다.</p>
        </Section>
        <Section title="계약 만료 · 갱신 통지">
          {r.lease_endings.length === 0 ? <p className="text-slate-500">가까운 만료가 없습니다.</p> : (
            <ul className="divide-y divide-slate-100">{r.lease_endings.map((e) => (
              <li key={e.unit_no} className="py-1">{e.unit_no}호 만료 {e.end_date} · 통지 {e.notice_sent_on ? `보냄(${e.notice_sent_on})` : `기한 ${e.notice_until}`}
                {e.deposit_to_return ? ` · 돌려줄 보증금 ${won(e.deposit_to_return)}` : ""}</li>))}</ul>
          )}
        </Section>
      </div>
    </article>
  );
}
