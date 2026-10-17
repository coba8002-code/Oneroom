"use client";

import { Download, Package, PackageMinus, Pencil, Plus, Trash2, Wrench, CalendarRange, Check } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiFetch, todayKst, won, type UnitOut } from "@/lib/api";
import { useMe } from "@/lib/me";

interface Codes { categories: Record<string, string>; owners: Record<string, string>; payers: Record<string, string> }
interface Fixture {
  id: string; unit_id: string | null; unit_no: string | null; category: string; category_label: string; name: string;
  brand: string | null; model: string | null; manufactured: string | null; installed_on: string | null; price: number | null;
  warranty_until: string | null; warranty_active: boolean | null; owner: "landlord" | "tenant"; replace_by: string | null;
  status: "in_use" | "removed"; removed_on: string | null; removed_reason: string | null; note: string | null;
  age_months: number | null; repair_count: number; repair_cost: number | null;
}
interface Repair {
  id: string; unit_id: string | null; unit_no: string | null; fixture_id: string | null; fixture_name: string | null;
  description: string; reported_on: string; status: "open" | "done"; completed_on: string | null; vendor: string | null;
  cost: number | null; payer: "landlord" | "tenant" | "undecided"; note: string | null;
}
interface Plan {
  from: string; to: string; unplanned: number; warranty_ending: Fixture[];
  groups: { month: string; category: string; category_label: string; count: number; units: string[]; models: string[] }[];
}
type Tab = "fixtures" | "repairs" | "plan";
const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const age = (m: number | null) => (m == null ? "—" : m < 12 ? `${m}개월` : `${Math.floor(m / 12)}년${m % 12 ? ` ${m % 12}개월` : ""}`);
const where = (unitNo: string | null) => (unitNo ? `${unitNo}호` : "건물 공용");
const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/[^\d]/g, "")));

