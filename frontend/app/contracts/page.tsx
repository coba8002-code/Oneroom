"use client";

import {
  Camera,
  CheckCircle2,
  ChevronLeft,
  FileCheck2,
  FileClock,
  FileText,
  FileX2,
  ImageUp,
  Loader2,
  RefreshCw,
  ScanText,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiFetch, type Contract, type ContractField, type DocumentDetail, won } from "@/lib/api";
import { useOrg } from "@/lib/useOrg";

const FIELD_META: { key: ContractField; label: string; kind: "money" | "day" | "date" }[] = [
  { key: "deposit", label: "보증금", kind: "money" },
  { key: "rent", label: "월세 (관리비 포함)", kind: "money" },
  { key: "due_day", label: "납부일 (매월)", kind: "day" },
  { key: "start_date", label: "계약 시작", kind: "date" },
  { key: "end_date", label: "계약 종료", kind: "date" },
];

const show = (kind: string, v: number | string | null | undefined) =>
  v == null || v === "" ? "—" : kind === "money" ? won(Number(v)) : kind === "day" ? `${v}일` : String(v);

function docState(c: Contract): { label: string; tone: string; icon: typeof FileText } {
  if (c.documents.length === 0) return { label: "계약서 없음", tone: "bg-slate-100 text-slate-600", icon: FileX2 };
  if (c.documents.some((d) => !d.verified_at)) return { label: "검수 대기", tone: "bg-amber-50 text-amber-800", icon: FileClock };
  return { label: "검수 완료", tone: "bg-emerald-50 text-emerald-700", icon: FileCheck2 };
}

