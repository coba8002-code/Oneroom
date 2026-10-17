"use client";

import { ArrowLeft, Printer } from "lucide-react";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, kst, todayKst, won } from "@/lib/api";
import { useMe } from "@/lib/me";

interface Cert {
  year: number; law: string; notice: string; generated_at: string; building: string; tenant_name: string;
  unit_no: string; address: string | null;
  lease: { start_date: string; end_date: string | null; ended_on: string | null; deposit: number; rent: number; due_day: number };
  lines: { paid_on: string; amount: number; periods: string[] }[];
  total: number; count: number; pending_review_in_year: number; bank_data_to: string | null;
  bank_complete: boolean; year_in_progress: boolean;
}

export default function CertificatePage() {
  return <Suspense fallback={<p className="text-sm text-slate-400">불러오는 중…</p>}><Certificate /></Suspense>;
}

function Certificate() {
  const lease = useSearchParams().get("lease") ?? "";
  const { me } = useMe();
  const thisYear = Number(todayKst().slice(0, 4));
  const [year, setYear] = useState(thisYear - 1);
  const [c, setC] = useState<Cert | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [landlord, setLandlord] = useState("");
  useEffect(() => { if (me?.user.name) setLandlord((v) => v || me.user.name || ""); }, [me]);

  const latest = useRef(0);  // 연도를 빨리 바꿀 때 늦게 온 예전 응답이 덮지 않게
  const load = useCallback(async () => {
    const ticket = ++latest.current;
    setErr(null); setC(null);
    try {
      const x = await api<Cert>(`/api/v1/leases/${lease}/rent-certificate?year=${year}`);
      if (ticket === latest.current) setC(x);
    } catch (e) { if (ticket === latest.current) setErr((e as Error).message); }
  }, [lease, year]);
  useEffect(() => { if (lease) load(); }, [load, lease]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <a href="/units" className="mb-1 inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft className="h-4 w-4" />호실·계약</a>
          <h1 className="page-title">월세 납부 확인서</h1>
          <p className="page-sub">임차인의 월세 세액공제 증빙에 곁들일 수 있는 확인서입니다. 장부에 월세로 확정된 입금만 적습니다.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm text-slate-600">연도 (입금일 기준)
            <select className="field mt-1 block" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {Array.from({ length: 6 }, (_, i) => thisYear - i).map((y) => <option key={y} value={y}>{y}년</option>)}</select></label>
          <label className="text-sm text-slate-600">임대인 이름 (확인서에만, 저장 안 함)
            <input className="field mt-1 block w-40" value={landlord} onChange={(e) => setLandlord(e.target.value)} /></label>
          <button type="button" className="btn-secondary" disabled={!c} onClick={() => window.print()}><Printer className="h-4 w-4" />인쇄·PDF</button>
        </div>
      </header>
      {!lease && <p className="text-sm text-slate-500">호실·계약 화면에서 계약을 골라 여세요.</p>}
      {err && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800" role="status">{err}</p>}
      {c && <Warnings c={c} />}
      {c ? <Paper c={c} landlord={landlord} /> : lease && !err && <p className="text-sm text-slate-400">불러오는 중…</p>}
    </div>
  );
}

function Warnings({ c }: { c: Cert }) {
  const w: string[] = [];
  if (c.pending_review_in_year > 0) w.push(`${c.year}년 입금 중 검토 대기 ${c.pending_review_in_year}건은 넣지 않았습니다 — 이 임차인의 월세가 있으면 임대료 관리에서 먼저 확정하세요.`);
  if (!c.bank_complete) w.push(c.bank_data_to ? `통장 내역이 ${c.bank_data_to}까지만 있습니다${c.year_in_progress ? " (올해는 진행 중)" : ""}. 그 뒤 입금은 들어가지 않았습니다.`
    : "가져온 통장 내역이 없습니다.");
  if (w.length === 0) return null;
  return <ul className="list-disc space-y-0.5 rounded-xl bg-amber-50 p-3 pl-7 text-sm text-amber-900 print:hidden">{w.map((x) => <li key={x}>{x}</li>)}</ul>;
}

function Paper({ c, landlord }: { c: Cert; landlord: string }) {
  const l = c.lease;
  const row = (k: string, v: React.ReactNode) => <tr><th className="w-32 bg-slate-50 px-3 py-1.5 text-left font-medium">{k}</th><td className="px-3 py-1.5">{v}</td></tr>;
  return (
    <article className="card mx-auto max-w-2xl space-y-5 p-6 text-sm print:max-w-none print:border-0 print:p-0 print:shadow-none">
      <h2 className="text-center text-2xl font-bold tracking-widest">월세 납부 확인서</h2>
      <table className="w-full border border-slate-300 [&_td]:border [&_td]:border-slate-300 [&_th]:border [&_th]:border-slate-300">
        <tbody>
          {row("임차인", c.tenant_name)}
          {row("임대 주택", [c.address, c.unit_no.startsWith(`${c.building} `) ? null : c.building, `${c.unit_no}호`]
            .filter(Boolean).join(" "))}{/* 건물이 여러 동이면 호실 이름에 건물 이름이 이미 들어 있음 */}
          {row("계약 기간", <>{l.start_date} ~ {l.end_date ?? "—"}{l.ended_on ? ` (실제 종료 ${l.ended_on})` : ""}</>)}
          {row("보증금 · 월세", <>{won(l.deposit)} · 월 {won(l.rent)} (매월 {l.due_day}일)</>)}
          {row("대상 기간", `${c.year}년 1월 1일 ~ 12월 31일 입금분`)}
        </tbody>
      </table>
      <table className="w-full tabular-nums">
        <thead className="border-b border-slate-300 text-xs text-slate-500"><tr><th className="py-1 text-left">입금일</th><th className="text-left">해당 청구 월</th><th className="text-right">금액</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {c.lines.length === 0 ? <tr><td colSpan={3} className="py-3 text-center text-slate-500">이 해에 월세로 확정된 입금이 없습니다.</td></tr>
            : c.lines.map((x, i) => <tr key={i}><td className="py-1">{x.paid_on}</td><td>{x.periods.join(", ") || "선납(다음 청구에 채움)"}</td><td className="text-right">{won(x.amount)}</td></tr>)}
        </tbody>
        <tfoot className="border-t border-slate-300 font-semibold"><tr><td className="py-1.5" colSpan={2}>합계 ({c.count}건)</td><td className="text-right">{won(c.total)}</td></tr></tfoot>
      </table>
      <p className="text-center leading-7">위 임차인으로부터 {c.year}년에 위와 같이 월세를 받았음을 확인합니다.<br />
        {todayKst()}</p>
      <p className="text-right leading-8">임대인 <span className="inline-block min-w-32 border-b border-slate-400 text-center">{landlord || " "}</span> (서명 또는 인)</p>
      <div className="space-y-1 border-t border-slate-200 pt-3 text-xs text-slate-500">
        <p>{c.notice}</p>
        <p>참고 법령: {c.law} · 기준: {c.bank_data_to ? `${c.bank_data_to}까지의 통장 내역` : "통장 내역 없음"} · 작성 {kst(c.generated_at)} (ROOMAX)</p>
        <p>보증금은 월세가 아니므로 넣지 않았습니다.</p>
      </div>
    </article>
  );
}
