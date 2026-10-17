"use client";

import { BellRing, Check, Copy, Loader2, Unplug } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type BankAccount, kst, won } from "@/lib/api";

interface Preview { direction: "in" | "out" | null; amount: number | null; counterparty: string | null;
  balance_after: number | null; occurred_at: string | null; time_from_text: boolean; problem: string | null }
interface Recent { id: string; account: string; text: string; status: "created" | "duplicate" | "unparsed" | "outgoing";
  created_at: string; parsed: Preview | null }

const STATUS: Record<Recent["status"], [string, string]> = {
  created: ["거래로 넣음", "bg-emerald-50 text-emerald-700"],
  duplicate: ["이미 있음", "bg-slate-100 text-slate-600"],
  unparsed: ["읽지 못함", "bg-amber-50 text-amber-700"],
  outgoing: ["출금 (무시)", "bg-slate-100 text-slate-600"],
};
const SAMPLE = "[KB]\n123456**789\n홍길동\n입금\n450,000\n잔액12,876,500";

export default function BankAlertCard({ orgId, canWrite }: { orgId: string; canWrite: boolean }) {
  const [accounts, setAccounts] = useState<BankAccount[] | null>(null);
  const [accountId, setAccountId] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const q = `organization_id=${orgId}`;

  const load = useCallback(async () => {
    const list = await api<BankAccount[]>(`/api/v1/bank-accounts?${q}`);
    setAccounts(list);
    setAccountId((cur) => cur || list[0]?.id || "");
    setRecent(await api<Recent[]>(`/api/v1/bank-alerts?${q}&limit=10`));
  }, [q]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: (e as Error).message })); }, [load]);

  const account = accounts?.find((a) => a.id === accountId);

  async function create() {
    if (account?.alert_since && !confirm("새 주소를 만들면 지금 휴대폰에 넣어 둔 주소는 바로 끊깁니다. 계속할까요?")) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ token: string; path: string }>(`/api/v1/bank-accounts/${accountId}/alert-token?${q}`, { method: "POST" });
      setUrl(`${window.location.origin}${r.path}${r.token}`); setCopied(false);
      await load();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  async function revoke() {
    if (!confirm("연결을 끊으면 휴대폰이 보내는 알림을 더는 받지 않습니다. 끊을까요?")) return;
    setBusy(true); setMsg(null);
    try {
      await api(`/api/v1/bank-accounts/${accountId}/alert-token?${q}`, { method: "DELETE" });
      setUrl(null);
      await load();
      setMsg({ ok: true, text: "연결을 끊었습니다." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  async function test() {
    setPreview(null);
    try {
      setPreview(await api<Preview>(`/api/v1/bank-alerts/preview?${q}`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: text || SAMPLE }) }));
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }

  async function copy() {
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setCopied(true); } catch { setCopied(false); }
  }

  return (
    <section id="bank-alerts" className="card p-5 xl:col-span-2">
      <div className="mb-4 flex gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-600"><BellRing className="h-5 w-5" /></span>
        <div>
          <h2 className="card-title">입금 알림 자동 연결</h2>
          <p className="mt-0.5 text-sm text-slate-500">은행 앱 알림·문자를 휴대폰이 이 주소로 보내면, 납부일에 입금을 바로 확인합니다. 사업자등록·공동인증서가 없어도 됩니다.</p>
        </div>
      </div>

      <div className="grid gap-5 text-sm lg:grid-cols-2">
        <div className="space-y-3">
          {accounts && accounts.length === 0 && <p className="text-slate-500">등록된 계좌가 없습니다. 호실 등록 때 계좌를 만드세요.</p>}
          {accounts && accounts.length > 1 && (
            <select className="field w-full" value={accountId} aria-label="계좌" onChange={(e) => { setAccountId(e.target.value); setUrl(null); }}>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.alias}</option>)}
            </select>
          )}
          {account && (
            <p className={account.alert_since ? "text-emerald-700" : "text-slate-600"}>
              {account.alias}: {account.alert_since ? `연결됨 (${kst(account.alert_since)}에 만든 주소)` : "연결 안 됨"}
            </p>
          )}
          {account && canWrite && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-primary" disabled={busy} onClick={create}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}{account.alert_since ? "새 주소로 바꾸기" : "연결 주소 만들기"}</button>
              {account.alert_since && <button type="button" className="btn-secondary" disabled={busy} onClick={revoke}><Unplug className="h-4 w-4" />연결 끊기</button>}
            </div>
          )}
          {url && (
            <div className="space-y-2 rounded-xl border border-blue-100 bg-blue-50 p-3">
              <p className="font-medium text-blue-900">이 주소는 지금 한 번만 보여 드립니다. 휴대폰 자동화 앱에 붙여 넣으세요.</p>
              <div className="flex gap-2">
                <input className="field min-w-0 flex-1 font-mono text-xs" readOnly value={url} aria-label="연결 주소" onFocus={(e) => e.target.select()} />
                <button type="button" className="btn-secondary shrink-0" onClick={copy}>{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{copied ? "복사됨" : "복사"}</button>
              </div>
              <p className="text-xs text-blue-900">주소를 아는 사람은 입금 알림을 넣을 수 있으니 다른 사람에게 보내지 마세요. 잃어버리면 새로 만들면 됩니다 (예전 주소는 끊김).</p>
            </div>
          )}

          <details className="rounded-xl border border-slate-100 p-3">
            <summary className="cursor-pointer font-medium">안드로이드 — MacroDroid (무료)</summary>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-slate-600">
              <li>트리거: <b>알림 수신</b> → 은행 앱 선택 (또는 <b>SMS 수신</b> → 은행 번호)</li>
              <li>제약(선택): 알림 내용에 &lsquo;입금&rsquo; 포함</li>
              <li>동작: <b>HTTP 요청</b> · 방식 POST · 위 주소 · 본문 형식 application/json</li>
              <li>본문: <code className="rounded bg-slate-100 px-1">{`{"text": "[notification_title] [notification]"}`}</code> (문자면 <code className="rounded bg-slate-100 px-1">[sms_message]</code>) — 매직 텍스트 이름은 앱 버전에 따라 다를 수 있습니다</li>
              <li>배터리 최적화에서 MacroDroid 제외</li>
            </ol>
          </details>
          <details className="rounded-xl border border-slate-100 p-3">
            <summary className="cursor-pointer font-medium">아이폰 — 단축어 (문자 알림만)</summary>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-slate-600">
              <li>아이폰은 다른 앱의 푸시 알림을 읽을 수 없어 <b>은행 입출금 문자 알림</b>을 신청해야 합니다 (은행에 따라 유료).</li>
              <li>단축어 → 자동화 → <b>메시지</b> · 보낸 사람: 은행 번호 · 메시지에 &lsquo;입금&rsquo; 포함 · <b>즉시 실행</b></li>
              <li>동작: <b>URL 콘텐츠 가져오기</b> · 위 주소 · 방법 POST · 본문 JSON · 키 <code className="rounded bg-slate-100 px-1">text</code> = 단축어 입력(메시지 내용)</li>
            </ol>
          </details>
          <p className="text-xs text-slate-500">알림은 &lsquo;들어왔다&rsquo;는 증거일 뿐이라, 알림이 없다고 미납으로 보지 않습니다. 미납·결산은 지금처럼 통장 내역 파일로 판단하고,
            내역을 올리면 알림으로 먼저 들어온 거래와 자동으로 합쳐집니다. 자동 확정 규칙도 같습니다 (입금자·금액이 확실할 때만).</p>
        </div>

        <div className="space-y-3">
          <label className="block font-medium">알림 문장 시험 (저장하지 않음)
            <textarea className="field mt-1 h-28 w-full font-mono text-xs" placeholder={SAMPLE} value={text} onChange={(e) => setText(e.target.value)} /></label>
          <button type="button" className="btn-secondary" onClick={test}>읽어 보기</button>
          {preview && (
            <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1 rounded-xl bg-slate-50 p-3">
              {preview.problem ? <><dt>결과</dt><dd className="text-amber-700">거래로 넣지 않음 — {preview.problem}</dd></> : null}
              <dt>구분</dt><dd>{preview.direction === "in" ? "입금" : preview.direction === "out" ? "출금 (무시)" : "—"}</dd>
              <dt>금액</dt><dd>{preview.amount == null ? "—" : won(preview.amount)}</dd>
              <dt>입금자</dt><dd>{preview.counterparty ?? "— (모르면 금액이 맞아도 검토 대기)"}</dd>
              <dt>잔액</dt><dd>{preview.balance_after == null ? "—" : won(preview.balance_after)}</dd>
              <dt>시각</dt><dd>{preview.occurred_at ? `${kst(preview.occurred_at)}${preview.time_from_text ? "" : " (받은 시각)"}` : "—"}</dd>
            </dl>
          )}
          <p className="text-xs text-slate-500">잘 안 읽히는 은행이 있으면 알림 문장(이름·금액은 바꿔서)을 알려 주세요. 형식을 추가합니다.</p>

          <h3 className="pt-2 font-medium">최근 받은 알림</h3>
          {recent.length === 0 ? <p className="text-slate-500">아직 받은 알림이 없습니다.</p> : (
            <ul className="divide-y divide-slate-100">
              {recent.map((r) => {
                const [label, tone] = STATUS[r.status];
                return (
                  <li key={r.id} className="flex items-start justify-between gap-2 py-1.5">
                    <span className="min-w-0"><span className="text-xs text-slate-500">{kst(r.created_at)} · {r.account}</span>
                      <span className="block truncate">{r.parsed?.amount != null ? `${won(r.parsed.amount)} ${r.parsed.counterparty ?? ""}` : r.text.slice(0, 40)}</span></span>
                    <span className={`chip shrink-0 ${tone}`}>{label}</span>
                  </li>);
              })}
            </ul>
          )}
        </div>
      </div>
      {msg && <p className={`mt-3 rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</p>}
    </section>
  );
}
