"use client";

import { useEffect, useRef, useState } from "react";
import { useMe } from "@/lib/me";
import {
  api,
  todayKst,
  type ChargeOut,
  type ImportOut,
  type OnboardingOut,
  type RowError,
  type UnitIn,
  type UseType,
  won,
} from "@/lib/api";

/** 입력 중에는 문자열로 들고 있다가 등록할 때 숫자·null 로 바꾼다 */
type UnitRow = { key: number; use_type: UseType } & {
  [K in Exclude<keyof UnitIn, "use_type">]: string;
};

const CSV_HEADER =
  "호실,층,면적㎡,용도,임차인,연락처,보증금,월세,관리비,납부일,계약시작,계약종료,보증금수령일";

let nextKey = 1;
function emptyRow(use_type: UseType = "rental"): UnitRow {
  return {
    key: nextKey++, use_type, unit_no: "", floor: "", area_m2: "", tenant_name: "",
    tenant_phone: "", deposit: "", rent: "", mgmt_fee: "", due_day: "", start_date: "", end_date: "",
    deposit_received_on: "",
  };
}

const initialRows = () => [...Array.from({ length: 9 }, () => emptyRow()), emptyRow("owner")];

const numOrNull = (s: string) => {
  const v = s.replace(/[,\s원]/g, "");
  return v === "" ? null : Number(v);
};
const strOrNull = (s: string) => (s.trim() === "" ? null : s.trim());

function toPayload(r: UnitRow): UnitIn {
  return {
    unit_no: r.unit_no.trim(),
    floor: numOrNull(r.floor),
    area_m2: numOrNull(r.area_m2),
    use_type: r.use_type,
    tenant_name: r.use_type === "owner" ? null : strOrNull(r.tenant_name),
    tenant_phone: r.use_type === "owner" ? null : strOrNull(r.tenant_phone),
    deposit: numOrNull(r.deposit),
    rent: numOrNull(r.rent),
    mgmt_fee: r.use_type === "owner" ? null : numOrNull(r.mgmt_fee),
    due_day: numOrNull(r.due_day),
    start_date: strOrNull(r.start_date),
    end_date: strOrNull(r.end_date),
    deposit_received_on: strOrNull(r.deposit_received_on),
  };
}

function fromPayload(u: UnitIn): UnitRow {
  const s = (v: string | number | null) => (v == null ? "" : String(v));
  return {
    key: nextKey++, use_type: u.use_type, unit_no: u.unit_no, floor: s(u.floor),
    area_m2: s(u.area_m2), tenant_name: s(u.tenant_name), tenant_phone: s(u.tenant_phone),
    deposit: s(u.deposit), rent: s(u.rent), mgmt_fee: s(u.mgmt_fee), due_day: s(u.due_day), start_date: s(u.start_date),
    end_date: s(u.end_date), deposit_received_on: s(u.deposit_received_on),
  };
}

function thisMonthKst(): string {
  // 'sv-SE' 는 YYYY-MM-DD 형식
  return new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 7);
}

