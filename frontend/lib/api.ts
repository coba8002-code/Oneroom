export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type UseType = "rental" | "owner";

export interface UnitIn {
  unit_no: string;
  floor: number | null;
  area_m2: number | null;
  use_type: UseType;
  tenant_name: string | null;
  tenant_phone: string | null;
  deposit: number | null;
  rent: number | null;
  due_day: number | null;
  start_date: string | null;
  end_date: string | null;
  deposit_received_on: string | null;
}

export interface RowError {
  row: number;
  message: string;
}

export interface OnboardingOut {
  organization_id: string;
  property_id: string;
  bank_account_id: string;
  units: number;
  leases: number;
  vacant: number;
  deposits_total: number;
}

export interface ChargeOut {
  unit_no: string;
  due_date: string;
  amount: number;
  status: string;
}

export interface ImportOut {
  total_rows: number;
  inserted: number;
  duplicates: number;
  errors: RowError[];
}

/** FastAPI 오류(detail 문자열 또는 검증 오류 배열)를 사람이 읽을 문장으로 */
async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((d: { msg: string }) => d.msg.replace(/^Value error, /, ""))
        .join("\n");
    }
  } catch {
    /* JSON 아님 */
  }
  return `요청 실패 (${res.status})`;
}

export const AUTH_PAGES = ["/login", "/signup", "/terms", "/privacy"];

/** 로그인 쿠키를 함께 보내는 fetch. 401 이면 로그인 화면으로 보낸다 (가입·로그인 화면 제외). */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new Error(`서버(${API_BASE})에 연결할 수 없습니다. 백엔드가 켜져 있는지 확인하세요.`);
  }
  if (res.status === 401 && typeof window !== "undefined" && !AUTH_PAGES.includes(window.location.pathname)
      && !path.startsWith("/api/v1/auth/")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
    throw new Error("로그인이 필요합니다");
  }
  return res;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) throw new Error(await errorText(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const won = (n: number | null | undefined) =>
  n == null ? "—" : `${n.toLocaleString("ko-KR")}원`;

export interface Organization {
  id: string;
  name: string;
}

export interface LeaseOut {
  lease_id: string;
  unit_no: string;
  tenant_name: string;
  rent: number;
  due_day: number;
}

export interface TransactionOut {
  id: string;
  occurred_at: string;
  amount: number;
  direction: "in" | "out";
  counterparty: string | null;
  description: string | null;
}

export type Category = "rent" | "deposit_in" | "personal" | "owner_household" | "other";

export const CATEGORY_LABEL: Record<string, string> = {
  rent: "월세",
  deposit_in: "보증금 수령",
  personal: "개인 생활비",
  owner_household: "주인세대",
  other: "기타",
  unclassified: "미분류",
  common_electricity: "공용전기",
  water: "수도",
  cleaning: "청소",
  repair: "수리",
  other_operating: "공용 기타",
  deposit_out: "보증금 반환",
};

/** 운영비(임대 순운영수익에 반영) */
export const OPERATING = ["common_electricity", "water", "cleaning", "repair", "other_operating"] as const;
/** 운영비 아님 — NOI 에서 제외 */
export const NON_OPERATING = ["owner_household", "personal"] as const;
export type ExpenseCategory = (typeof OPERATING)[number] | (typeof NON_OPERATING)[number];
export type OutCategory = ExpenseCategory | "deposit_out";

export interface UnitOut {
  unit_id: string;
  unit_no: string;
}

export interface ConfirmedOut {
  transaction: TransactionOut;
  splits: { category: string; amount: number; unit_no: string | null }[];
  reason: string | null;
}

export interface ExpenseOut {
  id: string;
  category: string;
  amount: number;
  spent_on: string;
  memo: string | null;
  unit_no: string | null;
  from_bank: boolean;
}

export interface ExpenseRuleOut {
  id: string;
  label: string;
  splits: { category: string; bp: number }[];
}

export interface MonthlyReport {
  period: string;
  rent_charged: number;
  rent_received: number;
  operating: Record<string, number>;
  operating_total: number;
  noi: number;
  excluded: Record<string, number>;
  unconfirmed_in: number;
  unconfirmed_out: number;
  complete: boolean;
  bank_data_as_of: string | null;
}

export const thisMonthKst = () =>
  new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 7);
export const todayKst = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });

