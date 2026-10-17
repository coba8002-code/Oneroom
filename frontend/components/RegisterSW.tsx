"use client";

import { useEffect } from "react";

/** 운영 빌드에서만 서비스 워커 등록 (개발 중 새로고침이 꼬이지 않게) */
export default function RegisterSW() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => { /* 지원하지 않거나 막힌 브라우저 — 앱은 그대로 동작 */ });
  }, []);
  return null;
}
