"use client";

import { Megaphone, Phone, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, todayKst } from "@/lib/api";
import { useMe } from "@/lib/me";

interface Building { property_id: string; name: string; contact_phone: string | null; contact_note: string | null;
  units: { unit_id: string; unit_no: string }[] }
interface Notice { id: string; property_id: string; unit_id: string | null; unit_no: string | null; title: string;
  body: string | null; starts_on: string; ends_on: string | null; state: "showing" | "scheduled" | "ended" }
interface Overview { buildings: Building[]; notices: Notice[] }

const STATE: Record<Notice["state"], [string, string]> = { showing: ["게시 중", "bg-emerald-50 text-emerald-700"],
  scheduled: ["예정", "bg-blue-50 text-blue-700"], ended: ["끝남", "bg-slate-100 text-slate-500"] };
const json = (method: string, body?: unknown) => ({ method,
  ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });

export default function TenantNoticesPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [ov, setOv] = useState<Overview | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(async () => {
    try { setOv(await api<Overview>("/api/v1/tenant-notices")); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
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
        <h1 className="page-title">임차인 공지</h1>
        <p className="page-sub">임차인 화면(초대 링크)에만 보이는 공지와 연락처입니다. 문자로 자동 발송하지 않습니다.</p>
      </header>
      {msg && <p className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</p>}
      {!ov ? <p className="text-sm text-slate-400">불러오는 중…</p> : (
        <>
          {canWrite && ov.buildings.length > 0 && <NoticeForm buildings={ov.buildings}
            onSave={(b) => run(() => api("/api/v1/tenant-notices", json("POST", b)), "공지를 올렸습니다.")} />}
          <section className="card p-4">
            <h2 className="card-title mb-2 flex items-center gap-1"><Megaphone className="h-4 w-4" />공지 {ov.notices.length}건</h2>
            {ov.notices.length === 0 ? <p className="text-sm text-slate-500">아직 공지가 없습니다.</p> : (
              <ul className="divide-y divide-slate-100 text-sm">
                {ov.notices.map((n) => {
                  const [label, tone] = STATE[n.state];
                  const b = ov.buildings.find((x) => x.property_id === n.property_id);
                  return (
                    <li key={n.id} className="py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`chip ${tone}`}>{label}</span><b className="min-w-0 break-words">{n.title}</b>
                        <span className="text-xs text-slate-500">{n.unit_no ? `${n.unit_no}호만` : `${ov.buildings.length > 1 ? `${b?.name} ` : ""}전체`} ·
                          {" "}{n.starts_on} ~ {n.ends_on ?? "지울 때까지"}</span>
                        {canWrite && <button type="button" className="btn-secondary btn-sm ml-auto" aria-label={`${n.title} 지우기`}
                          onClick={() => window.confirm(`'${n.title}' 공지를 지울까요? 임차인 화면에서도 바로 사라집니다.`)
                            && run(() => api(`/api/v1/tenant-notices/${n.id}`, json("DELETE")), "공지를 지웠습니다.")}>
                          <Trash2 className="h-3.5 w-3.5" />지우기</button>}
                      </div>
                      {n.body && <p className="mt-0.5 whitespace-pre-wrap break-words text-slate-600">{n.body}</p>}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          {ov.buildings.map((b) => <ContactCard key={b.property_id} b={b} canWrite={canWrite} multi={ov.buildings.length > 1}
            onSave={(phone, note) => run(() => api(`/api/v1/properties/${b.property_id}/tenant-contact`, json("PUT", { phone, note })),
              "연락처를 저장했습니다.")} />)}
        </>
      )}
    </div>
  );
}

function NoticeForm({ buildings, onSave }: { buildings: Building[];
  onSave: (b: Record<string, unknown>) => Promise<boolean> }) {
  const [f, setF] = useState({ property_id: buildings[0].property_id, unit_id: "", title: "", body: "", starts_on: todayKst(), ends_on: "" });
  const [busy, setBusy] = useState(false);
  const b = buildings.find((x) => x.property_id === f.property_id) ?? buildings[0];
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value, ...(k === "property_id" ? { unit_id: "" } : {}) });
  return (
    <section className="card grid gap-2 p-4 text-sm sm:grid-cols-2">
      <h2 className="card-title sm:col-span-2">공지 올리기</h2>
      {buildings.length > 1 && <label className="block text-xs text-slate-600">건물
        <select className="field mt-1 w-full" value={f.property_id} onChange={set("property_id")}>
          {buildings.map((x) => <option key={x.property_id} value={x.property_id}>{x.name}</option>)}</select></label>}
      <label className="block text-xs text-slate-600">보낼 곳
        <select className="field mt-1 w-full" value={f.unit_id} onChange={set("unit_id")}>
          <option value="">건물 전체</option>
          {b.units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_no}호만</option>)}</select></label>
      <label className="block text-xs text-slate-600 sm:col-span-2">제목
        <input className="field mt-1 w-full" maxLength={100} value={f.title} placeholder="예: 12/20(토) 물탱크 청소" onChange={set("title")} /></label>
      <label className="block text-xs text-slate-600 sm:col-span-2">내용 (선택)
        <textarea className="field mt-1 w-full" rows={3} maxLength={2000} value={f.body} onChange={set("body")} /></label>
      <label className="block text-xs text-slate-600">보이기 시작하는 날
        <input type="date" className="field mt-1 w-full" value={f.starts_on} onChange={set("starts_on")} /></label>
      <label className="block text-xs text-slate-600">끝나는 날 (비우면 지울 때까지)
        <input type="date" className="field mt-1 w-full" value={f.ends_on} onChange={set("ends_on")} /></label>
      <div className="sm:col-span-2">
        <button type="button" className="btn-primary btn-sm" disabled={busy || !f.title.trim()} onClick={async () => {
          setBusy(true);
          const ok = await onSave({ property_id: f.property_id, unit_id: f.unit_id || null, title: f.title, body: f.body || null,
            starts_on: f.starts_on || null, ends_on: f.ends_on || null });
          setBusy(false);
          if (ok) setF({ ...f, title: "", body: "", ends_on: "" });
        }}><Megaphone className="h-3.5 w-3.5" />공지 올리기</button>
      </div>
    </section>
  );
}

function ContactCard({ b, canWrite, multi, onSave }: { b: Building; canWrite: boolean; multi: boolean;
  onSave: (phone: string | null, note: string | null) => Promise<boolean> }) {
  const [phone, setPhone] = useState(b.contact_phone ?? "");
  const [note, setNote] = useState(b.contact_note ?? "");
  return (
    <section className="card space-y-2 p-4 text-sm">
      <h2 className="card-title flex items-center gap-1"><Phone className="h-4 w-4" />임차인 화면에 보일 연락처{multi ? ` — ${b.name}` : ""}</h2>
      <p className="text-xs text-slate-500">비워 두면 임차인 화면에 연락처가 나오지 않습니다. 번호는 암호화해 저장합니다.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs text-slate-600">전화번호
          <input className="field mt-1 w-full" inputMode="tel" value={phone} disabled={!canWrite} onChange={(e) => setPhone(e.target.value)} /></label>
        <label className="block text-xs text-slate-600">안내 (선택)
          <input className="field mt-1 w-full" maxLength={200} value={note} disabled={!canWrite} placeholder="예: 평일 9~18시, 누수는 언제든"
            onChange={(e) => setNote(e.target.value)} /></label>
      </div>
      {canWrite && <button type="button" className="btn-secondary btn-sm" onClick={() => onSave(phone.trim() || null, note.trim() || null)}>연락처 저장</button>}
    </section>
  );
}
