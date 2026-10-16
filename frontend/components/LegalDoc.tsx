import { House, TriangleAlert } from "lucide-react";

export default function LegalDoc({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <a href="/signup" className="mb-6 flex items-center gap-2 font-extrabold tracking-tight text-navy-800">
        <House className="h-6 w-6 text-blue-600" strokeWidth={2.4} /> ROOMAX
      </a>
      <h1 className="page-title">{title}</h1>
      <p className="mt-3 flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
        <TriangleAlert className="h-4 w-4 shrink-0 text-amber-600" />
        초안입니다. 정식 서비스 전에 법률 검토를 거쳐 시행일·사업자 정보·책임자 연락처를 확정합니다.
      </p>
      <article className="card mt-6 space-y-5 p-6 text-[15px] leading-relaxed text-slate-700 [&_h2]:mt-2 [&_h2]:text-base [&_h2]:font-bold [&_h2]:text-slate-900 [&_li]:ml-5 [&_li]:list-disc [&_table]:w-full [&_td]:border [&_td]:border-slate-200 [&_td]:p-2 [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:p-2 [&_th]:text-left">
        {children}
      </article>
    </div>
  );
}
