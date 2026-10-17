"use client";

import { Camera, Check, ClipboardCheck, Lock, Plus, Printer, Scale, Trash2, Unlock, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiFetch, kst, todayKst, won } from "@/lib/api";
import { shrinkImage } from "@/lib/image";
import { useMe } from "@/lib/me";

interface Codes { kinds: Record<string, string>; conditions: Record<string, string>; deduction_categories: Record<string, string> }
interface LeaseRow {
  lease_id: string; unit_no: string; tenant_name: string; start_date: string; end_date: string | null; status: string;
  move_in: boolean; move_out: boolean; settlement: "draft" | "confirmed" | null;
}
interface Photo { id: string; uploaded_at: string; size: number }
interface Item { id: string; area: string; fixture_id: string | null; condition: string | null; reading: string | null; note: string | null; photos: Photo[] }
interface Insp {
  id: string; kind: "move_in" | "move_out"; inspected_on: string; tenant_confirmed_on: string | null; confirm_note: string | null;
  note: string | null; locked: boolean; items: Item[];
}
interface Overview {
  lease: { id: string; unit_no: string; tenant_name: string; start_date: string; end_date: string | null; deposit: number; rent: number };
  move_in: Insp | null; move_out: Insp | null;
}
interface Deduction { id: string; category: string; label: string; amount: number; disputed: boolean; note: string | null;
  inspection_item_id: string | null; inspection_item_area: string | null }
interface Settlement {
  status: "draft" | "confirmed"; confirmed_at: string | null; note: string | null; as_of: string;
  deposit_unreturned: number | null; deposit_returned_on: string | null; prepaid_credit: number;
  unpaid: { period: string; due_date: string; amount: number }[]; unpaid_total: number; deductions: Deduction[];
  agreed_deductions: number; disputed_held: number; return_now: number | null; bank_data_as_of: string | null; warnings: string[];
}
type Tab = "move_in" | "move_out" | "compare" | "settlement";
const RANK: Record<string, number> = { good: 0, worn: 1, dirty: 2, damaged: 3, missing: 4 };
const TONE: Record<string, string> = { good: "bg-emerald-50 text-emerald-700", worn: "bg-slate-100 text-slate-700",
  dirty: "bg-amber-50 text-amber-800", damaged: "bg-red-50 text-red-700", missing: "bg-red-50 text-red-700" };
const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const isMeter = (area: string) => area.includes("계량기");

