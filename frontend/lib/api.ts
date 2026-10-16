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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new Error(`서버(${API_BASE})에 연결할 수 없습니다. 백엔드가 켜져 있는지 확인하세요.`);
  }
  if (!res.ok) throw new Error(await errorText(res));
  return res.json() as Promise<T>;
}

export const won = (n: number | null | undefined) =>
  n == null ? "—" : `${n.toLocaleString("ko-KR")}원`;
