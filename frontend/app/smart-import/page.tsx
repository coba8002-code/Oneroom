"use client";

import { Camera, FileText, Landmark, Sparkles, Upload } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, won } from "@/lib/api";
import { recognizeTexts } from "@/lib/freeOcr";
import { shrinkImage } from "@/lib/image";
import { batches, prepareFiles } from "@/lib/photoPrep";
import { useMe } from "@/lib/me";

interface Status { configured: boolean; daily_limit: number; max_files: number; used_today: number }
interface UnitRow { unit_no: string | null; tenant_name: string | null; tenant_phone: string | null; deposit: number | null;
  rent: number | null; mgmt_fee: number | null; due_day: number | null; start_date: string | null; end_date: string | null;
  signed_on: string | null; deposit_received_on: string | null; evidence: string | null }
interface BankRow { date: string | null; time: string | null; direction: "in" | "out" | null; amount: number | null;
  counterparty: string | null; description: string | null; balance_after: number | null }
interface ReadOut<T> { rows: T[]; notes: string[]; remaining_today?: number }
type Mode = "ai" | "free";
interface LeaseH { lease_id: string; tenant_name: string; status: string; start_date: string; end_date: string | null; deposit: number; rent: number }
interface UnitH { unit_id: string; unit_no: string; use_type: string; status: string; leases: LeaseH[] }
interface Account { id: string; alias: string }

const json = (method: string, body: unknown) => ({ method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(/[^\d]/g, "")));
const txt = (v: string) => (v.trim() === "" ? null : v);

const AI_MAX_FILES = 5;
const AI_MAX_BYTES = 3_800_000;

/** zip 풀기·긴 캡처 자르기 → 무료(기기 안 글자 인식) 또는 AI(5장씩 나눠 보내 결과 합치기) */
async function readPhotos<T>(kind: "units" | "bank", picked: FileList, mode: Mode, onStage: (s: string) => void): Promise<ReadOut<T>> {
  // 계약 화면은 사진 하나 = 호실 하나라 휴대폰 캡처(세로 2.2배 안팎)는 자르지 않는다. 통장 전체 캡처처럼 아주 긴 것만
  const files = await prepareFiles(Array.from(picked), { tallRatio: kind === "bank" ? 2.2 : 3.5 });
  if (!files.length) throw new Error("사진·PDF 를 찾지 못했습니다 (zip 안에도 없음)");
  if (mode === "free") {
    const texts = await recognizeTexts(files, (d, t) => onStage(`이 기기에서 글자를 읽는 중… ${d + 1}/${t}장`));
    return api<ReadOut<T>>("/api/v1/vision/parse-text", json("POST", { kind, texts }));
  }
  const shrunk: File[] = [];
  for (const f of files) shrunk.push(await shrinkImage(f));
  const groups = batches(shrunk, AI_MAX_FILES, AI_MAX_BYTES);
  const out: ReadOut<T> = { rows: [], notes: [] };
  for (const [i, g] of groups.entries()) {
    onStage(`AI가 읽는 중… ${i + 1}/${groups.length}묶음 (${files.length}장)`);
    const form = new FormData();
    for (const f of g) form.append("files", f);
    const r = await api<ReadOut<T>>(`/api/v1/vision/${kind}`, { method: "POST", body: form });
    out.rows.push(...r.rows);
    out.notes.push(...r.notes.map((n) => (groups.length > 1 ? `묶음 ${i + 1}: ${n}` : n)));
    out.remaining_today = r.remaining_today;
  }
  return out;
}

