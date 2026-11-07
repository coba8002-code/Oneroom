"use client";

import { CheckCircle2, CreditCard, Landmark, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, kst, won } from "@/lib/api";
import { useMe } from "@/lib/me";

interface Billing {
  enabled: boolean; client_key: string | null; customer_key?: string;
  plan: string; effective: "comp" | "trial" | "basic" | "grace" | "free"; unlimited: boolean;
  units: number; free_units: number; over_free: number;
  prices: { monthly: number; yearly: number; base: number; base_units: number; extra_unit: number; tax_helper: number };
  billing_cycle: string | null; trial_ends_at: string | null; current_period_end: string | null; canceled: boolean;
  past_due_since: string | null; card: string | null; tax_helper_until: string | null; tax_helper_active: boolean; notice: string;
  payments: { created_at: string; item: string; amount: number; units: number | null; status: string; failure: string | null }[];
}
const STATE: Record<Billing["effective"], string> = {
  comp: "무상 제공", trial: "무료 체험 중", basic: "유료 이용 중", grace: "결제 확인 중 (유예)", free: "무료 (임대 호실 3개까지)",
};
const ITEM: Record<string, string> = { basic_monthly: "월 이용료", basic_yearly: "연 이용료", tax_helper: "셀프 신고 도우미 1년" };

type TossPayments = (clientKey: string) => { payment: (o: { customerKey: string }) => {
  requestBillingAuth: (o: { method: "CARD"; successUrl: string; failUrl: string; customerEmail?: string }) => Promise<void> } };

function loadToss(): Promise<TossPayments> {
  const w = window as unknown as { TossPayments?: TossPayments };
  if (w.TossPayments) return Promise.resolve(w.TossPayments);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://js.tosspayments.com/v2/standard";
    s.onload = () => (w.TossPayments ? resolve(w.TossPayments) : reject(new Error("결제창을 불러오지 못했습니다")));
    s.onerror = () => reject(new Error("결제창을 불러오지 못했습니다"));
    document.head.appendChild(s);
  });
}