export default function MoveOutPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [codes, setCodes] = useState<Codes | null>(null);
  const [rows, setRows] = useState<LeaseRow[] | null>(null);
  const [leaseId, setLeaseId] = useState<string | null>(null);
  const [view, setView] = useState<Overview | null>(null);
  const [settle, setSettle] = useState<Settlement | null>(null);
  const [tab, setTab] = useState<Tab>("move_in");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const loadList = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([api<Codes>("/api/v1/move-out/codes"), api<LeaseRow[]>("/api/v1/move-out/leases")]);
      setCodes(c); setRows(r);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);
  const loadLease = useCallback(async () => {
    if (!leaseId) return;
    try {
      const [v, s] = await Promise.all([api<Overview>(`/api/v1/leases/${leaseId}/inspections`),
        api<Settlement>(`/api/v1/leases/${leaseId}/settlement`)]);
      setView(v); setSettle(s);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, [leaseId]);
  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("lease");
    if (q) setLeaseId(q);
  }, []);
  useEffect(() => { setView(null); setSettle(null); loadLease(); }, [loadLease]);

  async function run(fn: () => Promise<unknown>, ok: string | null) {
    setBusy(true); setMsg(null);
    try { await fn(); await Promise.all([loadLease(), loadList()]); if (ok) setMsg({ ok: true, text: ok }); }  // 화면을 새로 그린 뒤 알림
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  function pick(id: string) {
    setLeaseId(id); setTab("move_in"); setMsg(null);
    window.history.replaceState(null, "", `/move-out?lease=${id}`);
  }

  return (
    <div className="space-y-6">
      <header className="print:hidden">
        <h1 className="page-title">입주·퇴실</h1>
        <p className="page-sub">입주 때와 퇴실 때 같은 항목을 사진과 함께 남기고, 그 근거로 보증금을 정산합니다.</p>
      </header>

      <section className="card p-4 print:hidden" aria-label="계약 고르기">
        {rows === null ? <p className="text-sm text-slate-400">불러오는 중…</p> : rows.length === 0 ? (
          <p className="text-sm text-slate-500">계약이 없습니다. 건물·호실 등록에서 계약을 먼저 넣으세요.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {rows.map((r) => (
              <button key={r.lease_id} type="button" aria-pressed={leaseId === r.lease_id} onClick={() => pick(r.lease_id)}
                className={`rounded-xl border px-3 py-2 text-left text-sm ${leaseId === r.lease_id ? "border-blue-600 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
                <b>{r.unit_no}호</b> {r.tenant_name}
                <span className="mt-0.5 flex gap-1 text-[11px]">
                  <span className={`chip ${r.move_in ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>입주 {r.move_in ? "✓" : "—"}</span>
                  <span className={`chip ${r.move_out ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>퇴실 {r.move_out ? "✓" : "—"}</span>
                  {r.settlement && <span className={`chip ${r.settlement === "confirmed" ? "bg-blue-50 text-blue-700" : "bg-amber-50 text-amber-800"}`}>
                    정산 {r.settlement === "confirmed" ? "확정" : "작성 중"}</span>}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      {msg && <div className={`rounded-xl p-3 text-sm print:hidden ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}

      {leaseId && view && codes && settle && (
        <>
          <div className="flex flex-wrap items-center gap-2 print:hidden" role="tablist" aria-label="입주·퇴실">
            {([["move_in", "입주 점검"], ["move_out", "퇴실 점검"], ["compare", "입주↔퇴실 비교"], ["settlement", "퇴실 정산"]] as [Tab, string][]).map(([t, label]) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>{label}</button>
            ))}
            <button type="button" className="btn-secondary btn-sm ml-auto" onClick={() => window.print()}><Printer className="h-3.5 w-3.5" />인쇄·PDF</button>
          </div>
          <p className="hidden text-lg font-bold print:block">{view.lease.unit_no}호 {view.lease.tenant_name} — {
            { move_in: "입주 점검", move_out: "퇴실 점검", compare: "입주·퇴실 비교", settlement: "퇴실 정산서" }[tab]}</p>

          {(tab === "move_in" || tab === "move_out") && (
            <InspectionView key={tab} kind={tab} insp={view[tab]} codes={codes} canWrite={canWrite} busy={busy}
              leaseId={leaseId} run={run} hasMoveIn={!!view.move_in} />
          )}
          {tab === "compare" && <Compare a={view.move_in} b={view.move_out} codes={codes} />}
          {tab === "settlement" && <SettlementView s={settle} codes={codes} leaseId={leaseId} canWrite={canWrite}
            busy={busy} run={run} moveOut={view.move_out} />}
        </>
      )}
    </div>
  );
}

function InspectionView({ kind, insp, codes, canWrite, busy, leaseId, run, hasMoveIn }: {
  kind: "move_in" | "move_out"; insp: Insp | null; codes: Codes; canWrite: boolean; busy: boolean; leaseId: string;
  run: (fn: () => Promise<unknown>, ok: string | null) => Promise<void>; hasMoveIn: boolean }) {
  const [day, setDay] = useState(todayKst());
  const [newArea, setNewArea] = useState("");
  const label = codes.kinds[kind];
  if (!insp) return (
    <section className="card p-5">
      <h2 className="card-title mb-2">{label} 점검 시작</h2>
      <p className="mb-3 text-sm text-slate-600">
        기본 항목(현관·벽지·바닥·욕실·계량기 등)과 이 호실 자산대장의 품목으로 점검표를 만듭니다.
        {kind === "move_out" && (hasMoveIn ? " 입주 점검과 같은 항목·순서라 나란히 비교할 수 있습니다." : " 입주 점검 기록이 없어 비교는 못 하지만 퇴실 상태는 남길 수 있습니다.")}
      </p>
      {canWrite && <div className="flex flex-wrap gap-2">
        <input type="date" className="field" aria-label={`${label} 점검일`} value={day} onChange={(e) => setDay(e.target.value)} />
        <button type="button" className="btn-primary" disabled={busy}
          onClick={() => run(() => api(`/api/v1/leases/${leaseId}/inspections`, json("POST", { kind, inspected_on: day })), `${label} 점검표를 만들었습니다.`)}>
          <ClipboardCheck className="h-4 w-4" />{label} 점검 시작</button>
      </div>}
    </section>
  );
  const editable = canWrite && !insp.locked;
  return (
    <div className="space-y-4">
      <section className="card flex flex-wrap items-center gap-3 p-4 text-sm">
        <span><b>{label} 점검</b> {insp.inspected_on}</span>
        {insp.locked
          ? <span className="chip bg-blue-50 text-blue-700"><Lock className="h-3 w-3" />임차인 확인 {insp.tenant_confirmed_on}{insp.confirm_note ? ` · ${insp.confirm_note}` : ""}</span>
          : <span className="chip bg-amber-50 text-amber-800">임차인 확인 전</span>}
        {canWrite && <span className="ml-auto flex flex-wrap gap-2 print:hidden">
          {!insp.locked ? <>
            <button type="button" className="btn-primary btn-sm" disabled={busy} onClick={() => {
              const how = window.prompt("임차인과 함께 확인했나요? 확인 방법을 적어 주세요 (예: 현장 동행, 사진 문자 전송 후 동의)", "현장 동행");
              if (how !== null) run(() => api(`/api/v1/inspections/${insp.id}/confirm`, json("POST", { note: how })), "임차인 확인으로 잠갔습니다. 이제 고칠 수 없습니다.");
            }}><Check className="h-3.5 w-3.5" />임차인 확인 · 잠그기</button>
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => {
              if (window.confirm(`${label} 점검을 사진까지 모두 지울까요? 되돌릴 수 없습니다.`))
                run(() => api(`/api/v1/inspections/${insp.id}`, json("DELETE")), `${label} 점검을 지웠습니다.`);
            }}><Trash2 className="h-3.5 w-3.5" />점검 지우기</button>
          </> : (
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => {
              const why = window.prompt("확인을 풀면 다시 고칠 수 있습니다. 이유를 적어 주세요 (기록에 남습니다)");
              if (why !== null) run(() => api(`/api/v1/inspections/${insp.id}/unconfirm`, json("POST", { reason: why })), "확인을 풀었습니다.");
            }}><Unlock className="h-3.5 w-3.5" />확인 풀기</button>
          )}
        </span>}
      </section>
      <ul className="grid gap-3 lg:grid-cols-2 [&>*]:min-w-0">
        {insp.items.map((it) => <ItemCard key={it.id} it={it} codes={codes} editable={editable} busy={busy} run={run} />)}
      </ul>
      {editable && <div className="flex flex-wrap gap-2 print:hidden">
        <input className="field" aria-label="추가할 항목 이름" placeholder="예: 베란다 타일" value={newArea} onChange={(e) => setNewArea(e.target.value)} />
        <button type="button" className="btn-secondary" disabled={busy || !newArea.trim()}
          onClick={() => run(() => api(`/api/v1/inspections/${insp.id}/items`, json("POST", { area: newArea })), "항목을 더했습니다.").then(() => setNewArea(""))}>
          <Plus className="h-4 w-4" />항목 추가</button>
      </div>}
      <p className="text-xs text-slate-500 print:hidden">상태를 모르면 비워 두세요. 사진은 올린 시각이 함께 기록됩니다. 임차인과 확인한 뒤 잠그면 나중에 바뀌지 않아 분쟁 때 근거가 됩니다.</p>
    </div>
  );
}

function ItemCard({ it, codes, editable, busy, run }: { it: Item; codes: Codes; editable: boolean; busy: boolean;
  run: (fn: () => Promise<unknown>, ok: string | null) => Promise<void> }) {
  const [note, setNote] = useState(it.note ?? "");
  const [reading, setReading] = useState(it.reading ?? "");
  const save = (patch: Partial<Item>) => run(() => api(`/api/v1/inspection-items/${it.id}`, json("PUT", {
    condition: it.condition, reading: reading || null, note: note || null, ...patch })), null);
  async function upload(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      const small = await shrinkImage(f, { jpegOnly: true });
      const fd = new FormData(); fd.append("file", small);
      await run(() => api(`/api/v1/inspection-items/${it.id}/photos`, { method: "POST", body: fd }), "사진을 올렸습니다.");
    }
  }
  return (
    <li className="card break-inside-avoid p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <b className="text-sm">{it.area}</b>
        {it.condition && !editable && <span className={`chip ${TONE[it.condition]}`}>{codes.conditions[it.condition]}</span>}
      </div>
      {editable ? (
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={`${it.area} 상태`}>
          {Object.entries(codes.conditions).map(([k, v]) => (
            <button key={k} type="button" role="radio" aria-checked={it.condition === k} disabled={busy}
              onClick={() => save({ condition: it.condition === k ? null : k })}
              className={`chip border px-3 py-1.5 text-sm ${it.condition === k ? `${TONE[k]} border-current` : "border-slate-200 text-slate-600"}`}>{v}</button>
          ))}
        </div>
      ) : !it.condition && <p className="text-xs text-slate-500">상태 —</p>}
      {(isMeter(it.area) || it.reading) && (editable ? (
        <label className="mt-2 block text-xs text-slate-600">계량기 숫자
          <input className="field mt-1 w-40" inputMode="decimal" value={reading} onChange={(e) => setReading(e.target.value)}
            onBlur={() => reading !== (it.reading ?? "") && save({})} /></label>
      ) : <p className="mt-1 text-xs">계량기 {it.reading ?? "—"}</p>)}
      {editable ? (
        <input className="field mt-2 w-full text-sm" aria-label={`${it.area} 메모`} placeholder="메모 (예: 왼쪽 벽 긁힘 10cm)" value={note}
          onChange={(e) => setNote(e.target.value)} onBlur={() => note !== (it.note ?? "") && save({})} />
      ) : it.note && <p className="mt-1 text-xs text-slate-600">{it.note}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {it.photos.map((p) => <PhotoThumb key={p.id} p={p} canDelete={editable} busy={busy}
          onDelete={() => run(() => api(`/api/v1/inspection-photos/${p.id}`, json("DELETE")), "사진을 지웠습니다.")} />)}
        {editable && (
          <label className="grid h-20 w-20 cursor-pointer place-items-center rounded-xl border border-dashed border-slate-300 text-xs text-slate-500 hover:bg-slate-50 print:hidden">
            <span className="flex flex-col items-center"><Camera className="h-5 w-5" />사진</span>
            <input type="file" accept="image/*" capture="environment" multiple className="sr-only" aria-label={`${it.area} 사진 올리기`}
              disabled={busy} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
          </label>
        )}
      </div>
    </li>
  );
}

function PhotoThumb({ p, canDelete, busy, onDelete }: { p: Photo; canDelete: boolean; busy: boolean; onDelete: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    apiFetch(`/api/v1/inspection-photos/${p.id}`).then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b) { revoke = URL.createObjectURL(b); setUrl(revoke); } }).catch(() => {});
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [p.id]);
  return (
    <figure className="relative">
      <a href={url ?? undefined} target="_blank" rel="noreferrer">
        {url ? <img src={url} alt={`점검 사진 ${kst(p.uploaded_at)}`} className="h-20 w-20 rounded-xl border object-cover print:h-40 print:w-40" />
          : <span className="grid h-20 w-20 place-items-center rounded-xl border bg-slate-50 text-[10px] text-slate-400">불러오는 중</span>}
      </a>
      <figcaption className="mt-0.5 w-20 text-[10px] leading-tight text-slate-500">{kst(p.uploaded_at)}</figcaption>
      {canDelete && <button type="button" aria-label="사진 지우기" disabled={busy}
        onClick={() => window.confirm("이 사진을 지울까요?") && onDelete()}
        className="absolute -right-1.5 -top-1.5 grid h-6 w-6 place-items-center rounded-full bg-slate-800 text-white print:hidden"><X className="h-3.5 w-3.5" /></button>}
    </figure>
  );
}

function Compare({ a, b, codes }: { a: Insp | null; b: Insp | null; codes: Codes }) {
  const rows = useMemo(() => {
    const key = (i: Item) => `${i.area}|${i.fixture_id ?? ""}`;
    const out = new Map<string, { area: string; a?: Item; b?: Item }>();
    for (const i of a?.items ?? []) out.set(key(i), { area: i.area, a: i });
    for (const i of b?.items ?? []) out.set(key(i), { ...(out.get(key(i)) ?? { area: i.area }), b: i });
    return [...out.values()];
  }, [a, b]);
  if (!a || !b) return <div className="card p-6 text-sm text-slate-500">입주 점검과 퇴실 점검이 모두 있어야 비교할 수 있습니다.</div>;
  const worse = (r: { a?: Item; b?: Item }) => r.a?.condition && r.b?.condition && RANK[r.b.condition] > RANK[r.a.condition];
  const cell = (i?: Item) => !i ? <span className="text-slate-400">—</span> : (
    <div className="space-y-1">
      {i.condition ? <span className={`chip ${TONE[i.condition]}`}>{codes.conditions[i.condition]}</span> : <span className="text-slate-400">상태 —</span>}
      {i.reading && <div className="text-xs">계량기 {i.reading}</div>}
      {i.note && <div className="text-xs text-slate-600">{i.note}</div>}
      {i.photos.length > 0 && <div className="flex flex-wrap gap-1.5">{i.photos.map((p) => <PhotoThumb key={p.id} p={p} canDelete={false} busy={false} onDelete={() => {}} />)}</div>}
    </div>
  );
  return (
    <section className="card overflow-hidden">
      <p className="border-b border-slate-100 p-4 text-sm text-slate-600">입주 {a.inspected_on} ↔ 퇴실 {b.inspected_on}. 상태가 나빠진 항목을 표시합니다.
        생활하며 생긴 자연스러운 마모는 보통 임차인 부담이 아닙니다.</p>
      <ul className="divide-y divide-slate-100">
        {rows.map((r) => (
          <li key={r.area + (r.a?.id ?? r.b?.id)} className={`grid gap-3 p-4 text-sm sm:grid-cols-[10rem_1fr_1fr] ${worse(r) ? "bg-red-50/40" : ""}`}>
            <div className="font-semibold">{r.area}{worse(r) && <span className="chip ml-1 bg-red-100 text-red-700">나빠짐</span>}</div>
            <div><span className="mb-1 block text-xs text-slate-400 sm:hidden">입주</span>{cell(r.a)}</div>
            <div><span className="mb-1 block text-xs text-slate-400 sm:hidden">퇴실</span>{cell(r.b)}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SettlementView({ s, codes, leaseId, canWrite, busy, run, moveOut }: {
  s: Settlement; codes: Codes; leaseId: string; canWrite: boolean; busy: boolean; moveOut: Insp | null;
  run: (fn: () => Promise<unknown>, ok: string | null) => Promise<void> }) {
  const [d, setD] = useState({ category: "cleaning", label: "", amount: "", disputed: false, inspection_item_id: "", note: "" });
  const draft = s.status === "draft" && canWrite;
  const line = (label: string, v: number | null, sign: "+" | "−" | "", strong = false) => (
    <div className={`flex justify-between gap-3 py-1 ${strong ? "border-t border-slate-200 pt-2 text-base font-bold" : ""}`}>
      <span>{label}</span><span className="tabular-nums">{v == null ? "—" : `${v ? sign : ""}${won(v)}`}</span></div>);
  return (
    <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
      <section className="card p-5">
        <div className="mb-2 flex flex-wrap items-center gap-2"><Scale className="h-5 w-5 text-blue-600" /><h2 className="card-title">퇴실 정산서</h2>
          <span className={`chip ${s.status === "confirmed" ? "bg-blue-50 text-blue-700" : "bg-amber-50 text-amber-800"}`}>
            {s.status === "confirmed" ? `확정 ${kst(s.confirmed_at)}` : `작성 중 · ${s.as_of} 기준`}</span></div>
        <div className="text-sm">
          {line("돌려줄 보증금 (받은 금액 중 미반환)", s.deposit_unreturned, "")}
          {s.prepaid_credit > 0 && line("선납 잔액 (돌려줌)", s.prepaid_credit, "+")}
          {line("미납 월세 (납부일 지난 청구)", s.unpaid_total, "−")}
          {s.unpaid.map((u) => <div key={u.period} className="flex justify-between pl-3 text-xs text-slate-500"><span>{u.period} (납부일 {u.due_date})</span><span>{won(u.amount)}</span></div>)}
          {line("합의된 공제", s.agreed_deductions, "−")}
          {line("다툼 있는 공제 (따로 보관)", s.disputed_held, "−")}
          {s.return_now == null ? line("먼저 돌려줄 금액", null, "", true)
            : s.return_now >= 0 ? line("먼저 돌려줄 금액", s.return_now, "", true) : line("임차인에게 받을 금액", -s.return_now, "", true)}
          {s.disputed_held > 0 && <p className="mt-1 text-xs text-slate-600">다툼 있는 {won(s.disputed_held)}은 견적·감가를 맞춘 뒤 따로 정산합니다. 다툼 없는 금액은 먼저 돌려주는 것이 분쟁을 줄입니다.</p>}
          {s.note && <p className="mt-2 text-xs text-slate-600">메모: {s.note}</p>}
        </div>
        {s.warnings.length > 0 && <ul className="mt-3 space-y-1 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{s.warnings.map((w) => <li key={w}>• {w}</li>)}</ul>}
        <p className="mt-3 text-xs text-slate-500">실제로 돌려준 기록은 지출·운영비에서 은행 출금을 &lsquo;보증금 반환&rsquo;으로 확정할 때 남습니다. 은행 내역 {s.bank_data_as_of ? kst(s.bank_data_as_of) : "—"}까지.</p>
        {canWrite && <div className="mt-3 flex flex-wrap gap-2 print:hidden">
          {s.status === "draft" ? (
            <button type="button" className="btn-primary" disabled={busy || s.return_now == null} onClick={() => {
              const note = window.prompt("정산서를 확정합니다. 확정하면 숫자가 고정되고 공제 항목이 잠깁니다. 메모 (비워도 됨)");
              if (note !== null) run(() => api(`/api/v1/leases/${leaseId}/settlement/confirm`, json("POST", { note })), "정산서를 확정했습니다.");
            }}><Lock className="h-4 w-4" />정산서 확정</button>
          ) : (
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => {
              const why = window.prompt("확정을 풀면 다시 고칠 수 있습니다. 이유를 적어 주세요 (기록에 남습니다)");
              if (why !== null) run(() => api(`/api/v1/leases/${leaseId}/settlement/reopen`, json("POST", { reason: why })), "확정을 풀었습니다.");
            }}><Unlock className="h-4 w-4" />확정 풀기</button>
          )}
        </div>}
      </section>

      <section className="card p-5">
        <h2 className="card-title mb-2">공제 항목</h2>
        {s.deductions.length === 0 ? <p className="text-sm text-slate-500">공제 항목이 없습니다.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">{s.deductions.map((x) => (
            <li key={x.id} className="flex flex-wrap items-start gap-2 py-2">
              <span className="chip bg-slate-100 text-slate-700">{codes.deduction_categories[x.category]}</span>
              <span className="min-w-0 flex-1">{x.label}{x.inspection_item_area && <span className="text-xs text-slate-500"> · 근거: {x.inspection_item_area}</span>}
                {x.note && <span className="block text-xs text-slate-500">{x.note}</span>}</span>
              {x.disputed && <span className="chip bg-red-50 text-red-700">다툼</span>}
              <span className="tabular-nums">{won(x.amount)}</span>
              {draft && <button type="button" className="btn-secondary btn-sm print:hidden" aria-label={`${x.label} 지우기`} disabled={busy}
                onClick={() => window.confirm(`'${x.label}' 공제를 지울까요?`) && run(() => api(`/api/v1/settlement-deductions/${x.id}`, json("DELETE")), "공제 항목을 지웠습니다.")}>
                <Trash2 className="h-3.5 w-3.5" /></button>}
            </li>))}</ul>
        )}
        {draft && (
          <div className="mt-3 grid gap-2 border-t border-slate-100 pt-3 text-sm sm:grid-cols-2 print:hidden">
            <label className="block"><span className="mb-1 block font-medium text-slate-700">종류</span>
              <select className="field w-full" aria-label="공제 종류" value={d.category} onChange={(e) => setD({ ...d, category: e.target.value })}>
                {Object.entries(codes.deduction_categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="block"><span className="mb-1 block font-medium text-slate-700">금액 (원)</span>
              <input className="field w-full" inputMode="numeric" value={d.amount} onChange={(e) => setD({ ...d, amount: e.target.value.replace(/\D/g, "") })} /></label>
            <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">내용</span>
              <input className="field w-full" placeholder="예: 욕실 거울 파손 교체" value={d.label} onChange={(e) => setD({ ...d, label: e.target.value })} /></label>
            <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">근거 점검 항목 (퇴실 점검)</span>
              <select className="field w-full" aria-label="근거 점검 항목" value={d.inspection_item_id} onChange={(e) => setD({ ...d, inspection_item_id: e.target.value })}>
                <option value="">없음</option>
                {(moveOut?.items ?? []).map((i) => <option key={i.id} value={i.id}>{i.area}{i.condition ? ` (${codes.conditions[i.condition]})` : ""}</option>)}</select></label>
            <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">메모 (견적·감가 등)</span>
              <input className="field w-full" value={d.note} onChange={(e) => setD({ ...d, note: e.target.value })} /></label>
            <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" checked={d.disputed} onChange={(e) => setD({ ...d, disputed: e.target.checked })} />
              임차인과 다툼이 있는 금액 (먼저 돌려줄 금액에서 빼 따로 보관)</label>
            <button type="button" className="btn-primary sm:col-span-2" disabled={busy || !d.label.trim() || d.amount === ""}
              onClick={() => run(() => api(`/api/v1/leases/${leaseId}/settlement/deductions`, json("POST", {
                ...d, amount: Number(d.amount), inspection_item_id: d.inspection_item_id || null, note: d.note || null })), "공제 항목을 더했습니다.")
                .then(() => setD({ ...d, label: "", amount: "", note: "", disputed: false, inspection_item_id: "" }))}>
              <Plus className="h-4 w-4" />공제 항목 추가</button>
          </div>
        )}
      </section>
    </div>
  );
}
