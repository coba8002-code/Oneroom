"use client";

import { Check, Copy, Loader2, MessageSquareText, PlugZap, Send, Settings2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, kst, thisMonthKst, todayKst } from "@/lib/api";
import { useMe } from "@/lib/me";

interface NotifySettings {
  grace_days: number | null;
  rent_template: string | null;
  overdue_template: string | null;
  variables: Record<string, string>;
  provider?: { connected: boolean; name: string | null };
}
interface Message {
  id: string; kind: "rent_notice" | "overdue_notice"; status: "draft" | "approved" | "sent" | "failed";
  body: string | null; tenant_name: string | null; phone: string | null; unit_no: string | null; period: string | null;
  created_at: string; approved_at: string | null; sent_at: string | null; sent_via: string | null; error: string | null;
}
type Tab = "draft" | "approved" | "sent";
const KIND = { rent_notice: "월세 고지", overdue_notice: "미납 안내" };
const TABS: [Tab, string][] = [["draft", "초안"], ["approved", "보낼 것"], ["sent", "보냄"]];
const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });

export default function NotificationsPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [cfg, setCfg] = useState<NotifySettings | null>(null);
  const [items, setItems] = useState<Message[] | null>(null);
  const [tab, setTab] = useState<Tab>("draft");
  const [msg, setMsg] = useState<{ ok: boolean; text: string; list?: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, list] = await Promise.all([api<NotifySettings>("/api/v1/notification-settings"), api<Message[]>("/api/v1/notifications")]);
      setCfg(s); setItems(list);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string | ((r: unknown) => { text: string; list?: string[] })) {
    setBusy(true); setMsg(null);
    try {
      const r = await fn();
      setMsg(typeof ok === "string" ? { ok: true, text: ok } : { ok: true, ...ok(r) });
      await load();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  const count = (t: Tab) => items?.filter((i) => (t === "approved" ? ["approved", "failed"].includes(i.status) : i.status === t)).length ?? 0;
  const shown = items?.filter((i) => (tab === "approved" ? ["approved", "failed"].includes(i.status) : i.status === tab)) ?? [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">알림·메시지</h1>
        <p className="page-sub">월세 고지·미납 안내 문구를 만들고, 확인한 뒤 보냅니다. 승인하지 않은 메시지는 보내지 않습니다.</p>
      </header>

      <p className="flex gap-2 rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
        <PlugZap className="h-5 w-5 shrink-0 text-slate-400" />
        {cfg?.provider?.connected
          ? <span>알림톡 <b>{cfg.provider.name}</b> 연결됨 — 승인하면 바로 보냅니다.</span>
          : <span><b>카카오 알림톡은 아직 연결 전입니다.</b> 승인한 문구를 복사해 문자·카톡으로 직접 보내고 &lsquo;보냄으로 표시&rsquo;를 누르세요.
            나중에 알림톡을 연결하면 승인과 동시에 보내집니다.</span>}
      </p>

      <div className="grid gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        {cfg && <SettingsCard cfg={cfg} canWrite={canWrite} busy={busy}
          onSave={(body) => run(() => api("/api/v1/notification-settings", json("PUT", body)), "알림 설정을 저장했습니다.")} />}
        {cfg && <MakeCard cfg={cfg} canWrite={canWrite} busy={busy}
          onRent={(period) => run(() => api(`/api/v1/notifications/rent-notices?period=${period}`, json("POST")),
            (r) => { const x = r as { created: number; skipped: string[] }; setTab("draft");
              return { text: `월세 고지 초안 ${x.created}건을 만들었습니다.`, list: x.skipped }; })}
          onOverdue={(asOf) => run(() => api(`/api/v1/notifications/overdue-notices?as_of=${asOf}`, json("POST")),
            (r) => { const x = r as { created: number; skipped: string[] }; setTab("draft");
              return { text: `미납 안내 초안 ${x.created}건을 만들었습니다.`, list: x.skipped }; })} />}
      </div>

      {msg && (
        <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">
          {msg.text}
          {msg.list && msg.list.length > 0 && (
            <details className="mt-1 text-xs"><summary className="cursor-pointer">건너뛴 {msg.list.length}건 보기</summary>
              <ul className="mt-1 list-disc pl-4">{msg.list.map((s) => <li key={s}>{s}</li>)}</ul></details>
          )}
        </div>
      )}

      <section className="card p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap gap-2" role="tablist" aria-label="메시지 상태">
          {TABS.map(([t, label]) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>
              {label} {count(t)}
            </button>
          ))}
        </div>
        {items === null ? <p className="text-sm text-slate-400">불러오는 중…</p>
          : shown.length === 0 ? <p className="py-6 text-center text-sm text-slate-500">{
            tab === "draft" ? "초안이 없습니다. 위에서 월세 고지나 미납 안내를 만드세요."
              : tab === "approved" ? "보낼 메시지가 없습니다." : "보낸 메시지가 없습니다."}</p>
          : <ul className="space-y-3">{shown.map((m) => <MessageCard key={m.id} m={m} canWrite={canWrite} busy={busy} run={run} />)}</ul>}
      </section>
    </div>
  );
}

