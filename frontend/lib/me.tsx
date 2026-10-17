"use client";

import { createContext, useContext } from "react";
import type { Me } from "@/lib/api";

export const MeContext = createContext<{ me: Me | null; reload: () => Promise<void> }>({
  me: null,
  reload: async () => {},
});

/** 로그인한 사용자 · 사업장 (Shell 이 채움) */
export const useMe = () => useContext(MeContext);
