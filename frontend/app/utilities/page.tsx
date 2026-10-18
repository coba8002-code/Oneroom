"use client";

import { Droplets, Receipt, Settings2, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, todayKst, won } from "@/lib/api";
import { useMe } from "@/lib/me";

type Setting = { mode: string; method: string | null; vacant: string | null; owner: string | null } | null;
interface Settings {
  items: Record<string, string>; modes: Record<string, string>; methods: Record<string, string>; shares: Record<string, string>;
  buildings: { property_id: string; name: string; settings: Record<string, Setting> }[];
}
interface Share { unit_id: string; unit_no: string; role: "leased" | "vacant" | "owner"; lease_id: string | null; amount: number | null; billed: boolean }
interface Bill {
  id: string; property_id: string; item: string; item_label: string; period: string; total: number; note: string | null;
  manual: Record<string, number | null> | null; status: "draft" | "charged"; charged_at: string | null; problem: string | null;
  split: { method: string; shares: Share[]; billed_total: number; landlord_total: number } | null;
}

const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const ROLE: Record<Share["role"], string> = { leased: "", vacant: "공실", owner: "주인세대" };

export default function UtilitiesPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [s, setS] = useState<Settings | null>(null);
  const [period, setPeriod] = useState(todayKst().slice(0, 7));
  const [bills, setBills] = useState<Bill[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [st, b] = await Promise.all([api<Settings>("/api/v1/utility-settings"), api<Bill[]>(`/api/v1/utility-bills?period=${period}`)]);
      setS(st); setBills(b);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, [period]);
  useEffect(() => { load(); }, [load]);
  const run = async (fn: () => Promise<unknown>, text: string) => {
    setMsg(null);
    try { await fn(); await load(); setMsg({ ok: true, text }); return true; }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); return false; }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="page-title">공과금</h1>
        <p className="page-sub">건물마다·항목마다 처리 방식을 고르세요. '나눠서 청구'한 항목만 고지서를 넣어 호실별로 나누고, 월세와 같은 납부일로 청구합니다.</p>
      </header>
      {msg && <p className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</p>}
      {!s ? <p className="text-sm text-slate-400">불러오는 중…</p> : (
        <>
          {s.buildings.map((b) => (
            <section key={b.property_id} className="card p-4">
              <h2 className="card-title mb-3 flex items-center gap-1"><Settings2 className="h-4 w-4" />처리 방식{s.buildings.length > 1 ? ` — ${b.name}` : ""}</h2>
              <div className="grid gap-3 md:grid-cols-2 [&>*]:min-w-0">
                {Object.entries(s.items).map(([item, label]) => (
                  <SettingCard key={item} s={s} item={item} label={label} value={b.settings[item]} canWrite={canWrite}
                    onSave={(body) => run(() => api(`/api/v1/properties/${b.property_id}/utility-settings/${item}`, json("PUT", body)),
                      `${label} 처리 방식을 저장했습니다.`)} />
                ))}
              </div>
            </section>
          ))}

          <section className="card space-y-3 p-4">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <h2 className="card-title flex items-center gap-1"><Receipt className="h-4 w-4" />고지서 · 배분 청구</h2>
              <label className="text-sm text-slate-600">청구 월 <input type="month" className="field ml-1" aria-label="청구 월" value={period}
                onChange={(e) => e.target.value && setPeriod(e.target.value)} /></label>
            </div>
            {canWrite && <NewBill s={s} period={period} onSave={(body) => run(() => api("/api/v1/utility-bills", json("POST", body)), "고지서를 넣었습니다. 나눈 결과를 확인하고 청구하세요.")} />}
            {bills === null ? <p className="text-sm text-slate-400">불러오는 중…</p>
              : bills.length === 0 ? <p className="text-sm text-slate-500">{period} 고지서가 없습니다.</p>
              : bills.map((b) => <BillCard key={b.id} b={b} canWrite={canWrite} multi={s.buildings.length > 1}
                  building={s.buildings.find((x) => x.property_id === b.property_id)?.name ?? ""} run={run} />)}
          </section>
        </>
      )}
    </div>
  );
}