function SettingsCard({ cfg, canWrite, busy, onSave }: { cfg: NotifySettings; canWrite: boolean; busy: boolean;
  onSave: (b: { grace_days: number | null; rent_template: string; overdue_template: string }) => void }) {
  const [grace, setGrace] = useState(cfg.grace_days?.toString() ?? "");
  const [rent, setRent] = useState(cfg.rent_template ?? "");
  const [overdue, setOverdue] = useState(cfg.overdue_template ?? "");
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center gap-2"><Settings2 className="h-5 w-5 text-blue-600" /><h2 className="card-title">알림 설정</h2></div>
      <p className="mb-3 text-xs text-slate-500">유예기간과 문구는 직접 정하세요. 비워 두면 그 종류의 메시지는 만들지 않습니다.</p>
      <div className="space-y-3 text-sm">
        <label className="block">
          <span className="mb-1 block font-medium text-slate-700">유예기간 (납부일 뒤 며칠이 지나야 미납 안내를 만들지)</span>
          <input className="field w-32" inputMode="numeric" value={grace} disabled={!canWrite}
            onChange={(e) => setGrace(e.target.value.replace(/\D/g, ""))} /> 일
        </label>
        <label className="block">
          <span className="mb-1 block font-medium text-slate-700">월세 고지 문구</span>
          <textarea className="field min-h-20 w-full" value={rent} disabled={!canWrite} onChange={(e) => setRent(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1 block font-medium text-slate-700">미납 안내 문구</span>
          <textarea className="field min-h-20 w-full" value={overdue} disabled={!canWrite} onChange={(e) => setOverdue(e.target.value)} />
        </label>
        <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
          <p className="mb-1 font-medium text-slate-700">문구에 넣을 수 있는 칸 — 보낼 때 실제 값으로 바뀝니다</p>
          <ul className="flex flex-wrap gap-x-3 gap-y-1">{Object.entries(cfg.variables).map(([k, v]) => (
            <li key={k}><code className="rounded bg-white px-1">{`{${k}}`}</code> {v}</li>))}</ul>
          <p className="mt-1">입금 계좌 등 고정된 내용은 문구에 직접 쓰세요.</p>
        </div>
        {canWrite && <button type="button" className="btn-primary" disabled={busy}
          onClick={() => onSave({ grace_days: grace === "" ? null : Number(grace), rent_template: rent, overdue_template: overdue })}>저장</button>}
      </div>
    </section>
  );
}

function MakeCard({ cfg, canWrite, busy, onRent, onOverdue }: { cfg: NotifySettings; canWrite: boolean; busy: boolean;
  onRent: (p: string) => void; onOverdue: (d: string) => void }) {
  const [period, setPeriod] = useState(thisMonthKst());
  const [asOf, setAsOf] = useState(todayKst());
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center gap-2"><MessageSquareText className="h-5 w-5 text-blue-600" /><h2 className="card-title">메시지 만들기</h2></div>
      <div className="space-y-4 text-sm">
        <div>
          <p className="mb-1 font-medium text-slate-700">월세 고지 — 그 달 청구마다 (이미 낸 호실 제외)</p>
          <div className="flex flex-wrap gap-2">
            <input type="month" className="field" aria-label="고지할 달" value={period} onChange={(e) => setPeriod(e.target.value)} />
            <button type="button" className="btn-secondary" disabled={!canWrite || busy || !cfg.rent_template} onClick={() => onRent(period)}>월세 고지 만들기</button>
          </div>
          {!cfg.rent_template && <p className="mt-1 text-xs text-slate-500">월세 고지 문구를 먼저 정하세요.</p>}
        </div>
        <div>
          <p className="mb-1 font-medium text-slate-700">미납 안내 — 유예기간이 지나고, 은행 내역이 그때까지 있고, 입금 검토가 끝난 것만</p>
          <div className="flex flex-wrap gap-2">
            <input type="date" className="field" aria-label="미납 기준일" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
            <button type="button" className="btn-secondary" disabled={!canWrite || busy || cfg.grace_days == null || !cfg.overdue_template}
              onClick={() => onOverdue(asOf)}>미납 안내 만들기</button>
          </div>
          {(cfg.grace_days == null || !cfg.overdue_template) && <p className="mt-1 text-xs text-slate-500">유예기간과 미납 안내 문구를 먼저 정하세요.</p>}
        </div>
        <p className="text-xs text-slate-500">만든 메시지는 초안입니다. 내용을 확인·수정하고 승인해야 보낼 수 있습니다.</p>
      </div>
    </section>
  );
}

