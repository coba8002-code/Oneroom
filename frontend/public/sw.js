/* ROOMAX 서비스 워커 — 홈 화면 앱 설치와 '연결 끊김' 안내만.
 * - API(/api/*) 응답과 화면 HTML 은 저장하지 않는다: 장부·연락처가 휴대폰에 남지 않고, 지난 숫자를 사실처럼 보여 주지 않음
 * - 저장하는 것: 연결 끊김 안내 화면과 아이콘(개인 정보 없음)
 * - 화면 이동이 네트워크 오류로 실패하면 안내 화면을 보여 준다
 */
const CACHE = "roomax-shell-v1";
const SHELL = ["/offline.html", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || req.mode !== "navigate") return;  // API·정적 파일은 브라우저 기본 동작 그대로
  event.respondWith(fetch(req).catch(() => caches.match("/offline.html")));
});
