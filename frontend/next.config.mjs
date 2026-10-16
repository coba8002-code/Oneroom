/** @type {import('next').NextConfig} */
// standalone: 배포 이미지에 필요한 파일만 .next/standalone 에 모은다 (deploy/)
const nextConfig = { reactStrictMode: true, output: "standalone" };
export default nextConfig;
