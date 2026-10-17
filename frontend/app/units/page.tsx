"use client";

import { Calculator, ClipboardList, DoorOpen, LogOut, Plus, Undo2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, todayKst, won } from "@/lib/api";
import { useMe } from "@/lib/me";

interface LeaseH {
  lease_id: string; tenant_name: string; status: "active" | "ended" | "draft"; start_date: string; end_date: string | null;
  signed_on: string | null; ended_on: string | null; end_reason: string | null; deposit: number; rent: number; deposit_unreturned: number;
}
interface UnitH { unit_id: string; unit_no: string; use_type: "rental" | "owner"; status: string; leases: LeaseH[] }
const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const STATUS: Record<string, [string, string]> = { occupied: ["임대 중", "bg-blue-50 text-blue-700"], vacant: ["공실", "bg-amber-50 text-amber-800"],
  owner: ["주인세대", "bg-slate-100 text-slate-600"] };

export default function UnitsPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [units, setUnits] = useState<UnitH[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; list?: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [ending, setEnding] = useState<string | null>(null);
  const [letting, setLetting] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setUnits(await api<UnitH[]>("/api/v1/lease-history")); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: (r: unknown) => { text: string; list?: string[] }) {
    setBusy(true); setMsg(null);
    try { const r = await fn(); await load(); setMsg({ ok: true, ...ok(r) }); return true; }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); return false; }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">호실·계약</h1>
        <p className="page-sub">호실마다 지금 계약과 지난 계약. 퇴거하면 계약을 종료하고, 공실에는 새 계약을 넣습니다.</p>
      </header>
      {msg && (
        <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">
          {msg.text}
          {msg.list && msg.list.length > 0 && <ul className="mt-1 list-disc pl-4 text-xs">{msg.list.map((s) => <li key={s}>{s}</li>)}</ul>}
        </div>
      )}
      {units === null ? <p className="text-sm text-slate-400">불러오는 중…</p> : (
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          {units.map((u) => {
            const active = u.leases.find((l) => l.status === "active");
            const lastEnded = !active ? u.leases.find((l) => l.status === "ended") : undefined;
            const [label, tone] = STATUS[u.status] ?? [u.status, "bg-slate-100 text-slate-600"];
            return (
              <section key={u.unit_id} className="card p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <h2 className="card-title">{u.unit_no}호</h2><span className={`chip ${tone}`}>{label}</span>
                  {canWrite && u.use_type === "rental" && !active && letting !== u.unit_id && (
                    <button type="button" className="btn-primary btn-sm ml-auto" onClick={() => { setLetting(u.unit_id); setEnding(null); }}>
                      <Plus className="h-3.5 w-3.5" />새 계약</button>
                  )}
                </div>
                {letting === u.unit_id && <NewLeaseForm busy={busy} prevEnd={lastEnded?.ended_on ?? null} onCancel={() => setLetting(null)}
                  onSave={(body) => run(() => api(`/api/v1/units/${u.unit_id}/leases`, json("POST", body)),
                    () => ({ text: `${u.unit_no}호 새 계약을 넣었습니다. 보증금은 은행 입금을 '보증금 수령'으로 확정하면 기록됩니다.` }))
                    .then((ok) => ok && setLetting(null))} />}
                {u.leases.length === 0 ? <p className="text-sm text-slate-500">{u.use_type === "owner" ? "주인세대" : "계약 기록이 없습니다."}</p> : (
                  <ul className="divide-y divide-slate-100 text-sm">
                    {u.leases.map((l) => (
                      <li key={l.lease_id} className="py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <b>{l.tenant_name}</b>
                          <span className={`chip ${l.status === "active" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600"}`}>
                            {l.status === "active" ? "진행 중" : `종료 ${l.ended_on ?? ""}`}</span>
                          {l.deposit_unreturned > 0 && l.status === "ended" && <span className="chip bg-red-50 text-red-700">보증금 {won(l.deposit_unreturned)} 미반환</span>}
                        </div>
                        <p className="mt-0.5 text-xs text-slate-600">{l.start_date} ~ {l.end_date ?? "—"} · 보증금 {won(l.deposit)} · 월세 {won(l.rent)}
                          {l.end_reason ? ` · ${l.end_reason}` : ""}</p>
                        {canWrite && l.status === "active" && (ending === l.lease_id ? (
                          <EndForm busy={busy} onCancel={() => setEnding(null)} onSave={(body) => run(
                            () => api(`/api/v1/leases/${l.lease_id}/end`, json("POST", body)),
                            (r) => { const x = r as { waived: string[]; warnings: string[] };
                              return { text: `${u.unit_no}호 계약을 종료했습니다${x.waived.length ? ` (받지 않을 청구 ${x.waived.join(", ")})` : ""}. 남은 일:`, list: x.warnings }; })
                            .then((ok) => ok && setEnding(null))} />
                        ) : (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            <Link href={`/move-out?lease=${l.lease_id}`} className="btn-secondary btn-sm"><DoorOpen className="h-3.5 w-3.5" />입주·퇴실</Link>
                            <button type="button" className="btn-secondary btn-sm" aria-expanded={checking === l.lease_id}
                              onClick={() => setChecking(checking === l.lease_id ? null : l.lease_id)}>
                              <ClipboardList className="h-3.5 w-3.5" />법정 체크</button>
                            <button type="button" className="btn-secondary btn-sm" onClick={() => { setEnding(l.lease_id); setLetting(null); }}>
                              <LogOut className="h-3.5 w-3.5" />계약 종료</button>
                          </div>
                        ))}
                        {checking === l.lease_id && l.status === "active" && <Checklist leaseId={l.lease_id} canWrite={canWrite} />}
                        {canWrite && lastEnded?.lease_id === l.lease_id && (
                          <button type="button" className="btn-secondary btn-sm mt-1.5" disabled={busy}
                            onClick={() => window.confirm(`${u.unit_no}호 ${l.tenant_name} 계약 종료를 되돌릴까요? 종료 때 면제한 청구도 되살아납니다.`)
                              && run(() => api(`/api/v1/leases/${l.lease_id}/undo-end`, json("POST")), () => ({ text: "계약 종료를 되돌렸습니다." }))}>
                            <Undo2 className="h-3.5 w-3.5" />종료 되돌리기</button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EndForm({ busy, onSave, onCancel }: { busy: boolean; onSave: (b: { ended_on: string; reason: string | null }) => void; onCancel: () => void }) {
  const [day, setDay] = useState(todayKst());
  const [reason, setReason] = useState("");
  return (
    <div className="mt-2 space-y-2 rounded-xl bg-slate-50 p-3 text-sm">
      <p className="text-xs text-slate-600">종료일(실제 퇴거일) 뒤에 납부일이 오는 청구 중 아무것도 안 낸 것은 받지 않음으로 바뀝니다. 보증금은 돌려줄 때까지 부채로 남습니다.</p>
      <div className="flex flex-wrap gap-2">
        <label className="text-xs text-slate-600">종료일<input type="date" className="field mt-1 block" value={day} onChange={(e) => setDay(e.target.value)} /></label>
        <label className="min-w-0 flex-1 text-xs text-slate-600">사유 (선택)<input className="field mt-1 block w-full" value={reason}
          placeholder="예: 만기 퇴거, 중도 해지 합의" onChange={(e) => setReason(e.target.value)} /></label>
      </div>
      <div className="flex gap-2">
        <button type="button" className="btn-danger btn-sm" disabled={busy || !day} onClick={() => onSave({ ended_on: day, reason: reason || null })}>계약 종료</button>
        <button type="button" className="btn-secondary btn-sm" onClick={onCancel}>취소</button>
      </div>
    </div>
  );
}

function NewLeaseForm({ busy, prevEnd, onSave, onCancel }: { busy: boolean; prevEnd: string | null;
  onSave: (b: Record<string, unknown>) => void; onCancel: () => void }) {
  const [f, setF] = useState({ tenant_name: "", tenant_phone: "", deposit: "", rent: "", due_day: "", signed_on: "", start_date: "", end_date: "", deposit_received_on: "" });
  const set = (k: keyof typeof f, digits = false) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF({ ...f, [k]: digits ? e.target.value.replace(/\D/g, "") : e.target.value });
  const ready = f.tenant_name.trim() && f.rent && f.due_day && f.start_date;
  return (
    <div className="mb-3 grid gap-2 rounded-xl bg-slate-50 p-3 text-sm sm:grid-cols-2">
      {prevEnd && <p className="text-xs text-slate-600 sm:col-span-2">앞 계약이 {prevEnd}에 끝났습니다. 시작일은 그 뒤로 정하세요.</p>}
      <label className="block text-xs text-slate-600">임차인 이름<input className="field mt-1 w-full" value={f.tenant_name} onChange={set("tenant_name")} /></label>
      <label className="block text-xs text-slate-600">연락처 (선택, 암호화 저장)<input className="field mt-1 w-full" inputMode="tel" value={f.tenant_phone} onChange={set("tenant_phone")} /></label>
      <label className="block text-xs text-slate-600">보증금 (원)<input className="field mt-1 w-full" inputMode="numeric" value={f.deposit} onChange={set("deposit", true)} /></label>
      <label className="block text-xs text-slate-600">월세 (원, 관리비 포함)<input className="field mt-1 w-full" inputMode="numeric" value={f.rent} onChange={set("rent", true)} /></label>
      <label className="block text-xs text-slate-600">납부일 (매월 며칠)<input className="field mt-1 w-full" inputMode="numeric" value={f.due_day} onChange={set("due_day", true)} /></label>
      <label className="block text-xs text-slate-600">계약서 쓴 날 (임대차 신고 기한 기준)<input type="date" className="field mt-1 w-full" value={f.signed_on} onChange={set("signed_on")} /></label>
      <label className="block text-xs text-slate-600">계약 시작일<input type="date" className="field mt-1 w-full" value={f.start_date} onChange={set("start_date")} /></label>
      <label className="block text-xs text-slate-600">계약 만료일 (선택)<input type="date" className="field mt-1 w-full" value={f.end_date} onChange={set("end_date")} /></label>
      <label className="block text-xs text-slate-600">보증금 받은 날 (이미 받았으면)<input type="date" className="field mt-1 w-full" value={f.deposit_received_on} onChange={set("deposit_received_on")} /></label>
      <div className="flex gap-2 sm:col-span-2">
        <button type="button" className="btn-primary btn-sm" disabled={busy || !ready} onClick={() => onSave({
          tenant_name: f.tenant_name, tenant_phone: f.tenant_phone || null, deposit: Number(f.deposit || 0), rent: Number(f.rent),
          due_day: Number(f.due_day), signed_on: f.signed_on || null, start_date: f.start_date, end_date: f.end_date || null, deposit_received_on: f.deposit_received_on || null })}>계약 넣기</button>
        <button type="button" className="btn-secondary btn-sm" onClick={onCancel}>취소</button>
      </div>
      <p className="text-xs text-slate-500 sm:col-span-2">계약서를 찍어 두려면 계약 관리에서 올리세요 (OCR 결과는 검수 후 반영).</p>
    </div>
  );
}

interface CheckItem { key: string; label: string; basis: string; auto: boolean; status: "done" | "na" | "todo"; done_on: string | null;
  note: string | null; due_on: string | null; overdue: boolean; hint: string | null }
interface CheckOut { signed_on: string | null; deposit: number; rent: number; start_date: string; items: CheckItem[] }

function Checklist({ leaseId, canWrite }: { leaseId: string; canWrite: boolean }) {
  const [c, setC] = useState<CheckOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [signed, setSigned] = useState("");
  const load = useCallback(async () => {
    try { const x = await api<CheckOut>(`/api/v1/leases/${leaseId}/checklist`); setC(x); setSigned(x.signed_on ?? ""); }
    catch (e) { setErr((e as Error).message); }
  }, [leaseId]);
  useEffect(() => { load(); }, [load]);
  const put = async (path: string, body: unknown) => {
    setErr(null);
    try { await api(`/api/v1/leases/${leaseId}/${path}`, json("PUT", body)); await load(); } catch (e) { setErr((e as Error).message); }
  };
  if (!c) return <p className="mt-2 text-xs text-slate-400">{err ?? "불러오는 중…"}</p>;
  return (
    <div className="mt-2 space-y-3 rounded-xl border border-slate-200 p-3 text-sm">
      <label className="flex flex-wrap items-center gap-2 text-xs text-slate-600">계약서 쓴 날
        <input type="date" className="field" value={signed} disabled={!canWrite} onChange={(e) => setSigned(e.target.value)}
          onBlur={() => signed !== (c.signed_on ?? "") && put("signed-on", { signed_on: signed || null })} />
        <span>(임대차 신고 기한 = 이날부터 30일)</span></label>
      <ul className="space-y-2">
        {c.items.map((i) => (
          <li key={i.key} className="rounded-lg bg-slate-50 p-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`chip ${i.status === "done" ? "bg-emerald-50 text-emerald-700" : i.status === "na" ? "bg-slate-200 text-slate-600"
                : i.overdue ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800"}`}>
                {i.status === "done" ? `했음${i.done_on ? ` ${i.done_on}` : ""}` : i.status === "na" ? "해당 없음" : i.overdue ? "기한 지남" : "할 일"}</span>
              <b className="text-sm">{i.label}</b>
              {i.due_on && <span className="text-xs text-slate-500">기한 {i.due_on}</span>}
            </div>
            <p className="mt-0.5 text-xs text-slate-500">{i.basis}{i.auto ? " · 자동 확인" : ""}{i.note ? ` · ${i.note}` : ""}</p>
            {i.hint && <p className="mt-0.5 text-xs text-slate-600">{i.hint}</p>}
            {canWrite && !i.auto && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {i.status !== "done" && <button type="button" className="btn-secondary btn-sm" onClick={() => {
                  const note = window.prompt(`${i.label} — 언제, 어떻게 했나요? (예: 계약 때 등기부·확정일자 현황 보여 줌)`, "");
                  if (note !== null) put(`checks/${i.key}`, { status: "done", done_on: todayKst(), note });
                }}>했음</button>}
                {i.status !== "na" && <button type="button" className="btn-secondary btn-sm"
                  onClick={() => put(`checks/${i.key}`, { status: "na", note: null })}>해당 없음</button>}
                {i.status !== "todo" && <button type="button" className="btn-secondary btn-sm"
                  onClick={() => put(`checks/${i.key}`, { status: null })}>되돌리기</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
      <RentCalc deposit={c.deposit} rent={c.rent} since={c.start_date} />
      {err && <p className="text-xs text-red-700">{err}</p>}
    </div>
  );
}

function RentCalc({ deposit, rent, since }: { deposit: number; rent: number; since: string }) {
  const [inc, setInc] = useState<{ max_deposit: number; max_rent: number; claim_from: string; can_claim_now: boolean; note: string } | null>(null);
  const [from, setFrom] = useState(since);
  const [amount, setAmount] = useState("");
  const [base, setBase] = useState("");
  const [conv, setConv] = useState<{ rate_pct: string; monthly_max: number; rule: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api<typeof inc>(`/api/v1/rent-rules/increase?deposit=${deposit}&rent=${rent}&since=${from}`).then(setInc).catch((e) => setErr((e as Error).message));
  }, [deposit, rent, from]);
  return (
    <div className="space-y-2 border-t border-slate-100 pt-2 text-xs text-slate-700">
      <p className="flex items-center gap-1 font-semibold"><Calculator className="h-3.5 w-3.5" />증액·전환 계산 (주택임대차보호법 §7·§7조의2)</p>
      <label className="flex flex-wrap items-center gap-2">계약일 또는 마지막으로 올린 날
        <input type="date" className="field" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      {inc && <p>계약 중·갱신요구권 갱신 때 최대 보증금 <b>{won(inc.max_deposit)}</b> · 월세 <b>{won(inc.max_rent)}</b> (5%),
        청구는 <b>{inc.claim_from}</b>부터{inc.can_claim_now ? " (지금 가능)" : ""}. {inc.note}.</p>}
      <div className="flex flex-wrap items-end gap-2">
        <label>월세로 바꿀 보증금 (원)<input className="field mt-1 block w-36" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} /></label>
        <label>한국은행 기준금리 (%)<input className="field mt-1 block w-24" inputMode="decimal" placeholder="예: 3.00" value={base} onChange={(e) => setBase(e.target.value)} /></label>
        <button type="button" className="btn-secondary btn-sm" disabled={!amount || !base} onClick={() => {
          setErr(null);
          api<typeof conv>(`/api/v1/rent-rules/conversion?amount=${amount}&base_rate=${encodeURIComponent(base)}`).then(setConv).catch((e) => setErr((e as Error).message));
        }}>계산</button>
      </div>
      {conv && <p>전환율 상한 {conv.rate_pct}% ({conv.rule}) → 월세로 최대 <b>{won(conv.monthly_max)}</b>/월</p>}
      <p className="text-slate-500">기준금리는 바뀌므로 한국은행 발표를 확인해 넣으세요. 계산값은 법령 문언을 옮긴 참고값입니다.</p>
      {err && <p className="text-red-700">{err}</p>}
    </div>
  );
}
