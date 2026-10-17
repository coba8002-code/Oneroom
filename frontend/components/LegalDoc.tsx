import { House, Info } from "lucide-react";
import { LEGAL } from "@/lib/legal";

export default function LegalDoc({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <a href="/login" className="mb-6 flex items-center gap-2 font-extrabold tracking-tight text-navy-800">
        <House className="h-6 w-6 text-blue-600" strokeWidth={2.4} /> ROOMAX
      </a>
      <h1 className="page-title">{title}</h1>
      <p className="mt-1 text-sm text-slate-500">시행일 {LEGAL.effectiveDate} · 버전 {LEGAL.version}</p>
      <p className="mt-3 flex gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        <Info className="h-4 w-4 shrink-0 text-slate-500" />
        개인 사용·무료 단계의 문서입니다. 유료 상용화 전에 변호사 검토를 거쳐 사업자 정보와 함께 개정하며,
        개정 시 아래 &lsquo;변경 이력&rsquo;에 이전 판을 남깁니다.
      </p>
      <article className="card mt-6 space-y-5 p-6 text-[15px] leading-relaxed text-slate-700 [&_h2]:mt-2 [&_h2]:text-base [&_h2]:font-bold [&_h2]:text-slate-900 [&_h3]:mt-2 [&_h3]:font-semibold [&_h3]:text-slate-800 [&_li]:ml-5 [&_li]:list-disc [&_ol>li]:list-decimal [&_table]:w-full [&_table]:text-sm [&_td]:border [&_td]:border-slate-200 [&_td]:p-2 [&_td]:align-top [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:p-2 [&_th]:text-left">
        {children}
      </article>
    </div>
  );
}
