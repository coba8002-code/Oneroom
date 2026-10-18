"use client";

import { CalendarDays, House, Megaphone, Phone, Send, Wrench } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, kst, won } from "@/lib/api";

interface View {
  unit_no: string; building: string;
  lease: { start_date: string; end_date: string | null; rent: number; mgmt_fee: number | null; due_day: number; deposit: number; deposit_received: number | null };
  next_due: string | null;
  charges: { period: string; due_date: string; amount: number; paid: number; state: string; state_label: string; kind: string; kind_label: string }[];
  bank_data_as_of: string | null;
  repairs: { reported_on: string; description: string; status: string; completed_on: string | null }[];
  notices: { title: string; body: string | null; starts_on: string; ends_on: string | null; for_unit: boolean }[];
  contact: { phone: string | null; note: string | null } | null;
  link_expires_at: string; notice: string;
}

const TONE: Record<string, string> = { paid: "bg-emerald-50 text-emerald-700", partial: "bg-amber-50 text-amber-800",
  open: "bg-slate-100 text-slate-600", waived: "bg-slate-100 text-slate-500" };

export default function TenantPage() {
  const { token } = useParams<{ token: string }>();
  const [v, setV] = useState<View | null>(null);
  const [gone, setGone] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setV(await api<View>(`/api/v1/tenant/${encodeURIComponent(token)}`)); }
    catch (e) { setGone((e as Error).message); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="mx-auto min-h-screen max-w-xl space-y-4 px-4 py-6">
      <header className="flex items-center gap-2 text-navy-800">
        <House className="h-6 w-6 text-blue-600" strokeWidth={2.4} />
        <div>
          <h1 className="text-xl font-extrabold tracking-tight">{v ? `${v.unit_no}호` : "우리 집"}</h1>
          {v && <p className="text-xs text-slate-500">{v.building}</p>}
        </div>
      </header>
      {gone ? <p className="card p-4 text-sm text-slate-700" role="status">{gone}</p>
        : !v ? <p className="text-sm text-slate-400">불러오는 중…</p> : <Body v={v} token={token} reload={load} />}
    </div>
  );
}

