// Mes Comptes : service minimal pour pouvoir installer l'appli sur l'écran d'accueil.
// Rien n'est mis en cache : tout vient toujours d'Internet (données à jour).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="font-family:sans-serif;text-align:center;padding:60px 20px;color:#333">' +
    '<div style="font-size:48px">🐞</div><h2>Pas de connexion Internet</h2>' +
    '<p>Mes Comptes a besoin d\'Internet. Réessaie dès que tu es connecté.</p>' +
    '<button onclick="location.reload()" style="padding:10px 18px;font-size:16px">Réessayer</button></body>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
