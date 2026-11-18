const CACHE = "stride-v2";
const SHELL = [
  "/",
  "/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

// ─── Install: cache app shell ───────────────────────────────────────────────
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

// ─── Activate: remove old caches ────────────────────────────────────────────
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ─── Fetch: network-first, fallback to cache ────────────────────────────────
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Let API calls and non-GET pass through
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// ─── Background Sync: retry failed toggle actions when back online ───────────
self.addEventListener("sync", e => {
  if (e.tag === "sync-toggles") {
    e.waitUntil(syncPendingToggles());
  }
});

async function syncPendingToggles() {
  const db = await openDB();
  const pending = await getAllPending(db);
  for (const item of pending) {
    try {
      const res = await fetch(`/api/habits/${item.habitId}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: item.date })
      });
      if (res.ok) await deletePending(db, item.id);
    } catch {
      // Network still down — will retry on next sync event
    }
  }
}

// ─── Periodic Sync: daily habit reminder ────────────────────────────────────
self.addEventListener("periodicsync", e => {
  if (e.tag === "daily-reminder") {
    e.waitUntil(showDailyReminder());
  }
});

async function showDailyReminder() {
  // Only remind between 8 AM and 10 PM
  const hour = new Date().getHours();
  if (hour < 8 || hour > 22) return;

  // Don't notify if the app is already open
  const clients = await self.clients.matchAll({ type: "window" });
  if (clients.some(c => c.visibilityState === "visible")) return;

  return self.registration.showNotification("Stride – Daily Check-in 🏃", {
    body: "Don't forget to log your habits for today!",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    tag: "daily-reminder",
    renotify: false,
    vibrate: [200, 100, 200],
    actions: [
      { action: "open", title: "Log Now" },
      { action: "dismiss", title: "Later" }
    ],
    data: { url: "/?view=today" }
  });
}

// ─── Push Notifications: server-sent push messages ──────────────────────────
self.addEventListener("push", e => {
  let payload = { title: "Stride", body: "Time to log your habits!", url: "/" };
  if (e.data) {
    try { Object.assign(payload, e.data.json()); } catch { /* use defaults */ }
  }
  e.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      tag: "stride-push",
      vibrate: [200, 100, 200],
      data: { url: payload.url }
    })
  );
});

// ─── Notification click: open/focus app ─────────────────────────────────────
self.addEventListener("notificationclick", e => {
  e.notification.close();
  if (e.action === "dismiss") return;

  const target = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(clients => {
      const existing = clients.find(c => c.url.includes(self.location.origin));
      if (existing) return existing.focus();
      return self.clients.openWindow(target);
    })
  );
});

// ─── IndexedDB helpers for offline sync queue ───────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("stride-sync", 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore("pending", { keyPath: "id", autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function getAllPending(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("pending", "readonly");
    const req = tx.objectStore("pending").getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function deletePending(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("pending", "readwrite");
    const req = tx.objectStore("pending").delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

// Export for use from the app page
function addPendingToggle(db, habitId, date) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("pending", "readwrite");
    const req = tx.objectStore("pending").add({ habitId, date, timestamp: Date.now() });
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}
