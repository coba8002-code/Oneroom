"use client";

import { Loader2, MailCheck, Send } from "lucide-react";
import { useState } from "react";
import AuthFrame from "@/components/AuthFrame";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api<{ message: string }>("/api/v1/auth/password-reset/request", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email }),
      });
      setDone(r.message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="비밀번호 찾기" sub="가입한 이메일로 비밀번호 재설정 링크를 보내 드립니다.">
      {done ? (
        <div className="space-y-4">
          <p className="flex gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
            <MailCheck className="h-5 w-5 shrink-0" /> {done}
          </p>
          <p className="text-sm text-slate-500">링크는 1시간 동안, 한 번만 쓸 수 있습니다. 메일이 오지 않으면 몇 분 뒤 다시 요청하세요.</p>
          <a href="/login" className="btn-secondary w-full py-3">로그인으로 돌아가기</a>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">이메일</span>
            <input className="field w-full py-2.5" type="email" autoComplete="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </label>
          {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
          <button type="submit" className="btn-primary w-full py-3" disabled={busy || !email}>
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />} 재설정 링크 받기
          </button>
          <p className="text-center text-sm text-slate-500"><a href="/login" className="hover:underline">로그인으로 돌아가기</a></p>
        </form>
      )}
    </AuthFrame>
  );
}
