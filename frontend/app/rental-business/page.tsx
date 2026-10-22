"use client";

import { AlertTriangle, BadgeCheck, Info, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, won } from "@/lib/api";
import { useMe } from "@/lib/me";

type Codes = { housing_types: Record<string, string>; rental_types: Record<string, string>; providers: Record<string, string>;
  suggested_years: Record<string, number> };
interface Profile { registration_no: string | null; registered_on: string | null; tax_business_no: string | null; note: string | null;
  increase_cap_pct: string; report_months: number }
interface Guarantee { id: string; provider: string; policy_no: string | null; start_on: string | null; end_on: string | null; note: string | null }
interface Increase { previous_deposit: number; previous_rent: number; deposit_pct: string | null; rent_pct: string | null; cap_pct: string;
  over_cap: boolean; within_a_year: boolean }
interface LeaseRow { lease_id: string; unit_no: string; deposit: number; rent: number; start_date: string; signed_on: string | null;
  report_due_on: string | null; report_status: "done" | "na" | null; increase: Increase | null }
interface Registration { id: string; property_id: string; unit_id: string | null; place: string; housing_type: string; rental_type: string;
  registered_on: string | null; rental_start_on: string | null; obligation_years: number | null; obligation_end_on: string | null;
  lien_status: "done" | "na" | null; lien_done_on: string | null; note: string | null;
  guarantee_state: "none" | "ok" | "expiring" | "exempt"; guarantees: Guarantee[]; leases: LeaseRow[] }
interface Obligation { level: "warn" | "info"; kind: string; place: string; message: string; registration_id: string }
interface Building { property_id: string; name: string; units: { unit_id: string; unit_no: string }[] }
interface Overview { profile: Profile | null; rules: { increase_cap_pct: string; report_months: number; note: string;
  default_cap_pct: string; default_report_months: number }; registrations: Registration[]; obligations: Obligation[];
  buildings: Building[]; codes: Codes }

const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const GUARANTEE: Record<Registration["guarantee_state"], [string, string]> = {
  none: ["보증 기록 없음", "bg-red-50 text-red-700"], ok: ["보증 가입", "bg-emerald-50 text-emerald-700"],
  expiring: ["보증 곧 만료", "bg-amber-50 text-amber-800"], exempt: ["가입 면제", "bg-slate-200 text-slate-600"] };

