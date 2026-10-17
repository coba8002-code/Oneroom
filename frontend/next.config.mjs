/** @type {import('next').NextConfig} */
// standalone: 배포 이미지에 필요한 파일만 .next/standalone 에 모은다 (deploy/ docker)
// ROOMAX_API_ORIGIN 이 있으면(Vercel): 브라우저는 같은 주소의 /api/* 로 부르고, 그 요청을 백엔드로 넘긴다
//   → 화면과 API 가 같은 도메인이라 로그인 쿠키(HttpOnly·SameSite=Lax)가 그대로 동작
const apiOrigin = process.env.ROOMAX_API_ORIGIN?.replace(/\/$/, "");

const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
];

const nextConfig = {
  reactStrictMode: true,
  output: apiOrigin ? undefined : "standalone",
  poweredByHeader: false,
  ...(apiOrigin && {
    env: { NEXT_PUBLIC_API_BASE: "" },
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
    },
    async headers() {
      return [
        { source: "/:path*", headers: securityHeaders },
        // 임차인 화면 주소에는 비밀 토큰이 들어 있다 — 검색 제외, 다른 사이트에 주소를 넘기지 않음
        { source: "/t/:path*", headers: [{ key: "Referrer-Policy", value: "no-referrer" }, { key: "X-Robots-Tag", value: "noindex" }] },
      ];
    },
  }),
};
export default nextConfig;
