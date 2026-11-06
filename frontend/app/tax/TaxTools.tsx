"use client";

import { Calculator, Copy, Link2, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, kst, won } from "@/lib/api";

interface Est {
  year: number; registered: boolean; law_basis: string; notice: string; revenue: number | null;
  rent_received: number | null; mgmt_received: number | null; separate_available: boolean; advisor_recommended: boolean;
  separate: { revenue: number; expense_rate: number; income: number; deduction: number; taxable: number; income_tax: number; local_tax: number; total: number } | null;
  combined: { revenue: number; book_expenses: number | null; income: number; other_income: number; income_tax_added: number; local_tax: number; total: number } | null;
  lower_estimate: "separate" | "combined" | "same" | null; warnings: string[]; not_included: string[]; hometax_steps: string[];
}
const dash = (v: number | null | undefined) => (v == null ? "—" : won(v));

/** 셀프 신고 도우미 — 추정치만. 판정·대신 제출 없음 */
export function SelfFilingCard({ year }: { year: number }) {
  const [registered, setRegistered] = useState(false);
  const [other, setOther] = useState("");
  const [e, setE] = useState<Est | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function calc() {
    setErr(null);
    const q = new URLSearchParams({ registered: String(registered) });
    const n = other.replace(/[^\d]/g, "");
    if (n) q.set("other_income", n);
    try { setE(await api<Est>(`/api/v1/tax-prep/${year}/self-filing?${q}`)); }
    catch (x) { setE(null); setErr((x as Error).message); }
  }
  return (
    <section className="card p-5 text-sm" aria-labelledby="self-filing">
      <h2 id="self-filing" className="card-title mb-1 flex items-center gap-2"><Calculator className="h-4 w-4 text-blue-600" />셀프 신고 도우미 · {year}년 귀속</h2>
      <p className="mb-3 text-xs text-slate-500">통장 기준 임대수입으로 세액을 <b>추정</b>합니다. 신고는 본인이 홈택스에서 직접 하고, ROOMAX 는 대신 제출하거나 판정하지 않습니다.</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-2"><input type="checkbox" checked={registered} onChange={(x) => setRegistered(x.target.checked)} />등록 임대주택 (세무서·지자체 모두 등록)</label>
        <label className="grid gap-1 text-xs text-slate-600">다른 종합소득금액 (근로·사업소득 등, 원)
          <input className="field w-48" inputMode="numeric" value={other} onChange={(x) => setOther(x.target.value)} placeholder="예: 30000000" /></label>
        <button type="button" className="btn-primary" onClick={calc}>추정하기</button>
      </div>
      {err && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-amber-900" role="status">{err} {err.includes("이용권") && <a className="underline" href="/billing">요금제로</a>}</p>}
      {e && (
        <div className="mt-4 space-y-3">
          <p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{e.notice}</p>
          <p>수입금액(월세 {dash(e.rent_received)} + 관리비 {dash(e.mgmt_received)}): <b className="tabular-nums">{dash(e.revenue)}</b></p>
          {e.advisor_recommended && <p className="rounded-xl bg-blue-50 p-3 text-blue-900">수입이 2천만 원을 넘어 분리과세를 고를 수 없습니다. 종합과세 신고는 세무사 상담을 권합니다.</p>}
          <div className="grid gap-3 md:grid-cols-2 [&>*]:min-w-0">
            {e.separate && (
              <div className={`rounded-xl border p-3 ${e.lower_estimate === "separate" ? "border-emerald-300" : "border-slate-200"}`}>
                <h3 className="font-semibold">분리과세 (14%) 추정</h3>
                <dl className="mt-1 space-y-0.5 text-xs tabular-nums">
                  <div className="flex justify-between"><dt>필요경비율</dt><dd>{Math.round(e.separate.expense_rate * 100)}%</dd></div>
                  <div className="flex justify-between"><dt>소득금액</dt><dd>{won(e.separate.income)}</dd></div>
                  <div className="flex justify-between"><dt>기본공제</dt><dd>{won(e.separate.deduction)}</dd></div>
                  <div className="flex justify-between"><dt>과세표준</dt><dd>{won(e.separate.taxable)}</dd></div>
                  <div className="flex justify-between"><dt>소득세 + 지방소득세</dt><dd>{won(e.separate.income_tax)} + {won(e.separate.local_tax)}</dd></div>
                  <div className="flex justify-between font-semibold text-sm"><dt>합계 (추정)</dt><dd>{won(e.separate.total)}</dd></div>
                </dl>
              </div>)}
            {e.combined && (
              <div className={`rounded-xl border p-3 ${e.lower_estimate === "combined" ? "border-emerald-300" : "border-slate-200"}`}>
                <h3 className="font-semibold">종합과세 (장부 기준) 추정</h3>
                <dl className="mt-1 space-y-0.5 text-xs tabular-nums">
                  <div className="flex justify-between"><dt>장부 운영비</dt><dd>{dash(e.combined.book_expenses)}</dd></div>
                  <div className="flex justify-between"><dt>임대 소득금액</dt><dd>{won(e.combined.income)}</dd></div>
                  <div className="flex justify-between"><dt>다른 소득에 더해 늘어나는 소득세</dt><dd>{won(e.combined.income_tax_added)}</dd></div>
                  <div className="flex justify-between"><dt>지방소득세</dt><dd>{won(e.combined.local_tax)}</dd></div>
                  <div className="flex justify-between font-semibold text-sm"><dt>합계 (추정)</dt><dd>{won(e.combined.total)}</dd></div>
                </dl>
              </div>)}
          </div>
          {e.lower_estimate && e.lower_estimate !== "same" && <p className="text-xs text-slate-600">
            이 추정으로는 {e.lower_estimate === "separate" ? "분리과세" : "종합과세"} 쪽 숫자가 작습니다. 어느 방식으로 신고할지는 본인이 홈택스 모의계산으로 확인해 정하세요.</p>}
          {e.warnings.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-800">{e.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
          <details className="text-xs text-slate-600"><summary className="cursor-pointer">이 추정에 넣지 않은 것 · {e.law_basis}</summary>
            <ul className="mt-1 list-disc pl-5">{e.not_included.map((x) => <li key={x}>{x}</li>)}</ul></details>
          <div><h3 className="mb-1 font-semibold">홈택스에서 직접 신고하기</h3>
            <ol className="list-decimal space-y-0.5 pl-5 text-xs text-slate-700">{e.hometax_steps.map((s) => <li key={s}>{s}</li>)}</ol></div>
        </div>)}
    </section>
  );
}

/** 세무사에게 보낼 공유 링크 — 세무사는 가입 없이 읽기 전용으로 연다 */
export function AccountantLinkCard({ year, owner }: { year: number; owner: boolean }) {
  const [st, setSt] = useState<{ days: number[]; link: { created_at: string; expires_at: string; last_seen_at: string | null } | null } | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [days, setDays] = useState(90);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setSt(await api(`/api/v1/tax-prep/${year}/accountant-link`)); } catch (x) { setMsg((x as Error).message); }
  }, [year]);
  useEffect(() => { setUrl(null); load(); }, [load]);
  async function create() {
    setMsg(null);
    try {
      const r = await api<{ token: string }>(`/api/v1/tax-prep/${year}/accountant-link`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ days }) });
      setUrl(`${window.location.origin}/a/${r.token}`); await load();
    } catch (x) { setMsg((x as Error).message); }
  }
  async function revoke() {
    await api(`/api/v1/tax-prep/${year}/accountant-link`, { method: "DELETE" }).catch(() => null);
    setUrl(null); await load(); setMsg("링크를 껐습니다.");
  }
  return (
    <section className="card p-5 text-sm" aria-labelledby="accountant-link">
      <h2 id="accountant-link" className="card-title mb-1 flex items-center gap-2"><Send className="h-4 w-4 text-blue-600" />세무사에게 보내기 · {year}년 귀속</h2>
      <p className="mb-3 text-xs text-slate-500">세무사는 가입 없이 링크로 이 연도의 세무 준비 자료를 보고 엑셀로 받습니다 (읽기 전용, 임차인 이름·증빙 파일 제외). 새로 만들면 이전 링크는 바로 꺼집니다.</p>
      {st?.link ? <p>켜져 있음 — {kst(st.link.expires_at)}까지{st.link.last_seen_at && ` · 마지막 열람 ${kst(st.link.last_seen_at)}`}</p> : <p className="text-slate-500">보낸 링크 없음</p>}
      {url && <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-emerald-50 p-3">
        <Link2 className="h-4 w-4 text-emerald-700" /><code className="min-w-0 break-all text-xs">{url}</code>
        <button type="button" className="btn-secondary" onClick={() => navigator.clipboard.writeText(url).then(() => setMsg("복사했습니다. 문자·카톡으로 세무사에게 보내세요."))}>
          <Copy className="h-4 w-4" />복사</button>
        <p className="w-full text-xs text-emerald-900">이 주소는 지금 한 번만 보입니다. 주소를 아는 사람은 누구나 열 수 있으니 세무사에게만 보내세요.</p></div>}
      {owner && <div className="mt-3 flex flex-wrap items-center gap-2">
        <select className="field" aria-label="유효 기간" value={days} onChange={(x) => setDays(Number(x.target.value))}>
          {(st?.days ?? [30, 90, 180]).map((n) => <option key={n} value={n}>{n}일</option>)}</select>
        <button type="button" className="btn-primary" onClick={create}>{st?.link ? "새 링크 만들기" : "링크 만들기"}</button>
        {st?.link && <button type="button" className="btn-secondary" onClick={revoke}>링크 끄기</button>}
      </div>}
      {msg && <p className="mt-2 text-xs text-slate-600" role="status">{msg}</p>}
    </section>
  );
}
