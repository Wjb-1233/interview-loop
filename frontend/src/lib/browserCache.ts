/** Retire this application's former browser cache without touching other apps. */
export async function clearRetiredBrowserCache(): Promise<void> {
  const base = new URL(import.meta.env.BASE_URL, window.location.origin)
  const retiredScript = new URL('sw.js', base).href
  await Promise.allSettled([
    (async () => {
      if (!('serviceWorker' in navigator)) return
      const registrations = await navigator.serviceWorker.getRegistrations()
      await Promise.all(registrations
        .filter((registration) => registration.scope === base.href && [registration.active, registration.waiting, registration.installing].some((worker) => worker?.scriptURL === retiredScript))
        .map((registration) => registration.unregister()))
    })(),
    (async () => {
      if (!('caches' in window)) return
      const names = await caches.keys()
      await Promise.all(names.filter((name) => name.startsWith('yanjie-pwa-')).map((name) => caches.delete(name)))
    })(),
  ])
}
