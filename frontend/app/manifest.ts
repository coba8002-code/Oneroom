import type { MetadataRoute } from "next";

// 휴대폰 '홈 화면에 추가' 때 앱처럼 열리게 (PWA)
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ROOMAX — 임대 관리",
    short_name: "ROOMAX",
    description: "내 건물의 든든한 파트너 — 다가구주택 임대 관리",
    lang: "ko",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#172d4f",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