export default function BillingPage() {
  const { me } = useMe();
  const owner = me?.user.role === "owner";
  const [b, setB] = useState<Billing | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setB(await api<Billing>("/api/v1/billing")); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await fn(); await load(); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }

  // 결제창에서 카드 등록 후 돌아오면 (?authKey=…&customerKey=…) 빌링키로 바꾼다
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const authKey = q.get("authKey"), customerKey = q.get("customerKey");
    window.history.replaceState(null, "", "/billing");
    if (q.get("fail")) setMsg({ ok: false, text: q.get("message") || "카드를 등록하지 못했습니다" });
    if (authKey && customerKey) {
      run(() => api("/api/v1/billing/card", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auth_key: authKey, customer_key: customerKey }) }), "카드를 등록했습니다.");
    } else load();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  async function registerCard() {
    if (!b?.client_key || !b.customer_key) return;
    setMsg(null);
    try {
      const toss = (await loadToss())(b.client_key);
      const origin = window.location.origin;
      await toss.payment({ customerKey: b.customer_key }).requestBillingAuth({
        method: "CARD", successUrl: `${origin}/billing`, failUrl: `${origin}/billing?fail=1`, customerEmail: me?.user.email ?? undefined });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  const post = (path: string, body?: unknown) => api(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) });

  if (!b) return <p className="text-sm text-slate-400">{msg ? msg.text : "불러오는 중…"}</p>;
  const p = b.prices;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">요금제</h1>
        <p className="page-sub">임대 호실 {b.free_units}개까지 무료. 유료는 {p.base_units}호실까지 월 {won(p.base)}, 그 위로 호실당 월 {won(p.extra_unit)}. 연 결제는 2개월 할인.</p>
      </header>
      {msg && <div className={`rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`} role="status">{msg.text}</div>}
      {!b.enabled && <p className="rounded-xl bg-slate-100 p-3 text-sm text-slate-700">결제가 아직 열리지 않았습니다 — 지금은 한도 없이 모두 쓸 수 있습니다.</p>}

      <section className="card p-5 text-sm">
        <h2 className="card-title mb-3 flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-600" />지금 상태: {STATE[b.effective]}</h2>
        <dl className="grid gap-2 sm:grid-cols-2">
          <div><dt className="text-xs text-slate-500">임대 호실 (주인세대 제외)</dt><dd>{b.units}개</dd></div>
          <div><dt className="text-xs text-slate-500">이 호실 수의 요금</dt><dd>월 {won(p.monthly)} · 연 {won(p.yearly)}</dd></div>
          {b.effective === "trial" && b.trial_ends_at && <div><dt className="text-xs text-slate-500">체험 끝</dt><dd>{kst(b.trial_ends_at)}</dd></div>}
          {b.current_period_end && <div><dt className="text-xs text-slate-500">{b.canceled ? "이용 끝 (해지 예약)" : "다음 결제"}</dt><dd>{kst(b.current_period_end)}</dd></div>}
          <div><dt className="text-xs text-slate-500">결제 카드</dt><dd>{b.card ?? "없음"}</dd></div>
          {b.past_due_since && <div><dt className="text-xs text-slate-500">결제 실패</dt><dd className="text-red-700">{kst(b.past_due_since)}부터 — 카드를 바꿔 주세요 (7일 유예)</dd></div>}
        </dl>
        {b.effective === "free" && b.over_free > 0 && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
          무료 한도를 넘었습니다. 이미 넣은 장부는 그대로 보고 고칠 수 있지만, 새 호실은 유료로 바꾼 뒤 넣을 수 있습니다.</p>}
        {owner && b.enabled && b.effective !== "comp" && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" disabled={busy} onClick={registerCard}><CreditCard className="h-4 w-4" />{b.card ? "카드 바꾸기" : "카드 등록"}</button>
            {b.effective !== "basic" && <>
              <button type="button" className="btn-primary" disabled={busy || !b.card} onClick={() => run(() => post("/api/v1/billing/subscribe", { cycle: "monthly" }), "유료로 바꿨습니다.")}>
                월 {won(p.monthly)} 결제</button>
              <button type="button" className="btn-primary" disabled={busy || !b.card} onClick={() => run(() => post("/api/v1/billing/subscribe", { cycle: "yearly" }), "유료로 바꿨습니다.")}>
                연 {won(p.yearly)} 결제</button></>}
            {b.plan === "basic" && (b.canceled
              ? <button type="button" className="btn-secondary" disabled={busy} onClick={() => run(() => post("/api/v1/billing/resume"), "해지 예약을 풀었습니다.")}>해지 취소</button>
              : <button type="button" className="btn-secondary" disabled={busy} onClick={() => run(() => post("/api/v1/billing/cancel"), "해지를 예약했습니다. 남은 기간 끝까지 쓸 수 있습니다.")}>해지 예약</button>)}
            {busy && <Loader2 className="h-5 w-5 animate-spin text-slate-400" />}
          </div>)}
        <p className="mt-3 text-xs text-slate-500">{b.notice}</p>
      </section>

      <section className="card p-5 text-sm">
        <h2 className="card-title mb-2 flex items-center gap-2"><Landmark className="h-4 w-4 text-blue-600" />셀프 신고 도우미 — 연 {won(p.tax_helper)}</h2>
        <p className="text-slate-600">통장 기준 임대수입으로 분리과세·종합과세 세액을 추정하고, 홈택스에 넣을 숫자를 정리해 줍니다. 신고는 본인이 홈택스에서 직접 합니다 (대신 제출·세무 판정 없음).</p>
        <p className="mt-2">{b.tax_helper_active ? (b.tax_helper_until ? `이용 중 — ${b.tax_helper_until}까지` : "체험·무상 제공으로 이용 중") : "이용권 없음"}</p>
        {owner && b.enabled && !b.tax_helper_until && b.effective !== "comp" && (
          <button type="button" className="btn-secondary mt-3" disabled={busy || !b.card}
            onClick={() => run(() => post("/api/v1/billing/tax-helper"), "셀프 신고 도우미를 1년 이용할 수 있습니다.")}>{won(p.tax_helper)} 결제</button>)}
      </section>

      {b.payments.length > 0 && (
        <section className="card overflow-x-auto p-0 text-sm">
          <h2 className="card-title p-4 pb-2">결제 기록</h2>
          <table className="w-full min-w-[480px] text-left">
            <thead className="text-xs text-slate-500"><tr><th className="px-3 py-2">시각</th><th className="px-3">항목</th><th className="px-3 text-right">금액</th><th className="px-3">결과</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{b.payments.map((x, i) => (
              <tr key={i}><td className="px-3 py-1.5">{kst(x.created_at)}</td><td className="px-3">{ITEM[x.item] ?? x.item}{x.units != null && ` (${x.units}호실)`}</td>
                <td className="px-3 text-right tabular-nums">{won(x.amount)}</td>
                <td className="px-3">{x.status === "done" ? "완료" : <span className="text-red-700">실패 — {x.failure}</span>}</td></tr>))}</tbody>
          </table>
        </section>)}
    </div>
  );
}
