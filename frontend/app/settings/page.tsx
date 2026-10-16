"use client";

import {
  ArchiveRestore,
  CheckCircle2,
  DatabaseBackup,
  Download,
  FileSearch,
  KeyRound,
  Loader2,
  ScanText,
  ServerCog,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, api, kst } from "@/lib/api";
import { useOrg } from "@/lib/useOrg";

const MIN = 8;
const COUNT_LABELS: [string, string][] = [
  ["units", "호실"], ["leases", "계약"], ["tenants", "임차인"], ["transactions", "은행 거래"],
  ["charges", "청구"], ["expenses", "지출"], ["lease_documents", "계약서"], ["audit_logs", "변경 기록"],
];

interface Inspect {
  organization: { id: string; name: string };
  created_at: string;
  schema_revision: string;
  compatible: boolean;
  counts: Record<string, number>;
  files: number;
  exists: boolean;
  existing_name: string | null;
}

async function errorOf(res: Response) {
  try {
    const b = await res.json();
    return typeof b.detail === "string" ? b.detail : `요청 실패 (${res.status})`;
  } catch {
    return `요청 실패 (${res.status})`;
  }
}

export default function SettingsPage() {
  const { orgs, orgId, error: orgError } = useOrg();
  const [lastBackup, setLastBackup] = useState<string | null | undefined>(undefined);
  const [ocr, setOcr] = useState<boolean | null>(null);

  const reload = useCallback(async () => {
    try {
      setOcr((await api<{ configured: boolean }>("/api/v1/settings/ocr")).configured);
      if (orgId) setLastBackup((await api<{ last_backup_at: string | null }>(`/api/v1/backups/status?organization_id=${orgId}`)).last_backup_at);
    } catch {
      /* 화면 아래 각 카드가 자체 오류를 보여줌 */
    }
  }, [orgId]);
  useEffect(() => { reload(); }, [reload]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">설정</h1>
        <p className="page-sub">백업·복구와 연동 상태를 관리합니다.</p>
      </header>
      {orgError && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{orgError}</p>}

      <div className="grid gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        {orgs && orgs.length > 0 && <ExportCard orgId={orgId} lastBackup={lastBackup} onDone={reload} />}
        <RestoreCard onDone={reload} />
        <ServerBackupCard />
        <OcrCard configured={ocr} />
      </div>
    </div>
  );
}

function CardHead({ icon: Icon, title, sub }: { icon: typeof KeyRound; title: string; sub: string }) {
  return (
    <div className="mb-4 flex gap-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-600"><Icon className="h-5 w-5" /></span>
      <div>
        <h2 className="card-title">{title}</h2>
        <p className="mt-0.5 text-sm text-slate-500">{sub}</p>
      </div>
    </div>
  );
}

