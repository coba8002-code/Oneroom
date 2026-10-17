"use client";

import { Check, Loader2, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import AuthFrame from "@/components/AuthFrame";
import { api, signupOpen } from "@/lib/api";

function Rule({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className={`flex items-center gap-1 ${ok ? "text-emerald-700" : "text-slate-400"}`}>
      <Check className="h-3.5 w-3.5" /> {children}
    </li>
  );
}

export default function SignupPage() {
  const [f, setF] = useState({ name: "", email: "", password: "", password2: "", organization_name: "" });
  const [agree, setAgree] = useState({ terms: false, privacy: false, marketing: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<boolean | null>(null);
  useEffect(() => { signupOpen().then(setOpen); }, []);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF((v) => ({ ...v, [k]: e.target.value }));

  const longEnough = f.password.length >= 10;
  const mixed = /\d/.test(f.password) && /[^\d]/.test(f.password);
  const same = f.password !== "" && f.password === f.password2;
  // 서버 규칙과 같게: 4자 이상인 이메일 아이디는 비밀번호에 넣을 수 없음 (backend/app/auth.py password_problem)
  const local = f.email.trim().split("@")[0].toLowerCase();
  const noId = local.length < 4 || !f.password.toLowerCase().includes(local);
  const all = agree.terms && agree.privacy && agree.marketing;
  const ready = f.name && f.email && f.organization_name && longEnough && mixed && same && noId && agree.terms && agree.privacy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/api/v1/auth/signup", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: f.name, email: f.email, password: f.password, organization_name: f.organization_name,
          agree_terms: agree.terms, agree_privacy: agree.privacy, agree_marketing: agree.marketing,
        }),
      });
      window.location.href = "/onboarding";
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const box = "h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500";
  if (open === false) {
    return (
      <AuthFrame title="회원가입" sub="이 서버는 개인 사용 모드입니다.">
        <div className="space-y-4">
          <p className="rounded-xl bg-slate-100 p-4 text-sm text-slate-700" role="status">
            사업장 대표가 이미 가입해 새 가입은 받지 않습니다. 함께 쓰려면 대표에게 초대를 요청하고,
            초대 메일의 링크로 참여하세요.
          </p>
          <a href="/login" className="btn-primary w-full py-3">로그인</a>
        </div>
      </AuthFrame>
    );
  }
  return (
    <AuthFrame title="회원가입" sub="가입하면 내 사업장이 만들어지고, 바로 건물·호실을 등록할 수 있습니다.">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">이름</span>
            <input className="field w-full py-2.5" autoComplete="name" required value={f.name} onChange={set("name")} />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">사업장 이름</span>
            <input className="field w-full py-2.5" placeholder="예: 행복빌라 임대" required value={f.organization_name}
              onChange={set("organization_name")} />
          </label>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">이메일 (로그인 아이디)</span>
          <input className="field w-full py-2.5" type="email" autoComplete="email" required value={f.email} onChange={set("email")} />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">비밀번호</span>
            <input className="field w-full py-2.5" type="password" autoComplete="new-password" required value={f.password}
              onChange={set("password")} />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">비밀번호 확인</span>
            <input className="field w-full py-2.5" type="password" autoComplete="new-password" required value={f.password2}
              onChange={set("password2")} />
          </label>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <Rule ok={longEnough}>10자 이상</Rule>
          <Rule ok={mixed}>문자와 숫자 함께</Rule>
          <Rule ok={same}>두 번 같게</Rule>
          {local.length >= 4 && <Rule ok={f.password !== "" && noId}>이메일 아이디 넣지 않기</Rule>}
        </ul>

        <fieldset className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4 text-sm">
          <legend className="sr-only">약관 동의</legend>
          <label className="flex items-center gap-2 border-b border-slate-100 pb-2 font-semibold">
            <input type="checkbox" className={box} checked={all}
              onChange={(e) => setAgree({ terms: e.target.checked, privacy: e.target.checked, marketing: e.target.checked })} />
            아래 내용에 모두 동의
          </label>
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
          <label className="flex items-start gap-2">
            <input type="checkbox" className={`${box} mt-0.5`} checked={agree.marketing}
              onChange={(e) => setAgree((a) => ({ ...a, marketing: e.target.checked }))} />
            <span className="flex-1">
              <b className="text-slate-500">[선택]</b> 광고성 정보(새 기능·할인 안내) 이메일 수신
              <span className="block text-xs text-slate-400">동의하지 않아도 가입·이용에 제한이 없습니다. 설정에서 언제든 끌 수 있습니다.</span>
            </span>
          </label>
        </fieldset>

        {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        <button type="submit" className="btn-primary w-full py-3" disabled={!ready || busy}>
          {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <UserPlus className="h-5 w-5" />} 가입하고 시작하기
        </button>
        <p className="text-center text-sm text-slate-500">
          이미 계정이 있나요? <a href="/login" className="font-semibold text-blue-600 hover:underline">로그인</a>
        </p>
      </form>
    </AuthFrame>
  );
}
