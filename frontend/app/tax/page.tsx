"use client";

import { Download, FileText, Paperclip, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, apiFetch, kst, won } from "@/lib/api";
import { shrinkImage } from "@/lib/image";
import { useMe } from "@/lib/me";

interface Month { period: string; future: boolean; bank_covered?: boolean; rent_charged?: number | null; rent_received?: number | null;
  operating_total?: number | null; excluded?: { owner_household: number | null; personal: number | null }; unconfirmed?: number }
interface Receipt { id: string; name: string | null; content_type: string; uploaded_at: string }
interface Exp { id: string; spent_on: string; category: string; label: string; operating: boolean; amount: number; unit_no: string | null;
  memo: string | null; from_bank: boolean; receipts: Receipt[] }
interface Annual {
  year: number; generated_at: string; notice: string;
  status: { months_with_bank_data: string[]; months_without_bank_data: string[]; unconfirmed_transactions: number;
    pending_review_in: number; pending_review_out: number; operating_without_receipt: number; year_complete: boolean };
  months: Month[];
  totals_known_months: { rent_charged: number | null; rent_received: number | null; operating_total: number | null;
    mgmt_charged: number | null; mgmt_received: number | null; utility_charged: number | null; utility_received: number | null; by_category: Record<string, number> };
  deposits_at: string; deposits: { unit_no: string; tenant_name: string; amount: number; received_at: string; returned_at: string | null; lease_status: string }[];
  deposits_total: number; expenses: Exp[];
}
const LABEL: Record<string, string> = { common_electricity: "공용 전기료", water: "수도료", cleaning: "청소비", repair: "수리비", other_operating: "공용 기타" };

