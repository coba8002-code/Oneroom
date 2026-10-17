"use client";

import { CheckCircle2, Loader2, TriangleAlert } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import AuthFrame from "@/components/AuthFrame";
import { api } from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<"loading" | "ok" | "error">(token ? "loading" : "error");
  const [message, setMessage] = useState(token ? "" : "링크가 올바르지 않습니다. 메일의 링크를 그대로 열어 주세요.");
  const once = useRef(false);  // 링크는 한 번만 쓸 수 있으므로 두 번 호출하지 않는다

  useEffect(() => {
    if (!token || once.current) return;
    once.current = true;
    api("/api/v1/auth/verify-email", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }) })
      .then(() => setState("ok"))
      .catch((e) => { setState("error"); setMessage((e as Error).message); });
  }, [token]);

  if (state === "loading") return <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> 확인 중…</p>;
  if (state === "ok") {
    return (
      <div className="space-y-4">
        <p className="flex gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
          <CheckCircle2 className="h-5 w-5 shrink-0" /> 이메일 주소를 확인했습니다. 이제 비밀번호를 잊어도 이 주소로 되찾을 수 있습니다.
        </p>
        <a href="/" className="btn-primary w-full py-3">ROOMAX 시작하기</a>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <p className="flex gap-2 rounded-xl bg-red-50 p-4 text-sm text-red-800"><TriangleAlert className="h-5 w-5 shrink-0" /> {message}</p>
      <p className="text-sm text-slate-500">로그인한 뒤 화면 위의 &lsquo;확인 메일 다시 보내기&rsquo;로 새 링크를 받을 수 있습니다.</p>
      <a href="/" className="btn-secondary w-full py-3">ROOMAX로 가기</a>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <AuthFrame title="이메일 확인" sub="가입한 이메일 주소가 맞는지 확인합니다.">
      <Suspense><Verify /></Suspense>
    </AuthFrame>
  );
}