export default function RentalBusinessPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [ov, setOv] = useState<Overview | null>(null);
  const [editing, setEditing] = useState<Registration | "new" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(async () => {
    try { setOv(await api<Overview>("/api/v1/rental-business")); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const run = async (fn: () => Promise<unknown>, text: string) => {
    setMsg(null);
    try { await fn(); await load(); setMsg({ ok: true, text }); return true; }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); return false; }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="page-title">임대사업자</h1>
        <p className="page-sub">등록임대주택(민간임대주택에 관한 특별법)의 보증·부기등기·신고·증액 상한·의무기간을 챙깁니다.
          등록 여부나 의무를 판정하지 않고, 등록증·보증서에서 확인해 적은 값만 씁니다.</p>
      </header>
      {msg && <p className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</p>}
      {!ov ? <p className="text-sm text-slate-400">불러오는 중…</p> : (
        <>
          <p className="flex items-start gap-1.5 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />확인 필요 — 증액 상한 {ov.rules.increase_cap_pct}%, 임대차계약 신고 기한
            계약일부터 {ov.rules.report_months}개월로 계산합니다. {ov.rules.note}. 값은 아래 사업자 정보에서 바꿀 수 있습니다.</p>

          {ov.registrations.length > 0 && (
            <section className="card p-4">
              <h2 className="card-title mb-2">챙길 일 {ov.obligations.length}건</h2>
              {ov.obligations.length === 0 ? <p className="text-sm text-slate-500">지금 챙길 일이 없습니다.</p> : (
                <ul className="space-y-1.5 text-sm">
                  {ov.obligations.map((o, i) => (
                    <li key={i} className={`flex items-start gap-2 rounded-lg p-2 ${o.level === "warn" ? "bg-red-50 text-red-900" : "bg-slate-50 text-slate-700"}`}>
                      {o.level === "warn" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
                      <span><b>{o.place}</b> — {o.message}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <ProfileCard ov={ov} canWrite={canWrite} onSave={(b) => run(() => api("/api/v1/rental-business", json("PUT", b)), "사업자 정보를 저장했습니다.")} />

          <section className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="card-title">등록 임대주택 {ov.registrations.length}건</h2>
              {canWrite && editing === null && ov.buildings.length > 0 &&
                <button type="button" className="btn-primary btn-sm ml-auto" onClick={() => setEditing("new")}><Plus className="h-3.5 w-3.5" />등록 임대주택 추가</button>}
            </div>
            {ov.buildings.length === 0 && <p className="text-sm text-slate-500">먼저 건물·호실을 등록하세요.</p>}
            {editing !== null && <RegistrationForm ov={ov} initial={editing === "new" ? null : editing} onCancel={() => setEditing(null)}
              onSave={async (b) => {
                const ok = editing === "new"
                  ? await run(() => api("/api/v1/registered-rentals", json("POST", b)), "등록 임대주택을 추가했습니다.")
                  : await run(() => api(`/api/v1/registered-rentals/${editing.id}`, json("PUT", b)), "고쳤습니다.");
                if (ok) setEditing(null);
              }} />}
            {ov.registrations.length === 0 && editing === null && ov.buildings.length > 0 &&
              <p className="card p-4 text-sm text-slate-500">아직 등록 임대주택이 없습니다. 임대사업자로 등록한 호실(또는 다가구 건물 전체)을 추가하면 의무를 챙겨 드립니다.</p>}
            {ov.registrations.map((r) => <RegistrationCard key={r.id} r={r} codes={ov.codes} canWrite={canWrite}
              onEdit={() => setEditing(r)}
              onDelete={() => window.confirm(`'${r.place}' 등록 기록과 보증 기록을 지울까요? 계약·장부는 그대로 남습니다.`)
                && run(() => api(`/api/v1/registered-rentals/${r.id}`, json("DELETE")), "등록 기록을 지웠습니다.")}
              onAddGuarantee={(b) => run(() => api(`/api/v1/registered-rentals/${r.id}/guarantees`, json("POST", b)), "보증 기록을 넣었습니다.")}
              onDeleteGuarantee={(id) => run(() => api(`/api/v1/rental-guarantees/${id}`, json("DELETE")), "보증 기록을 지웠습니다.")} />)}
          </section>
        </>
      )}
    </div>
  );
}

function ProfileCard({ ov, canWrite, onSave }: { ov: Overview; canWrite: boolean; onSave: (b: Record<string, unknown>) => Promise<boolean> }) {
  const p = ov.profile;
  const [f, setF] = useState({ registration_no: p?.registration_no ?? "", registered_on: p?.registered_on ?? "",
    tax_business_no: p?.tax_business_no ?? "", increase_cap_pct: ov.rules.increase_cap_pct, report_months: String(ov.rules.report_months),
    note: p?.note ?? "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <section className="card grid gap-2 p-4 text-sm sm:grid-cols-2">
      <h2 className="card-title sm:col-span-2">사업자 정보</h2>
      <label className="block text-xs text-slate-600">임대사업자 등록번호 (지자체)
        <input className="field mt-1 w-full" maxLength={50} value={f.registration_no} disabled={!canWrite} onChange={set("registration_no")} /></label>
      <label className="block text-xs text-slate-600">등록일
        <input type="date" className="field mt-1 w-full" value={f.registered_on} disabled={!canWrite} onChange={set("registered_on")} /></label>
      <label className="block text-xs text-slate-600">사업자등록번호 (세무서, 선택)
        <input className="field mt-1 w-full" maxLength={20} value={f.tax_business_no} disabled={!canWrite} onChange={set("tax_business_no")} /></label>
      <label className="block text-xs text-slate-600">메모 (선택)
        <input className="field mt-1 w-full" maxLength={1000} value={f.note} disabled={!canWrite} onChange={set("note")} /></label>
      <label className="block text-xs text-slate-600">임대료 증액 상한 (%) — 확인 필요, 법 문언 기본 {ov.rules.default_cap_pct}%
        <input className="field mt-1 w-full" inputMode="decimal" value={f.increase_cap_pct} disabled={!canWrite} onChange={set("increase_cap_pct")} /></label>
      <label className="block text-xs text-slate-600">임대차계약 신고 기한 (계약일부터 개월) — 확인 필요, 기본 {ov.rules.default_report_months}개월
        <input className="field mt-1 w-full" inputMode="numeric" value={f.report_months} disabled={!canWrite} onChange={set("report_months")} /></label>
      {canWrite && <div className="sm:col-span-2"><button type="button" className="btn-secondary btn-sm" onClick={() => onSave({
        registration_no: f.registration_no || null, registered_on: f.registered_on || null, tax_business_no: f.tax_business_no || null,
        increase_cap_pct: f.increase_cap_pct || null, report_months: f.report_months ? Number(f.report_months) : null, note: f.note || null })}>
        사업자 정보 저장</button></div>}
    </section>
  );
}

function RegistrationForm({ ov, initial, onSave, onCancel }: { ov: Overview; initial: Registration | null;
  onSave: (b: Record<string, unknown>) => Promise<void>; onCancel: () => void }) {
  const [f, setF] = useState({ property_id: initial?.property_id ?? ov.buildings[0].property_id, unit_id: initial?.unit_id ?? "",
    housing_type: initial?.housing_type ?? "", rental_type: initial?.rental_type ?? "", registered_on: initial?.registered_on ?? "",
    rental_start_on: initial?.rental_start_on ?? "", obligation_years: initial?.obligation_years?.toString() ?? "",
    lien_status: initial?.lien_status ?? "", lien_done_on: initial?.lien_done_on ?? "", note: initial?.note ?? "" });
  const [busy, setBusy] = useState(false);
  const b = ov.buildings.find((x) => x.property_id === f.property_id) ?? ov.buildings[0];
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const v = e.target.value;
    const next = { ...f, [k]: v, ...(k === "property_id" ? { unit_id: "" } : {}) };
    // 임대 유형을 고르면 의무기간 칸이 비어 있을 때만 흔한 값을 채워 준다 (등록증으로 확인해 고치세요)
    if (k === "rental_type" && !f.obligation_years && ov.codes.suggested_years[v]) next.obligation_years = String(ov.codes.suggested_years[v]);
    setF(next);
  };
  return (
    <section className="card grid gap-2 p-4 text-sm sm:grid-cols-2">
      <h2 className="card-title sm:col-span-2">{initial ? `${initial.place} 고치기` : "등록 임대주택 추가"}</h2>
      {ov.buildings.length > 1 && <label className="block text-xs text-slate-600">건물
        <select className="field mt-1 w-full" value={f.property_id} onChange={set("property_id")}>
          {ov.buildings.map((x) => <option key={x.property_id} value={x.property_id}>{x.name}</option>)}</select></label>}
      <label className="block text-xs text-slate-600">범위
        <select className="field mt-1 w-full" value={f.unit_id} onChange={set("unit_id")}>
          <option value="">건물 전체 (다가구처럼 한 채로 등록)</option>
          {b.units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_no}호</option>)}</select></label>
      <label className="block text-xs text-slate-600">주택 유형
        <select className="field mt-1 w-full" value={f.housing_type} onChange={set("housing_type")}>
          <option value="">고르세요</option>
          {Object.entries(ov.codes.housing_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="block text-xs text-slate-600">임대 유형
        <select className="field mt-1 w-full" value={f.rental_type} onChange={set("rental_type")}>
          <option value="">고르세요</option>
          {Object.entries(ov.codes.rental_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="block text-xs text-slate-600">임대주택 등록일
        <input type="date" className="field mt-1 w-full" value={f.registered_on} onChange={set("registered_on")} /></label>
      <label className="block text-xs text-slate-600">임대의무기간 시작일 (등록증 확인, 모르면 비움)
        <input type="date" className="field mt-1 w-full" value={f.rental_start_on} onChange={set("rental_start_on")} /></label>
      <label className="block text-xs text-slate-600">임대의무기간 (년, 모르면 비움)
        <input className="field mt-1 w-full" inputMode="numeric" value={f.obligation_years}
          onChange={(e) => setF({ ...f, obligation_years: e.target.value.replace(/\D/g, "") })} /></label>
      <label className="block text-xs text-slate-600">부기등기
        <select className="field mt-1 w-full" value={f.lien_status} onChange={set("lien_status")}>
          <option value="">아직 / 모름</option><option value="done">했음</option><option value="na">해당 없음</option></select></label>
      {f.lien_status === "done" && <label className="block text-xs text-slate-600">부기등기 한 날 (선택)
        <input type="date" className="field mt-1 w-full" value={f.lien_done_on} onChange={set("lien_done_on")} /></label>}
      <label className="block text-xs text-slate-600 sm:col-span-2">메모 (선택)
        <input className="field mt-1 w-full" maxLength={1000} value={f.note} onChange={set("note")} /></label>
      <div className="flex gap-2 sm:col-span-2">
        <button type="button" className="btn-primary btn-sm" disabled={busy || !f.housing_type || !f.rental_type} onClick={async () => {
          setBusy(true);
          await onSave({ property_id: f.property_id, unit_id: f.unit_id || null, housing_type: f.housing_type, rental_type: f.rental_type,
            registered_on: f.registered_on || null, rental_start_on: f.rental_start_on || null,
            obligation_years: f.obligation_years ? Number(f.obligation_years) : null, lien_status: f.lien_status || null,
            lien_done_on: f.lien_done_on || null, note: f.note || null });
          setBusy(false);
        }}>저장</button>
        <button type="button" className="btn-secondary btn-sm" onClick={onCancel}>취소</button>
      </div>
    </section>
  );
}

function RegistrationCard({ r, codes, canWrite, onEdit, onDelete, onAddGuarantee, onDeleteGuarantee }: { r: Registration; codes: Codes;
  canWrite: boolean; onEdit: () => void; onDelete: () => void; onAddGuarantee: (b: Record<string, unknown>) => Promise<boolean>;
  onDeleteGuarantee: (id: string) => void }) {
  const [g, setG] = useState({ provider: "", policy_no: "", start_on: "", end_on: "" });
  const [gl, gt] = GUARANTEE[r.guarantee_state];
  return (
    <section className="card space-y-3 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-base">{r.place}</b>
        <span className="chip bg-slate-100 text-slate-700">{codes.housing_types[r.housing_type]}</span>
        <span className="chip bg-slate-100 text-slate-700">{codes.rental_types[r.rental_type]}</span>
        <span className={`chip ${gt}`}>{gl}</span>
        {canWrite && <span className="ml-auto flex gap-1.5">
          <button type="button" className="btn-secondary btn-sm" onClick={onEdit}><Pencil className="h-3.5 w-3.5" />고치기</button>
          <button type="button" className="btn-secondary btn-sm" aria-label={`${r.place} 등록 기록 지우기`} onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></button>
        </span>}
      </div>
      <dl className="grid gap-x-4 gap-y-1 text-xs text-slate-600 sm:grid-cols-2">
        <div>등록일 <b>{r.registered_on ?? "—"}</b></div>
        <div>의무기간 <b>{r.rental_start_on ?? "—"} ~ {r.obligation_end_on ?? "—"}</b>{r.obligation_years ? ` (${r.obligation_years}년)` : ""}</div>
        <div>부기등기 <b>{r.lien_status === "done" ? `했음${r.lien_done_on ? ` ${r.lien_done_on}` : ""}` : r.lien_status === "na" ? "해당 없음" : "—"}</b></div>
        {r.note && <div>메모 {r.note}</div>}
      </dl>

      <div>
        <p className="mb-1 flex items-center gap-1 text-xs font-semibold text-slate-700"><ShieldCheck className="h-3.5 w-3.5" />임대보증금 보증</p>
        {r.guarantees.length === 0 ? <p className="text-xs text-slate-500">기록 없음</p> : (
          <ul className="space-y-1 text-xs">
            {r.guarantees.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center gap-2">
                <span>{codes.providers[x.provider]}{x.policy_no ? ` · ${x.policy_no}` : ""} · {x.start_on ?? "—"} ~ {x.end_on ?? "—"}</span>
                {canWrite && <button type="button" className="text-slate-400 hover:text-red-600" aria-label="보증 기록 지우기"
                  onClick={() => window.confirm("이 보증 기록을 지울까요?") && onDeleteGuarantee(x.id)}><Trash2 className="h-3.5 w-3.5" /></button>}
              </li>
            ))}
          </ul>
        )}
        {canWrite && (
          <div className="mt-2 flex flex-wrap items-end gap-2 text-xs">
            <label className="text-slate-600">보증기관
              <select className="field mt-1 block" value={g.provider} onChange={(e) => setG({ ...g, provider: e.target.value })}>
                <option value="">고르세요</option>
                {Object.entries(codes.providers).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="text-slate-600">증권번호 (선택)<input className="field mt-1 block w-32" maxLength={50} value={g.policy_no}
              onChange={(e) => setG({ ...g, policy_no: e.target.value })} /></label>
            <label className="text-slate-600">시작<input type="date" className="field mt-1 block" value={g.start_on}
              onChange={(e) => setG({ ...g, start_on: e.target.value })} /></label>
            <label className="text-slate-600">끝<input type="date" className="field mt-1 block" value={g.end_on}
              onChange={(e) => setG({ ...g, end_on: e.target.value })} /></label>
            <button type="button" className="btn-secondary btn-sm" disabled={!g.provider} onClick={async () => {
              if (await onAddGuarantee({ provider: g.provider, policy_no: g.policy_no || null, start_on: g.start_on || null, end_on: g.end_on || null }))
                setG({ provider: "", policy_no: "", start_on: "", end_on: "" });
            }}><Plus className="h-3.5 w-3.5" />보증 넣기</button>
          </div>
        )}
      </div>

      <div>
        <p className="mb-1 flex items-center gap-1 text-xs font-semibold text-slate-700"><BadgeCheck className="h-3.5 w-3.5" />진행 중 계약 {r.leases.length}건</p>
        {r.leases.length === 0 ? <p className="text-xs text-slate-500">진행 중 계약이 없습니다.</p> : (
          <ul className="divide-y divide-slate-100 text-xs">
            {r.leases.map((l) => (
              <li key={l.lease_id} className="flex flex-wrap gap-x-3 gap-y-0.5 py-1.5">
                <b>{l.unit_no}</b>
                <span>보증금 {won(l.deposit)} · 월세 {won(l.rent)}</span>
                <span>신고 {l.report_status === "done" ? "했음" : l.report_status === "na" ? "해당 없음" : l.report_due_on ? `기한 ${l.report_due_on}` : "계약일 모름"}</span>
                {l.increase ? <span className={l.increase.over_cap || l.increase.within_a_year ? "text-red-700" : "text-slate-500"}>
                  직전 계약 대비 보증금 {l.increase.deposit_pct ?? "—"}% · 월세 {l.increase.rent_pct ?? "—"}% (상한 {l.increase.cap_pct}%)
                  {l.increase.within_a_year ? " · 1년 안 증액" : ""}</span> : <span className="text-slate-400">직전 계약 없음</span>}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-xs text-slate-500">임대차계약 신고·표준계약서 사용은 호실·계약 화면의 체크리스트에서 표시합니다.</p>
      </div>
    </section>
  );
}