export default function ContractsPage() {
  const { orgs, orgId, error: orgError } = useOrg();
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [ocrReady, setOcrReady] = useState<boolean | null>(null);
  const [active, setActive] = useState<{ contract: Contract; docId: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const q = `organization_id=${orgId}`;
  const reload = useCallback(async () => {
    if (!orgId) return;
    try {
      const [c, s] = await Promise.all([
        api<Contract[]>(`/api/v1/contracts?${q}`),
        api<{ configured: boolean }>("/api/v1/settings/ocr"),
      ]);
      setContracts(c);
      setOcrReady(s.configured);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, q]);
  useEffect(() => { reload(); }, [reload]);

  if (orgs && orgs.length === 0) {
    return <p className="text-slate-600">먼저 <a className="font-semibold text-blue-600 underline" href="/onboarding">건물·호실을 등록</a>하세요.</p>;
  }

  if (active) {
    return (
      <Register orgId={orgId} contract={active.contract} initialDocId={active.docId} ocrReady={!!ocrReady}
        onClose={() => { setActive(null); reload(); }} />
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">계약 관리</h1>
        <p className="page-sub">종이 계약서를 찍어 올리면 글자를 읽어 값을 제안합니다. 확정은 사장님이 검수한 뒤에만 됩니다.</p>
      </header>

      <OcrBanner ready={ocrReady} />
      {(error || orgError) && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error ?? orgError}</p>}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {contracts.map((c) => {
          const st = docState(c);
          const pending = c.documents.find((d) => !d.verified_at);
          return (
            <div key={c.lease_id} className="card flex flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-lg font-bold">{c.unit_no}호</div>
                  <div className="text-sm text-slate-500">{c.tenant_name}</div>
                </div>
                <span className={`chip ${st.tone}`}><st.icon className="h-3.5 w-3.5" />{st.label}</span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                <dt className="text-slate-500">월세</dt><dd className="text-right font-medium tabular-nums">{won(c.rent)}</dd>
                <dt className="text-slate-500">보증금</dt><dd className="text-right tabular-nums">{won(c.deposit)}</dd>
                <dt className="text-slate-500">납부일</dt><dd className="text-right">매월 {c.due_day}일</dd>
                <dt className="text-slate-500">기간</dt><dd className="text-right text-xs tabular-nums">{c.start_date} ~ {c.end_date ?? "—"}</dd>
              </dl>
              <div className="mt-4 flex gap-2 pt-1">
                {pending ? (
                  <button type="button" className="btn-primary flex-1" onClick={() => setActive({ contract: c, docId: pending.id })}>
                    <ScanText className="h-4 w-4" /> 검수하기
                  </button>
                ) : (
                  <button type="button" className={`${c.documents.length ? "btn-secondary" : "btn-primary"} flex-1`}
                    onClick={() => setActive({ contract: c, docId: null })}>
                    <Camera className="h-4 w-4" /> {c.documents.length ? "새 계약서 등록" : "계약서 등록"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {orgs && contracts.length === 0 && !error && (
        <p className="text-sm text-slate-500">입주 중인 계약이 없습니다.</p>
      )}
    </div>
  );
}

function OcrBanner({ ready }: { ready: boolean | null }) {
  if (ready == null) return null;
  return ready ? (
    <div className="flex gap-3 rounded-2xl border border-blue-100 bg-blue-50/70 p-4 text-sm text-blue-950">
      <ShieldCheck className="h-5 w-5 shrink-0 text-blue-600" />
      <p>
        <b>클라우드 OCR(NAVER CLOVA) 연결됨.</b> 계약서 이미지는 글자를 읽기 위해 네이버 클라우드로 전송됩니다.
        원본은 이 서버에 암호화해 보관하고, 이름·연락처는 값으로 뽑지 않습니다.
      </p>
    </div>
  ) : (
    <div className="flex gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <TriangleAlert className="h-5 w-5 shrink-0 text-amber-600" />
      <p>
        <b>OCR이 아직 설정되지 않았습니다.</b> 계약서는 암호화해 저장되고, 값은 직접 입력해 검수합니다.
        서버 <code className="rounded bg-white/70 px-1">backend/.env</code>에 <code className="rounded bg-white/70 px-1">ROOMAX_CLOVA_OCR_URL</code> ·
        <code className="rounded bg-white/70 px-1">ROOMAX_CLOVA_OCR_SECRET</code>을 넣으면 자동으로 읽습니다.
      </p>
    </div>
  );
}

const STEPS = ["촬영", "확인", "저장"] as const;

function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex items-center gap-2" aria-label="진행 단계">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ${
            i === step ? "bg-blue-600 text-white" : i < step ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-500"}`}
            aria-current={i === step ? "step" : undefined}>
            <span className={`grid h-5 w-5 place-items-center rounded-full text-xs ${i === step ? "bg-white text-blue-600" : "bg-white/70"}`}>{i + 1}</span>
            {s}
          </span>
          {i < STEPS.length - 1 && <span className="h-px w-4 bg-slate-300 sm:w-8" />}
        </li>
      ))}
    </ol>
  );
}

function Register({ orgId, contract, initialDocId, ocrReady, onClose }: {
  orgId: string; contract: Contract; initialDocId: string | null; ocrReady: boolean; onClose: () => void;
}) {
  const q = `organization_id=${orgId}`;
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [step, setStep] = useState(initialDocId ? 1 : 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialDocId) api<DocumentDetail>(`/api/v1/documents/${initialDocId}?${q}`).then(setDoc).catch((e) => setError(e.message));
  }, [initialDocId, q]);

  async function upload(file: File) {
    setBusy(true); setError(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setDoc(await api<DocumentDetail>(`/api/v1/leases/${contract.lease_id}/documents?${q}`, { method: "POST", body: fd }));
      setStep(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-white" aria-label="목록으로">
          <ChevronLeft className="h-6 w-6" />
        </button>
        <div className="mr-auto">
          <h1 className="page-title">계약서 등록 · {contract.unit_no}호</h1>
          <p className="text-sm text-slate-500">{contract.tenant_name}</p>
        </div>
        <Stepper step={step} />
      </div>
      {error && <p className="whitespace-pre-line rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}

      {step === 0 && <Capture busy={busy} ocrReady={ocrReady} onFile={upload} />}
      {step === 1 && doc && (
        <Review orgId={orgId} doc={doc} onDoc={setDoc} onDone={() => setStep(2)} />
      )}
      {step === 1 && !doc && !error && <p className="text-sm text-slate-500">불러오는 중…</p>}
      {step === 2 && doc?.verified_fields && <Saved doc={doc} onClose={onClose} />}
    </div>
  );
}

function Capture({ busy, ocrReady, onFile }: { busy: boolean; ocrReady: boolean; onFile: (f: File) => void }) {
  const camera = useRef<HTMLInputElement>(null);
  const album = useRef<HTMLInputElement>(null);
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) onFile(f);
    e.target.value = "";
  };
  return (
    <div className="card mx-auto max-w-md p-5">
      <div className="relative mx-auto grid aspect-[3/4] max-h-[420px] place-items-center rounded-2xl bg-slate-800 text-slate-300">
        {(["left-3 top-3 border-l-4 border-t-4", "right-3 top-3 border-r-4 border-t-4",
          "bottom-3 left-3 border-b-4 border-l-4", "bottom-3 right-3 border-b-4 border-r-4"] as const).map((c) => (
          <span key={c} className={`absolute h-8 w-8 rounded-sm border-white/90 ${c}`} />
        ))}
        <div className="flex flex-col items-center gap-2 px-6 text-center">
          {busy ? <Loader2 className="h-10 w-10 animate-spin" /> : <FileText className="h-12 w-12" strokeWidth={1.5} />}
          <p className="text-sm">{busy ? (ocrReady ? "올리고 글자를 읽는 중…" : "올리는 중…") : "계약서 전체가 틀 안에 들어오게 찍어 주세요"}</p>
          <p className="text-xs text-slate-400">여러 장이면 PDF 한 파일로 올리세요 · JPG/PNG/PDF 10MB</p>
        </div>
      </div>
      <div className="mt-5 space-y-2">
        <button type="button" className="btn-primary w-full py-3" disabled={busy} onClick={() => camera.current?.click()}>
          <Camera className="h-5 w-5" /> 사진 촬영
        </button>
        <button type="button" className="btn-secondary w-full py-3" disabled={busy} onClick={() => album.current?.click()}>
          <ImageUp className="h-5 w-5" /> 앨범·파일에서 선택
        </button>
        <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" onChange={pick} />
        <input ref={album} type="file" accept="image/jpeg,image/png,application/pdf" className="hidden" onChange={pick} />
      </div>
    </div>
  );
}

function Preview({ orgId, doc }: { orgId: string; doc: DocumentDetail }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    apiFetch(`/api/v1/documents/${doc.id}/file?organization_id=${orgId}`)
      .then((r) => r.blob())
      .then((b) => { revoke = URL.createObjectURL(b); setUrl(revoke); })
      .catch(() => setUrl(null));
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [doc.id, orgId]);
  if (!url) return <div className="grid aspect-[3/4] place-items-center rounded-xl bg-slate-100 text-sm text-slate-400">미리보기 불러오는 중…</div>;
  return doc.content_type === "application/pdf" ? (
    <iframe src={url} title="계약서 PDF" className="aspect-[3/4] w-full rounded-xl border" />
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt="올린 계약서" className="max-h-[70vh] w-full rounded-xl border object-contain" />
  );
}

function Review({ orgId, doc, onDoc, onDone }: {
  orgId: string; doc: DocumentDetail; onDoc: (d: DocumentDetail) => void; onDone: () => void;
}) {
  const q = `organization_id=${orgId}`;
  const initial = (k: ContractField) => {
    const ocr = doc.fields?.[k]?.value;
    const v = ocr ?? doc.current[k];
    return v == null ? "" : String(v);
  };
  const [values, setValues] = useState<Record<ContractField, string>>(
    () => Object.fromEntries(FIELD_META.map((f) => [f.key, initial(f.key)])) as Record<ContractField, string>);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);

  async function retry() {
    setBusy(true); setError(null);
    try {
      const d = await api<DocumentDetail>(`/api/v1/documents/${doc.id}/ocr?${q}`, { method: "POST" });
      onDoc(d);
      setValues((v) => {
        const next = { ...v };
        for (const f of FIELD_META) if (d.fields?.[f.key]?.value != null) next[f.key] = String(d.fields[f.key].value);
        return next;
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true); setError(null);
    const num = (s: string) => Number(s.replace(/[,\s원]/g, ""));
    try {
      onDoc(await api<DocumentDetail>(`/api/v1/documents/${doc.id}/verify?${q}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          deposit: num(values.deposit), rent: num(values.rent), due_day: num(values.due_day),
          start_date: values.start_date, end_date: values.end_date || null,
        }),
      }));
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const missing = (["deposit", "rent", "due_day", "start_date"] as ContractField[]).some((k) => values[k].trim() === "");

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="card p-3"><Preview orgId={orgId} doc={doc} /></div>

      <div className="space-y-4">
        {doc.ocr_status === "done" ? (
          <p className="flex items-center gap-2 rounded-xl bg-blue-50 p-3 text-sm text-blue-900">
            <ScanText className="h-4 w-4" /> 글자를 읽어 값을 제안했습니다. 계약서와 대조해 고친 뒤 확정하세요.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
            <TriangleAlert className="h-4 w-4 text-amber-600" />
            <span className="flex-1">{doc.ocr_error ?? "OCR 결과가 없습니다."} 현재 원장 값을 채워 두었습니다.</span>
            {doc.ocr_status === "failed" && (
              <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={retry}>
                <RefreshCw className="h-3.5 w-3.5" /> 다시 읽기
              </button>
            )}
          </div>
        )}

        <div className="card divide-y divide-slate-100">
          {FIELD_META.map((f) => {
            const cur = doc.current[f.key];
            const cand = doc.fields?.[f.key];
            const changed = values[f.key] !== (cur == null ? "" : String(cur));
            return (
              <div key={f.key} className="grid gap-2 p-4 sm:grid-cols-[8rem_minmax(0,1fr)_11rem] sm:items-start">
                <div className="text-sm font-semibold text-slate-700">{f.label}</div>
                <div className="space-y-1 text-xs text-slate-500">
                  <div>지금 원장: <b className="font-semibold text-slate-700">{show(f.kind, cur)}</b></div>
                  {doc.ocr_status === "done" && (
                    cand?.value != null ? (
                      <div>
                        OCR 제안: <b className="font-semibold text-blue-700">{show(f.kind, cand.value)}</b>
                        {cand.evidence && <span className="mt-0.5 block rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-500">“{cand.evidence}”</span>}
                      </div>
                    ) : <div className="text-amber-700">OCR이 찾지 못함 — 계약서를 보고 입력</div>
                  )}
                </div>
                <div>
                  <input className={`field w-full ${changed ? "border-blue-400 bg-blue-50/40" : ""}`}
                    type={f.kind === "date" ? "date" : "text"} inputMode={f.kind === "date" ? undefined : "numeric"}
                    value={values[f.key]} aria-label={`${f.label} 확정값`}
                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
                  {f.kind === "money" && /^[\d,]+$/.test(values[f.key].trim()) && (
                    <div className="mt-1 text-[11px] tabular-nums text-slate-500">= {won(Number(values[f.key].replace(/,/g, "")))}</div>
                  )}
                  {changed && <div className="mt-1 text-[11px] font-medium text-blue-700">원장 값에서 바뀜</div>}
                </div>
              </div>
            );
          })}
        </div>

        <ul className="space-y-1 text-xs text-slate-500">
          <li>· 월세·납부일을 바꾸면 <b>다음에 만드는 청구부터</b> 적용됩니다. 이미 만든 청구는 그대로입니다.</li>
          <li>· 이미 받은 보증금은 여기서 바꿀 수 없습니다. 증액·반환은 실제 입출금으로 처리하세요.</li>
        </ul>

        {doc.ocr_text && (
          <div>
            <button type="button" className="text-xs font-semibold text-slate-500 underline" onClick={() => setShowText((s) => !s)}>
              {showText ? "읽은 글자 숨기기" : "OCR이 읽은 글자 전체 보기"}
            </button>
            {showText && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-xs text-slate-600">{doc.ocr_text}</pre>}
          </div>
        )}

        {error && <p className="whitespace-pre-line rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        <button type="button" className="btn-primary w-full py-3" disabled={busy || missing} onClick={verify}>
          {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <CheckCircle2 className="h-5 w-5" />} 검수 완료 · 원장에 반영
        </button>
      </div>
    </div>
  );
}

function Saved({ doc, onClose }: { doc: DocumentDetail; onClose: () => void }) {
  const v = doc.verified_fields!;
  return (
    <div className="card mx-auto max-w-md p-6 text-center">
      <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-500" />
      <h2 className="mt-3 text-lg font-bold">{doc.unit_no}호 계약을 반영했습니다</h2>
      <p className="mt-1 text-sm text-slate-500">
        {v.changed.length ? `바뀐 항목: ${v.changed.map((k) => FIELD_META.find((f) => f.key === k)!.label).join(", ")}` : "원장 값과 같아 바뀐 것은 없습니다."}
      </p>
      <dl className="mt-4 grid grid-cols-2 gap-y-1 rounded-xl bg-slate-50 p-4 text-left text-sm">
        {FIELD_META.map((f) => (
          <div key={f.key} className="contents">
            <dt className={v.changed.includes(f.key) ? "font-semibold text-blue-700" : "text-slate-500"}>{f.label}</dt>
            <dd className="text-right tabular-nums">{show(f.kind, v[f.key])}</dd>
          </div>
        ))}
      </dl>
      <button type="button" className="btn-primary mt-5 w-full py-3" onClick={onClose}>목록으로</button>
    </div>
  );
}