function SettingCard({ s, item, label, value, canWrite, onSave }: { s: Settings; item: string; label: string; value: Setting;
  canWrite: boolean; onSave: (b: Record<string, string | null>) => Promise<boolean> }) {
  const [f, setF] = useState({ mode: value?.mode ?? "", method: value?.method ?? "", vacant: value?.vacant ?? "", owner: value?.owner ?? "" });
  const ready = f.mode && (f.mode !== "split" || (f.method && (f.method === "manual" || (f.vacant && f.owner))));
  const sel = (k: keyof typeof f, opts: Record<string, string>, aria: string) => (
    <select className="field mt-1 block w-full" aria-label={aria} value={f[k]} disabled={!canWrite}
      onChange={(e) => setF({ ...f, [k]: e.target.value })}>
      <option value="">고르세요</option>
      {Object.entries(opts).map(([k2, v]) => <option key={k2} value={k2}>{v}</option>)}
    </select>
  );
  return (
    <div className="rounded-xl border border-slate-200 p-3 text-sm" data-item={item}>
      <p className="mb-1 font-semibold">{label} {value ? <span className="chip ml-1 bg-slate-100 text-slate-600">{s.modes[value.mode]}</span>
        : <span className="chip ml-1 bg-amber-50 text-amber-800">아직 정하지 않음</span>}</p>
      <label className="block text-xs text-slate-600">처리 방식{sel("mode", s.modes, `${label} 처리 방식`)}</label>
      {f.mode === "split" && <label className="mt-2 block text-xs text-slate-600">나누는 방법{sel("method", s.methods, `${label} 나누는 방법`)}</label>}
      {f.mode === "split" && f.method && f.method !== "manual" && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <label className="block text-xs text-slate-600">공실 몫{sel("vacant", s.shares, `${label} 공실 몫`)}</label>
          <label className="block text-xs text-slate-600">주인세대 몫{sel("owner", s.shares, `${label} 주인세대 몫`)}</label>
        </div>
      )}
      {canWrite && <button type="button" className="btn-secondary btn-sm mt-2" disabled={!ready}
        onClick={() => onSave({ mode: f.mode, method: f.method || null, vacant: f.vacant || null, owner: f.owner || null })}>저장</button>}
    </div>
  );
}

function NewBill({ s, period, onSave }: { s: Settings; period: string; onSave: (b: Record<string, unknown>) => Promise<boolean> }) {
  const options = s.buildings.flatMap((b) => Object.entries(b.settings).filter(([, v]) => v?.mode === "split")
    .map(([item]) => ({ key: `${b.property_id}:${item}`, label: `${s.buildings.length > 1 ? `${b.name} ` : ""}${s.items[item]}` })));
  const [pick, setPick] = useState("");
  const [total, setTotal] = useState("");
  const [note, setNote] = useState("");
  if (options.length === 0) return <p className="rounded-xl bg-slate-50 p-3 text-sm text-slate-600">'나눠서 청구'로 정한 항목이 없습니다. 위에서 처리 방식을 먼저 고르세요.</p>;
  const key = pick || options[0].key;
  return (
    <div className="grid gap-2 rounded-xl bg-slate-50 p-3 text-sm sm:grid-cols-4 sm:items-end">
      <label className="block text-xs text-slate-600">항목
        <select className="field mt-1 block w-full" value={key} onChange={(e) => setPick(e.target.value)}>
          {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}</select></label>
      <label className="block text-xs text-slate-600">고지서 금액 (원)
        <input className="field mt-1 block w-full" inputMode="numeric" value={total} onChange={(e) => setTotal(e.target.value.replace(/\D/g, ""))} /></label>
      <label className="block text-xs text-slate-600">메모 (선택)
        <input className="field mt-1 block w-full" maxLength={200} placeholder="예: 9월 사용분" value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <button type="button" className="btn-primary btn-sm" disabled={!total} onClick={async () => {
        const [property_id, item] = key.split(":");
        if (await onSave({ property_id, item, period, total: Number(total), note: note || null })) { setTotal(""); setNote(""); }
      }}><Droplets className="h-3.5 w-3.5" />고지서 넣기</button>
    </div>
  );
}

