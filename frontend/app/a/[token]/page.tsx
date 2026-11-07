"use client";

import { Download, Landmark } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, apiFetch, kst, won } from "@/lib/api";

interface View {
  year: number; organization_name: string; generated_at: string; notice: string; link_expires_at: string;
  status: { months_with_bank_data: string[]; months_without_bank_data: string[]; unconfirmed_transactions: number;
    operating_without_receipt: number; year_complete: boolean };
  totals_known_months: { rent_received: number | null; mgmt_received: number | null; utility_received: number | null;
    operating_total: number | null; by_category: Record<string, number> };
  deposits_total: number;
  expenses: { spent_on: string; label: string; operating: boolean; amount: number; memo: string | null; receipts: { name: string | null }[] }[];
}
const LABEL: Record<string, string> = { common_electricity: "공용 전기료", water: "수도료", cleaning: "청소비", repair: "수리비", other_operating: "공용 기타" };
const dash = (v: number | null | undefined) => (v == null ? "—" : won(v));

/** 세무사가 건물주에게 받은 링크로 여는 화면 — 로그인 없음, 읽기 전용 */
export default function AccountantPage() {
  const { token } = useParams<{ token: string }>();
  const [v, setV] = useState<View | null>(null);
  const [gone, setGone] = useState<string | null>(null);
  useEffect(() => {
    api<View>(`/api/v1/accountant/${encodeURIComponent(token)}`).then(setV).catch((e) => setGone((e as Error).message));
  }, [token]);

  async function download() {
    const res = await apiFetch(`/api/v1/accountant/${encodeURIComponent(token)}/export.xlsx`);
    if (!res.ok) return setGone("내려받지 못했습니다");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = `roomax-tax-${v?.year ?? ""}.xlsx`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  return (
    <div className="mx-auto min-h-screen max-w-3xl space-y-4 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-navy-800">
          <Landmark className="h-6 w-6 text-blue-600" strokeWidth={2.4} />
          <div>
            <h1 className="text-xl font-extrabold tracking-tight">{v ? `${v.year}년 귀속 세무 준비 자료` : "세무 준비 자료"}</h1>
            {v && <p className="text-xs text-slate-500">{v.organization_name} · 읽기 전용 · 링크 만료 {kst(v.link_expires_at)}</p>}
          </div>
        </div>
        {v && <button type="button" className="btn-primary" onClick={download}><Download className="h-4 w-4" />엑셀 내려받기</button>}
      </header>
      {gone ? <p className="card p-4 text-sm text-slate-700" role="status">{gone}</p> : !v ? <p className="text-sm text-slate-400">불러오는 중…</p> : (
        <>
          <p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{v.notice}</p>
          <section className="card p-5 text-sm">
            <h2 className="card-title mb-2">입력자료 상태</h2>
            <dl className="grid gap-2 sm:grid-cols-2">
              <div><dt className="text-xs text-slate-500">은행 내역 있는 달</dt><dd>{v.status.months_with_bank_data.join(", ") || "—"}</dd></div>
              <div><dt className="text-xs text-slate-500">은행 내역 없는 달 (합계에서 빠짐)</dt><dd>{v.status.months_without_bank_data.join(", ") || "없음"}</dd></div>
              <div><dt className="text-xs text-slate-500">확정 안 된 거래</dt><dd>{v.status.unconfirmed_transactions}건</dd></div>
              <div><dt className="text-xs text-slate-500">증빙 없는 운영비</dt><dd>{v.status.operating_without_receipt}건</dd></div>
              <div><dt className="text-xs text-slate-500">연도</dt><dd>{v.status.year_complete ? "마감" : "진행 중"}</dd></div>
              <div><dt className="text-xs text-slate-500">작성 시각</dt><dd>{kst(v.generated_at)}</dd></div>
            </dl>
          </section>
          <section className="card p-5 text-sm">
            <h2 className="card-title mb-2">합계 — 자료 있는 달만</h2>
            <dl className="space-y-1">
              <div className="flex justify-between"><dt>월세 입금 (확정 입금)</dt><dd className="tabular-nums">{dash(v.totals_known_months.rent_received)}</dd></div>
              <div className="flex justify-between"><dt>관리비 입금 (확정 입금)</dt><dd className="tabular-nums">{dash(v.totals_known_months.mgmt_received)}</dd></div>
              <div className="flex justify-between"><dt>공과금 입금 (배분 청구분)</dt><dd className="tabular-nums">{dash(v.totals_known_months.utility_received)}</dd></div>
              <div className="flex justify-between"><dt>운영비</dt><dd className="tabular-nums">{dash(v.totals_known_months.operating_total)}</dd></div>
              {Object.entries(v.totals_known_months.by_category).map(([k, x]) => (
                <div key={k} className="flex justify-between pl-3 text-xs text-slate-600"><dt>{LABEL[k] ?? k}</dt><dd>{won(x)}</dd></div>))}
              <div className="flex justify-between border-t border-slate-100 pt-1"><dt>보증금 잔액 (부채)</dt><dd className="tabular-nums">{won(v.deposits_total)}</dd></div>
            </dl>
          </section>
          <section className="card overflow-x-auto p-0 text-sm">
            <h2 className="card-title p-4 pb-2">경비 내역 ({v.expenses.length}건)</h2>
            <table className="w-full min-w-[560px] text-left">
              <thead className="text-xs text-slate-500"><tr><th className="px-3 py-2">날짜</th><th className="px-3">분류</th><th className="px-3 text-right">금액</th><th className="px-3">메모</th><th className="px-3">증빙</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{v.expenses.map((e, i) => (
                <tr key={i} className={e.operating ? "" : "text-slate-400"}>
                  <td className="px-3 py-1.5">{e.spent_on}</td><td className="px-3">{e.label}{!e.operating && " (운영비 아님)"}</td>
                  <td className="px-3 text-right tabular-nums">{won(e.amount)}</td><td className="px-3">{e.memo ?? ""}</td>
                  <td className="px-3">{e.receipts.length ? `${e.receipts.length}개` : "—"}</td></tr>))}</tbody>
            </table>
          </section>
          <p className="text-xs text-slate-500">이 화면은 건물주가 ROOMAX 장부에서 보낸 자료입니다. 임차인 이름·연락처와 증빙 파일은 포함하지 않습니다.</p>
        </>
      )}
    </div>
  );
}
