"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  CATEGORY_LABEL,
  type ConfirmedOut,
  type ExpenseCategory,
  type ExpenseOut,
  type ExpenseRuleOut,
  kst,
  type LeaseOut,
  type MonthlyReport,
  NON_OPERATING,
  OPERATING,
  type OutCategory,
  type QueueItem,
  thisMonthKst,
  todayKst,
  type UnitOut,
  won,
} from "@/lib/api";
import { useOrg } from "@/lib/useOrg";

const btn = "btn";
const primary = `${btn} bg-blue-600 text-white hover:bg-blue-700`;
const field = "field py-1.5";
const EXPENSE_CATS: ExpenseCategory[] = [...OPERATING, ...NON_OPERATING];
const OUT_CATS: OutCategory[] = [...EXPENSE_CATS, "deposit_out"];

const toInt = (s: string) => {
  const v = s.replace(/[,\s원]/g, "");
  return /^\d+$/.test(v) ? Number(v) : 0;
};

export default function ExpensesPage() {
  const { orgs, orgId, setOrgId, error: orgError } = useOrg();
  const [period, setPeriod] = useState(thisMonthKst());
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [confirmed, setConfirmed] = useState<ConfirmedOut[]>([]);
  const [list, setList] = useState<ExpenseOut[]>([]);
  const [rules, setRules] = useState<ExpenseRuleOut[]>([]);
  const [units, setUnits] = useState<UnitOut[]>([]);
  const [leases, setLeases] = useState<LeaseOut[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const q = `organization_id=${orgId}`;
  const reload = useCallback(async () => {
    if (!orgId) return;
    try {
      const [r, qu, c, l, ru, u, le] = await Promise.all([
        api<MonthlyReport>(`/api/v1/reports/monthly?${q}&period=${period}`),
        api<QueueItem[]>(`/api/v1/expenses/queue?${q}`),
        api<ConfirmedOut[]>(`/api/v1/expenses/confirmed?${q}&limit=20`),
        api<ExpenseOut[]>(`/api/v1/expenses?${q}&period=${period}`),
        api<ExpenseRuleOut[]>(`/api/v1/expense-rules?${q}`),
        api<UnitOut[]>(`/api/v1/units?${q}`),
        api<LeaseOut[]>(`/api/v1/leases?${q}`),
      ]);
      setReport(r); setQueue(qu); setConfirmed(c); setList(l); setRules(ru); setUnits(u); setLeases(le);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, q, period]);

  useEffect(() => { reload(); }, [reload]);

  async function act(fn: () => Promise<string | void>, done?: string): Promise<boolean> {
    setError(null); setNotice(null); setBusy(true);
    try {
      const message = await fn();
      await reload();
      setNotice(typeof message === "string" ? message : done ?? null);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const post = (path: string, body?: unknown) =>
    api(path, {
      method: "POST",
      ...(body ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}),
    });

  if (orgs && orgs.length === 0) {
    return <p className="text-slate-600">아직 등록된 건물이 없습니다. <a className="underline" href="/onboarding">초기 등록</a>부터 하세요.</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="page-title">지출·운영비</h1>
          <p className="page-sub">통장 출금을 운영비·주인세대·생활비로 나누고 순운영수익을 계산합니다.</p>
        </div>
        {orgs && orgs.length > 1 && (
          <select className={field} value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}
        <button type="button" disabled={busy || !orgId} className={primary}
          onClick={() => act(async () => {
            const r = await api<{ auto_confirmed: number; pending: number }>(
              `/api/v1/expenses/classify?${q}`, { method: "POST" });
            return `기억한 규칙으로 자동 확정 ${r.auto_confirmed}건 · 검토 대기에 추가 ${r.pending}건`;
          })}>
          출금 자동 분류
        </button>
      </div>

      {notice && <p className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
      {(error || orgError) && (
        <p className="whitespace-pre-line rounded-xl bg-red-50 p-3 text-sm text-red-800">{error ?? orgError}</p>
      )}

      {report && <Report report={report} period={period} onPeriod={setPeriod} />}

      <section className="space-y-2">
        <h2 className="card-title">출금 검토 대기 <span className="text-slate-500">{queue.length}</span></h2>
        <p className="text-xs text-slate-500">
          &lsquo;기억&rsquo;한 거래처만 자동 확정됩니다. 한국전력·마트 같은 이름만으로는 공용/주인세대/생활비를
          알 수 없어 제안까지만 합니다. 섞인 거래는 나눠서 확정하세요.
        </p>
        {queue.length === 0 && <p className="text-sm text-slate-500">검토할 출금이 없습니다.</p>}
        {queue.map((item) => (
          <OutCard key={`${item.transaction.id}:${item.suggestion?.allocation_id ?? "none"}`}
            item={item} units={units} leases={leases} busy={busy}
            onDecide={(body) => act(() => post(`/api/v1/transactions/${item.transaction.id}/expense-decision?${q}`, body)
              .then(() => undefined), "확정했습니다.")} />
        ))}
      </section>

      <ManualExpense units={units} busy={busy}
        onAdd={(body) => act(() => post(`/api/v1/expenses?${q}`, body).then(() => undefined), "현금 지출을 기록했습니다.")} />

      <section className="space-y-2">
        <h2 className="card-title">{period} 지출 내역</h2>
        {list.length === 0 && <p className="text-sm text-slate-500">없습니다.</p>}
        <ul className="divide-y card">
          {list.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
              <span className="tabular-nums text-slate-500">{e.spent_on}</span>
              <CategoryChip category={e.category} />
              {e.unit_no && <span className="text-xs text-slate-500">{e.unit_no}호</span>}
              <span className="tabular-nums font-medium">{won(e.amount)}</span>
              <span className="flex-1 text-xs text-slate-500">{e.memo ?? (e.from_bank ? "은행 출금" : "")}</span>
              {!e.from_bank && (
                <button type="button" disabled={busy} className="text-xs text-slate-500 hover:text-red-700"
                  onClick={() => act(() => api(`/api/v1/expenses/${e.id}?${q}`, { method: "DELETE" }).then(() => undefined),
                    "삭제했습니다.")}>삭제</button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="card-title">최근 확정 출금</h2>
        {confirmed.length === 0 && <p className="text-sm text-slate-500">아직 없습니다.</p>}
        <ul className="divide-y card">
          {confirmed.map((c) => (
            <li key={c.transaction.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
              <span className="tabular-nums text-slate-500">{kst(c.transaction.occurred_at)}</span>
              <span>{c.transaction.counterparty ?? c.transaction.description ?? "—"}</span>
              <span className="tabular-nums font-medium">{won(c.transaction.amount)}</span>
              <span className="flex flex-wrap gap-1">
                {c.splits.map((s, i) => (
                  <span key={i} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                    {CATEGORY_LABEL[s.category] ?? s.category}{s.unit_no ? `(${s.unit_no})` : ""}
                    {c.splits.length > 1 ? ` ${won(s.amount)}` : ""}
                  </span>
                ))}
              </span>
              <span className="w-full text-xs text-slate-500 sm:w-auto sm:flex-1">{c.reason}</span>
              <button type="button" disabled={busy} className="text-xs text-slate-500 hover:text-red-700"
                onClick={() => act(() => post(`/api/v1/transactions/${c.transaction.id}/expense-cancel?${q}`)
                  .then(() => undefined), "확정을 취소했습니다. 거래는 검토 대기로 돌아갔습니다.")}>
                취소
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="card-title">기억한 거래처 규칙</h2>
        {rules.length === 0 && <p className="text-sm text-slate-500">없습니다. 확정할 때 &lsquo;기억&rsquo;을 고르면 생깁니다.</p>}
        <ul className="divide-y card">
          {rules.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
              <span className="font-medium">{r.label}</span>
              <span className="flex-1 text-xs text-slate-600">
                {r.splits.map((s) => `${CATEGORY_LABEL[s.category] ?? s.category} ${s.bp / 100}%`).join(" + ")}
              </span>
              <button type="button" disabled={busy} className="text-xs text-slate-500 hover:text-red-700"
                onClick={() => act(() => api(`/api/v1/expense-rules/${r.id}?${q}`, { method: "DELETE" }).then(() => undefined),
                  "규칙을 지웠습니다. 이미 확정된 거래는 그대로입니다.")}>지우기</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function CategoryChip({ category }: { category: string }) {
  const operating = (OPERATING as readonly string[]).includes(category);
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs ${operating ? "bg-sky-50 text-sky-900" : "bg-slate-100 text-slate-700"}`}>
      {CATEGORY_LABEL[category] ?? category}
    </span>
  );
}

function Report({ report: r, period, onPeriod }: {
  report: MonthlyReport; period: string; onPeriod: (p: string) => void;
}) {
  return (
    <section className="card space-y-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">월 결산</h2>
        <input type="month" className={field} value={period} onChange={(e) => e.target.value && onPeriod(e.target.value)} />
      </div>
      {!r.complete && (
        <p className="rounded-xl bg-amber-50 p-2 text-xs text-amber-900">
          확정 전 수치 — 이 달 미확정 거래: 입금 {r.unconfirmed_in}건 · 출금 {r.unconfirmed_out}건.
          수납·운영비 검토를 마치면 확정 수치가 됩니다.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="월세 청구" value={won(r.rent_charged)} />
        <Stat label="월세 입금(확정)" value={won(r.rent_received)} />
        <Stat label="운영비" value={won(r.operating_total)} />
        <Stat label="순운영수익" value={won(r.noi)} strong />
      </div>
      <div className="grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-medium text-slate-500">운영비 내역 (순운영수익에 반영)</h3>
          <dl className="space-y-0.5">
            {OPERATING.map((c) => (
              <div key={c} className="flex justify-between"><dt>{CATEGORY_LABEL[c]}</dt>
                <dd className="tabular-nums">{won(r.operating[c] ?? 0)}</dd></div>
            ))}
          </dl>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-medium text-slate-500">순운영수익에서 제외</h3>
          <dl className="space-y-0.5">
            {(["personal", "owner_household", "deposit_in", "deposit_out"] as const).map((c) => (
              <div key={c} className="flex justify-between"><dt>{CATEGORY_LABEL[c]}</dt>
                <dd className="tabular-nums">{won(r.excluded[c] ?? 0)}</dd></div>
            ))}
          </dl>
          <p className="mt-1 text-xs text-slate-500">보증금은 돌려줄 돈(부채)이라 수입·비용이 아닙니다.</p>
        </div>
      </div>
      <p className="text-xs text-slate-500">은행 내역 최신 거래: {kst(r.bank_data_as_of)}</p>
    </section>
  );
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`rounded-xl p-3 ${strong ? "bg-blue-600 text-white" : "bg-slate-50"}`}>
      <div className={`text-xs ${strong ? "text-blue-100" : "text-slate-500"}`}>{label}</div>
      <div className="mt-0.5 font-semibold tabular-nums">{value}</div>
    </div>
  );
}

type SplitRow = { key: number; category: OutCategory; amount: string; unit_id: string };
let splitKey = 1;

function OutCard({ item, units, leases, busy, onDecide }: {
  item: QueueItem; units: UnitOut[]; leases: LeaseOut[]; busy: boolean;
  onDecide: (body: { splits: { category: OutCategory; amount: number; unit_id: string | null }[];
    lease_id: string | null; remember: boolean }) => void;
}) {
  const t = item.transaction;
  const s = item.suggestion;
  const initial = (s && (OUT_CATS as string[]).includes(s.category) ? s.category : "other_operating") as OutCategory;
  const [rows, setRows] = useState<SplitRow[]>([{ key: splitKey++, category: initial, amount: String(t.amount), unit_id: "" }]);
  const [leaseId, setLeaseId] = useState(s?.lease_id ?? "");
  const [remember, setRemember] = useState(false);

  const total = rows.reduce((a, r) => a + toInt(r.amount), 0);
  const remaining = t.amount - total;
  const isDeposit = rows.some((r) => r.category === "deposit_out");
  const valid = remaining === 0 && rows.every((r) => toInt(r.amount) > 0)
    && (!isDeposit || (rows.length === 1 && leaseId !== ""));
  const update = (key: number, patch: Partial<SplitRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  return (
    <div className="card p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="tabular-nums text-slate-500">{kst(t.occurred_at)}</span>
        <span className="font-medium">{t.counterparty ?? "(거래처 없음)"}</span>
        <span className="text-base font-semibold tabular-nums">{won(t.amount)}</span>
        {t.description && <span className="text-xs text-slate-500">{t.description}</span>}
      </div>
      <p className="mt-1 text-xs text-slate-600">
        {s ? <>{s.reason}{s.confidence != null && (
          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">신뢰도 {Math.round(s.confidence * 100)}%</span>
        )}</> : "제안 없음 (확정을 취소한 거래)"}
      </p>

      <div className="mt-2 space-y-2">
        {rows.map((r) => (
          <div key={r.key} className="flex flex-wrap items-center gap-2">
            <select className={field} value={r.category} onChange={(e) => update(r.key, { category: e.target.value as OutCategory })}>
              <optgroup label="운영비">
                {OPERATING.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
              </optgroup>
              <optgroup label="운영비 아님">
                {NON_OPERATING.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
                <option value="deposit_out">{CATEGORY_LABEL.deposit_out}</option>
              </optgroup>
            </select>
            <input className={`${field} w-32 text-right tabular-nums`} inputMode="numeric" value={r.amount}
              aria-label="금액" onChange={(e) => update(r.key, { amount: e.target.value })} />
            {r.category === "repair" && (
              <select className={field} value={r.unit_id} onChange={(e) => update(r.key, { unit_id: e.target.value })}>
                <option value="">호실 (선택)</option>
                {units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_no}</option>)}
              </select>
            )}
            {r.category === "deposit_out" && (
              <select className={field} value={leaseId} onChange={(e) => setLeaseId(e.target.value)}>
                <option value="">계약 선택</option>
                {leases.map((l) => <option key={l.lease_id} value={l.lease_id}>{l.unit_no} · {l.tenant_name}</option>)}
                {s?.lease_id && !leases.some((l) => l.lease_id === s.lease_id) && (
                  <option value={s.lease_id}>제안된 계약 (종료)</option>
                )}
              </select>
            )}
            {rows.length > 1 && (
              <button type="button" className="text-xs text-slate-400 hover:text-red-600"
                onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>빼기</button>
            )}
          </div>
        ))}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {!isDeposit && (
          <button type="button" className={`${btn} border bg-white px-2 py-1 text-xs hover:bg-slate-50`}
            onClick={() => setRows((rs) => [...rs, {
              key: splitKey++, category: "owner_household", amount: String(Math.max(remaining, 0)), unit_id: "" }])}>
            + 나누기
          </button>
        )}
        <span className={remaining === 0 ? "text-slate-500" : "font-medium text-red-700"}>
          {remaining === 0 ? "합계 일치" : remaining > 0 ? `${won(remaining)} 남음` : `${won(-remaining)} 초과`}
        </span>
        {remaining !== 0 && rows.length > 1 && (
          <button type="button" className="underline"
            onClick={() => setRows((rs) => rs.map((r, i) => i === rs.length - 1
              ? { ...r, amount: String(toInt(r.amount) + remaining) } : r))}>
            마지막 칸에 맞추기
          </button>
        )}
        {!isDeposit && (t.counterparty || t.description) && (
          <label className="flex items-center gap-1 text-slate-600">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            &lsquo;{t.counterparty ?? t.description}&rsquo; 기억 (다음부터 {rows.length > 1 ? "같은 비율로 " : ""}자동)
          </label>
        )}
        <button type="button" disabled={busy || !valid} className={`${primary} ml-auto`}
          onClick={() => onDecide({
            splits: rows.map((r) => ({ category: r.category, amount: toInt(r.amount), unit_id: r.unit_id || null })),
            lease_id: isDeposit ? leaseId : null,
            remember: !isDeposit && remember,
          })}>
          확정
        </button>
      </div>
    </div>
  );
}

function ManualExpense({ units, busy, onAdd }: {
  units: UnitOut[]; busy: boolean;
  onAdd: (body: { category: ExpenseCategory; amount: number; spent_on: string; memo: string | null; unit_id: string | null }) => Promise<boolean>;
}) {
  const [category, setCategory] = useState<ExpenseCategory>("repair");
  const [amount, setAmount] = useState("");
  const [spentOn, setSpentOn] = useState(todayKst());
  const [memo, setMemo] = useState("");
  const [unitId, setUnitId] = useState("");
  return (
    <section className="space-y-2 card p-4">
      <h2 className="card-title">현금 지출 기록</h2>
      <p className="text-xs text-slate-500">통장을 거치지 않은 지출만 여기에. 통장 출금은 위 검토 대기에서 확정하세요.</p>
      <div className="flex flex-wrap items-center gap-2">
        <input type="date" className={field} value={spentOn} onChange={(e) => setSpentOn(e.target.value)} aria-label="날짜" />
        <select className={field} value={category} onChange={(e) => setCategory(e.target.value as ExpenseCategory)}>
          {EXPENSE_CATS.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
        </select>
        <input className={`${field} w-32 text-right`} inputMode="numeric" placeholder="금액" value={amount}
          onChange={(e) => setAmount(e.target.value)} />
        <select className={field} value={unitId} onChange={(e) => setUnitId(e.target.value)}>
          <option value="">호실 (선택)</option>
          {units.map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_no}</option>)}
        </select>
        <input className={`${field} w-full min-w-0 sm:w-auto sm:flex-1`} placeholder="메모 (선택)" maxLength={200} value={memo}
          onChange={(e) => setMemo(e.target.value)} />
        <button type="button" disabled={busy || toInt(amount) <= 0 || !spentOn} className={primary}
          onClick={async () => {
            const ok = await onAdd({
              category, amount: toInt(amount), spent_on: spentOn, memo: memo.trim() || null, unit_id: unitId || null });
            if (ok) { setAmount(""); setMemo(""); }  // 실패하면 입력값을 남겨 둔다
          }}>
          기록
        </button>
      </div>
    </section>
  );
}