function Body({ v, token, reload }: { v: View; token: string; reload: () => Promise<void> }) {
  const l = v.lease;
  return (
    <>
      {v.notices.length > 0 && (
        <section className="card space-y-2 border-l-4 border-l-blue-500 p-4" aria-labelledby="notices">
          <h2 id="notices" className="card-title flex items-center gap-1"><Megaphone className="h-4 w-4" />공지</h2>
          <ul className="space-y-2 text-sm">
            {v.notices.map((n, i) => (
              <li key={i}>
                <b className="break-words">{n.title}</b>{n.for_unit && <span className="chip ml-1 bg-blue-50 text-blue-700">우리 집</span>}
                {n.body && <p className="whitespace-pre-wrap break-words text-slate-600">{n.body}</p>}
                <p className="text-xs text-slate-400">{n.starts_on}{n.ends_on ? ` ~ ${n.ends_on}` : ""}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="grid grid-cols-2 gap-3">
        <div className="card col-span-2 p-4">
          <p className="flex items-center gap-1 text-xs text-slate-500"><CalendarDays className="h-3.5 w-3.5" />다음 납부일</p>
          <p className="text-2xl font-bold">{v.next_due ?? "—"}</p>
          <p className="text-xs text-slate-500">매월 {l.due_day}일 · 월세 {won(l.rent)}{l.mgmt_fee ? ` · 관리비 ${won(l.mgmt_fee)}` : ""}</p>
        </div>
        <div className="card p-3"><p className="text-xs text-slate-500">계약 기간</p>
          <p className="text-sm font-semibold">{l.start_date}<br />~ {l.end_date ?? "—"}</p></div>
        <div className="card p-3"><p className="text-xs text-slate-500">보증금</p>
          <p className="text-sm font-semibold">{won(l.deposit)}</p>
          <p className="text-xs text-slate-500">받은 기록 {won(l.deposit_received)}</p></div>
      </section>

      <section className="card p-4">
        <h2 className="card-title mb-1">청구 · 입금 확인</h2>
        <p className="mb-2 text-xs text-slate-500">
          {v.bank_data_as_of ? `${kst(v.bank_data_as_of)}까지의 통장 내역으로 확인했습니다.` : "아직 통장 내역이 반영되지 않았습니다."}</p>
        {v.charges.length === 0 ? <p className="text-sm text-slate-500">아직 청구가 없습니다.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {v.charges.map((c) => (
              <li key={c.period + c.kind} className="flex items-center justify-between gap-2 py-2 tabular-nums">
                <span>{c.period} {c.kind_label}<span className="block text-xs text-slate-500">납부일 {c.due_date}</span></span>
                <span className="text-right">{won(c.amount)}
                  {c.paid > 0 && c.paid < c.amount && <span className="block text-xs text-slate-500">확인 {won(c.paid)}</span>}</span>
                <span className={`chip shrink-0 ${TONE[c.state] ?? TONE.open}`}>{c.state_label}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-slate-500">{v.notice}</p>
      </section>

      <Repairs v={v} token={token} reload={reload} />

      <p className="px-1 text-xs text-slate-500">
        이 링크는 {kst(v.link_expires_at)}까지 열립니다. 본인만 보세요 — 잃어버렸거나 다른 사람이 봤다면 집주인에게 새 링크를 요청하세요.</p>
    </>
  );
}

function Repairs({ v, token, reload }: { v: View; token: string; reload: () => Promise<void> }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function send() {
    setBusy(true); setMsg(null);
    try {
      await api(`/api/v1/tenant/${encodeURIComponent(token)}/repairs`, { method: "POST",
        headers: { "content-type": "application/json" }, body: JSON.stringify({ description: text }) });
      setText(""); await reload(); setMsg({ ok: true, text: "집주인에게 보냈습니다." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
  return (
    <section className="card space-y-2 p-4">
      <h2 className="card-title flex items-center gap-1"><Wrench className="h-4 w-4" />수리 요청</h2>
      <label className="block text-xs text-slate-600">어디가 어떻게 고장 났나요?
        <textarea className="field mt-1 block w-full" rows={3} maxLength={1000} value={text}
          placeholder="예: 욕실 세면대 배수가 느려요 (3일 전부터)" onChange={(e) => setText(e.target.value)} /></label>
      <button type="button" className="btn-primary btn-sm" disabled={busy || !text.trim()} onClick={send}>
        <Send className="h-3.5 w-3.5" />수리 요청 보내기</button>
      {msg && <p className={`text-sm ${msg.ok ? "text-emerald-700" : "text-red-700"}`} role="status">{msg.text}</p>}
      {v.contact?.phone ? (
        <p className="flex flex-wrap items-center gap-1 text-sm"><Phone className="h-4 w-4 text-slate-500" />급한 일(누수·가스·전기)은 바로 전화하세요:
          <a className="font-semibold text-blue-700 underline" href={`tel:${v.contact.phone.replace(/[^\d+]/g, "")}`}>{v.contact.phone}</a>
          {v.contact.note && <span className="text-xs text-slate-500">({v.contact.note})</span>}</p>
      ) : <p className="text-xs text-slate-500">급한 일(누수·가스·전기)은 집주인에게 바로 전화하세요.</p>}
      {v.repairs.length > 0 && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100 text-sm">
          {v.repairs.map((r, i) => (
            <li key={i} className="flex items-start justify-between gap-2 py-2">
              <span className="min-w-0 break-words">{r.description}<span className="block text-xs text-slate-500">{r.reported_on} 요청</span></span>
              <span className={`chip shrink-0 ${r.status === "done" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>
                {r.status === "done" ? `완료 ${r.completed_on ?? ""}` : "처리 중"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
