"use client";

import { Check, ClipboardCopy, DoorOpen, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, todayKst, won } from "@/lib/api";
import { useMe } from "@/lib/me";

interface Row {
  unit_id: string; unit_no: string; floor: number | null; vacant_since: string | null; days_vacant: number | null;
  previous_rent: number | null; previous_deposit: number | null; missed_due_dates: number | null; missed_rent: number | null;
  asking_deposit: number | null; asking_rent: number | null; available_on: string | null; activity: Record<string, number>;
}
interface Summary { as_of: string; units: Row[]; missed_rent_total_known: number | null; units_without_history: string[]; kinds: Record<string, string> }
interface Activity { id: string; kind: string; happened_on: string; agent_name: string | null; agent_phone: string | null; note: string | null }
interface Detail {
  unit_id: string; unit_no: string; options: string[]; ad_text: string; activities: Activity[];
  listing: { asking_deposit: number | null; asking_rent: number | null; asking_mgmt_fee: number | null; mgmt_includes: string | null;
    available_on: string | null; note: string | null } | null;
}
const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/[^\d]/g, "")));

export default function VacancyPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [s, setS] = useState<Summary | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try { setS(await api<Summary>("/api/v1/vacancies")); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">공실 관리</h1>
        <p className="page-sub">공실 기간과 그동안 놓친 월세(직전 계약 조건 기준), 모집 조건·광고 문구, 중개사·문의·방 보기 기록.</p>
      </header>
      {msg && <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}
      {!s ? <p className="text-sm text-slate-400">불러오는 중…</p> : s.units.length === 0 ? (
        <div className="card p-6 text-center text-sm text-slate-500">공실이 없습니다. 계약이 끝나 공실이 되면 여기에서 모집을 관리합니다.</div>
      ) : (
        <>
          <section className="card p-4 text-sm">
            <p>공실 <b>{s.units.length}실</b> · 놓친 월세(직전 조건 기준) <b>{won(s.missed_rent_total_known)}</b>
              {s.units_without_history.length > 0 && <span className="text-slate-500"> — 직전 계약 기록이 없는 {s.units_without_history.join(", ")}호는 빠짐</span>}</p>
            <p className="mt-1 text-xs text-slate-500">놓친 월세 = 공실 기간에 돌아온 직전 계약의 납부일 수 × 직전 월세. 시세를 추정한 값이 아닙니다.</p>
          </section>
          <ul className="space-y-3">
            {s.units.map((u) => (
              <li key={u.unit_id} className="card p-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <DoorOpen className="h-4 w-4 text-slate-400" /><b>{u.unit_no}호</b>
                  <span className="chip bg-amber-50 text-amber-800">{u.days_vacant != null ? `공실 ${u.days_vacant}일` : "공실 (시작일 모름)"}</span>
                  <span className="ml-auto text-xs text-slate-500">문의 {u.activity.inquiry} · 방 보기 {u.activity.viewing} · 중개사 {u.activity.agent}</span>
                </div>
                <p className="mt-1 text-xs text-slate-600 tabular-nums">
                  공실 시작 {u.vacant_since ?? "—"} · 직전 월세 {won(u.previous_rent)} · 놓친 월세 {won(u.missed_rent)}
                  {u.missed_due_dates != null && ` (${u.missed_due_dates}회)`} · 모집 {u.asking_deposit != null || u.asking_rent != null
                    ? `${won(u.asking_deposit)} / ${won(u.asking_rent)}` : "조건 미정"}{u.available_on && ` · 입주 ${u.available_on}`}
                </p>
                <button type="button" className="btn-secondary btn-sm mt-2" aria-expanded={open === u.unit_id}
                  onClick={() => setOpen(open === u.unit_id ? null : u.unit_id)}>{open === u.unit_id ? "닫기" : "모집 조건·광고·기록"}</button>
                {open === u.unit_id && <UnitPanel unitId={u.unit_id} kinds={s.kinds} canWrite={canWrite} onChange={load} />}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function UnitPanel({ unitId, kinds, canWrite, onChange }: { unitId: string; kinds: Record<string, string>; canWrite: boolean; onChange: () => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [f, setF] = useState({ deposit: "", rent: "", mgmt: "", includes: "", available_on: "", note: "" });
  const [a, setA] = useState({ kind: "inquiry", happened_on: todayKst(), agent_name: "", agent_phone: "", note: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const x = await api<Detail>(`/api/v1/vacancies/${unitId}`);
    setD(x);
    setF({ deposit: x.listing?.asking_deposit?.toString() ?? "", rent: x.listing?.asking_rent?.toString() ?? "",
      mgmt: x.listing?.asking_mgmt_fee?.toString() ?? "", includes: x.listing?.mgmt_includes ?? "",
      available_on: x.listing?.available_on ?? "", note: x.listing?.note ?? "" });
  }, [unitId]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: (e as Error).message })); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string, after?: () => void) {
    setBusy(true); setMsg(null);
    try { await fn(); after?.(); await load(); onChange(); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  if (!d) return <p className="mt-2 text-sm text-slate-400">불러오는 중…</p>;
  return (
    <div className="mt-3 grid gap-4 text-sm lg:grid-cols-2 [&>*]:min-w-0">
      <div className="space-y-3">
        <h3 className="font-medium">모집 조건 (직접 정함)</h3>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs text-slate-600">보증금 (원)<input className="field mt-1 w-full" inputMode="numeric" value={f.deposit}
            onChange={(e) => setF({ ...f, deposit: e.target.value.replace(/\D/g, "") })} disabled={!canWrite} /></label>
          <label className="block text-xs text-slate-600">월세 (원)<input className="field mt-1 w-full" inputMode="numeric" value={f.rent}
            onChange={(e) => setF({ ...f, rent: e.target.value.replace(/\D/g, "") })} disabled={!canWrite} /></label>
          <label className="block text-xs text-slate-600">관리비 (원, 없으면 0)<input className="field mt-1 w-full" inputMode="numeric" value={f.mgmt}
            onChange={(e) => setF({ ...f, mgmt: e.target.value.replace(/\D/g, "") })} disabled={!canWrite} /></label>
          <label className="block text-xs text-slate-600">관리비에 포함된 것<input className="field mt-1 w-full" value={f.includes} maxLength={200}
            onChange={(e) => setF({ ...f, includes: e.target.value })} placeholder="예: 수도·인터넷" disabled={!canWrite} /></label>
          {Number(f.mgmt) >= 100000 && <p className="col-span-2 text-xs text-amber-800">월 10만원 이상 정액 관리비는 중개 광고에 항목별 금액을 나눠 적어야 합니다
            (국토부 중개대상물 표시·광고 명시사항 세부기준, 2024.1 시행). &lsquo;포함된 것&rsquo;에 항목별 금액을 적으세요.</p>}
          <label className="block text-xs text-slate-600">입주 가능일<input type="date" className="field mt-1 w-full" value={f.available_on}
            onChange={(e) => setF({ ...f, available_on: e.target.value })} disabled={!canWrite} /></label>
          <label className="col-span-2 block text-xs text-slate-600">광고에 붙일 설명<textarea className="field mt-1 min-h-16 w-full" value={f.note}
            onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="예: 남향, 역 5분, 반려동물 불가" disabled={!canWrite} /></label>
        </div>
        {canWrite && <button type="button" className="btn-primary btn-sm" disabled={busy}
          onClick={() => run(() => api(`/api/v1/vacancies/${unitId}/listing`, json("PUT", { asking_deposit: num(f.deposit), asking_rent: num(f.rent),
            asking_mgmt_fee: num(f.mgmt), mgmt_includes: f.includes || null, available_on: f.available_on || null, note: f.note || null })), "모집 조건을 저장했습니다.")}>저장</button>}
        <h3 className="pt-1 font-medium">광고 문구 (직방·다방·피터팬에 붙여 넣기)</h3>
        <pre className="whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-xs">{d.ad_text}</pre>
        <button type="button" className="btn-secondary btn-sm" onClick={async () => {
          try { await navigator.clipboard.writeText(d.ad_text); setCopied(true); } catch { setCopied(false); } }}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <ClipboardCopy className="h-3.5 w-3.5" />}{copied ? "복사됨" : "복사"}</button>
        <p className="text-xs text-slate-500">문구는 호실 정보·옵션(자산대장의 임대인 옵션)·위 조건에 적힌 값만으로 만듭니다. 빈 값은 빼고 지어내지 않습니다.
          {d.options.length === 0 && " 자산대장에 옵션을 넣으면 '옵션:' 줄이 생깁니다."}</p>
      </div>
      <div className="space-y-3">
        <h3 className="font-medium">활동 기록</h3>
        {canWrite && (
          <div className="grid grid-cols-2 gap-2 rounded-xl border border-slate-100 p-3">
            <label className="block text-xs text-slate-600">종류<select className="field mt-1 w-full" aria-label="종류" value={a.kind} onChange={(e) => setA({ ...a, kind: e.target.value })}>
              {Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="block text-xs text-slate-600">날짜<input type="date" className="field mt-1 w-full" max={todayKst()} value={a.happened_on}
              onChange={(e) => setA({ ...a, happened_on: e.target.value })} /></label>
            <label className="block text-xs text-slate-600">중개사무소<input className="field mt-1 w-full" value={a.agent_name} onChange={(e) => setA({ ...a, agent_name: e.target.value })} /></label>
            <label className="block text-xs text-slate-600">연락처 (암호화 저장)<input className="field mt-1 w-full" inputMode="tel" value={a.agent_phone} onChange={(e) => setA({ ...a, agent_phone: e.target.value })} /></label>
            <label className="col-span-2 block text-xs text-slate-600">메모<input className="field mt-1 w-full" value={a.note} onChange={(e) => setA({ ...a, note: e.target.value })} placeholder="예: 수수료 조건, 방 본 사람 반응" /></label>
            <button type="button" className="btn-primary btn-sm col-span-2 justify-self-start" disabled={busy}
              onClick={() => run(() => api(`/api/v1/vacancies/${unitId}/activities`, json("POST", { kind: a.kind, happened_on: a.happened_on,
                agent_name: a.agent_name || null, agent_phone: a.agent_phone || null, note: a.note || null })), "기록했습니다.",
                () => setA({ ...a, agent_name: "", agent_phone: "", note: "" }))}><Plus className="h-3.5 w-3.5" />기록 추가</button>
          </div>
        )}
        {d.activities.length === 0 ? <p className="text-slate-500">아직 기록이 없습니다.</p> : (
          <ul className="divide-y divide-slate-100">{d.activities.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="chip bg-slate-100 text-slate-700">{kinds[x.kind]}</span><span className="tabular-nums">{x.happened_on}</span>
              {x.agent_name && <span>{x.agent_name}</span>}{x.agent_phone && <a className="text-blue-700" href={`tel:${x.agent_phone}`}>{x.agent_phone}</a>}
              {x.note && <span className="text-slate-500">{x.note}</span>}
              {canWrite && <button type="button" className="ml-auto text-red-700" aria-label="기록 지우기" disabled={busy}
                onClick={() => window.confirm("이 기록을 지울까요?") && run(() => api(`/api/v1/vacancy-activities/${x.id}`, json("DELETE")), "지웠습니다.")}>
                <Trash2 className="h-4 w-4" /></button>}
            </li>))}</ul>
        )}
      </div>
      {msg && <div className={`rounded-xl p-3 lg:col-span-2 ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}
    </div>
  );
}