function MessageCard({ m, canWrite, busy, run }: { m: Message; canWrite: boolean; busy: boolean;
  run: (fn: () => Promise<unknown>, ok: string) => void }) {
  const [body, setBody] = useState(m.body ?? "");
  const [copied, setCopied] = useState(false);
  const who = `${m.unit_no ?? "—"}호 ${m.tenant_name ?? ""}`;
  const post = (path: string) => api(`/api/v1/notifications/${m.id}/${path}`, json("POST"));
  return (
    <li className="rounded-2xl border border-slate-200 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span className={`chip ${m.kind === "overdue_notice" ? "bg-orange-50 text-orange-800" : "bg-blue-50 text-blue-700"}`}>{KIND[m.kind]}</span>
        <b>{who}</b><span className="text-slate-500">{m.period}</span>
        <span className="ml-auto tabular-nums text-slate-600">{m.phone ?? "연락처 없음"}</span>
      </div>
      {m.status === "draft" && canWrite
        ? <textarea className="field min-h-20 w-full text-sm" aria-label={`${who} 메시지 내용`} value={body} onChange={(e) => setBody(e.target.value)} />
        : <p className="whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm">{m.body}</p>}
      {m.error && <p className="mt-2 rounded-lg bg-red-50 p-2 text-xs text-red-800">보내지 못함: {m.error}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>{m.status === "sent" ? `보냄 ${kst(m.sent_at)} · ${m.sent_via === "manual" ? "직접" : m.sent_via}`
          : m.approved_at ? `승인 ${kst(m.approved_at)}` : `만듦 ${kst(m.created_at)}`}</span>
        {canWrite && m.status === "draft" && (
          <span className="ml-auto flex flex-wrap gap-2">
            {body !== m.body && <button type="button" className="btn-secondary btn-sm" disabled={busy}
              onClick={() => run(() => api(`/api/v1/notifications/${m.id}`, json("PATCH", { body })), "내용을 고쳤습니다.")}>고친 내용 저장</button>}
            <button type="button" className="btn-secondary btn-sm" disabled={busy}
              onClick={() => run(() => post("discard"), "초안을 버렸습니다.")}><Trash2 className="h-3.5 w-3.5" />버리기</button>
            <button type="button" className="btn-primary btn-sm" disabled={busy || body !== m.body}
              title={body !== m.body ? "고친 내용을 먼저 저장하세요" : undefined}
              onClick={() => run(() => post("approve"), "승인했습니다. '보낼 것'에서 보내세요.")}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}승인</button>
          </span>
        )}
        {canWrite && (m.status === "approved" || m.status === "failed") && (
          <span className="ml-auto flex flex-wrap gap-2">
            <button type="button" className="btn-secondary btn-sm"
              onClick={async () => { await navigator.clipboard.writeText(m.body ?? "").catch(() => {}); setCopied(true); }}>
              <Copy className="h-3.5 w-3.5" />{copied ? "복사됨" : "문구 복사"}</button>
            <button type="button" className="btn-secondary btn-sm" disabled={busy}
              onClick={() => run(() => post("discard"), "메시지를 버렸습니다.")}>버리기</button>
            <button type="button" className="btn-primary btn-sm" disabled={busy}
              onClick={() => run(() => post("mark-sent"), "보냄으로 표시했습니다.")}><Send className="h-3.5 w-3.5" />보냄으로 표시</button>
          </span>
        )}
      </div>
    </li>
  );
}
