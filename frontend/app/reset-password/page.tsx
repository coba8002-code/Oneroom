"use client";

import { Check, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import AuthFrame from "@/components/AuthFrame";
import { api } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const longEnough = pw.length >= 10;
  const mixed = /\d/.test(pw) && /[^\d]/.test(pw);
  const same = pw !== "" && pw === pw2;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/api/v1/auth/password-reset/confirm", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ token, new_password: pw }),
      });
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="space-y-4">
        <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">링크가 올바르지 않습니다. 메일의 링크를 그대로 열어 주세요.</p>
        <a href="/forgot-password" className="btn-secondary w-full py-3">재설정 메일 다시 받기</a>
      </div>
    );
  }
  if (done) {
    return (
      <div className="space-y-4">
        <p className="flex gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
          <CheckCircle2 className="h-5 w-5 shrink-0" /> 비밀번호를 바꿨습니다. 로그인돼 있던 모든 기기는 로그아웃되었습니다.
        </p>
        <a href="/login" className="btn-primary w-full py-3">새 비밀번호로 로그인</a>
      </div>
    );
  }
  const rule = (ok: boolean, t: string) => (
    <li className={`flex items-center gap-1 ${ok ? "text-emerald-700" : "text-slate-400"}`}><Check className="h-3.5 w-3.5" /> {t}</li>
  );
  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">새 비밀번호</span>
        <input className="field w-full py-2.5" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
      </label>
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">새 비밀번호 확인</span>
        <input className="field w-full py-2.5" type="password" autoComplete="new-password" required value={pw2} onChange={(e) => setPw2(e.target.value)} />
      </label>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">{rule(longEnough, "10자 이상")}{rule(mixed, "문자와 숫자 함께")}{rule(same, "두 번 같게")}</ul>
      {error && (
        <div className="space-y-2 rounded-xl bg-red-50 p-3 text-sm text-red-800">
          <p>{error}</p>
          {error.includes("링크") && <a href="/forgot-password" className="font-semibold underline">재설정 메일 다시 받기</a>}
        </div>
      )}
      <button type="submit" className="btn-primary w-full py-3" disabled={busy || !(longEnough && mixed && same)}>
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <KeyRound className="h-5 w-5" />} 비밀번호 바꾸기
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <AuthFrame title="새 비밀번호 정하기" sub="새 비밀번호를 두 번 입력하세요.">
      <Suspense><ResetForm /></Suspense>
    </AuthFrame>
  );
}
