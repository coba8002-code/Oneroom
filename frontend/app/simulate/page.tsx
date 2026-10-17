"use client";

import { Calculator, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, won } from "@/lib/api";

interface Row { lease_id: string; unit_no: string; tenant_name: string; deposit: number; rent: number; end_date: string | null;
  new_deposit: number; new_rent: number }
interface Summary { annual_rent: number; deposit_total: number; deposit_income: number | null; annual_net: number | null;
  equity: number | null; equity_yield_pct: string | null }
interface Sim {
  as_of: string; rows: Row[]; current: Summary; scenario: Summary; tax_note: string;
  liquidity: { months: { month: string; due: number; cumulative: number; shortfall: number | null }[]; max_cumulative_due: number;
    cash_on_hand: number | null; covered: boolean | null; leases_without_end_date: string[] };
  reference: { months_with_data: number; operating_total: number | null };
}
const json = (body: unknown) => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/[^\d-]/g, "")));

export default function SimulatePage() {
  const [sim, setSim] = useState<Sim | null>(null);
  const [edits, setEdits] = useState<Record<string, { deposit: string; rent: string }>>({});
  const [opts, setOpts] = useState({ deposit_yield_pct: "", annual_opex: "", cash_on_hand: "", property_value: "", conv_rate: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (rows: { lease_id: string; deposit: number; rent: number }[] = []) => {
    setBusy(true); setErr(null);
    try {
      setSim(await api<Sim>("/api/v1/rent-sim", json({ rows, deposit_yield_pct: opts.deposit_yield_pct || null,
        annual_opex: num(opts.annual_opex), cash_on_hand: num(opts.cash_on_hand), property_value: num(opts.property_value) })));
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }, [opts]);
  useEffect(() => { run(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const rowsOut = () => Object.entries(edits).map(([lease_id, v]) => ({ lease_id, deposit: Number(v.deposit || 0), rent: Number(v.rent || 0) }));
  const edit = (r: Row) => edits[r.lease_id] ?? { deposit: String(r.new_deposit), rent: String(r.new_rent) };
  const convert = (r: Row, amount: number) => {
    const rate = Number(opts.conv_rate);
    if (!rate) { setErr("전환율(%)을 먼저 넣으세요"); return; }
    const cur = edit(r);
    setEdits({ ...edits, [r.lease_id]: { deposit: String(Number(cur.deposit) - amount),
      rent: String(Number(cur.rent) + Math.floor((amount * rate) / 100 / 12)) } });
  };
  const cell = (v: number | null | undefined, suffix = "") => (v == null ? "—" : `${won(v)}${suffix}`);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">전월세 시뮬레이션</h1>
        <p className="page-sub">지금 계약에서 출발해 호실별 보증금·월세를 바꿔 보고, 수입·보증금 부채·반환 자금을 비교합니다.</p>
      </header>

      <section className="card grid gap-3 p-5 text-sm sm:grid-cols-2 lg:grid-cols-5">
        {([["deposit_yield_pct", "보증금 운용 수익률 (연 %)", "예: 3"], ["annual_opex", "연 운영비 (원)", "직접 입력"],
          ["cash_on_hand", "보증금 반환에 쓸 현금 (원)", ""], ["property_value", "건물 가치 (원, 선택)", ""],
          ["conv_rate", "전환율 (연 %, 아래 전환 버튼용)", "예: 5"]] as [keyof typeof opts, string, string][]).map(([k, label, ph]) => (
          <label key={k} className="block text-xs text-slate-600">{label}
            <input className="field mt-1 w-full" inputMode="decimal" placeholder={ph} value={opts[k]} onChange={(e) => setOpts({ ...opts, [k]: e.target.value })} /></label>
        ))}
        <p className="text-xs text-slate-500 sm:col-span-2 lg:col-span-5">
          비운 값은 추정하지 않고 결과도 &lsquo;—&rsquo;로 둡니다. 참고: 지난 12개월 실제 운영비 {sim ? `${cell(sim.reference.operating_total)} (자료 ${sim.reference.months_with_data}개월)` : "—"}.
          법정 전환율 상한은 연 10%와 &lsquo;기준금리+2%&rsquo; 중 낮은 값입니다 (호실·계약 → 법정 체크).</p>
        <div className="flex gap-2 sm:col-span-2 lg:col-span-5">
          <button type="button" className="btn-primary" disabled={busy} onClick={() => run(rowsOut())}><Calculator className="h-4 w-4" />계산</button>
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => { setEdits({}); run([]); }}><RotateCcw className="h-4 w-4" />처음으로</button>
        </div>
      </section>
      {err && <div className="rounded-xl bg-red-50 p-3 text-sm text-red-800" role="status">{err}</div>}

      {sim && (
        <>
          <section className="card overflow-x-auto p-0 text-sm">
            <table className="w-full min-w-[720px] tabular-nums">
              <thead className="text-xs text-slate-500"><tr className="text-right">
                <th className="px-3 py-2 text-left">호실</th><th className="px-3">지금 보증금</th><th className="px-3">지금 월세</th>
                <th className="px-3">바꿀 보증금</th><th className="px-3">바꿀 월세</th><th className="px-3 text-left">보증금→월세 전환</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{sim.rows.map((r) => {
                const e = edit(r);
                return (
                  <tr key={r.lease_id} className="text-right">
                    <td className="px-3 py-1.5 text-left"><b>{r.unit_no}호</b> <span className="text-xs text-slate-500">{r.end_date ? `만료 ${r.end_date}` : "만료일 없음"}</span></td>
                    <td className="px-3">{won(r.deposit)}</td><td className="px-3">{won(r.rent)}</td>
                    <td className="px-3"><input className="field w-32 text-right" inputMode="numeric" aria-label={`${r.unit_no}호 바꿀 보증금`} value={e.deposit}
                      onChange={(ev) => setEdits({ ...edits, [r.lease_id]: { ...e, deposit: ev.target.value.replace(/\D/g, "") } })} /></td>
                    <td className="px-3"><input className="field w-28 text-right" inputMode="numeric" aria-label={`${r.unit_no}호 바꿀 월세`} value={e.rent}
                      onChange={(ev) => setEdits({ ...edits, [r.lease_id]: { ...e, rent: ev.target.value.replace(/\D/g, "") } })} /></td>
                    <td className="px-3 text-left">
                      {[1_000_000, 5_000_000].map((a) => (
                        <button key={a} type="button" className="btn-secondary btn-sm mr-1" disabled={Number(e.deposit) < a} onClick={() => convert(r, a)}>
                          {a / 10_000}만</button>))}
                    </td>
                  </tr>);
              })}</tbody>
            </table>
          </section>

          <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
            <section className="card p-5 text-sm">
              <h2 className="card-title mb-2">지금 ↔ 바꾼 뒤 (연간)</h2>
              <table className="w-full tabular-nums">
                <thead className="text-xs text-slate-500"><tr><th className="text-left" /><th className="text-right">지금</th><th className="text-right">바꾼 뒤</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {([["연 월세 수입", "annual_rent"], ["보증금 합계 (부채)", "deposit_total"], ["보증금 운용수익", "deposit_income"],
                    ["연 순수익 (월세+운용−운영비)", "annual_net"], ["자기자본 (건물가치−보증금)", "equity"]] as [string, keyof Summary][]).map(([label, k]) => (
                    <tr key={k}><td className="py-1.5">{label}</td><td className="text-right">{cell(sim.current[k] as number | null)}</td>
                      <td className={`text-right ${sim.current[k] !== sim.scenario[k] ? "font-semibold text-blue-700" : ""}`}>{cell(sim.scenario[k] as number | null)}</td></tr>))}
                  <tr><td className="py-1.5">자기자본 수익률</td><td className="text-right">{sim.current.equity_yield_pct ? `${sim.current.equity_yield_pct}%` : "—"}</td>
                    <td className="text-right">{sim.scenario.equity_yield_pct ? `${sim.scenario.equity_yield_pct}%` : "—"}</td></tr>
                </tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">{sim.tax_note}</p>
            </section>
            <section className="card p-5 text-sm">
              <h2 className="card-title mb-2">보증금 반환 자금 (앞으로 12개월, 바꾼 뒤 기준)</h2>
              {sim.liquidity.months.length === 0 ? <p className="text-slate-500">12개월 안에 만료되는 계약이 없습니다.</p> : (
                <ul className="divide-y divide-slate-100 tabular-nums">{sim.liquidity.months.map((m) => (
                  <li key={m.month} className="flex justify-between gap-2 py-1.5">
                    <span>{m.month}</span><span>{won(m.due)} <span className="text-xs text-slate-500">(누적 {won(m.cumulative)})</span>
                      {m.shortfall ? <span className="ml-1 chip bg-red-50 text-red-700">부족 {won(m.shortfall)}</span> : null}</span></li>))}</ul>
              )}
              <p className="mt-2 text-xs text-slate-600">{sim.liquidity.cash_on_hand == null ? "보유 현금을 넣으면 부족한 달을 표시합니다."
                : sim.liquidity.covered ? "보유 현금으로 12개월 안 반환을 모두 감당할 수 있습니다." : "보유 현금이 모자라는 달이 있습니다 — 다음 임차인 보증금이나 대출 계획이 필요합니다."}
                {sim.liquidity.leases_without_end_date.length > 0 && ` 만료일 없는 계약: ${sim.liquidity.leases_without_end_date.join(", ")}호 (계산에서 빠짐).`}</p>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