function ExportCard({ orgId, lastBackup, onDone }: { orgId: string; lastBackup: string | null | undefined; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const valid = pw.length >= MIN && pw === pw2;

  async function download() {
    setBusy(true); setMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/backups/export?organization_id=${orgId}`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ passphrase: pw }) });
      if (!res.ok) throw new Error(await errorOf(res));
      const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "roomax.roomaxbak";
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
      setMsg({ ok: true, text: `${name} (${(blob.size / 1024).toFixed(0)}KB) 을 내려받았습니다. 비밀번호와 따로 보관하세요.` });
      setPw(""); setPw2("");
      onDone();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-5">
      <CardHead icon={DatabaseBackup} title="백업 파일 내려받기"
        sub="호실·계약·임차인·은행 거래·운영비·변경 기록과 계약서 원본까지 파일 하나로 받습니다." />
      <p className="mb-4 text-sm text-slate-600">
        마지막 백업: <b>{lastBackup === undefined ? "…" : lastBackup ? kst(lastBackup) : "없음"}</b>
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">백업 비밀번호 ({MIN}자 이상)</span>
          <input className="field w-full" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">비밀번호 확인</span>
          <input className="field w-full" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
        </label>
      </div>
      {pw2 && pw !== pw2 && <p className="mt-1 text-xs text-red-600">비밀번호가 서로 다릅니다.</p>}
      <p className="mt-3 flex gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-950">
        <KeyRound className="h-4 w-4 shrink-0 text-amber-600" />
        연락처·계약서가 들어 있어 파일 전체를 이 비밀번호로 암호화합니다. 비밀번호는 서버에 남지 않으며,
        잃어버리면 이 백업은 복구할 수 없습니다.
      </p>
      <button type="button" className="btn-primary mt-4 w-full py-2.5" disabled={!valid || busy} onClick={download}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} 백업 파일 내려받기
      </button>
      {msg && <p className={`mt-3 rounded-xl p-3 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`}>{msg.text}</p>}
    </section>
  );
}

function RestoreCard({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [pw, setPw] = useState("");
  const [info, setInfo] = useState<Inspect | null>(null);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ replaced: boolean; safety_backup: string | null; name: string } | null>(null);

  const form = (extra?: Record<string, string>) => {
    const fd = new FormData();
    fd.append("file", file!);
    fd.append("passphrase", pw);
    for (const [k, v] of Object.entries(extra ?? {})) fd.append(k, v);
    return fd;
  };

  async function inspect() {
    setBusy(true); setError(null); setInfo(null); setDone(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/backups/inspect`, { method: "POST", body: form() });
      if (!res.ok) throw new Error(await errorOf(res));
      setInfo(await res.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function restore() {
    if (!info) return;
    setBusy(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/backups/restore`, {
        method: "POST", body: form(info.exists ? { confirm_name: confirm } : undefined) });
      if (!res.ok) throw new Error(await errorOf(res));
      const r = await res.json();
      setDone({ replaced: r.replaced, safety_backup: r.safety_backup, name: r.organization.name });
      setInfo(null); setFile(null); setPw(""); setConfirm("");
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-5">
      <CardHead icon={ArchiveRestore} title="백업에서 복구"
        sub="새 서버로 옮기거나, 잘못된 변경을 백업 시점으로 되돌릴 때 씁니다." />
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">백업 파일 (.roomaxbak)</span>
          <input className="field w-full py-1.5 file:mr-2 file:rounded-lg file:border-0 file:bg-slate-100 file:px-2 file:py-1 file:text-xs"
            type="file" accept=".roomaxbak,application/octet-stream"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setInfo(null); setDone(null); }} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">백업 비밀번호</span>
          <input className="field w-full" type="password" autoComplete="off" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
      </div>
      <button type="button" className="btn-secondary mt-3 w-full py-2.5" disabled={!file || !pw || busy} onClick={inspect}>
        {busy && !info ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />} 백업 내용 확인
      </button>

      {info && (
        <div className="mt-4 space-y-3 rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <b className="text-base">{info.organization.name}</b>
            <span className="text-xs text-slate-500">백업 시각 {kst(info.created_at)}</span>
          </div>
          <dl className="grid grid-cols-4 gap-2 text-center text-xs">
            {COUNT_LABELS.map(([k, label]) => (
              <div key={k} className="rounded-lg bg-slate-50 p-2">
                <dt className="text-slate-500">{label}</dt>
                <dd className="text-sm font-semibold tabular-nums">{(info.counts[k] ?? 0).toLocaleString("ko-KR")}</dd>
              </div>
            ))}
          </dl>
          {!info.compatible ? (
            <p className="flex gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-800">
              <TriangleAlert className="h-4 w-4 shrink-0" /> 다른 버전({info.schema_revision})에서 만든 백업이라 이 서버에서는 복구할 수 없습니다.
            </p>
          ) : info.exists ? (
            <div className="space-y-2 rounded-xl bg-red-50 p-3 text-sm text-red-900">
              <p className="flex gap-2">
                <TriangleAlert className="h-4 w-4 shrink-0 text-red-600" />
                <span>이 서버의 <b>{info.existing_name}</b> 데이터를 백업 시점으로 <b>덮어씁니다.</b> 그 뒤에 입력한 내용은 사라집니다.
                  덮어쓰기 직전 상태는 서버에 같은 비밀번호로 자동 백업됩니다.</span>
              </p>
              <label className="block">
                <span className="mb-1 block text-xs">확인을 위해 사업장 이름 <b>{info.existing_name}</b> 을 입력하세요</span>
                <input className="field w-full" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
              </label>
            </div>
          ) : (
            <p className="rounded-xl bg-blue-50 p-3 text-sm text-blue-900">이 서버에는 없는 데이터입니다. 그대로 추가됩니다.</p>
          )}
          <button type="button" className={`btn w-full py-2.5 text-white ${info.exists ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"}`}
            disabled={busy || !info.compatible || (info.exists && confirm.trim() !== info.existing_name)} onClick={restore}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArchiveRestore className="h-4 w-4" />}
            {info.exists ? "덮어써서 복구" : "복구"}
          </button>
        </div>
      )}
      {error && <p className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {done && (
        <p className="mt-3 flex gap-2 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>
            <b>{done.name}</b> 복구를 마쳤습니다.
            {done.safety_backup && <> 덮어쓰기 전 상태는 서버 <code className="rounded bg-white/70 px-1">{done.safety_backup}</code> 에 있습니다.</>}
          </span>
        </p>
      )}
    </section>
  );
}

function ServerBackupCard() {
  return (
    <section className="card p-5">
      <CardHead icon={ServerCog} title="서버 자동 백업" sub="매일 정해진 시각에 서버가 스스로 백업 파일을 만듭니다 (운영 담당자 설정)." />
      <pre className="overflow-x-auto rounded-xl bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">{`# crontab -e  (매일 03:10 KST, 최근 30개 보관)
10 3 * * * cd /srv/roomax/backend && \\
  ROOMAX_BACKUP_PASSPHRASE='…' \\
  .venv/bin/python -m app.backup_cli \\
  --out /srv/roomax-backups --keep 30`}</pre>
      <ul className="mt-3 space-y-1 text-xs text-slate-500">
        <li>· 백업 폴더는 다른 디스크나 외부 저장소로 한 번 더 복사해 두세요.</li>
        <li>· 비밀번호는 명령줄이 아니라 환경변수로만 넘깁니다.</li>
      </ul>
    </section>
  );
}

function OcrCard({ configured }: { configured: boolean | null }) {
  return (
    <section className="card p-5">
      <CardHead icon={ScanText} title="계약서 OCR" sub="NAVER CLOVA OCR (General)" />
      {configured == null ? <p className="text-sm text-slate-500">확인 중…</p> : configured ? (
        <p className="flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" /> 연결됨</p>
      ) : (
        <p className="text-sm text-slate-600">
          설정 안 됨 — 서버 <code className="rounded bg-slate-100 px-1">backend/.env</code> 의
          <code className="rounded bg-slate-100 px-1">ROOMAX_CLOVA_OCR_URL</code> ·
          <code className="rounded bg-slate-100 px-1">ROOMAX_CLOVA_OCR_SECRET</code> 를 채우고 재시작하세요.
        </p>
      )}
    </section>
  );
}