export default function AssetsPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const orgId = me?.organization.id;
  const [tab, setTab] = useState<Tab>("fixtures");
  const [codes, setCodes] = useState<Codes | null>(null);
  const [units, setUnits] = useState<UnitOut[]>([]);
  const [items, setItems] = useState<Fixture[] | null>(null);
  const [repairs, setRepairs] = useState<Repair[] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [showRemoved, setShowRemoved] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Fixture | "new" | null>(null);
  const [repairing, setRepairing] = useState<Repair | { fixture?: Fixture } | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      const [c, u, f, r, p] = await Promise.all([
        api<Codes>("/api/v1/fixture-codes"), api<UnitOut[]>(`/api/v1/units?organization_id=${orgId}`),
        api<Fixture[]>(`/api/v1/fixtures?include_removed=${showRemoved}`), api<Repair[]>("/api/v1/repairs"),
        api<Plan>("/api/v1/fixtures/replacement-plan"),
      ]);
      setCodes(c); setUnits(u); setItems(f); setRepairs(r); setPlan(p);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, [orgId, showRemoved]);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string, after?: () => void) {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); after?.(); await load(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  async function download() {
    try {
      const res = await apiFetch("/api/v1/fixtures/export.csv");
      if (!res.ok) throw new Error("내려받지 못했습니다");
      const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "roomax-assets.csv";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await res.blob()); a.download = name; a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }

  const openRepairs = repairs?.filter((r) => r.status === "open").length ?? 0;
  const TABS: [Tab, string, number | null][] = [
    ["fixtures", "자산대장", items?.filter((i) => i.status === "in_use").length ?? null],
    ["repairs", "수리 이력", openRepairs || null], ["plan", "교체 계획", null]];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">자산·수리</h1>
          <p className="page-sub">호실 옵션·집기와 건물 공용 설비, 수리 기록을 한곳에. 옵션과 임차인 소유를 나눠 두면 퇴실·수리 책임 다툼이 줄어듭니다.</p>
        </div>
        <button type="button" className="btn-secondary" onClick={download}><Download className="h-4 w-4" />엑셀(CSV) 내려받기</button>
      </header>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="자산·수리">
        {TABS.map(([t, label, n]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>
            {label}{n != null ? ` ${n}` : ""}
          </button>
        ))}
      </div>

      {msg && <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}

      {codes && tab === "fixtures" && (
        <>
          {canWrite && editing === null && (
            <button type="button" className="btn-primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />품목 추가</button>
          )}
          {editing && <FixtureForm codes={codes} units={units} initial={editing === "new" ? null : editing} busy={busy}
            onCancel={() => setEditing(null)}
            onSave={(body, id) => run(() => api(id ? `/api/v1/fixtures/${id}` : "/api/v1/fixtures", json(id ? "PUT" : "POST", body)),
              id ? "품목을 고쳤습니다." : "품목을 추가했습니다.", () => setEditing(null))} />}
          {repairing && <RepairForm codes={codes} units={units} fixtures={items ?? []} initial={repairing} busy={busy}
            onCancel={() => setRepairing(null)}
            onSave={(body, id) => run(() => api(id ? `/api/v1/repairs/${id}` : "/api/v1/repairs", json(id ? "PUT" : "POST", body)),
              "수리 기록을 저장했습니다.", () => setRepairing(null))} />}
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} />뺀 품목도 보기
          </label>
          <FixtureList items={items} codes={codes} canWrite={canWrite} busy={busy}
            onEdit={(f) => { setRepairing(null); setEditing(f); }}
            onRepair={(f) => { setEditing(null); setRepairing({ fixture: f }); }}
            onRemove={(f, reason) => run(() => api(`/api/v1/fixtures/${f.id}/remove`, json("POST", { reason })), `${where(f.unit_no)} ${f.name}을(를) 뺐습니다.`)}
            onDelete={(f) => run(() => api(`/api/v1/fixtures/${f.id}`, json("DELETE")), `${where(f.unit_no)} ${f.name}을(를) 지웠습니다.`)} />
        </>
      )}

      {codes && tab === "repairs" && (
        <>
          {canWrite && repairing === null && (
            <button type="button" className="btn-primary" onClick={() => setRepairing({})}><Wrench className="h-4 w-4" />수리 기록 추가</button>
          )}
          {repairing && <RepairForm codes={codes} units={units} fixtures={items ?? []} initial={repairing} busy={busy}
            onCancel={() => setRepairing(null)}
            onSave={(body, id) => run(() => api(id ? `/api/v1/repairs/${id}` : "/api/v1/repairs", json(id ? "PUT" : "POST", body)),
              "수리 기록을 저장했습니다.", () => setRepairing(null))} />}
          <RepairList repairs={repairs} codes={codes} canWrite={canWrite} busy={busy} onEdit={(r) => setRepairing(r)}
            onDone={(r) => run(() => api(`/api/v1/repairs/${r.id}`, json("PUT", { ...repairBody(r), completed_on: todayKst() })), "완료로 표시했습니다.")}
            onDelete={(r) => run(() => api(`/api/v1/repairs/${r.id}`, json("DELETE")), "수리 기록을 지웠습니다.")} />
          <p className="text-xs text-slate-500">여기 적는 수리비는 기록용입니다. 월 결산(순운영수익)에는 은행 출금을 &lsquo;수리비&rsquo;로 분류한 금액만 들어갑니다.</p>
        </>
      )}

      {tab === "plan" && <PlanView plan={plan} />}
    </div>
  );
}

const repairBody = (r: Repair) => ({ description: r.description, reported_on: r.reported_on, unit_id: r.unit_id,
  fixture_id: r.fixture_id, vendor: r.vendor, cost: r.cost, payer: r.payer, completed_on: r.completed_on, note: r.note });

