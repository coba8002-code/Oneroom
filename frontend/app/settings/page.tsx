"use client";

import {
  ArchiveRestore,
  LockKeyhole,
  Smartphone,
  UserRound,
  CheckCircle2,
  DatabaseBackup,
  Download,
  FileSearch,
  KeyRound,
  Loader2,
  ScanText,
  ServerCog,
  Trash2,
  TriangleAlert,
  UserPlus,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, apiFetch, kst } from "@/lib/api";
import { useMe } from "@/lib/me";
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
  const { me } = useMe();
  const isOwner = me?.user.role === "owner";  // 백업·복구는 대표만 (서버도 같은 규칙)
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
        <p className="page-sub">계정 보안, 백업·복구, 연동 상태를 관리합니다.</p>
      </header>
      {orgError && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{orgError}</p>}

      <div className="grid gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        <AccountCard />
        <SecurityCard />
        {isOwner && <MembersCard />}
        {isOwner && orgs && orgs.length > 0 && <ExportCard orgId={orgId} lastBackup={lastBackup} onDone={reload} />}
        {isOwner && <RestoreCard onDone={reload} />}
        <ServerBackupCard />
        <OcrCard configured={ocr} />
      </div>
      <DeleteAccountCard />
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
      const res = await apiFetch(`/api/v1/backups/export?organization_id=${orgId}`, {
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
      const res = await apiFetch("/api/v1/backups/inspect", { method: "POST", body: form() });
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
      const res = await apiFetch("/api/v1/backups/restore", {
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

function Msg({ m }: { m: { ok: boolean; text: string } | null }) {
  if (!m) return null;
  return <p className={`mt-3 rounded-xl p-3 text-sm ${m.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"}`}>{m.text}</p>;
}

function AccountCard() {
  const { me, reload } = useMe();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (!me) return null;
  async function toggleMarketing(agree: boolean) {
    try {
      await api("/api/v1/auth/marketing", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ agree }) });
      await reload();
      setMsg({ ok: true, text: agree ? "광고성 정보 수신에 동의했습니다." : "광고성 정보 수신 동의를 철회했습니다." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }
  return (
    <section className="card p-5">
      <CardHead icon={UserRound} title="내 계정" sub="로그인 정보와 수신 동의" />
      <dl className="grid grid-cols-[6rem_1fr] gap-y-2 text-sm">
        <dt className="text-slate-500">이름</dt><dd>{me.user.name}</dd>
        <dt className="text-slate-500">이메일</dt>
        <dd className="flex flex-wrap items-center gap-2"><span className="break-all">{me.user.email}</span>
          <span className={`chip ${me.user.email_verified ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>
            {me.user.email_verified ? "확인됨" : "확인 전"}</span></dd>
        <dt className="text-slate-500">사업장</dt><dd>{me.organization.name}</dd>
        <dt className="text-slate-500">권한</dt><dd>{ {owner: "대표 (전체)", manager: "관리자 (입력·수정)", viewer: "조회만"}[me.user.role] }</dd>
      </dl>
      <label className="mt-4 flex items-center gap-2 rounded-xl bg-slate-50 p-3 text-sm">
        <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-blue-600" checked={me.user.marketing_agreed}
          onChange={(e) => toggleMarketing(e.target.checked)} />
        광고성 정보(새 기능·할인 안내) 이메일 수신 <span className="text-xs text-slate-400">(선택)</span>
      </label>
      <Msg m={msg} />
    </section>
  );
}

function SecurityCard() {
  const { me, reload } = useMe();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [disablePw, setDisablePw] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const post = (path: string, body?: unknown) => api(path, { method: "POST",
    ...(body ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); if (ok) setMsg({ ok: true, text: ok }); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  if (!me) return null;
  return (
    <section className="card p-5">
      <CardHead icon={LockKeyhole} title="보안" sub="비밀번호, 2단계 인증, 다른 기기 로그아웃" />
      <div className="space-y-2">
        <div className="text-sm font-semibold text-slate-700">비밀번호 변경</div>
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <input className="field w-full min-w-0" type="password" aria-label="현재 비밀번호" placeholder="현재 비밀번호" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
          <input className="field w-full min-w-0" type="password" aria-label="새 비밀번호" placeholder="새 비밀번호 (10자 이상, 문자+숫자)" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <button type="button" className="btn-secondary whitespace-nowrap" disabled={!cur || next.length < 10}
            onClick={() => run(async () => { await post("/api/v1/auth/password", { current_password: cur, new_password: next }); setCur(""); setNext(""); },
              "비밀번호를 바꿨습니다. 다른 기기는 로그아웃되었습니다.")}>변경</button>
        </div>
      </div>

      <div className="mt-5 space-y-2 border-t border-slate-100 pt-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <Smartphone className="h-4 w-4" /> 2단계 인증 (인증 앱)
          <span className={`chip ${me.user.mfa_enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
            {me.user.mfa_enabled ? "사용 중" : "꺼짐"}</span>
        </div>
        {!me.user.mfa_enabled && !setup && (
          <button type="button" className="btn-secondary btn-sm"
            onClick={() => run(async () => setSetup(await post("/api/v1/auth/mfa/setup") as { secret: string; otpauth_uri: string }),
              "인증 앱에 아래 키를 등록하고 6자리 코드를 넣으세요.")}>켜기</button>
        )}
        {setup && !me.user.mfa_enabled && (
          <div className="space-y-2 rounded-xl bg-slate-50 p-3 text-sm">
            <p>Google Authenticator 등 인증 앱에서 &lsquo;설정 키 입력&rsquo;으로 아래 키를 넣으세요. 휴대폰에서 보고 있다면
              <a href={setup.otpauth_uri} className="font-semibold text-blue-600 underline"> 앱으로 열기</a>.</p>
            <code className="block break-all rounded-lg bg-white p-2 text-center font-mono text-base tracking-wider">{setup.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
            <div className="flex gap-2">
              <input className="field min-w-0 flex-1 text-center tracking-[0.3em]" inputMode="numeric" maxLength={6} aria-label="인증 앱 6자리 코드" placeholder="6자리 코드"
                value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              <button type="button" className="btn-primary" disabled={code.length !== 6}
                onClick={() => run(async () => { await post("/api/v1/auth/mfa/enable", { code }); setSetup(null); setCode(""); await reload(); },
                  "2단계 인증을 켰습니다. 다음 로그인부터 코드를 묻습니다.")}>확인</button>
            </div>
          </div>
        )}
        {me.user.mfa_enabled && (
          <div className="flex flex-wrap gap-2">
            <input className="field min-w-0 flex-1" type="password" aria-label="2단계 인증 끄기 — 비밀번호" placeholder="비밀번호" value={disablePw} onChange={(e) => setDisablePw(e.target.value)} />
            <input className="field w-28 text-center" inputMode="numeric" maxLength={6} aria-label="2단계 인증 끄기 — 인증 코드" placeholder="코드" value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            <button type="button" className="btn-secondary whitespace-nowrap" disabled={!disablePw || code.length !== 6}
              onClick={() => run(async () => { await post("/api/v1/auth/mfa/disable", { password: disablePw, code }); setDisablePw(""); setCode(""); await reload(); },
                "2단계 인증을 껐습니다.")}>끄기</button>
          </div>
        )}
      </div>

      <div className="mt-5 flex items-center justify-between gap-2 border-t border-slate-100 pt-4 text-sm">
        <span className="text-slate-600">이 기기를 뺀 모든 기기에서 로그아웃</span>
        <button type="button" className="btn-secondary btn-sm"
          onClick={() => run(async () => { const r = await post("/api/v1/auth/sessions/revoke-others") as { revoked: number };
            setMsg({ ok: true, text: `${r.revoked}개 기기에서 로그아웃했습니다.` }); }, "")}>로그아웃</button>
      </div>
      <Msg m={msg} />
    </section>
  );
}

interface DeletionPreview {
  scope: "organization" | "member";
  organization_name: string;
  other_accounts?: number;
  counts?: { units: number; leases: number; transactions: number; documents: number };
}

/** 회원 탈퇴 · 사업장 해지. 되돌릴 수 없으므로 열어야 보이고, 비밀번호(+코드)·사업장 이름을 다시 받는다. */
function DeleteAccountCard() {
  const { me } = useMe();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<DeletionPreview | null>(null);
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (!me) return null;
  const owner = me.user.role === "owner";

  async function start() {
    setMsg(null);
    try {
      setPreview(await api<DeletionPreview>("/api/v1/auth/account/deletion-preview"));
      setOpen(true);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }
  async function remove() {
    setBusy(true); setMsg(null);
    try {
      await api("/api/v1/auth/account/delete", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ password, otp: me!.user.mfa_enabled ? otp : null, confirm_name: owner ? name : null }) });
      window.location.href = "/login?deleted=1";
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
      setBusy(false);
    }
  }
  const ready = password && (!me.user.mfa_enabled || otp.length === 6) && (!owner || name === preview?.organization_name);

  return (
    <section className="card border-red-200 p-5">
      <div className="mb-4 flex gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-red-50 text-red-600"><Trash2 className="h-5 w-5" /></span>
        <div>
          <h2 className="card-title">{owner ? "사업장 해지 · 회원 탈퇴" : "회원 탈퇴"}</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            {owner ? "이 사업장의 모든 데이터와 계정을 영구 삭제합니다. 되돌릴 수 없습니다."
              : "내 계정만 삭제합니다. 사업장 데이터는 대표에게 그대로 남습니다."}</p>
        </div>
      </div>
      {!open ? (
        <button type="button" className="btn-secondary border-red-200 text-red-700 hover:bg-red-50" onClick={start}>
          {owner ? "사업장 해지 진행" : "탈퇴 진행"}</button>
      ) : preview && (
        <div className="space-y-3 text-sm">
          {preview.scope === "organization" && preview.counts && (
            <>
              <div className="rounded-xl bg-red-50 p-3 text-red-900">
                <p className="font-semibold">함께 지워지는 것 — {preview.organization_name}</p>
                <p className="mt-1">호실 {preview.counts.units} · 계약 {preview.counts.leases} · 은행 거래 {preview.counts.transactions} ·
                  계약서 파일 {preview.counts.documents} · 이 사업장의 다른 계정 {preview.other_accounts ?? 0}개 · 복구 직전 안전 백업</p>
                <p className="mt-1 text-xs text-red-800">임차인 연락처·계약서 원본을 포함한 모든 업무 데이터가 즉시 삭제됩니다.
                  남는 것은 개인정보 없는 파기 기록(일시·건수)뿐입니다.</p>
              </div>
              <p className="flex gap-2 rounded-xl bg-amber-50 p-3 text-amber-950">
                <TriangleAlert className="h-5 w-5 shrink-0 text-amber-600" />
                <span>지우기 전에 위 <b>백업 내려받기</b>로 백업 파일을 받아 두세요. 나중에 새로 가입해 그 파일로 복구할 수 있습니다.
                  서버 정기 백업에 남은 사본은 보관 기간이 지나면 순환 삭제됩니다.</span>
              </p>
            </>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <input className="field w-full min-w-0" type="password" aria-label="탈퇴 확인 — 비밀번호" placeholder="비밀번호" autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)} />
            {me.user.mfa_enabled && (
              <input className="field w-full min-w-0 text-center tracking-[0.3em]" inputMode="numeric" maxLength={6} aria-label="탈퇴 확인 — 인증 앱 코드" placeholder="인증 앱 코드"
                value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
            )}
          </div>
          {owner && (
            <label className="block">
              <span className="mb-1 block text-slate-600">확인을 위해 사업장 이름 <b className="text-slate-900">{preview.organization_name}</b> 을 그대로 입력하세요</span>
              <input className="field w-full" value={name} onChange={(e) => setName(e.target.value)} aria-label="사업장 이름 확인" />
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-danger" disabled={!ready || busy} onClick={remove}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {owner ? "사업장과 모든 데이터 영구 삭제" : "내 계정 영구 삭제"}</button>
            <button type="button" className="btn-secondary" onClick={() => { setOpen(false); setPassword(""); setOtp(""); setName(""); setMsg(null); }}>취소</button>
          </div>
        </div>
      )}
      <Msg m={msg} />
    </section>
  );
}

interface MemberRow { id: string; name: string | null; email: string; role: "owner" | "manager" | "viewer"; me: boolean;
  mfa_enabled: boolean; last_login_at: string | null }
interface InviteRow { id: string; email: string; role: "manager" | "viewer"; expires_at: string; expired: boolean }

const ROLE_NAME = { owner: "대표", manager: "관리자", viewer: "조회" } as const;

/** 멤버 초대·권한·내보내기 (대표만). 관리자 = 입력·수정, 조회 = 보기만. */
function MembersCard() {
  const [data, setData] = useState<{ members: MemberRow[]; invitations: InviteRow[] } | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"manager" | "viewer">("manager");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(async () => {
    try { setData(await api("/api/v1/members")); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const json = (method: string, body?: unknown) => ({ method,
    ...(body ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}) });
  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
  const invite = (to: string, r: "manager" | "viewer") => run(async () => {
    await api("/api/v1/members/invitations", json("POST", { email: to, role: r }));
    setEmail("");
  }, `${to} 로 초대 메일을 보냈습니다 (7일 동안 유효).`);

  return (
    <section className="card p-5">
      <CardHead icon={Users} title="멤버" sub="함께 관리할 사람을 초대합니다. 관리자는 입력·수정, 조회는 보기만 합니다." />
      <ul className="divide-y divide-slate-100 text-sm">
        {data?.members.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{m.name ?? "—"} {m.me && <span className="text-xs text-slate-400">(나)</span>}</div>
              <div className="truncate text-xs text-slate-500">{m.email} · 최근 로그인 {m.last_login_at ? kst(m.last_login_at) : "—"}</div>
            </div>
            {m.role === "owner" ? <span className="chip bg-blue-50 text-blue-700">대표</span> : (
              <>
                <select className="field py-1 text-xs" aria-label={`${m.name ?? m.email} 권한`} value={m.role} disabled={busy}
                  onChange={(e) => run(() => api(`/api/v1/members/${m.id}`, json("PATCH", { role: e.target.value })),
                    `${m.name ?? m.email} 님의 권한을 ${ROLE_NAME[e.target.value as "manager" | "viewer"]}(으)로 바꿨습니다.`)}>
                  <option value="manager">관리자</option>
                  <option value="viewer">조회</option>
                </select>
                <button type="button" className="btn-secondary btn-sm text-red-700 hover:bg-red-50" disabled={busy}
                  onClick={() => window.confirm(`${m.name ?? m.email} 님을 내보낼까요? 그 계정은 삭제되고 바로 로그아웃됩니다. 입력한 기록은 남습니다.`)
                    && run(() => api(`/api/v1/members/${m.id}`, json("DELETE")), "멤버를 내보냈습니다.")}>내보내기</button>
              </>
            )}
          </li>
        ))}
        {data?.invitations.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium text-slate-600">{i.email}</div>
              <div className="text-xs text-slate-500">{ROLE_NAME[i.role]} · {i.expired ? "초대 만료" : `초대 대기 — ${kst(i.expires_at)}까지`}</div>
            </div>
            <span className={`chip ${i.expired ? "bg-slate-100 text-slate-500" : "bg-amber-50 text-amber-800"}`}>{i.expired ? "만료" : "대기"}</span>
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => invite(i.email, i.role)}>다시 보내기</button>
            <button type="button" className="btn-secondary btn-sm" disabled={busy}
              onClick={() => run(() => api(`/api/v1/members/invitations/${i.id}/revoke`, json("POST")), "초대를 취소했습니다.")}>취소</button>
          </li>
        ))}
      </ul>
      <form className="mt-3 grid gap-2 border-t border-slate-100 pt-4 sm:grid-cols-[minmax(0,1fr)_auto_auto]"
        onSubmit={(e) => { e.preventDefault(); invite(email.trim(), role); }}>
        <input className="field w-full min-w-0" type="email" placeholder="초대할 이메일" aria-label="초대할 이메일"
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <select className="field" aria-label="초대 권한" value={role} onChange={(e) => setRole(e.target.value as "manager" | "viewer")}>
          <option value="manager">관리자 (입력·수정)</option>
          <option value="viewer">조회 (보기만)</option>
        </select>
        <button type="submit" className="btn-primary whitespace-nowrap" disabled={busy || !email.includes("@")}>
          <UserPlus className="h-4 w-4" /> 초대 보내기</button>
      </form>
      <Msg m={msg} />
    </section>
  );
}