function BillCard({ b, canWrite, multi, building, run }: { b: Bill; canWrite: boolean; multi: boolean; building: string;
  run: (fn: () => Promise<unknown>, text: string) => Promise<boolean> }) {
  const manual = b.split?.method === "manual" || (b.problem !== null && b.manual !== null);
  const [amounts, setAmounts] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(b.manual ?? {}).map(([k, v]) => [k, v == null ? "" : String(v)])));
  const draft = b.status === "draft";
  return (
    <div className="rounded-xl border border-slate-200 p-3 text-sm" data-bill={b.item}>
      <div className="flex flex-wrap items-center gap-2">
        <b>{multi ? `${building} ` : ""}{b.item_label} {won(b.total)}</b>
        <span className={`chip ${draft ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>{draft ? "청구 전" : "청구함"}</span>
        {b.note && <span className="text-xs text-slate-500">{b.note}</span>}
      </div>
      {b.problem && <p className="mt-1 text-xs text-red-700" role="status">{b.problem}</p>}
      {b.split && (
        <>
          <table className="mt-2 w-full tabular-nums">
            <thead className="text-xs text-slate-500"><tr><th className="text-left">호실</th><th className="text-right">몫</th><th className="text-right">청구</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {b.split.shares.map((x) => (
                <tr key={x.unit_id}>
                  <td className="py-1">{x.unit_no}호 <span className="text-xs text-slate-500">{ROLE[x.role]}</span></td>
                  <td className="text-right">
                    {manual && draft && x.role === "leased" && canWrite
                      ? <input className="field w-28 text-right" inputMode="numeric" aria-label={`${x.unit_no}호 금액`} value={amounts[x.unit_id] ?? ""}
                          onChange={(e) => setAmounts({ ...amounts, [x.unit_id]: e.target.value.replace(/\D/g, "") })} />
                      : won(x.amount)}
                  </td>
                  <td className="text-right text-xs">{x.billed ? "청구" : x.amount != null ? "집주인 부담" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-600">임차인 청구 합 <b>{won(b.split.billed_total)}</b> · 집주인 부담 <b>{won(b.split.landlord_total)}</b>
            {" "}(끝수는 원 단위로 맞춰 합이 고지서 금액과 같습니다)</p>
        </>
      )}
      {canWrite && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {draft && manual && <button type="button" className="btn-secondary btn-sm" onClick={() => run(() => api(`/api/v1/utility-bills/${b.id}`, json("PUT", {
            total: b.total, note: b.note, manual: Object.fromEntries(Object.entries(amounts).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])),
          })), "호실별 금액을 저장했습니다.")}>금액 저장</button>}
          {draft && <button type="button" className="btn-primary btn-sm" disabled={!b.split}
            onClick={() => window.confirm(`${b.item_label} ${won(b.split?.billed_total)}을 호실별로 청구할까요? 월세와 같은 납부일로 들어갑니다.`)
              && run(() => api(`/api/v1/utility-bills/${b.id}/charge`, json("POST")), `${b.item_label} 청구를 만들었습니다.`)}>청구하기</button>}
          {draft && <button type="button" className="btn-secondary btn-sm" onClick={() => window.confirm("이 고지서를 지울까요?")
            && run(() => api(`/api/v1/utility-bills/${b.id}`, json("DELETE")), "고지서를 지웠습니다.")}><Trash2 className="h-3.5 w-3.5" />지우기</button>}
          {!draft && <button type="button" className="btn-secondary btn-sm" onClick={() => window.confirm("청구를 취소할까요? 입금이 배분된 청구가 있으면 취소할 수 없습니다.")
            && run(() => api(`/api/v1/utility-bills/${b.id}/uncharge`, json("POST")), "청구를 취소했습니다.")}><Undo2 className="h-3.5 w-3.5" />청구 취소</button>}
        </div>
      )}
    </div>
  );
}