function downloadTemplate() {
  const blob = new Blob(["﻿" + CSV_HEADER + "\n"], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "roomax_호실_등록양식.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

const input =
  "field w-full py-1.5";
const btn =
  "btn";

export default function OnboardingPage() {
  const [propertyName, setPropertyName] = useState("");
  const [address, setAddress] = useState("");
  const [rows, setRows] = useState<UnitRow[]>(initialRows);
  const [csvErrors, setCsvErrors] = useState<RowError[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<OnboardingOut | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { me } = useMe();
  // 두 번째 건물부터: 이미 있는 통장을 함께 쓸지 (기본 = 첫 통장), 새 통장을 만들지
  const [accounts, setAccounts] = useState<{ id: string; alias: string }[]>([]);
  const [accountId, setAccountId] = useState("");
  useEffect(() => {
    const org = me?.organization.id;
    if (!org) return;
    api<{ id: string; alias: string }[]>(`/api/v1/bank-accounts?organization_id=${org}`)
      .then((a) => { setAccounts(a); setAccountId(a[0]?.id ?? ""); })
      .catch(() => setAccounts([]));
  }, [me]);

  const update = (key: number, patch: Partial<UnitRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  async function onCsv(file: File) {
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await api<{ units: UnitIn[]; errors: RowError[] }>(
        "/api/v1/onboarding/csv-preview",
        { method: "POST", body: fd },
      );
      if (res.units.length) setRows(res.units.map(fromPayload));
      setCsvErrors(res.errors);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onSubmit() {
    setError(null);
    const filled = rows.filter((r) => r.unit_no.trim() !== "");
    if (!propertyName.trim()) return setError("건물 이름을 입력하세요.");
    if (filled.length === 0) return setError("호실 번호를 하나 이상 입력하세요.");
    setBusy(true);
    try {
      const res = await api<OnboardingOut>("/api/v1/onboarding", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          property: { name: propertyName.trim(), address: strOrNull(address) },
          bank_account_id: accountId || null,
          units: filled.map(toPayload),
        }),
      });
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (result) return <NextSteps result={result} />;

  const rental = rows.filter((r) => r.use_type === "rental" && r.unit_no.trim()).length;
  const occupied = rows.filter((r) => r.use_type === "rental" && r.tenant_name.trim()).length;
  const monthlyRent = rows.reduce(
    (s, r) => s + (r.use_type === "rental" && r.tenant_name.trim() ? numOrNull(r.rent) ?? 0 : 0),
    0,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">건물·호실 등록</h1>
        <p className="mt-1 text-sm text-slate-600">
          건물과 호실, 현재 계약(월세·보증금·납부일)을 입력합니다. 빈 칸은 나중에 채워도 됩니다.
          임차인이 없는 임대 호실은 공실로 등록됩니다.
        </p>
      </div>

      <section className="grid gap-3 card p-4 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">건물 이름</span>
          <input className={input} value={propertyName} onChange={(e) => setPropertyName(e.target.value)}
            placeholder="예: OO동 다가구" />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">주소 (선택)</span>
          <input className={input} value={address} onChange={(e) => setAddress(e.target.value)} />
        </label>
        {accounts.length > 0 && (
          <>
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">월세 받는 통장</span>
              <select className={input} aria-label="월세 받는 통장" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.alias} (함께 쓰기)</option>)}
                <option value="">새 통장 따로 등록</option>
              </select>
            </label>
            <p className="self-end text-xs text-slate-500">
              두 번째 건물부터는 모든 화면에서 호실이 &lsquo;건물 이름 + 호실&rsquo;(예: {propertyName.trim() || "행복빌라 2동"} 101)로 표시됩니다.
              건물 이름은 서로 달라야 합니다.
            </p>
          </>
        )}
      </section>

      <section className="flex flex-wrap items-center gap-2 rounded-2xl border border-dashed border-slate-300 bg-white p-4 text-sm">
        <span className="mr-auto text-slate-600">엑셀로 정리해 두었다면 CSV로 불러올 수 있습니다.</span>
        <button type="button" className={`${btn} border bg-white hover:bg-slate-50`} onClick={downloadTemplate}>
          빈 양식 받기
        </button>
        <label className={`${btn} cursor-pointer bg-blue-600 text-white hover:bg-blue-700`}>
          CSV 불러오기
          <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden"
            onChange={(e) => e.target.files?.[0] && onCsv(e.target.files[0])} />
        </label>
        {csvErrors.length > 0 && (
          <ul className="w-full list-disc space-y-0.5 rounded-xl bg-amber-50 p-3 pl-6 text-amber-900">
            {csvErrors.map((e) => (
              <li key={e.row}>{e.row}행: {e.message}</li>
            ))}
            <li className="list-none text-amber-700">
              위 행은 불러오지 않았습니다. 아래에서 직접 입력하거나 파일을 고쳐 다시 불러오세요.
            </li>
          </ul>
        )}
      </section>

      <section className="space-y-3">
        {rows.map((r, i) => (
          <UnitCard key={r.key} row={r} index={i} onChange={(p) => update(r.key, p)}
            onRemove={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} />
        ))}
        <button type="button" className={`${btn} border bg-white hover:bg-slate-50`}
          onClick={() => setRows((rs) => [...rs, emptyRow()])}>
          + 호실 추가
        </button>
      </section>

      <section className="sticky bottom-[60px] -mx-4 flex rounded-t-2xl lg:bottom-0 flex-wrap items-center gap-3 border-t bg-white/95 px-4 py-3 backdrop-blur">
        <div className="mr-auto text-sm text-slate-600">
          임대 {rental}실 · 입주 {occupied} · 월세 합계 <b className="text-slate-900">{won(monthlyRent)}</b>
        </div>
        {error && <p className="w-full whitespace-pre-line text-sm text-red-700 sm:order-first">{error}</p>}
        <button type="button" disabled={busy} onClick={onSubmit}
          className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>
          {busy ? "등록 중…" : "등록"}
        </button>
      </section>
    </div>
  );
}

function UnitCard({ row: r, index, onChange, onRemove }: {
  row: UnitRow; index: number; onChange: (p: Partial<UnitRow>) => void; onRemove: () => void;
}) {
  const owner = r.use_type === "owner";
  const field = (k: keyof UnitRow, label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="text-xs">
      <span className="mb-1 block text-slate-500">{label}</span>
      <input className={input} value={r[k] as string} disabled={owner && !["unit_no", "floor", "area_m2"].includes(k)}
        onChange={(e) => onChange({ [k]: e.target.value } as Partial<UnitRow>)} {...extra} />
    </label>
  );
  return (
    <div className={`card p-3 ${owner ? "border-slate-300 bg-slate-50" : ""}`}>
      <div className="mb-2 flex items-center gap-2 text-sm">
        <span className="font-medium text-slate-500">#{index + 1}</span>
        <select className="field py-1" aria-label={`#${index + 1} 용도`} value={r.use_type}
          onChange={(e) => onChange({ use_type: e.target.value as UseType })}>
          <option value="rental">임대</option>
          <option value="owner">주인세대</option>
        </select>
        <button type="button" onClick={onRemove} className="ml-auto text-xs text-slate-400 hover:text-red-600">
          삭제
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {field("unit_no", "호실", { placeholder: "101" })}
        {field("floor", "층", { inputMode: "numeric" })}
        {field("area_m2", "면적㎡", { inputMode: "decimal" })}
        {field("tenant_name", "임차인")}
        {field("tenant_phone", "연락처", { inputMode: "tel", autoComplete: "off" })}
        {field("due_day", "납부일(1~31)", { inputMode: "numeric", placeholder: "매월 n일" })}
        {field("rent", "월세", { inputMode: "numeric" })}
        {field("mgmt_fee", "관리비(모르면 비움)", { inputMode: "numeric" })}
        {field("deposit", "보증금", { inputMode: "numeric" })}
        {field("start_date", "계약시작", { type: "date" })}
        {field("end_date", "계약종료", { type: "date" })}
        {field("deposit_received_on", "보증금 받은 날", { type: "date", max: todayKst() })}
      </div>
      {!owner && (r.rent || r.deposit) && (
        <p className="mt-2 text-xs text-slate-500">
          월세 {won(numOrNull(r.rent))} · 보증금 {won(numOrNull(r.deposit))} (보증금은 돌려줄 돈으로 따로 관리)
        </p>
      )}
    </div>
  );
}

function NextSteps({ result }: { result: OnboardingOut }) {
  const [period, setPeriod] = useState(thisMonthKst());
  const [charges, setCharges] = useState<ChargeOut[] | null>(null);
  const [imported, setImported] = useState<ImportOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setError(null);
    try {
      const q = new URLSearchParams({ organization_id: result.organization_id, period });
      const res = await api<{ charges: ChargeOut[] }>(`/api/v1/charges/generate?${q}`, { method: "POST" });
      setCharges(res.charges);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function importBank(file: File) {
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setImported(await api<ImportOut>(`/api/v1/bank-accounts/${result.bank_account_id}/import`,
        { method: "POST", body: fd }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
        <h1 className="text-lg font-semibold">등록 완료</h1>
        <p className="mt-1">
          호실 {result.units} · 계약 {result.leases} · 공실 {result.vacant} · 보증금(반환의무) 합계{" "}
          {won(result.deposits_total)}
        </p>
      </section>

      {error && <p className="whitespace-pre-line text-sm text-red-700">{error}</p>}

      <section className="space-y-3 card p-4">
        <h2 className="card-title">1. 월 청구 만들기</h2>
        <div className="flex items-center gap-2">
          <input type="month" aria-label="청구 월" className={`${input} w-auto`} value={period} onChange={(e) => setPeriod(e.target.value)} />
          <button type="button" className={`${btn} bg-blue-600 text-white hover:bg-blue-700`} onClick={generate}>
            청구 생성
          </button>
        </div>
        <p className="text-xs text-slate-500">다시 눌러도 같은 달 청구가 두 번 생기지 않습니다.</p>
        {charges && (
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500">
              <tr><th className="py-1">호실</th><th>납부일</th><th className="text-right">금액</th></tr>
            </thead>
            <tbody>
              {charges.map((c) => (
                <tr key={c.unit_no} className="border-t">
                  <td className="py-1">{c.unit_no}</td><td>{c.due_date}</td>
                  <td className="text-right tabular-nums">{won(c.amount)}</td>
                </tr>
              ))}
              {charges.length === 0 && (
                <tr><td colSpan={3} className="py-2 text-slate-500">이 달에 청구할 계약이 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </section>

      <section className="space-y-3 card p-4">
        <h2 className="card-title">2. 은행 거래내역 가져오기</h2>
        <p className="text-xs text-slate-500">
          인터넷뱅킹에서 받은 CSV 또는 XLSX. 같은 파일을 다시 올려도 거래가 중복되지 않습니다.
          입금 매칭은 다음 단계에서 검토 후 확정합니다.
        </p>
        <input type="file" aria-label="은행 거래내역 파일 (CSV·XLSX)" accept=".csv,.xlsx" className="text-sm"
          onChange={(e) => e.target.files?.[0] && importBank(e.target.files[0])} />
        {imported && (
          <div className="text-sm">
            <p>전체 {imported.total_rows}건 · 새로 저장 <b>{imported.inserted}</b> · 이미 있음 {imported.duplicates}</p>
            {imported.errors.length > 0 && (
              <ul className="mt-2 list-disc rounded-xl bg-amber-50 p-3 pl-6 text-amber-900">
                {imported.errors.map((e) => <li key={e.row}>{e.row}행: {e.message}</li>)}
              </ul>
            )}
            <a href="/payments" className={`${btn} mt-3 inline-block bg-blue-600 text-white hover:bg-blue-700`}>
              입금 매칭하러 가기 →
            </a>
          </div>
        )}
      </section>
    </div>
  );
}
