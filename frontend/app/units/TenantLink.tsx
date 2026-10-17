"use client";

import { Copy, Link2, Link2Off } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, kst } from "@/lib/api";

interface Status { lease_active: boolean; days: number[];
  link: { created_at: string; expires_at: string; last_seen_at: string | null } | null }

/** 계약별 임차인 화면 초대 링크 — 만들 때 한 번만 주소를 보여 준다 (서버에는 해시만). */
export default function TenantLink({ leaseId, unitNo, canWrite }: { leaseId: string; unitNo: string; canWrite: boolean }) {
  const [s, setS] = useState<Status | null>(null);
  const [days, setDays] = useState(90);
  const [url, setUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const path = `/api/v1/leases/${leaseId}/tenant-link`;
  const load = useCallback(async () => {
    try { setS(await api<Status>(path)); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, [path]);
  useEffect(() => { load(); }, [load]);

  async function create() {
    if (s?.link && !window.confirm(`${unitNo}호 새 링크를 만들까요? 지금 링크는 바로 열리지 않게 됩니다.`)) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ path: string; expires_at: string }>(path, { method: "POST",
        headers: { "content-type": "application/json" }, body: JSON.stringify({ days }) });
      setUrl(window.location.origin + r.path); await load();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
  async function revoke() {
    if (!window.confirm(`${unitNo}호 임차인 링크를 끌까요? 임차인은 더 이상 화면을 열 수 없습니다.`)) return;
    setBusy(true); setMsg(null);
    try { await api(path, { method: "DELETE" }); setUrl(null); await load(); setMsg({ ok: true, text: "링크를 껐습니다." }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
  async function copy() {
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setMsg({ ok: true, text: "복사했습니다. 문자·카카오톡으로 임차인에게 보내세요." }); }
    catch { setMsg({ ok: false, text: "복사하지 못했습니다. 주소를 길게 눌러 직접 복사하세요." }); }
  }

  if (!s) return <p className="mt-2 text-xs text-slate-400">{msg?.text ?? "불러오는 중…"}</p>;
  return (
    <div className="mt-2 space-y-2 rounded-xl border border-slate-200 p-3 text-sm">
      <p className="text-xs text-slate-600">임차인이 로그인 없이 자기 계약·월세 입금 확인·수리 요청을 보는 화면입니다.
        다른 호실·이름·연락처·관리 메모는 보이지 않습니다. 계약이 끝나면 자동으로 닫힙니다.</p>
      <p className="text-xs">{s.link
        ? <>지금 링크: {kst(s.link.created_at)} 만듦 · <b>{kst(s.link.expires_at)}</b>까지 · 마지막 열람 {s.link.last_seen_at ? kst(s.link.last_seen_at) : "아직 없음"}</>
        : "지금 열리는 링크가 없습니다."}</p>
      {url && (
        <div className="space-y-1 rounded-lg bg-blue-50 p-2">
          <label className="block text-xs text-blue-900">임차인 링크 (이 화면을 닫으면 다시 볼 수 없습니다)
            <input className="field mt-1 block w-full" readOnly value={url} onFocus={(e) => e.target.select()} /></label>
          <button type="button" className="btn-secondary btn-sm" onClick={copy}><Copy className="h-3.5 w-3.5" />복사</button>
        </div>
      )}
      {canWrite && s.lease_active && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-slate-600">열 수 있는 기간
            <select className="field mt-1 block" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {s.days.map((d) => <option key={d} value={d}>{d}일</option>)}</select></label>
          <button type="button" className="btn-primary btn-sm" disabled={busy} onClick={create}>
            <Link2 className="h-3.5 w-3.5" />{s.link ? "새 링크로 바꾸기" : "링크 만들기"}</button>
          {s.link && <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={revoke}>
            <Link2Off className="h-3.5 w-3.5" />링크 끄기</button>}
        </div>
      )}
      {msg && <p className={`text-xs ${msg.ok ? "text-emerald-700" : "text-red-700"}`} role="status">{msg.text}</p>}
    </div>
  );
}
