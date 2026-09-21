/* 香港巴士到站地圖 — Service Worker
 * 策略:
 *  - 靜態資源(首頁、icons、manifest): install 時預快取
 *  - 數據檔 (kmb/mtr/gmb_data.json): 首次成功抓取後快取 → 之後離線可用 (cache-first, 網絡成功時更新)
 *  - Leaflet CDN: 快取成功回應做離線 fallback
 *  - etabus 即時 ETA API: 永不快取(即時數據)
 */
const CACHE = 'bus-eta-map-v1';
const PRECACHE = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-512-maskable.png'
];
// 數據檔 — 離線使用關鍵
const DATA_URLS = [
  './kmb_data.json',
  './mtr_data.json',
  './gmb_data.json'
];
// 即時 API — 永不快取
const LIVE_URLS = [
  'data.etabus.gov.hk/',
  'data.etagmb.gov.hk/'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = req.url;
  if (req.method !== 'GET') return;

  // 即時 API 永不快取
  if (LIVE_URLS.some((u) => url.includes(u))) return;

  // 數據檔: cache-first, 網絡成功時背景更新
  if (DATA_URLS.some((u) => url.includes(u.split('/').pop()))) {
    e.respondWith(
      caches.match(req).then((cached) => {
        const network = fetch(req).then((res) => {
          if (res && res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(req, clone));
          }
          return res;
        }).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // 外部資源 (Leaflet CDN, OSM/CARTO tiles) — 快取成功回應做離線 fallback
  if (url.startsWith('http') && !url.includes(location.origin)) {
    e.respondWith(
      caches.match(req).then((cached) => {
        const network = fetch(req).then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(req, clone));
          }
          return res;
        }).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // 本地資源 — stale-while-revalidate
  e.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req).then((res) => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then((c) => c.put(req, clone));
        }
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
