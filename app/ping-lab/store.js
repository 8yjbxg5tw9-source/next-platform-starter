/** localStorage kalıcılığı — sunucu yok, VDS yok, her şey cihazında kalır. */

const KEYS = {
  profiles: 'pinglab.profiles.v1',
  watch: 'pinglab.watch.v1',
  settings: 'pinglab.settings.v1',
};

const MAX_WATCH = 30000;

function read(key, fallback) {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* kota doldu — sessizce yut */
  }
}

export function loadProfiles() {
  return read(KEYS.profiles, {});
}

export function saveProfile(name, payload) {
  const all = loadProfiles();
  all[name] = { ...payload, savedAt: Date.now() };
  write(KEYS.profiles, all);
  return all;
}

export function deleteProfile(name) {
  const all = loadProfiles();
  delete all[name];
  write(KEYS.profiles, all);
  return all;
}

/**
 * Nöbet verisi için harici mağaza. useSyncExternalStore ile kullanılıyor;
 * böylece localStorage'a abonelik React'in önerdiği yoldan yapılıyor ve
 * sunucu/istemci anlık görüntüleri ayrı tutulabiliyor (hydration uyumu).
 */
const EMPTY_WATCH = [];
let watchCache = null;
const watchListeners = new Set();

function emitWatch() {
  watchListeners.forEach((fn) => fn());
}

export function subscribeWatch(fn) {
  watchListeners.add(fn);
  return () => watchListeners.delete(fn);
}

export function getWatchSnapshot() {
  if (watchCache === null) watchCache = read(KEYS.watch, []);
  return watchCache;
}

/** Sunucuda localStorage yok — sabit boş dizi döndürür (referans kararlılığı şart). */
export function getWatchServerSnapshot() {
  return EMPTY_WATCH;
}

export function loadWatch() {
  return getWatchSnapshot();
}

export function appendWatch(entries) {
  const all = getWatchSnapshot().concat(entries);
  watchCache = all.length > MAX_WATCH ? all.slice(all.length - MAX_WATCH) : all;
  write(KEYS.watch, watchCache);
  emitWatch();
  return watchCache;
}

export function clearWatch() {
  watchCache = [];
  write(KEYS.watch, []);
  emitWatch();
  return watchCache;
}

export function loadSettings() {
  return read(KEYS.settings, { profile: 'Ev Wi-Fi', rounds: 15 });
}

export function saveSettings(s) {
  write(KEYS.settings, s);
}
