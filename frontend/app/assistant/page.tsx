"use client";

import { Bot, Loader2, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, kst } from "@/lib/api";
import { useMe } from "@/lib/me";

interface Status { configured: boolean; model: string; daily_limit: number; remaining_today: number }
interface Source { tool: string; input: Record<string, unknown>; error: boolean }
interface Answer { answer: string; kind: "fact" | "unknown" | "denied"; sources: Source[]; queried_at: string; remaining_today: number }
interface Turn { role: "user" | "assistant"; text: string; meta?: Answer }

const TOOL_LABEL: Record<string, string> = {
  get_overview: "홈 요약", list_unpaid: "미수 현황", get_month_report: "월 결산", list_leases: "진행 중 계약",
  list_lease_endings: "만료·갱신 통지", list_vacancies: "공실", list_maintenance: "정기 점검·수리", get_tax_prep: "세무 준비 자료",
};
const EXAMPLES = ["이번 달 미납 있는 호실 알려줘", "지난달 순운영수익은?", "갱신 통지 챙겨야 할 계약 있어?",
  "공실 때문에 놓친 월세는 얼마야?", "이번 주 정기 점검 할 일", "올해 세무 준비 자료 상태는?"];

export default function AssistantPage() {
  const { me } = useMe();
  const canAsk = me?.user.role !== "viewer";
  const [status, setStatus] = useState<Status | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { api<Status>("/api/v1/assistant/status").then(setStatus).catch((e) => setErr((e as Error).message)); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns, busy]);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true); setErr(null); setQ("");
    const history = turns.map(({ role, text: t }) => ({ role, text: t }));
    setTurns([...turns, { role: "user", text }]);
    try {
      const a = await api<Answer>("/api/v1/assistant/ask", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: text, history }) });
      setTurns((t) => [...t, { role: "assistant", text: a.answer, meta: a }]);
      setStatus((s) => (s ? { ...s, remaining_today: a.remaining_today } : s));
    } catch (e) {
      setErr((e as Error).message);
      setTurns((t) => t.slice(0, -1)); setQ(text);  // 실패하면 질문을 입력칸에 돌려놓음
    } finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header>
        <h1 className="page-title flex items-center gap-2"><Bot className="h-6 w-6 text-blue-600" />AI 비서</h1>
        <p className="page-sub">장부에 대해 물어보세요. 비서는 장부를 조회해 나온 숫자만 옮기고, 장부를 바꾸거나 세금·법적 판단을 하지 않습니다.</p>
      </header>

      {status && !status.configured && (
        <section className="card space-y-1 p-4 text-sm">
          <p className="font-medium">아직 연결되지 않았습니다.</p>
          <p className="text-slate-600">서버(Vercel API 프로젝트) 환경변수에 <code className="rounded bg-slate-100 px-1">ANTHROPIC_API_KEY</code>를 넣고 다시 배포하면 켜집니다.
            키는 console.anthropic.com → API Keys에서 만듭니다. 키를 채팅이나 화면에 붙여 넣지 마세요.</p>
        </section>
      )}

      <section className="card min-h-64 space-y-3 p-4" aria-live="polite">
        {turns.length === 0 ? (
          <div className="space-y-2 text-sm">
            <p className="text-slate-500">예시 질문</p>
            <div className="flex flex-wrap gap-1.5">{EXAMPLES.map((e) => (
              <button key={e} type="button" className="chip min-h-8 bg-slate-100 text-slate-700 hover:bg-slate-200"
                disabled={!status?.configured || !canAsk || busy} onClick={() => ask(e)}>{e}</button>))}</div>
          </div>
        ) : turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "flex justify-end" : ""}>
            <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${t.role === "user" ? "bg-blue-600 text-white" : "bg-slate-50"}`}>
              {t.text}
              {t.meta && (
                <p className="mt-2 border-t border-slate-200 pt-1 text-[11px] text-slate-500">
                  {t.meta.kind === "fact" ? `근거: ${[...new Set(t.meta.sources.filter((s) => !s.error).map((s) => TOOL_LABEL[s.tool] ?? s.tool))].join(", ")}`
                    : t.meta.kind === "denied" ? "답할 수 없는 질문" : "장부를 조회하지 않은 답 — 숫자는 화면에서 확인하세요"} · 조회 {kst(t.meta.queried_at)}
                </p>
              )}
            </div>
          </div>
        ))}
        {busy && <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />장부를 조회하는 중…</p>}
        <div ref={end} />
      </section>

      {err && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800" role="status">{err}</p>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <label className="sr-only" htmlFor="ask">질문</label>
        <input id="ask" className="field min-w-0 flex-1" value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000}
          placeholder={canAsk ? "예: 101호 이번 달 입금됐어?" : "조회 전용 권한은 질문할 수 없습니다"} disabled={!status?.configured || !canAsk || busy} />
        <button type="submit" className="btn-primary shrink-0" disabled={!status?.configured || !canAsk || busy || !q.trim()}><Send className="h-4 w-4" />묻기</button>
      </form>
      <p className="text-xs text-slate-500">
        {status ? `오늘 남은 질문 ${status.remaining_today}/${status.daily_limit}회. ` : ""}
        질문과 조회한 장부 수치(호실 번호·금액·날짜)는 답을 만들기 위해 Anthropic(미국)으로 보내집니다. 임차인 이름·연락처는 보내지 않으니 질문에도 적지 마세요 (개인정보 처리방침 제7조).
      </p>
    </div>
  );
}
