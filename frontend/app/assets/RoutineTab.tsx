"use client";

import { CalendarCheck, Check, History, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, todayKst, won, type UnitOut } from "@/lib/api";

interface Codes { categories: Record<string, string>; suggestions: { title: string; category: string }[]; soon_days: number }
type State = "overdue" | "soon" | "no_date" | "ok" | "finished" | "stopped";
export interface RoutineTask {
  id: string; title: string; category: string; unit_id: string | null; unit_no: string | null; fixture_id: string | null;
  fixture_name: string | null; interval_months: number | null; next_due_on: string | null; days_left: number | null;
  last_done_on: string | null; done_count: number; vendor: string | null; note: string | null; status: "active" | "stopped";
  state: State; cost_total: number | null;
}
interface Log { id: string; done_on: string; cost: number | null; vendor: string | null; note: string | null }
interface FixtureLite { id: string; unit_id: string | null; name: string; model: string | null; status: string }

const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
const where = (unitNo: string | null) => (unitNo ? `${unitNo}호` : "건물 공용");
const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/[^\d]/g, "")));

function chip(t: RoutineTask): [string, string] {
  switch (t.state) {
    case "overdue": return [`${-(t.days_left ?? 0)}일 지남`, "bg-red-50 text-red-700"];
    case "soon": return [t.days_left === 0 ? "오늘" : `D-${t.days_left}`, "bg-amber-50 text-amber-800"];
    case "no_date": return ["예정일 없음", "bg-slate-100 text-slate-600"];
    case "ok": return [`D-${t.days_left}`, "bg-emerald-50 text-emerald-700"];
    case "finished": return ["끝남", "bg-slate-100 text-slate-600"];
    default: return ["멈춤", "bg-slate-100 text-slate-500"];
  }
}