export interface QueueItem {
  transaction: TransactionOut;
  suggestion: {
    allocation_id: string;
    lease_id: string | null;
    unit_no: string | null;
    category: string;
    confidence: number | null;
    reason: string | null;
  } | null;
}

export interface AllocationOut {
  id: string;
  transaction: TransactionOut;
  lease_id: string | null;
  unit_no: string | null;
  category: string;
  amount: number;
  confidence: number | null;
  reason: string | null;
}

export interface Receivables {
  as_of: string;
  bank_data_as_of: string | null;
  pending_review: number;
  items: {
    unit_no: string;
    tenant_name: string;
    period: string;
    due_date: string;
    amount: number;
    paid: number;
    outstanding: number;
    days_past_due: number;
  }[];
  credits: { unit_no: string; credit: number }[];
}

/** 저장은 UTC, 표시는 KST */
export const kst = (iso: string | null) =>
  iso == null
    ? "—"
    : new Date(iso).toLocaleString("ko-KR", {
        timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false,
      });

export interface BankAccount {
  id: string;
  alias: string;
}

export interface Dashboard {
  as_of: string;
  period: string;
  bank_data_as_of: string | null;
  counts: { total: number; rental: number; occupied: number; vacant: number; owner: number };
  units: {
    unit_no: string;
    floor: number | null;
    use_type: "rental" | "owner";
    status: "occupied" | "vacant" | "owner";
    tenant_name: string | null;
    rent: number | null;
    due_day: number | null;
    due_date: string | null;
    charge_status: "paid" | "partial" | "open" | "waived" | "none" | null;
    outstanding: number | null;
    paid_on: string | null;
    lease_end: string | null;
  }[];
  money: {
    rent_charged: number;
    rent_received: number;
    overdue_total: number;
    overdue_count: number;
    operating_total: number;
    noi: number;
    non_operating_total: number;
    complete: boolean;
  };
  recent_transactions: { occurred_at: string; direction: "in" | "out"; amount: number; label: string; confirmed: boolean }[];
  due_soon: { unit_no: string; due_date: string; outstanding: number }[];
  lease_endings: {
    unit_no: string; tenant_name: string; end_date: string; days_left: number; deposit_to_return: number | null;
  }[];
  tax_events: {
    name: string; start: string; end: string; note: string; url: string; in_progress: boolean; days_until_end: number;
  }[];
  attention: { level: "warn" | "info"; kind: string; message: string; href: string }[];
}

/** 450000 → "45만원", 425000 → "42.5만원" */
export const manwon = (n: number | null | undefined) => {
  if (n == null) return "—";
  const v = n / 10000;
  return `${Number.isInteger(v) ? v.toLocaleString("ko-KR") : v.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만원`;
};

/** "2026-11-05" → "11.05" */
export const mmdd = (iso: string | null | undefined) => (iso ? iso.slice(5, 10).replace("-", ".") : "—");

export interface DocumentSummary {
  id: string;
  original_name: string | null;
  created_at: string;
  ocr_status: "not_configured" | "done" | "failed";
  verified_at: string | null;
}

export interface Contract {
  lease_id: string;
  unit_no: string;
  tenant_name: string;
  deposit: number;
  rent: number;
  due_day: number;
  start_date: string;
  end_date: string | null;
  documents: DocumentSummary[];
}

export type ContractField = "deposit" | "rent" | "due_day" | "start_date" | "end_date";

export interface DocumentDetail {
  id: string;
  lease_id: string;
  unit_no: string;
  original_name: string | null;
  content_type: string | null;
  created_at: string;
  ocr_status: "not_configured" | "done" | "failed";
  ocr_provider: string | null;
  ocr_error: string | null;
  ocr_text: string | null;
  fields: Record<ContractField, { value: number | string | null; evidence: string | null }> | null;
  current: Record<ContractField, number | string | null>;
  verified_at: string | null;
  verified_fields: (Record<ContractField, number | string | null> & { changed: ContractField[] }) | null;
}

export interface Me {
  user: { id: string; email: string; name: string | null; role: "owner" | "manager" | "viewer"; mfa_enabled: boolean;
    marketing_agreed: boolean };
  organization: { id: string; name: string };
}

export const ROLE_LABEL: Record<Me["user"]["role"], string> = { owner: "대표", manager: "관리자", viewer: "조회" };