export default function SmartImportPage() {
  const { me } = useMe();
  const canWrite = me?.user.role !== "viewer";
  const [st, setSt] = useState<Status | null>(null);
  const [tab, setTab] = useState<"units" | "bank">("units");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [choice, setChoice] = useState<Mode | null>(null);
  const mode: Mode = choice ?? (st?.configured ? "ai" : "free");
  const loadStatus = useCallback(() => api<Status>("/api/v1/vision/status").then(setSt).catch((e) => setMsg({ ok: false, text: e.message })), []);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="page-title">사진으로 넣기</h1>
        <p className="page-sub">계약서·임대관리 앱 캡처, 통장 거래내역 캡처를 올리면 표로 옮겨 적습니다.
          표를 확인하고 고친 뒤 <b>넣기</b>를 눌러야 장부에 들어갑니다. 사진은 저장하지 않습니다.</p>
      </header>
      {msg && <p className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</p>}
      {st && (
        <section className="card space-y-2 p-3 text-sm" aria-label="판독 방식">
          <div className="flex flex-wrap gap-2">
            <button type="button" aria-pressed={mode === "free"} className={mode === "free" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
              onClick={() => setChoice("free")}>무료 판독 (이 기기 안에서)</button>
            <button type="button" aria-pressed={mode === "ai"} disabled={!st.configured} className={mode === "ai" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
              onClick={() => setChoice("ai")}><Sparkles className="h-3.5 w-3.5" />AI 판독 (Claude)</button>
          </div>
          {mode === "free"
            ? <p className="text-xs text-slate-600">무료·사진이 기기 밖으로 나가지 않음. 글자만 읽어 규칙으로 나누므로 <b>깨끗한 캡처</b>에 맞고, 표를 꼭 확인하세요.
              계약서는 한 장씩(보증금·월세·납부일·기간), 통장은 연도까지 보이는 거래만 읽습니다. 처음엔 인식 데이터(약 10MB)를 받아 1분쯤 걸릴 수 있습니다.</p>
            : <p className="text-xs text-slate-600">오늘 {st.used_today}/{st.daily_limit}회 · 한 번에 {st.max_files}장(합쳐 4MB). 표·여러 호실 목록까지 정확히 읽습니다.
              사진 속 이름·연락처는 판독을 위해 Anthropic(미국)으로 전송됩니다(처리방침 국외 이전).</p>}
          {!st.configured && <p className="text-xs text-slate-500">AI 판독을 쓰려면 <Link href="/settings#ai-key" className="underline">설정 → AI 연결</Link>에서 Claude API 키를 넣으세요.
            통장 CSV·엑셀은 <Link href="/payments" className="underline">임대료 관리</Link>에서 바로 올리는 것이 가장 정확합니다.</p>}
        </section>
      )}
      <div className="flex gap-2" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "units"} className={tab === "units" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
          onClick={() => setTab("units")}><FileText className="h-3.5 w-3.5" />계약·호실</button>
        <button type="button" role="tab" aria-selected={tab === "bank"} className={tab === "bank" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
          onClick={() => setTab("bank")}><Landmark className="h-3.5 w-3.5" />통장 내역</button>
      </div>
      {tab === "units"
        ? <UnitsTab enabled={!!st && canWrite} mode={mode} onMsg={setMsg} onRead={loadStatus} />
        : <BankTab enabled={!!st && canWrite} mode={mode} orgId={me?.organization.id ?? ""} onMsg={setMsg} onRead={loadStatus} />}
    </div>
  );
}

function Picker({ enabled, busy, mode, label, stage, onPick }: { enabled: boolean; busy: boolean; mode: Mode; label: string; stage?: string; onPick: (f: FileList) => void }) {
  return (
    <label className={`card flex cursor-pointer flex-col items-center gap-2 border-2 border-dashed p-6 text-center text-sm text-slate-600 ${enabled && !busy ? "" : "pointer-events-none opacity-50"}`}>
      {busy ? <Sparkles className="h-6 w-6 animate-pulse" /> : <Camera className="h-6 w-6" />}
      <span>{busy ? (stage || (mode === "ai" ? "AI가 읽는 중…" : "이 기기에서 글자를 읽는 중… (첫 사용은 1분 안팎)")) : label}</span>
      <span className="text-xs text-slate-400">사진 여러 장 · zip 묶음 가능{mode === "ai" ? " · PDF" : ""}</span>
      <input type="file" multiple accept={mode === "ai" ? "image/*,application/pdf,.zip" : "image/*,.zip"} className="sr-only" aria-label={label} disabled={!enabled || busy}
        onChange={(e) => { if (e.target.files?.length) onPick(e.target.files); e.target.value = ""; }} />
    </label>
  );
}

function Notes({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return <ul className="list-disc rounded-xl bg-amber-50 p-3 pl-7 text-xs text-amber-900">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>;
}

// ── 계약·호실 ────────────────────────────────────────────────

// new: 빈 호실에 새 계약 · same: 장부와 같음(건너뜀) · skip: 넣지 않음
// end: 지금 계약을 새 계약 시작 전날로 종료하고 새 계약 · delete: 잘못 넣은 지금 계약을 지우고 새 계약
type Action = "new" | "same" | "skip" | "end" | "delete";
type UnitEdit = UnitRow & { unit_id: string; fuzzy: boolean; action: Action; result?: string };
const ACTION_LABEL: Record<Action, string> = { new: "새 계약 넣기", same: "장부와 같음", skip: "넣지 않음",
  end: "지금 계약 종료 후 새 계약", delete: "지금 계약 지우고 새 계약" };

function activeLease(u: UnitH | undefined): LeaseH | undefined {
  return u?.leases.find((l) => l.status === "active");
}

function defaultAction(r: UnitRow, u: UnitH | undefined): Action {
  if (!u || u.use_type !== "rental") return "skip";
  const cur = activeLease(u);
  if (!cur) return "new";
  const same = cur.tenant_name === r.tenant_name && cur.deposit === r.deposit && cur.rent === r.rent && cur.start_date === r.start_date;
  return same ? "same" : "skip";  // 지금 계약을 바꾸는 것은 사람이 고른다
}

/** 사진의 호실 번호 → 등록된 호실. 글자 인식이 '호'를 숫자로 읽은 경우(3022 → 302)는 '확인 필요'로 맞춘다 */
function matchUnit(list: UnitH[], no: string | null): { unit?: UnitH; fuzzy: boolean } {
  if (!no) return { fuzzy: false };
  const n = no.replace(/호$/, "");
  const exact = list.find((u) => u.unit_no === n || u.unit_no.endsWith(` ${n}`));
  if (exact) return { unit: exact, fuzzy: false };
  const cut = n.length >= 3 ? list.find((u) => u.unit_no === n.slice(0, -1) || u.unit_no.endsWith(` ${n.slice(0, -1)}`)) : undefined;
  return { unit: cut, fuzzy: !!cut };
}

function UnitsTab({ enabled, mode, onMsg, onRead }: { enabled: boolean; mode: Mode; onMsg: (m: { ok: boolean; text: string } | null) => void; onRead: () => void }) {
  const [units, setUnits] = useState<UnitH[]>([]);
  const [rows, setRows] = useState<UnitEdit[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const loadUnits = useCallback(() => api<UnitH[]>("/api/v1/lease-history").then(setUnits).catch(() => setUnits([])), []);
  useEffect(() => { loadUnits(); }, [loadUnits]);
  const unitOf = (id: string) => units.find((x) => x.unit_id === id);
  const complete = (r: UnitEdit) => !!r.tenant_name && r.rent != null && r.due_day != null && !!r.start_date;
  const ready = (r: UnitEdit) => !!r.unit_id && complete(r) && !r.result
    && (r.action === "new" ? !activeLease(unitOf(r.unit_id)) : r.action === "end" || r.action === "delete");

  const pick = async (files: FileList) => {
    setBusy(true); setStage(""); onMsg(null);
    try {
      const [out, list] = await Promise.all([readPhotos<UnitRow>("units", files, mode, setStage), api<UnitH[]>("/api/v1/lease-history")]);
      setUnits(list);  // 화면을 연 뒤 바뀐 계약까지 반영해 짝짓기
      setRows(out.rows.map((r) => {
        const { unit, fuzzy } = matchUnit(list, r.unit_no);
        return { ...r, unit_id: unit?.unit_id ?? "", fuzzy, action: defaultAction(r, unit) };
      }));
      setNotes(out.notes);
      onMsg({ ok: true, text: `${out.rows.length}줄을 읽었습니다. 표를 확인하고, 이미 계약이 있는 호실은 바꿀지 고른 뒤 적용하세요.` });
    } catch (e) { onMsg({ ok: false, text: (e as Error).message }); }
    setBusy(false); setStage(""); onRead();
  };
  const set = (i: number, patch: Partial<UnitEdit>) => setRows(rows.map((r, j) => {
    if (j !== i) return r;
    const next = { ...r, ...patch };
    if (patch.unit_id !== undefined) next.action = defaultAction(next, unitOf(patch.unit_id));
    return next;
  }));
  const save = async () => {
    const replacing = rows.filter((r) => ready(r) && r.action !== "new");
    if (replacing.length && !window.confirm(`${replacing.map((r) => `${unitOf(r.unit_id)?.unit_no}호: ${ACTION_LABEL[r.action]}`).join("\n")}\n\n지금 계약을 바꿉니다. 진행할까요?`)) return;
    setBusy(true);
    const next = [...rows];
    let ok = 0;
    for (const [i, r] of rows.entries()) {
      if (!ready(r)) continue;
      const body = { tenant_name: r.tenant_name, tenant_phone: r.tenant_phone, deposit: r.deposit ?? 0, rent: r.rent, mgmt_fee: r.mgmt_fee,
        due_day: r.due_day, start_date: r.start_date, end_date: r.end_date, signed_on: r.signed_on, deposit_received_on: r.deposit_received_on };
      try {
        if (r.action === "new") await api(`/api/v1/units/${r.unit_id}/leases`, json("POST", body));
        else await api(`/api/v1/units/${r.unit_id}/replace-lease`, json("POST", { ...body, mode: r.action }));
        next[i] = { ...r, result: r.action === "new" ? "넣음" : "바꿈" }; ok += 1;
      } catch (e) { next[i] = { ...r, result: (e as Error).message }; }
    }
    setRows(next); await loadUnits(); setBusy(false);
    const failed = next.filter((r) => r.result && !["넣음", "바꿈"].includes(r.result)).length;
    onMsg({ ok: failed === 0, text: `계약 ${ok}건을 적용했습니다.${failed ? ` ${failed}건은 적용하지 못했습니다 — 사유를 확인하세요.` : ""}` });
  };
  const count = rows.filter(ready).length;
  const done = (r: UnitEdit) => r.result === "넣음" || r.result === "바꿈";

  return (
    <section className="space-y-3">
      <Picker enabled={enabled} busy={busy} mode={mode} stage={stage} onPick={pick}
        label={mode === "ai" ? "계약서·호실 목록·임대관리 앱 캡처 고르기" : "계약서·임대관리 앱(자리톡) 호실 화면 캡처 고르기"} />
      <Notes notes={notes} />
      {rows.length > 0 && (
        <div className="card overflow-x-auto p-3">
          <table className="w-full min-w-[64rem] text-xs">
            <thead className="text-left text-slate-500"><tr>
              <th className="p-1">호실</th><th className="p-1">적용</th><th className="p-1">임차인</th><th className="p-1">연락처</th>
              <th className="p-1">보증금</th><th className="p-1">월세</th><th className="p-1">관리비</th><th className="p-1">납부일</th>
              <th className="p-1">시작</th><th className="p-1">만료</th><th className="p-1">보증금 받은 날</th><th className="p-1">근거·결과</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const u = unitOf(r.unit_id);
                const cur = activeLease(u);
                return (
                  <tr key={i} className={`border-t border-slate-100 align-top ${r.action === "end" || r.action === "delete" ? "bg-amber-50" : ""}`}>
                    <td className="p-1">
                      <select className="field w-24" aria-label="호실" value={r.unit_id} disabled={done(r)} onChange={(e) => set(i, { unit_id: e.target.value, fuzzy: false })}>
                        <option value="">{r.unit_no ? `${r.unit_no}?` : "고르기"}</option>
                        {units.filter((x) => x.use_type === "rental").map((x) => <option key={x.unit_id} value={x.unit_id}>{x.unit_no}{activeLease(x) ? " (계약 중)" : ""}</option>)}
                      </select>
                      {r.fuzzy && <p className="mt-0.5 text-amber-700">사진엔 '{r.unit_no}' — 확인</p>}
                      {cur && <p className="mt-0.5 w-32 text-slate-500">지금: {cur.tenant_name} · {won(cur.deposit)}/{won(cur.rent)} · {cur.start_date}~</p>}
                    </td>
                    <td className="p-1">
                      <select className="field w-44" aria-label="적용" value={r.action} disabled={done(r) || !r.unit_id} onChange={(e) => set(i, { action: e.target.value as Action })}>
                        {(cur ? ["skip", "same", "end", "delete"] as Action[] : ["new", "skip"] as Action[])
                          .filter((a) => a !== "same" || r.action === "same").map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}
                      </select>
                    </td>
                    <td className="p-1"><input className="field w-20" aria-label="임차인" value={r.tenant_name ?? ""} onChange={(e) => set(i, { tenant_name: txt(e.target.value) })} /></td>
                    <td className="p-1"><input className="field w-28" aria-label="연락처" value={r.tenant_phone ?? ""} onChange={(e) => set(i, { tenant_phone: txt(e.target.value) })} /></td>
                    {(["deposit", "rent", "mgmt_fee"] as const).map((k) => (
                      <td key={k} className="p-1"><input className="field w-24" inputMode="numeric" aria-label={k} value={r[k] ?? ""} onChange={(e) => set(i, { [k]: num(e.target.value) })} /></td>))}
                    <td className="p-1"><input className="field w-12" inputMode="numeric" aria-label="납부일" value={r.due_day ?? ""} onChange={(e) => set(i, { due_day: num(e.target.value) })} /></td>
                    {(["start_date", "end_date", "deposit_received_on"] as const).map((k) => (
                      <td key={k} className="p-1"><input type="date" className="field" aria-label={k} value={r[k] ?? ""} onChange={(e) => set(i, { [k]: txt(e.target.value) })} /></td>))}
                    <td className="p-1 text-slate-500">{r.result ? <b className={done(r) ? "text-emerald-700" : "text-red-700"}>{r.result}</b>
                      : !r.unit_id ? "호실을 고르세요" : !complete(r) ? "임차인·월세·납부일·시작일 필요"
                      : r.action === "same" ? "장부와 같아 건너뜀" : r.action === "skip" && cur ? "이미 계약 중 — 바꾸려면 '적용'에서 고르기" : r.evidence ?? ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || count === 0} onClick={save}><Upload className="h-3.5 w-3.5" />확인한 {count}건 적용</button>
            <span className="text-xs text-slate-500">빈 칸은 사진에서 읽지 못한 값입니다(추측하지 않음). '지우고 새 계약'은 청구·입금·받은 보증금 기록이 없는 계약만 됩니다.
              보증금은 받은 날을 적어야 '받음'으로 기록됩니다.</span>
          </div>
        </div>
      )}
    </section>
  );
}

// ── 통장 내역 ────────────────────────────────────────────────

type BankEdit = BankRow & { pick: boolean };

function BankTab({ enabled, mode, orgId, onMsg, onRead }: { enabled: boolean; mode: Mode; orgId: string; onMsg: (m: { ok: boolean; text: string } | null) => void; onRead: () => void }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [acct, setAcct] = useState("");
  const [rows, setRows] = useState<BankEdit[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!orgId) return;
    api<Account[]>(`/api/v1/bank-accounts?organization_id=${orgId}`).then((a) => { setAccounts(a); setAcct(a[0]?.id ?? ""); }).catch(() => setAccounts([]));
  }, [orgId]);
  const [stage, setStage] = useState("");
  const ready = (r: BankEdit) => !!r.date && !!r.direction && !!r.amount && r.amount > 0;
  const pick = async (files: FileList) => {
    setBusy(true); setStage(""); onMsg(null);
    try {
      const out = await readPhotos<BankRow>("bank", files, mode, setStage);
      // 긴 캡처를 겹치게 잘랐으므로 같은 거래(날짜·시각·방향·금액·잔액)가 두 번 나오면 하나만
      const seen = new Set<string>();
      const uniq = out.rows.filter((r) => {
        const key = [r.date, r.time, r.direction, r.amount, r.balance_after].join("|");
        if (r.balance_after == null || !seen.has(key)) { seen.add(key); return true; }
        return false;
      });
      setRows(uniq.map((r) => ({ ...r, pick: true })));
      setNotes(out.notes);
      onMsg({ ok: true, text: `${uniq.length}건을 읽었습니다. 금액·날짜를 사진과 맞춰 본 뒤 넣으세요.` });
    } catch (e) { onMsg({ ok: false, text: (e as Error).message }); }
    setBusy(false); setStage(""); onRead();
  };
  const set = (i: number, patch: Partial<BankEdit>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const chosen = rows.filter((r) => r.pick && ready(r));
  const save = async () => {
    setBusy(true);
    try {
      const out = await api<{ inserted: number; duplicates: number; errors: { message: string }[] }>(
        `/api/v1/bank-accounts/${acct}/import-rows`, json("POST", { rows: chosen.map(({ pick: _p, ...r }) => r) }));
      setRows([]); setNotes([]);
      onMsg({ ok: true, text: `새 거래 ${out.inserted}건 · 이미 있던 거래 ${out.duplicates}건${out.errors.length ? ` · 오류 ${out.errors.length}건` : ""}. 임대료 관리에서 매칭을 실행하세요.` });
    } catch (e) { onMsg({ ok: false, text: (e as Error).message }); }
    setBusy(false);
  };
  const noBalance = chosen.some((r) => r.balance_after == null);

  return (
    <section className="space-y-3">
      <Picker enabled={enabled} busy={busy} mode={mode} stage={stage} label="은행 앱·인터넷뱅킹 거래내역 캡처 고르기 (긴 캡처는 잘라서 읽음)" onPick={pick} />
      <p className="text-xs text-slate-500">은행에서 CSV·엑셀을 받을 수 있으면 <Link href="/payments" className="underline">임대료 관리</Link>의 파일 가져오기가 더 정확합니다.
        나중에 같은 기간 파일을 올려도 날짜·시각·금액·잔액이 같은 거래는 한 번만 들어갑니다.</p>
      <Notes notes={notes} />
      {rows.length > 0 && (
        <div className="card overflow-x-auto p-3">
          <table className="w-full min-w-[48rem] text-xs">
            <thead className="text-left text-slate-500"><tr>
              <th className="p-1">넣기</th><th className="p-1">날짜</th><th className="p-1">시각</th><th className="p-1">구분</th><th className="p-1">금액</th>
              <th className="p-1">보낸·받는 사람</th><th className="p-1">적요</th><th className="p-1">잔액</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="p-1"><input type="checkbox" aria-label={`${i + 1}번째 거래 넣기`} checked={r.pick && ready(r)} disabled={!ready(r)}
                    onChange={(e) => set(i, { pick: e.target.checked })} /></td>
                  <td className="p-1"><input type="date" className="field" aria-label="날짜" value={r.date ?? ""} onChange={(e) => set(i, { date: txt(e.target.value) })} /></td>
                  <td className="p-1"><input className="field w-16" aria-label="시각" placeholder="—" value={r.time ?? ""} onChange={(e) => set(i, { time: txt(e.target.value) })} /></td>
                  <td className="p-1"><select className="field" aria-label="구분" value={r.direction ?? ""} onChange={(e) => set(i, { direction: (e.target.value || null) as BankRow["direction"] })}>
                    <option value="">?</option><option value="in">입금</option><option value="out">출금</option></select></td>
                  <td className="p-1"><input className="field w-24" inputMode="numeric" aria-label="금액" value={r.amount ?? ""} onChange={(e) => set(i, { amount: num(e.target.value) })} /></td>
                  <td className="p-1"><input className="field w-28" aria-label="보낸·받는 사람" value={r.counterparty ?? ""} onChange={(e) => set(i, { counterparty: txt(e.target.value) })} /></td>
                  <td className="p-1"><input className="field w-24" aria-label="적요" value={r.description ?? ""} onChange={(e) => set(i, { description: txt(e.target.value) })} /></td>
                  <td className="p-1"><input className="field w-28" inputMode="numeric" aria-label="잔액" placeholder="—" value={r.balance_after ?? ""} onChange={(e) => set(i, { balance_after: num(e.target.value) })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {accounts.length > 1 && <select className="field" aria-label="통장" value={acct} onChange={(e) => setAcct(e.target.value)}>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.alias}</option>)}</select>}
            <button type="button" className="btn-primary btn-sm" disabled={busy || !acct || chosen.length === 0} onClick={save}>
              <Upload className="h-3.5 w-3.5" />확인한 {chosen.length}건 통장 내역에 넣기</button>
            <span className="text-xs text-slate-500">입금 {won(chosen.filter((r) => r.direction === "in").reduce((s, r) => s + (r.amount ?? 0), 0))}
              {" "}· 출금 {won(chosen.filter((r) => r.direction === "out").reduce((s, r) => s + (r.amount ?? 0), 0))}</span>
          </div>
          {noBalance && <p className="mt-1 text-xs text-amber-800">잔액이 비어 있는 줄은 나중에 같은 기간 파일을 올리면 중복으로 들어갈 수 있습니다. 가능하면 잔액까지 보이게 캡처하세요.</p>}
        </div>
      )}
    </section>
  );
}
