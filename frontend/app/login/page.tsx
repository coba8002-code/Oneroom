"use client";

import { KeyRound, Loader2, LogIn } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import AuthFrame from "@/components/AuthFrame";
import { api, signupOpen } from "@/lib/api";

function safeNext(next: string | null) {
  // 열린 리다이렉트 방지: 우리 사이트 안의 경로만
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function LoginForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [canSignup, setCanSignup] = useState(true);
  useEffect(() => { signupOpen().then((o) => setCanSignup(o !== false)); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const res = await api<{ mfa_required?: boolean }>("/api/v1/auth/login", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, otp: needOtp ? otp : null }),
      });
      if (res.mfa_required) {
        setNeedOtp(true);
        return;
      }
      window.location.href = safeNext(params.get("next"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {!needOtp ? (
        <>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">이메일</span>
            <input className="field w-full py-2.5" type="email" autoComplete="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">비밀번호</span>
            <input className="field w-full py-2.5" type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        </>
      ) : (
        <label className="block text-sm">
          <span className="mb-1 flex items-center gap-1.5 font-medium text-slate-700"><KeyRound className="h-4 w-4" /> 인증 앱의 6자리 코드</span>
          <input className="field w-full py-2.5 text-center text-lg tracking-[0.4em]" inputMode="numeric" autoComplete="one-time-code"
            maxLength={6} autoFocus required value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
          <span className="mt-1 block text-xs text-slate-500">2단계 인증을 켠 계정입니다.</span>
        </label>
      )}
      {params.get("deleted") && !error && (
        <p className="rounded-xl bg-slate-100 p-3 text-sm text-slate-700" role="status">계정이 삭제되었습니다. 그동안 이용해 주셔서 감사합니다.</p>
      )}
      {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      <button type="submit" className="btn-primary w-full py-3" disabled={busy}>
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <LogIn className="h-5 w-5" />} {needOtp ? "확인" : "로그인"}
      </button>
      <div className="flex justify-between text-sm text-slate-500">
        <a href="/forgot-password" className="hover:text-slate-700 hover:underline">비밀번호를 잊으셨나요?</a>
        {canSignup && <span>처음이신가요? <a href="/signup" className="font-semibold text-blue-600 hover:underline">회원가입</a></span>}
      </div>
    </form>
  );
}

export default function LoginPage() {
  return (
    <AuthFrame title="로그인" sub="건물 현황을 확인하려면 로그인하세요.">
      <Suspense><LoginForm /></Suspense>
    </AuthFrame>
  );
}
