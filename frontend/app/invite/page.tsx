"use client";

import { Building2, Check, Loader2, UserPlus } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import AuthFrame from "@/components/AuthFrame";
import { api } from "@/lib/api";

interface Preview { organization_name: string; email: string; role: "manager" | "viewer"; expires_at: string }

const ROLE_TEXT = { manager: "관리자 — 입력·수정 가능", viewer: "조회 — 보기만 가능" };

function InviteForm() {
  const token = useSearchParams().get("token") ?? "";
  const [pv, setPv] = useState<Preview | null>(null);
  const [bad, setBad] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [agree, setAgree] = useState({ terms: false, privacy: false, marketing: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) { setBad("링크가 올바르지 않습니다. 메일의 링크를 그대로 열어 주세요."); return; }
    api<Preview>("/api/v1/auth/invitation/preview", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }) }).then(setPv).catch((e) => setBad((e as Error).message));
  }, [token]);

  const longEnough = pw.length >= 10;
  const mixed = /\d/.test(pw) && /[^\d]/.test(pw);
  const same = pw !== "" && pw === pw2;
  // 서버 규칙과 같게: 4자 이상인 이메일 아이디는 비밀번호에 넣을 수 없음 (backend/app/auth.py password_problem)
  const local = (pv?.email ?? "").split("@")[0].toLowerCase();
  const noId = local.length < 4 || !pw.toLowerCase().includes(local);
  const ready = name.trim() && longEnough && mixed && same && noId && agree.terms && agree.privacy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/api/v1/auth/invitation/accept", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ token, name, password: pw, agree_terms: agree.terms, agree_privacy: agree.privacy,
          agree_marketing: agree.marketing }) });
      window.location.href = "/";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (bad) {
    return (
      <div className="space-y-4">
        <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{bad}</p>
        <a href="/login" className="btn-secondary w-full py-3">로그인 화면으로</a>
      </div>
    );
  }
  if (!pv) return <p className="text-sm text-slate-400">초대 내용을 확인하는 중…</p>;

  const rule = (ok: boolean, t: string) => (
    <li className={`flex items-center gap-1 ${ok ? "text-emerald-700" : "text-slate-400"}`}><Check className="h-3.5 w-3.5" /> {t}</li>
  );
  const box = "h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500";
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex gap-3 rounded-2xl bg-blue-50 p-4 text-sm text-blue-950">
        <Building2 className="h-5 w-5 shrink-0 text-blue-600" />
        <div>
          <p><b>{pv.organization_name}</b> 사업장에 초대되었습니다.</p>
          <p className="mt-0.5 text-blue-800">권한: {ROLE_TEXT[pv.role]}</p>
        </div>
      </div>
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">이메일 (로그인 아이디)</span>
        <input className="field w-full py-2.5" value={pv.email} readOnly disabled />
      </label>
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">이름</span>
        <input className="field w-full py-2.5" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">비밀번호</span>
          <input className="field w-full py-2.5" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">비밀번호 확인</span>
          <input className="field w-full py-2.5" type="password" autoComplete="new-password" required value={pw2} onChange={(e) => setPw2(e.target.value)} />
        </label>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">{rule(longEnough, "10자 이상")}{rule(mixed, "문자와 숫자 함께")}{rule(same, "두 번 같게")}{local.length >= 4 && rule(pw !== "" && noId, "이메일 아이디 넣지 않기")}</ul>

      <fieldset className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4 text-sm">
        <legend className="sr-only">약관 동의</legend>
        <label className="flex items-center gap-2">
          <input type="checkbox" className={box} checked={agree.terms} onChange={(e) => setAgree((a) => ({ ...a, terms: e.target.checked }))} />
          <span className="flex-1"><b className="text-blue-700">[필수]</b> 이용약관</span>
          <a href="/terms" target="_blank" className="text-xs text-slate-500 underline">보기</a>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" className={box} checked={agree.privacy} onChange={(e) => setAgree((a) => ({ ...a, privacy: e.target.checked }))} />
          <span className="flex-1"><b className="text-blue-700">[필수]</b> 개인정보 수집·이용</span>
          <a href="/privacy" target="_blank" className="text-xs text-slate-500 underline">보기</a>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" className={box} checked={agree.marketing} onChange={(e) => setAgree((a) => ({ ...a, marketing: e.target.checked }))} />
          <span className="flex-1"><b className="text-slate-500">[선택]</b> 광고성 정보 이메일 수신</span>
        </label>
      </fieldset>

      {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      <button type="submit" className="btn-primary w-full py-3" disabled={!ready || busy}>
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <UserPlus className="h-5 w-5" />} 참여하고 시작하기
      </button>
    </form>
  );
}

export default function InvitePage() {
  return (
    <AuthFrame title="초대 수락" sub="이름과 비밀번호를 정하면 바로 사업장에 참여합니다.">
      <Suspense><InviteForm /></Suspense>
    </AuthFrame>
  );
}