function FixtureForm({ codes, units, initial, busy, onSave, onCancel }: {
  codes: Codes; units: UnitOut[]; initial: Fixture | null; busy: boolean;
  onSave: (body: Record<string, unknown>, id?: string) => void; onCancel: () => void }) {
  const [f, setF] = useState({
    category: initial?.category ?? "aircon", name: initial?.name ?? "", brand: initial?.brand ?? "", model: initial?.model ?? "",
    manufactured: initial?.manufactured ?? "", installed_on: initial?.installed_on ?? "", price: initial?.price?.toString() ?? "",
    warranty_until: initial?.warranty_until ?? "", owner: initial?.owner ?? "landlord", replace_by: initial?.replace_by ?? "",
    note: initial?.note ?? "" });
  const [picked, setPicked] = useState<string[]>(initial?.unit_id ? [initial.unit_id] : []);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });
  const body = { ...f, name: f.name || null, brand: f.brand || null, model: f.model || null, manufactured: f.manufactured || null,
    installed_on: f.installed_on || null, price: num(f.price), warranty_until: f.warranty_until || null,
    replace_by: f.replace_by || null, note: f.note || null };
  const toggle = (id: string) => setPicked(initial ? [id] : picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center gap-2"><Package className="h-5 w-5 text-blue-600" />
        <h2 className="card-title">{initial ? `${where(initial.unit_no)} ${initial.name} 고치기` : "품목 추가"}</h2></div>
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <label className="block"><span className="mb-1 block font-medium text-slate-700">종류</span>
          <select className="field w-full" aria-label="종류" value={f.category} onChange={set("category")}>
            {Object.entries(codes.categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">이름 (비우면 종류 이름)</span>
          <input className="field w-full" value={f.name} onChange={set("name")} placeholder={codes.categories[f.category]} /></label>
        <fieldset className="sm:col-span-2">
          <legend className="mb-1 font-medium text-slate-700">{initial ? "위치" : "위치 — 여러 호실을 고르면 같은 품목을 한 번에 넣습니다 (안 고르면 건물 공용)"}</legend>
          <div className="flex flex-wrap gap-1.5">
            <button type="button" aria-pressed={picked.length === 0} onClick={() => setPicked([])}
              className={`chip border px-3 py-1.5 text-sm ${picked.length === 0 ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-600"}`}>건물 공용</button>
            {units.map((u) => (
              <button key={u.unit_id} type="button" aria-pressed={picked.includes(u.unit_id)} onClick={() => toggle(u.unit_id)}
                className={`chip border px-3 py-1.5 text-sm ${picked.includes(u.unit_id) ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-600"}`}>{u.unit_no}호</button>
            ))}
          </div>
        </fieldset>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">제조사</span>
          <input className="field w-full" value={f.brand} onChange={set("brand")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">모델명</span>
          <input className="field w-full" value={f.model} onChange={set("model")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">제조연월 (제품 명판)</span>
          <input type="month" className="field w-full" value={f.manufactured} onChange={set("manufactured")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">설치·구입일</span>
          <input type="date" className="field w-full" value={f.installed_on} onChange={set("installed_on")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">구입가 (원)</span>
          <input className="field w-full" inputMode="numeric" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value.replace(/\D/g, "") })} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">무상 보증 만료일</span>
          <input type="date" className="field w-full" value={f.warranty_until} onChange={set("warranty_until")} /></label>
        <fieldset><legend className="mb-1 font-medium text-slate-700">소유</legend>
          <div className="flex gap-3">{Object.entries(codes.owners).map(([k, v]) => (
            <label key={k} className="flex items-center gap-1"><input type="radio" name="owner" value={k} checked={f.owner === k} onChange={set("owner")} />{v}</label>))}</div>
        </fieldset>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">교체 예정월 (직접 정함)</span>
          <input type="month" className="field w-full" value={f.replace_by} onChange={set("replace_by")} /></label>
        <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">메모</span>
          <textarea className="field min-h-16 w-full" value={f.note} onChange={set("note")} /></label>
      </div>
      <p className="mt-2 text-xs text-slate-500">모르는 칸은 비워 두세요. 비운 값은 &lsquo;—&rsquo;로 보이고 추정해서 채우지 않습니다.</p>
      <div className="mt-3 flex gap-2">
        <button type="button" className="btn-primary" disabled={busy}
          onClick={() => onSave(initial ? { ...body, unit_id: picked[0] ?? null } : { ...body, unit_ids: picked }, initial?.id)}>
          {initial ? "저장" : picked.length > 1 ? `${picked.length}개 호실에 추가` : "추가"}</button>
        <button type="button" className="btn-secondary" onClick={onCancel}>취소</button>
      </div>
    </section>
  );
}

function FixtureList({ items, codes, canWrite, busy, onEdit, onRepair, onRemove, onDelete }: {
  items: Fixture[] | null; codes: Codes; canWrite: boolean; busy: boolean; onEdit: (f: Fixture) => void;
  onRepair: (f: Fixture) => void; onRemove: (f: Fixture, reason: string) => void; onDelete: (f: Fixture) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, Fixture[]>();
    for (const f of items ?? []) m.set(where(f.unit_no), [...(m.get(where(f.unit_no)) ?? []), f]);
    return [...m.entries()];
  }, [items]);
  if (items === null) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  if (items.length === 0) return (
    <div className="card p-6 text-center text-sm text-slate-500">
      아직 등록한 품목이 없습니다. 에어컨·세탁기·냉장고처럼 호실마다 같은 옵션은 &lsquo;품목 추가&rsquo;에서 여러 호실을 골라 한 번에 넣으세요.
    </div>);
  return (
    <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
      {groups.map(([place, fs]) => (
        <section key={place} className="card p-4">
          <h2 className="card-title mb-2">{place} <span className="text-sm font-normal text-slate-500">{fs.length}개</span></h2>
          <ul className="divide-y divide-slate-100">
            {fs.map((f) => (
              <li key={f.id} className={`py-2.5 ${f.status === "removed" ? "opacity-60" : ""}`}>
                <div className="flex flex-wrap items-center gap-1.5 text-sm">
                  <b>{f.name}</b>
                  {f.name !== f.category_label && <span className="text-xs text-slate-500">{f.category_label}</span>}
                  {f.owner === "tenant" && <span className="chip bg-amber-50 text-amber-800">{codes.owners.tenant}</span>}
                  {f.status === "removed" && <span className="chip bg-slate-100 text-slate-600">뺌 {f.removed_on}</span>}
                  {f.warranty_active && <span className="chip bg-emerald-50 text-emerald-700">보증 ~{f.warranty_until}</span>}
                </div>
                <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-slate-600 sm:grid-cols-3">
                  <div><dt className="inline text-slate-400">모델 </dt><dd className="inline">{[f.brand, f.model].filter(Boolean).join(" ") || "—"}</dd></div>
                  <div><dt className="inline text-slate-400">제조 </dt><dd className="inline">{f.manufactured ?? "—"}</dd></div>
                  <div><dt className="inline text-slate-400">경과 </dt><dd className="inline">{age(f.age_months)}</dd></div>
                  <div><dt className="inline text-slate-400">구입가 </dt><dd className="inline">{won(f.price)}</dd></div>
                  <div><dt className="inline text-slate-400">교체 예정 </dt><dd className="inline">{f.replace_by ?? "—"}</dd></div>
                  <div><dt className="inline text-slate-400">수리 </dt><dd className="inline">{f.repair_count}건{f.repair_count ? ` · ${won(f.repair_cost)}` : ""}</dd></div>
                </dl>
                {(f.note || f.removed_reason) && <p className="mt-1 text-xs text-slate-500">{f.removed_reason ?? f.note}</p>}
                {canWrite && f.status === "in_use" && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <button type="button" className="btn-secondary btn-sm" onClick={() => onRepair(f)}><Wrench className="h-3.5 w-3.5" />수리 기록</button>
                    <button type="button" className="btn-secondary btn-sm" onClick={() => onEdit(f)}><Pencil className="h-3.5 w-3.5" />고치기</button>
                    <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => {
                      const reason = window.prompt(`${where(f.unit_no)} ${f.name}을(를) 뺍니다 (교체·폐기·철거). 이유를 적어 주세요 (비워도 됨)`);
                      if (reason !== null) onRemove(f, reason);
                    }}><PackageMinus className="h-3.5 w-3.5" />빼기</button>
                    {f.repair_count === 0 && <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => {
                      if (window.confirm(`${where(f.unit_no)} ${f.name} 기록을 지울까요? 잘못 넣은 품목만 지우세요. 교체·폐기는 '빼기'를 쓰면 기록이 남습니다.`)) onDelete(f);
                    }}><Trash2 className="h-3.5 w-3.5" />지우기</button>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function RepairForm({ codes, units, fixtures, initial, busy, onSave, onCancel }: {
  codes: Codes; units: UnitOut[]; fixtures: Fixture[]; initial: Repair | { fixture?: Fixture }; busy: boolean;
  onSave: (body: Record<string, unknown>, id?: string) => void; onCancel: () => void }) {
  const rep = "id" in initial ? initial : null;
  const fx = "fixture" in initial ? initial.fixture : undefined;
  const [r, setR] = useState({
    unit_id: rep?.unit_id ?? fx?.unit_id ?? "", fixture_id: rep?.fixture_id ?? fx?.id ?? "", reported_on: rep?.reported_on ?? todayKst(),
    description: rep?.description ?? "", vendor: rep?.vendor ?? "", cost: rep?.cost?.toString() ?? "", payer: rep?.payer ?? "undecided",
    completed_on: rep?.completed_on ?? "", note: rep?.note ?? "" });
  const set = (k: keyof typeof r) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setR({ ...r, [k]: e.target.value });
  const choices = fixtures.filter((f) => f.status === "in_use" && (f.unit_id ?? "") === r.unit_id);
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center gap-2"><Wrench className="h-5 w-5 text-blue-600" />
        <h2 className="card-title">{rep ? "수리 기록 고치기" : "수리 기록 추가"}</h2></div>
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <label className="block"><span className="mb-1 block font-medium text-slate-700">위치</span>
          <select className="field w-full" aria-label="위치" value={r.unit_id} onChange={(e) => setR({ ...r, unit_id: e.target.value, fixture_id: "" })}>
            <option value="">건물 공용</option>{units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_no}호</option>)}</select></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">품목 (선택)</span>
          <select className="field w-full" aria-label="품목 (선택)" value={r.fixture_id} onChange={set("fixture_id")}>
            <option value="">품목과 상관없음 (누수·도배 등)</option>
            {choices.map((f) => <option key={f.id} value={f.id}>{f.name}{f.model ? ` (${f.model})` : ""}</option>)}</select></label>
        <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">무엇을 고치나요</span>
          <input className="field w-full" value={r.description} onChange={set("description")} placeholder="예: 에어컨 냉매 보충, 화장실 누수" /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">접수일</span>
          <input type="date" className="field w-full" value={r.reported_on} onChange={set("reported_on")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">완료일 (끝났으면)</span>
          <input type="date" className="field w-full" value={r.completed_on} onChange={set("completed_on")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">업체</span>
          <input className="field w-full" value={r.vendor} onChange={set("vendor")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">비용 (원)</span>
          <input className="field w-full" inputMode="numeric" value={r.cost} onChange={(e) => setR({ ...r, cost: e.target.value.replace(/\D/g, "") })} /></label>
        <fieldset className="sm:col-span-2"><legend className="mb-1 font-medium text-slate-700">비용 부담</legend>
          <div className="flex flex-wrap gap-3">{Object.entries(codes.payers).map(([k, v]) => (
            <label key={k} className="flex items-center gap-1"><input type="radio" name="payer" value={k} checked={r.payer === k} onChange={set("payer")} />{v}</label>))}</div>
          <p className="mt-1 text-xs text-slate-500">옵션의 자연 노후 고장은 보통 임대인, 임차인 과실(파손·관리 소홀)이면 임차인 — 계약서 특약이 있으면 그에 따릅니다.</p>
        </fieldset>
        <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">메모</span>
          <textarea className="field min-h-16 w-full" value={r.note} onChange={set("note")} /></label>
      </div>
      <div className="mt-3 flex gap-2">
        <button type="button" className="btn-primary" disabled={busy || !r.description.trim()} onClick={() => onSave({
          ...r, unit_id: r.unit_id || null, fixture_id: r.fixture_id || null, vendor: r.vendor || null, cost: num(r.cost),
          completed_on: r.completed_on || null, note: r.note || null }, rep?.id)}>저장</button>
        <button type="button" className="btn-secondary" onClick={onCancel}>취소</button>
      </div>
    </section>
  );
}

function RepairList({ repairs, codes, canWrite, busy, onEdit, onDone, onDelete }: {
  repairs: Repair[] | null; codes: Codes; canWrite: boolean; busy: boolean;
  onEdit: (r: Repair) => void; onDone: (r: Repair) => void; onDelete: (r: Repair) => void }) {
  if (repairs === null) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  if (repairs.length === 0) return <div className="card p-6 text-center text-sm text-slate-500">수리 기록이 없습니다. 고장 신고를 받으면 바로 적어 두세요.</div>;
  return (
    <ul className="space-y-3">
      {repairs.map((r) => (
        <li key={r.id} className="card p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className={`chip ${r.status === "open" ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>
              {r.status === "open" ? "진행 중" : `완료 ${r.completed_on}`}</span>
            <b>{where(r.unit_no)}</b>{r.fixture_name && <span className="text-slate-500">{r.fixture_name}</span>}
            <span className="ml-auto text-xs text-slate-500">접수 {r.reported_on}</span>
          </div>
          <p className="mt-1 text-sm">{r.description}</p>
          <p className="mt-1 text-xs text-slate-600">업체 {r.vendor ?? "—"} · 비용 {won(r.cost)} · 부담 {codes.payers[r.payer]}</p>
          {r.note && <p className="mt-1 text-xs text-slate-500">{r.note}</p>}
          {canWrite && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {r.status === "open" && <button type="button" className="btn-primary btn-sm" disabled={busy} onClick={() => onDone(r)}><Check className="h-3.5 w-3.5" />오늘 완료</button>}
              <button type="button" className="btn-secondary btn-sm" onClick={() => onEdit(r)}><Pencil className="h-3.5 w-3.5" />고치기</button>
              <button type="button" className="btn-secondary btn-sm" disabled={busy}
                onClick={() => window.confirm(`${where(r.unit_no)} '${r.description}' 기록을 지울까요?`) && onDelete(r)}><Trash2 className="h-3.5 w-3.5" />지우기</button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function PlanView({ plan }: { plan: Plan | null }) {
  if (plan === null) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  return (
    <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
      <section className="card p-5">
        <div className="mb-2 flex items-center gap-2"><CalendarRange className="h-5 w-5 text-blue-600" />
          <h2 className="card-title">교체 예정 ({plan.from} ~ {plan.to})</h2></div>
        {plan.groups.length === 0 ? (
          <p className="text-sm text-slate-500">교체 예정월을 적은 옵션 품목이 없습니다. 자산대장에서 품목을 고쳐 교체 예정월을 정하세요.</p>
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {plan.groups.map((g) => (
              <li key={g.month + g.category} className="py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`chip ${g.month === "overdue" ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-700"}`}>
                    {g.month === "overdue" ? "예정월 지남" : g.month}</span>
                  <b>{g.category_label} {g.count}대</b>
                  {g.count > 1 && <span className="chip bg-blue-50 text-blue-700">함께 구매 검토</span>}
                </div>
                <p className="mt-0.5 text-xs text-slate-600">{g.units.map((u) => (u === "공용" ? u : `${u}호`)).join(", ")}
                  {g.models.length ? ` · 지금 모델 ${g.models.join(", ")}` : ""}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-slate-500">옵션(임대인 소유) 품목만, 관리자가 정한 교체 예정월로 묶습니다. 교체 예정월이 없는 옵션 {plan.unplanned}개.
          같은 달 같은 품목이 여럿이면 한 번에 사면 배송·설치비를 줄일 수 있습니다.</p>
      </section>
      <section className="card p-5">
        <h2 className="card-title mb-2">60일 안에 무상 보증이 끝나는 품목</h2>
        {plan.warranty_ending.length === 0 ? <p className="text-sm text-slate-500">없습니다.</p> : (
          <ul className="space-y-1 text-sm">{plan.warranty_ending.map((f) => (
            <li key={f.id}>{where(f.unit_no)} {f.name} — 보증 {f.warranty_until}까지 <span className="text-xs text-slate-500">(고장이 있으면 그 전에 무상 수리 요청)</span></li>))}</ul>
        )}
      </section>
    </div>
  );
}
