"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AllocationOut,
  type BankAccount,
  type ImportOut,
  type Category,
  CATEGORY_LABEL,
  kst,
  type LeaseOut,
  type Organization,
  type QueueItem,
  type Receivables,
  won,
} from "@/lib/api";

const btn =
  "btn";
const select = "field py-1.5";
const LEASE_CATEGORIES: Category[] = ["rent", "deposit_in"];

export default function PaymentsPage() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [orgId, setOrgId] = useState<string>("");
  const [leases, setLeases] = useState<LeaseOut[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [recv, setRecv] = useState<Receivables | null>(null);
  const [recent, setRecent] = useState<AllocationOut[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [asOf, setAsOf] = useState<string>(
    () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }));

  useEffect(() => {
    api<Organization[]>("/api/v1/organizations")
      .then((os) => {
        setOrgs(os);
        if (os.length) setOrgId(os[os.length - 1].id);
      })
      .catch((e) => setError(e.message));
  }, []);

  const q = `organization_id=${orgId}`;
  const reload = useCallback(async () => {
    if (!orgId) return;
    try {
      const [l, qu, r, a] = await Promise.all([
        api<LeaseOut[]>(`/api/v1/leases?${q}`),
        api<QueueItem[]>(`/api/v1/matching/queue?${q}`),
        api<Receivables>(`/api/v1/receivables?${q}&as_of=${asOf}`),
        api<AllocationOut[]>(`/api/v1/allocations?${q}&limit=20`),
      ]);
      setLeases(l); setQueue(qu); setRecv(r); setRecent(a);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, q, asOf]);

  useEffect(() => { reload(); }, [reload]);

  async function act(fn: () => Promise<string | void>, done?: string) {
    setError(null); setNotice(null); setBusy(true);
    try {
      const message = await fn();
      await reload();
      if (typeof message === "string") setNotice(message);
      else if (done) setNotice(done);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const runMatching = () =>
    act(async () => {
      const r = await api<{ auto_confirmed: number; pending: number }>(
        `/api/v1/matching/run?${q}`, { method: "POST" });
      return `자동 확정 ${r.auto_confirmed}건 · 검토 대기에 추가 ${r.pending}건`;
    });

  if (orgs && orgs.length === 0) {
    return (
      <p className="text-slate-600">
        아직 등록된 건물이 없습니다. <a className="underline" href="/onboarding">초기 등록</a>부터 하세요.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="page-title">임대료 관리</h1>
          <p className="page-sub">통장 입금을 호실별 월세와 맞추고, 미수를 확인합니다.</p>
        </div>
        {orgs && orgs.length > 1 && (
          <select className={select} aria-label="사업장" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}
        <button type="button" disabled={busy || !orgId} onClick={runMatching}
          className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>
          입금 매칭 실행
        </button>
      </div>

      <BankImport orgId={orgId} busy={busy} onFile={(accountId, file) => act(async () => {
        const fd = new FormData();
        fd.append("file", file);
        const r = await api<ImportOut>(`/api/v1/bank-accounts/${accountId}/import`, { method: "POST", body: fd });
        const errs = r.errors.length ? ` · 읽지 못한 행 ${r.errors.length}개 (${r.errors.slice(0, 3).map((e) => `${e.row}행`).join(", ")}${r.errors.length > 3 ? " …" : ""})` : "";
        const merged = r.merged_alerts ? ` · 입금 알림과 합침 ${r.merged_alerts}` : "";
        const orphan = r.alerts_without_statement
          ? ` ⚠ 이 기간의 입금 알림 ${r.alerts_without_statement}건이 내역에 없습니다 — 다른 계좌 알림이거나 잘못 읽은 알림일 수 있으니 확인하세요.` : "";
        return `${file.name}: 전체 ${r.total_rows}건 · 새로 저장 ${r.inserted} · 이미 있음 ${r.duplicates}${merged}${errs}. 이어서 '입금 매칭 실행'을 누르세요.${orphan}`;
      })} />

      {notice && <p className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
      {error && <p className="whitespace-pre-line rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}

      <ReviewQueue queue={queue} leases={leases} busy={busy}
        onDecide={(txnId, body) => act(() => api(`/api/v1/transactions/${txnId}/decision?${q}`, {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        }), "확정했습니다.")} />

      {recv && <ReceivablesView recv={recv} asOf={asOf} onAsOf={setAsOf} />}

      <section className="space-y-2">
        <h2 className="card-title">최근 확정</h2>
        {recent.length === 0 && <p className="text-sm text-slate-500">아직 없습니다.</p>}
        <ul className="divide-y card">
          {recent.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
              <span className="tabular-nums text-slate-500">{kst(a.transaction.occurred_at)}</span>
              <span>{a.transaction.counterparty ?? "—"}</span>
              <span className="tabular-nums font-medium">{won(a.amount)}</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                {a.unit_no ? `${a.unit_no} · ` : ""}{CATEGORY_LABEL[a.category] ?? a.category}
              </span>
              <span className="w-full text-xs text-slate-500 sm:w-auto sm:flex-1">{a.reason}</span>
              <button type="button" disabled={busy} className="text-xs text-slate-500 hover:text-red-700"
                onClick={() => act(() => api(`/api/v1/allocations/${a.id}/cancel?${q}`, { method: "POST" }),
                  "확정을 취소했습니다. 해당 거래는 검토 대기로 돌아갔습니다.")}>
                취소
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ReviewQueue({ queue, leases, busy, onDecide }: {
  queue: QueueItem[];
  leases: LeaseOut[];
  busy: boolean;
  onDecide: (txnId: string, body: { lease_id: string | null; category: Category; remember_alias: boolean }) => void;
}) {
  return (
    <section className="space-y-2">
      <h2 className="card-title">
        검토 대기 <span className="text-slate-500">{queue.length}</span>
      </h2>
      <p className="text-xs text-slate-500">
        입금자와 금액이 확실히 일치하는 것만 자동 확정됩니다. 나머지는 여기서 직접 확정하세요.
      </p>
      {queue.length === 0 && <p className="text-sm text-slate-500">검토할 입금이 없습니다.</p>}
      {queue.map((item) => (
        // 제안이 바뀌면 (매칭 실행 후 등) 카드 입력값을 새 제안으로 다시 채운다
        <QueueCard key={`${item.transaction.id}:${item.suggestion?.allocation_id ?? "none"}`} item={item} leases={leases} busy={busy} onDecide={onDecide} />
      ))}
    </section>
  );
}

function QueueCard({ item, leases, busy, onDecide }: {
  item: QueueItem;
  leases: LeaseOut[];
  busy: boolean;
  onDecide: (txnId: string, body: { lease_id: string | null; category: Category; remember_alias: boolean }) => void;
}) {
  const s = item.suggestion;
  const t = item.transaction;
  const [category, setCategory] = useState<Category>(
    s && s.category in CATEGORY_LABEL && s.category !== "unclassified" ? (s.category as Category) : "rent");
  const [leaseId, setLeaseId] = useState<string>(s?.lease_id ?? "");
  const lease = leases.find((l) => l.lease_id === leaseId);
  const differsFromTenant = !!(t.counterparty && lease && t.counterparty.replace(/\s/g, "") !== lease.tenant_name.replace(/\s/g, ""));
  const [remember, setRemember] = useState(false);
  const needsLease = LEASE_CATEGORIES.includes(category);

  return (
    <div className="card p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="tabular-nums text-slate-500">{kst(t.occurred_at)}</span>
        <span className="font-medium">{t.counterparty ?? "(입금자 없음)"}</span>
        <span className="tabular-nums text-base font-semibold">{won(t.amount)}</span>
        {t.description && <span className="text-xs text-slate-500">{t.description}</span>}
      </div>
      <p className="mt-1 text-xs text-slate-600">
        {s ? (
          <>
            {s.reason}
            {s.confidence != null && (
              <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">
                신뢰도 {Math.round(s.confidence * 100)}%
              </span>
            )}
          </>
        ) : "제안 없음 (거절했거나 확정을 취소한 거래)"}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select className={select} aria-label={`${t.counterparty ?? "입금"} 분류`} value={category} onChange={(e) => setCategory(e.target.value as Category)}>
          {(["rent", "deposit_in", "personal", "owner_household", "other"] as Category[]).map((c) => (
            <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
          ))}
        </select>
        {needsLease && (
          <select className={select} aria-label={`${t.counterparty ?? "입금"} 호실`} value={leaseId} onChange={(e) => setLeaseId(e.target.value)}>
            <option value="">호실 선택</option>
            {leases.map((l) => (
              <option key={l.lease_id} value={l.lease_id}>{l.unit_no} · {l.tenant_name} · {won(l.rent)}</option>
            ))}
          </select>
        )}
        {needsLease && differsFromTenant && (
          <label className="flex items-center gap-1 text-xs text-slate-600">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            &lsquo;{t.counterparty}&rsquo; = {lease?.unit_no} 로 기억 (다음부터 자동)
          </label>
        )}
        <button type="button" disabled={busy || (needsLease && !leaseId)}
          className={`${btn} ml-auto bg-blue-600 text-white hover:bg-blue-700`}
          onClick={() => onDecide(t.id, {
            lease_id: needsLease ? leaseId : null, category, remember_alias: needsLease && remember,
          })}>
          확정
        </button>
      </div>
    </div>
  );
}

function ReceivablesView({ recv, asOf, onAsOf }: {
  recv: Receivables; asOf: string; onAsOf: (d: string) => void;
}) {
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">미수 현황</h2>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          기준일
          <input type="date" className={select} value={asOf}
            onChange={(e) => e.target.value && onAsOf(e.target.value)} />
        </label>
      </div>
      <div className="rounded-xl bg-slate-100 p-3 text-xs text-slate-700">
        은행 내역 최신 거래: <b>{kst(recv.bank_data_as_of)}</b>
        {recv.pending_review > 0 && (
          <> · 검토 대기 <b>{recv.pending_review}건</b> — 확정 전에는 아래 미수가 실제로는 납부됐을 수 있습니다.</>
        )}
        <br />연락·독촉은 최신 내역을 가져오고 검토를 마친 뒤 직접 판단하세요. 자동 발송하지 않습니다.
      </div>
      {recv.items.length === 0 ? (
        <p className="text-sm text-slate-500">납부일이 지난 미수가 없습니다.</p>
      ) : (
        <div className="overflow-x-auto card">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr>
                <th className="p-2">호실</th><th className="p-2">청구월</th><th className="p-2">납부일</th>
                <th className="p-2 text-right">받은 금액</th><th className="p-2 text-right">미수</th>
                <th className="p-2 text-right">경과</th>
              </tr>
            </thead>
            <tbody>
              {recv.items.map((i) => (
                <tr key={`${i.unit_no}-${i.period}`} className="border-t">
                  <td className="p-2">{i.unit_no} <span className="text-slate-500">{i.tenant_name}</span></td>
                  <td className="p-2">{i.period}</td>
                  <td className="p-2 tabular-nums">{i.due_date}</td>
                  <td className="p-2 text-right tabular-nums">{won(i.paid)}</td>
                  <td className="p-2 text-right font-medium tabular-nums">{won(i.outstanding)}</td>
                  <td className="p-2 text-right tabular-nums">{i.days_past_due}일</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {recv.credits.length > 0 && (
        <p className="text-xs text-slate-600">
          선납 잔액(다음 청구에 자동 차감): {recv.credits.map((c) => `${c.unit_no} ${won(c.credit)}`).join(" · ")}
        </p>
      )}
    </section>
  );
}

function BankImport({ orgId, busy, onFile }: {
  orgId: string; busy: boolean; onFile: (accountId: string, file: File) => void;
}) {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [accountId, setAccountId] = useState("");
  useEffect(() => {
    if (!orgId) return;
    api<BankAccount[]>(`/api/v1/bank-accounts?organization_id=${orgId}`)
      .then((a) => { setAccounts(a); setAccountId(a[0]?.id ?? ""); })
      .catch(() => setAccounts([]));
  }, [orgId]);
  if (!accounts.length) return null;
  return (
    <section className="flex flex-wrap items-center gap-2 rounded-2xl border border-dashed border-slate-300 bg-white p-3 text-sm">
      <span className="mr-auto text-slate-600">
        은행 거래내역 가져오기 <span className="text-xs text-slate-500">(CSV·XLSX, 같은 파일을 다시 올려도 중복 없음)</span>
      </span>
      {accounts.length > 1 && (
        <select className={select} aria-label="은행 계좌" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.alias}</option>)}
        </select>
      )}
      <label className={`${btn} cursor-pointer border bg-white hover:bg-slate-50 ${busy ? "pointer-events-none opacity-50" : ""}`}>
        파일 선택
        <input type="file" accept=".csv,.xlsx" className="hidden" disabled={busy}
          onChange={(e) => { const f = e.target.files?.[0]; if (f && accountId) onFile(accountId, f); e.target.value = ""; }} />
      </label>
    </section>
  );
}
