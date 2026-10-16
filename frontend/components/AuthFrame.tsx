import { Building2, House, ShieldCheck, Wallet } from "lucide-react";

/** 로그인·가입 화면 틀: 데스크톱은 왼쪽에 브랜드 패널 */
export default function AuthFrame({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-gradient-to-br from-navy-800 to-navy-950 p-12 text-white lg:flex lg:flex-col">
        <a href="/login" className="flex items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-xl bg-white/10"><House className="h-7 w-7" strokeWidth={2.2} /></span>
          <span>
            <span className="block text-3xl font-extrabold tracking-tight">ROOMAX</span>
            <span className="block text-sm text-slate-300">내 건물의 든든한 파트너</span>
          </span>
        </a>
        <div className="mt-auto space-y-5">
          <h2 className="text-3xl font-bold leading-snug">원룸 건물 임대관리,<br />통장 정리부터 결산까지.</h2>
          <ul className="space-y-3 text-[15px] text-slate-200">
            <li className="flex gap-3"><Wallet className="h-5 w-5 shrink-0 text-sky-300" /> 통장 입금을 호실별 월세와 자동으로 맞춤</li>
            <li className="flex gap-3"><Building2 className="h-5 w-5 shrink-0 text-sky-300" /> 공용 운영비와 생활비를 나눠 순수익 계산</li>
            <li className="flex gap-3"><ShieldCheck className="h-5 w-5 shrink-0 text-sky-300" /> 연락처·계약서는 암호화해 보관</li>
          </ul>
        </div>
        <House className="pointer-events-none absolute -right-16 -top-10 h-80 w-80 text-white/5" strokeWidth={1} />
      </aside>
      <main className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-md">
          <a href="/login" className="mb-8 flex items-center gap-2 text-xl font-extrabold tracking-tight text-navy-800 lg:hidden">
            <House className="h-7 w-7 text-blue-600" strokeWidth={2.4} /> ROOMAX
          </a>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-slate-500">{sub}</p>
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  );
}