export default function RoutineTab({ units, fixtures, canWrite, onCount }: {
  units: UnitOut[]; fixtures: FixtureLite[]; canWrite: boolean; onCount: (n: number) => void }) {
  const [codes, setCodes] = useState<Codes | null>(null);
  const [tasks, setTasks] = useState<RoutineTask[] | null>(null);
  const [showStopped, setShowStopped] = useState(false);
  const [editing, setEditing] = useState<RoutineTask | "new" | null>(null);
  const [doing, setDoing] = useState<string | null>(null);
  const [history, setHistory] = useState<{ id: string; logs: Log[] } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, t] = await Promise.all([api<Codes>("/api/v1/routine-codes"),
        api<RoutineTask[]>(`/api/v1/routine-tasks?include_stopped=${showStopped}`)]);
      setCodes(c); setTasks(t);
      onCount(t.filter((x) => x.state === "overdue" || x.state === "soon").length);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, [showStopped, onCount]);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string, after?: () => void) {
    setBusy(true); setMsg(null);
    try { await fn(); after?.(); await load(); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  async function openHistory(t: RoutineTask) {
    if (history?.id === t.id) { setHistory(null); return; }
    try { setHistory({ id: t.id, logs: await api<Log[]>(`/api/v1/routine-tasks/${t.id}/logs`) }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }

  if (!codes) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  return (
    <div className="space-y-4">
      {msg && <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}
      {canWrite && editing === null && (
        <button type="button" className="btn-primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />할 일 추가</button>
      )}
      {editing && <TaskForm codes={codes} units={units} fixtures={fixtures} initial={editing === "new" ? null : editing} busy={busy}
        onCancel={() => setEditing(null)}
        onSave={(body, id) => run(() => api(id ? `/api/v1/routine-tasks/${id}` : "/api/v1/routine-tasks", json(id ? "PUT" : "POST", body)),
          id ? "고쳤습니다." : "추가했습니다.", () => setEditing(null))} />}
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" checked={showStopped} onChange={(e) => setShowStopped(e.target.checked)} />멈춘 일도 보기
      </label>

      {tasks && tasks.length === 0 ? (
        <div className="card p-6 text-center text-sm text-slate-500">
          정기적으로 챙길 일이 없습니다. 소화기 점검·정화조 청소·보험 갱신처럼 반복되는 일을 넣어 두면 예정일 전에 홈에 알려 드립니다.
        </div>
      ) : (
        <ul className="space-y-3">
          {tasks?.map((t) => {
            const [label, tone] = chip(t);
            return (
              <li key={t.id} className="card p-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className={`chip ${tone}`}>{label}</span>
                  <b>{t.title}</b>
                  <span className="text-slate-500">{where(t.unit_no)}{t.fixture_name ? ` · ${t.fixture_name}` : ""}</span>
                  <span className="ml-auto text-xs text-slate-500">{codes.categories[t.category]}</span>
                </div>
                <p className="mt-1 text-xs text-slate-600 tabular-nums">
                  {t.interval_months ? `${t.interval_months}개월마다` : "한 번"} · 다음 {t.next_due_on ?? "—"} · 마지막 {t.last_done_on ?? "—"}
                  {t.done_count > 0 && ` (${t.done_count}회, 비용 ${won(t.cost_total)})`}{t.vendor && ` · 업체 ${t.vendor}`}
                </p>
                {t.note && <p className="mt-1 text-xs text-slate-500">{t.note}</p>}
                {canWrite && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {t.status === "active" && t.state !== "finished" &&
                      <button type="button" className="btn-primary btn-sm" onClick={() => setDoing(doing === t.id ? null : t.id)}><Check className="h-3.5 w-3.5" />했음 기록</button>}
                    <button type="button" className="btn-secondary btn-sm" onClick={() => openHistory(t)}><History className="h-3.5 w-3.5" />기록 {t.done_count}</button>
                    <button type="button" className="btn-secondary btn-sm" onClick={() => setEditing(t)}><Pencil className="h-3.5 w-3.5" />고치기</button>
                    <button type="button" className="btn-secondary btn-sm" disabled={busy}
                      onClick={() => run(() => api(`/api/v1/routine-tasks/${t.id}/status`, json("POST", { status: t.status === "active" ? "stopped" : "active" })),
                        t.status === "active" ? `'${t.title}'을(를) 멈췄습니다.` : `'${t.title}'을(를) 다시 시작했습니다.`)}>
                      {t.status === "active" ? <><Pause className="h-3.5 w-3.5" />멈춤</> : <><Play className="h-3.5 w-3.5" />다시</>}</button>
                    {t.done_count === 0 && <button type="button" className="btn-secondary btn-sm" disabled={busy}
                      onClick={() => window.confirm(`'${t.title}'을(를) 지울까요?`) && run(() => api(`/api/v1/routine-tasks/${t.id}`, json("DELETE")), "지웠습니다.")}>
                      <Trash2 className="h-3.5 w-3.5" />지우기</button>}
                  </div>
                )}
                {doing === t.id && <DoneForm task={t} busy={busy} onCancel={() => setDoing(null)}
                  onSave={(body) => run(() => api(`/api/v1/routine-tasks/${t.id}/done`, json("POST", body)),
                    t.interval_months ? `기록했습니다. 다음 예정일을 ${t.interval_months}개월 뒤로 옮겼습니다.` : "기록했습니다.",
                    () => { setDoing(null); setHistory(null); })} />}
                {history?.id === t.id && (
                  <div className="mt-2 rounded-xl bg-slate-50 p-3 text-xs">
                    {history.logs.length === 0 ? <p className="text-slate-500">아직 한 기록이 없습니다.</p> : (
                      <ul className="divide-y divide-slate-200">{history.logs.map((g, i) => (
                        <li key={g.id} className="flex flex-wrap items-center gap-2 py-1.5 tabular-nums">
                          <b>{g.done_on}</b><span>{won(g.cost)}</span>{g.vendor && <span>{g.vendor}</span>}{g.note && <span className="text-slate-500">{g.note}</span>}
                          {canWrite && i === 0 && <button type="button" className="ml-auto text-red-700 hover:underline" disabled={busy}
                            onClick={() => window.confirm(`${g.done_on} 기록을 지우고 예정일을 그 전으로 되돌릴까요?`) &&
                              run(() => api(`/api/v1/routine-logs/${g.id}`, json("DELETE")), "기록을 지우고 예정일을 되돌렸습니다.", () => setHistory(null))}>
                            지우기</button>}
                        </li>))}</ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-xs text-slate-500">주기와 예정일은 직접 정한 값만 씁니다 — 소방·정화조 등 법정 주기는 관할 기관 안내나 업체 계약으로 확인해 적으세요.
        예정일이 지났거나 {codes.soon_days}일 안이면 홈 &lsquo;확인 필요&rsquo;에 뜹니다. 비용은 기록용이고, 월 결산에는 은행 출금 분류만 들어갑니다.</p>
    </div>
  );
}

function DoneForm({ task, busy, onSave, onCancel }: { task: RoutineTask; busy: boolean;
  onSave: (body: Record<string, unknown>) => void; onCancel: () => void }) {
  const [d, setD] = useState({ done_on: todayKst(), cost: "", vendor: task.vendor ?? "", note: "" });
  return (
    <div className="mt-2 grid gap-2 rounded-xl border border-blue-100 bg-blue-50/50 p-3 text-sm sm:grid-cols-4">
      <label className="block"><span className="mb-1 block text-xs font-medium text-slate-700">한 날</span>
        <input type="date" className="field w-full" max={todayKst()} value={d.done_on} onChange={(e) => setD({ ...d, done_on: e.target.value })} /></label>
      <label className="block"><span className="mb-1 block text-xs font-medium text-slate-700">비용 (원, 모르면 비움)</span>
        <input className="field w-full" inputMode="numeric" value={d.cost} onChange={(e) => setD({ ...d, cost: e.target.value.replace(/\D/g, "") })} /></label>
      <label className="block"><span className="mb-1 block text-xs font-medium text-slate-700">업체</span>
        <input className="field w-full" value={d.vendor} onChange={(e) => setD({ ...d, vendor: e.target.value })} /></label>
      <label className="block"><span className="mb-1 block text-xs font-medium text-slate-700">메모</span>
        <input className="field w-full" value={d.note} onChange={(e) => setD({ ...d, note: e.target.value })} /></label>
      <div className="flex gap-2 sm:col-span-4">
        <button type="button" className="btn-primary btn-sm" disabled={busy || !d.done_on}
          onClick={() => onSave({ done_on: d.done_on, cost: num(d.cost), vendor: d.vendor || null, note: d.note || null })}>저장</button>
        <button type="button" className="btn-secondary btn-sm" onClick={onCancel}>취소</button>
      </div>
    </div>
  );
}

function TaskForm({ codes, units, fixtures, initial, busy, onSave, onCancel }: {
  codes: Codes; units: UnitOut[]; fixtures: FixtureLite[]; initial: RoutineTask | null; busy: boolean;
  onSave: (body: Record<string, unknown>, id?: string) => void; onCancel: () => void }) {
  const [t, setT] = useState({
    title: initial?.title ?? "", category: initial?.category ?? "safety", interval: initial?.interval_months?.toString() ?? "",
    next_due_on: initial?.next_due_on ?? "", vendor: initial?.vendor ?? "", note: initial?.note ?? "",
    unit_id: initial?.unit_id ?? "", fixture_id: initial?.fixture_id ?? "" });
  const [unitIds, setUnitIds] = useState<string[]>([]);
  const set = (k: keyof typeof t) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setT({ ...t, [k]: e.target.value });
  const placeUnit = initial ? t.unit_id : unitIds.length === 1 ? unitIds[0] : "";
  const choices = fixtures.filter((f) => f.status === "in_use" && (f.unit_id ?? "") === placeUnit && (initial || unitIds.length <= 1));
  const common = { title: t.title, category: t.category, interval_months: num(t.interval), next_due_on: t.next_due_on || null,
    vendor: t.vendor || null, note: t.note || null, fixture_id: t.fixture_id || null };
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center gap-2"><CalendarCheck className="h-5 w-5 text-blue-600" />
        <h2 className="card-title">{initial ? "정기 점검 고치기" : "정기 점검 추가"}</h2></div>
      {!initial && (
        <div className="mb-3 flex flex-wrap gap-1.5" aria-label="예시">
          {codes.suggestions.map((s) => (
            <button key={s.title} type="button" className={`chip min-h-8 ${t.title === s.title ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
              onClick={() => setT({ ...t, title: s.title, category: s.category })}>{s.title}</button>))}
        </div>
      )}
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <label className="block"><span className="mb-1 block font-medium text-slate-700">할 일</span>
          <input className="field w-full" value={t.title} onChange={set("title")} placeholder="예: 소화기 점검" /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">분류</span>
          <select className="field w-full" aria-label="분류" value={t.category} onChange={set("category")}>
            {Object.entries(codes.categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        {initial ? (
          <label className="block"><span className="mb-1 block font-medium text-slate-700">위치</span>
            <select className="field w-full" aria-label="위치" value={t.unit_id} onChange={(e) => setT({ ...t, unit_id: e.target.value, fixture_id: "" })}>
              <option value="">건물 공용</option>{units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_no}호</option>)}</select></label>
        ) : (
          <fieldset className="sm:col-span-2"><legend className="mb-1 font-medium text-slate-700">위치 (안 고르면 건물 공용, 여러 호실이면 호실마다 따로)</legend>
            <div className="flex flex-wrap gap-1.5">{units.map((u) => {
              const on = unitIds.includes(u.unit_id);
              return <button key={u.unit_id} type="button" aria-pressed={on}
                className={`min-h-9 min-w-14 rounded-lg border px-2 text-sm ${on ? "border-blue-600 bg-blue-50 text-blue-800" : "border-slate-200"}`}
                onClick={() => { setUnitIds(on ? unitIds.filter((x) => x !== u.unit_id) : [...unitIds, u.unit_id]); setT({ ...t, fixture_id: "" }); }}>
                {u.unit_no}호</button>;
            })}</div></fieldset>
        )}
        {choices.length > 0 && (
          <label className="block"><span className="mb-1 block font-medium text-slate-700">품목 (선택)</span>
            <select className="field w-full" aria-label="품목 (선택)" value={t.fixture_id} onChange={set("fixture_id")}>
              <option value="">품목과 상관없음</option>
              {choices.map((f) => <option key={f.id} value={f.id}>{f.name}{f.model ? ` (${f.model})` : ""}</option>)}</select></label>
        )}
        <label className="block"><span className="mb-1 block font-medium text-slate-700">주기 (개월, 한 번만이면 비움)</span>
          <input className="field w-full" inputMode="numeric" value={t.interval} onChange={(e) => setT({ ...t, interval: e.target.value.replace(/\D/g, "") })} placeholder="예: 6" /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">다음 예정일 (모르면 비움)</span>
          <input type="date" className="field w-full" value={t.next_due_on} onChange={set("next_due_on")} /></label>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">업체</span>
          <input className="field w-full" value={t.vendor} onChange={set("vendor")} /></label>
        <label className="block sm:col-span-2"><span className="mb-1 block font-medium text-slate-700">메모</span>
          <textarea className="field min-h-16 w-full" value={t.note} onChange={set("note")} placeholder="예: 관할 소방서 안내 기준, 업체 연락처" /></label>
      </div>
      <div className="mt-3 flex gap-2">
        <button type="button" className="btn-primary" disabled={busy || !t.title.trim()}
          onClick={() => onSave(initial ? { ...common, unit_id: t.unit_id || null } : { ...common, unit_ids: unitIds }, initial?.id)}>저장</button>
        <button type="button" className="btn-secondary" onClick={onCancel}>취소</button>
      </div>
    </section>
  );
}
