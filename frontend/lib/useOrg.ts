"use client";

import { useEffect, useState } from "react";
import { api, type Organization } from "@/lib/api";

/** 등록된 조직 목록과 선택값. 개인용이라 보통 하나, 여러 개면 가장 최근 것을 기본으로. */
export function useOrg() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [orgId, setOrgId] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Organization[]>("/api/v1/organizations")
      .then((os) => {
        setOrgs(os);
        if (os.length) setOrgId(os[os.length - 1].id);
      })
      .catch((e) => setError(e.message));
  }, []);
  return { orgs, orgId, setOrgId, error };
}
