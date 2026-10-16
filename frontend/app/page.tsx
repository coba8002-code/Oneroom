export default function Home() {
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">ROOMAX</h1>
      <p className="text-slate-600">
        호실·계약·납부일을 먼저 등록하면 월 청구와 은행 거래 가져오기를 쓸 수 있습니다.
      </p>
      <a
        href="/onboarding"
        className="inline-block rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        초기 등록 시작
      </a>
    </section>
  );
}