export default function TaxPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const thisYear = Number(new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 4));
  const [year, setYear] = useState(thisYear);
  const [d, setD] = useState<Annual | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [onlyMissing, setOnlyMissing] = useState(false);

  const load = useCallback(async () => {
    try { setD(await api<Annual>(`/api/v1/tax-prep/${year}`)); }
    catch (e) { setD(null); setMsg({ ok: false, text: (e as Error).message }); }
  }, [year]);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await fn(); await load(); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
  async function download(path: string, fallback: string, open = false) {
    try {
      const res = await apiFetch(path);
      if (!res.ok) throw new Error("내려받지 못했습니다");
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      if (open) a.target = "_blank"; else a.download = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? fallback;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  async function attach(expId: string, files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      const file = f.type === "application/pdf" ? f : await shrinkImage(f, { jpegOnly: true });
      const fd = new FormData(); fd.append("file", file);
      await run(() => api(`/api/v1/expenses/${expId}/receipts`, { method: "POST", body: fd }), "증빙을 붙였습니다.");
    }
  }
  const dash = (v: number | null | undefined) => (v == null ? "—" : won(v));
  const shown = d?.expenses.filter((e) => !onlyMissing || (e.operating && e.receipts.length === 0)) ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">세무 준비</h1>
          <p className="page-sub">귀속연도별 입력자료 모음과 지출 증빙. 세액을 계산하거나 신고를 확정하지 않습니다.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className="field" aria-label="귀속연도" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[thisYear, thisYear - 1, thisYear - 2].map((y) => <option key={y} value={y}>{y}년 귀속</option>)}</select>
          <button type="button" className="btn-secondary" disabled={!d} onClick={() => download(`/api/v1/tax-prep/${year}/export.xlsx`, `roomax-tax-${year}.xlsx`)}>
            <Download className="h-4 w-4" />엑셀 내려받기</button>
        </div>
      </header>
      {msg && <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}
      {!d ? <p className="text-sm text-slate-400">불러오는 중…</p> : (
        <>
          <section className="card p-5 text-sm">
            <h2 className="card-title mb-2">입력자료 상태 · {d.year}년 귀속</h2>
            <p className="mb-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{d.notice}</p>
            <dl className="grid gap-2 sm:grid-cols-2">
              <div><dt className="text-xs text-slate-500">은행 내역 있는 달</dt><dd>{d.status.months_with_bank_data.join(", ") || "—"}</dd></div>
              <div><dt className="text-xs text-slate-500">은행 내역 없는 달 (합계에서 빠짐)</dt><dd>{d.status.months_without_bank_data.join(", ") || "없음"}</dd></div>
              <div><dt className="text-xs text-slate-500">확정 안 된 거래 (그 해)</dt><dd>{d.status.unconfirmed_transactions}건</dd></div>
              <div><dt className="text-xs text-slate-500">증빙 없는 운영비</dt><dd>{d.status.operating_without_receipt}건</dd></div>
              <div><dt className="text-xs text-slate-500">연도</dt><dd>{d.status.year_complete ? "마감" : "진행 중 — 연도가 끝나지 않았습니다"}</dd></div>
              <div><dt className="text-xs text-slate-500">작성 시각</dt><dd>{kst(d.generated_at)}</dd></div>
            </dl>
          </section>

          <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
            <section className="card p-5 text-sm">
              <h2 className="card-title mb-2">합계 — 자료 있는 달만</h2>
              <dl className="space-y-1">
                <div className="flex justify-between"><dt>월세 청구 (납부일 기준)</dt><dd className="tabular-nums">{dash(d.totals_known_months.rent_charged)}</dd></div>
                <div className="flex justify-between"><dt>월세 입금 (확정 입금 기준)</dt><dd className="tabular-nums">{dash(d.totals_known_months.rent_received)}</dd></div>
                {d.totals_known_months.mgmt_charged != null && <>
                  <div className="flex justify-between"><dt>관리비 청구</dt><dd className="tabular-nums">{dash(d.totals_known_months.mgmt_charged)}</dd></div>
                  <div className="flex justify-between"><dt>관리비 입금 (확정 입금 기준)</dt><dd className="tabular-nums">{dash(d.totals_known_months.mgmt_received)}</dd></div></>}
                {d.totals_known_months.utility_charged != null && <>
                  <div className="flex justify-between"><dt>공과금 청구 (배분)</dt><dd className="tabular-nums">{dash(d.totals_known_months.utility_charged)}</dd></div>
                  <div className="flex justify-between"><dt>공과금 입금 (확정 입금 기준)</dt><dd className="tabular-nums">{dash(d.totals_known_months.utility_received)}</dd></div></>}
                <div className="flex justify-between"><dt>운영비</dt><dd className="tabular-nums">{dash(d.totals_known_months.operating_total)}</dd></div>
                {Object.entries(d.totals_known_months.by_category).map(([k, v]) => (
                  <div key={k} className="flex justify-between pl-3 text-xs text-slate-600"><dt>{LABEL[k]}</dt><dd>{won(v)}</dd></div>))}
              </dl>
              <p className="mt-2 text-xs text-slate-500">두 기준 중 어느 쪽이 수입 시기인지는 세무사 확인이 필요합니다. 주인세대·생활비는 운영비에서 뺐습니다.</p>
            </section>
            <section className="card p-5 text-sm">
              <h2 className="card-title mb-2">보증금 잔액 ({d.deposits_at} 기준) — 수입 아님, 부채</h2>
              {d.deposits.length === 0 ? <p className="text-slate-500">받은 보증금 기록이 없습니다.</p> : (
                <ul className="space-y-1">{d.deposits.map((x, i) => (
                  <li key={i} className="flex justify-between gap-2"><span>{x.unit_no}호 {x.tenant_name}{x.lease_status !== "active" && <span className="text-xs text-slate-500"> (종료)</span>}</span>
                    <span className="tabular-nums">{won(x.amount)}</span></li>))}
                  <li className="flex justify-between border-t border-slate-100 pt-1 font-semibold"><span>합계</span><span className="tabular-nums">{won(d.deposits_total)}</span></li></ul>
              )}
              <p className="mt-2 text-xs text-slate-500">간주임대료 해당 여부(주택 수·보증금 합계 등)는 판정하지 않습니다.</p>
            </section>
          </div>

          <section className="card overflow-x-auto p-0 text-sm">
            <h2 className="card-title p-4 pb-2">월별</h2>
            <table className="w-full min-w-[640px] text-right tabular-nums">
              <thead className="text-xs text-slate-500"><tr>
                <th className="px-3 py-2 text-left">월</th><th className="px-3">은행 내역</th><th className="px-3">청구</th><th className="px-3">입금</th>
                <th className="px-3">운영비</th><th className="px-3">미확정</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{d.months.map((m) => (
                <tr key={m.period} className={m.future ? "text-slate-300" : ""}>
                  <td className="px-3 py-1.5 text-left">{m.period}</td>
                  <td className="px-3">{m.future ? "아직" : m.bank_covered ? "있음" : <span className="text-amber-700">없음</span>}</td>
                  <td className="px-3">{m.future ? "" : dash(m.rent_charged)}</td><td className="px-3">{m.future ? "" : dash(m.rent_received)}</td>
                  <td className="px-3">{m.future ? "" : dash(m.operating_total)}</td><td className="px-3">{m.future ? "" : m.unconfirmed}</td>
                </tr>))}</tbody>
            </table>
          </section>

          <section className="card p-5 text-sm">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <h2 className="card-title">지출과 증빙 ({d.expenses.length}건)</h2>
              <label className="flex items-center gap-1 text-xs text-slate-600"><input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />증빙 없는 운영비만</label>
            </div>
            {shown.length === 0 ? <p className="text-slate-500">{onlyMissing ? "증빙 없는 운영비가 없습니다." : "이 해의 지출이 없습니다."}</p> : (
              <ul className="divide-y divide-slate-100">{shown.map((e) => (
                <li key={e.id} className="flex flex-wrap items-center gap-2 py-2">
                  <span className="w-24 text-xs text-slate-500">{e.spent_on}</span>
                  <span className={`chip ${e.operating ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600"}`}>{e.label}</span>
                  <span className="min-w-0 flex-1 truncate">{e.unit_no ? `${e.unit_no}호 · ` : ""}{e.memo ?? (e.from_bank ? "은행 출금" : "수기")}</span>
                  <span className="tabular-nums">{won(e.amount)}</span>
                  <span className="flex w-full flex-wrap items-center gap-1.5 sm:w-auto">
                    {e.receipts.map((r) => (
                      <span key={r.id} className="chip bg-emerald-50 text-emerald-800">
                        <button type="button" className="underline-offset-2 hover:underline" onClick={() => download(`/api/v1/expense-receipts/${r.id}`, r.name ?? "증빙", true)}>
                          <FileText className="mr-0.5 inline h-3 w-3" />{r.name ?? "증빙"}</button>
                        {canWrite && <button type="button" aria-label={`${r.name ?? "증빙"} 지우기`} disabled={busy}
                          onClick={() => window.confirm("이 증빙을 지울까요?") && run(() => api(`/api/v1/expense-receipts/${r.id}`, { method: "DELETE" }), "증빙을 지웠습니다.")}>
                          <Trash2 className="h-3 w-3" /></button>}
                      </span>))}
                    {canWrite && (
                      <label className="btn-secondary btn-sm cursor-pointer"><Paperclip className="h-3.5 w-3.5" />증빙
                        <input type="file" accept="image/*,application/pdf" multiple className="sr-only" aria-label={`${e.spent_on} ${e.label} 증빙 붙이기`}
                          disabled={busy} onChange={(ev) => { attach(e.id, ev.target.files); ev.target.value = ""; }} /></label>
                    )}
                  </span>
                </li>))}</ul>
            )}
            <p className="mt-2 text-xs text-slate-500">영수증·세금계산서 사진이나 PDF (4MB 이하). 증빙이 붙은 지출은 증빙을 먼저 지워야 지울 수 있습니다.</p>
          </section>
        </>
      )}
    </div>
  );
}
