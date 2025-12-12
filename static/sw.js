self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// まずは「オフライン対応なし」でOK（安全運用）
// ※あとでキャッシュ機能を追加できます
