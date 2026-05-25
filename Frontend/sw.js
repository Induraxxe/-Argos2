/**
 * Service Worker - Argos2
 * Cache de assets estáticos para funcionamiento offline básico
 */

const CACHE_NAME = 'argos2-v1';

// Assets a cachear durante la instalación
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/dashboard.html',
    '/admin.html',
    '/registro.html',
    '/verificacion.html',
    '/recuperar.html',
    '/reset-password.html',
    '/css/styles.css',
    '/js/toast.js',
    '/js/auth2.js',
    '/js/auth.js',
    '/js/admin.js',
    '/js/vision.js',
    '/js/recuperar.js',
    '/js/reset-password.js',
    '/js/verificacion.js',
    '/assets/img/Logo.png',
    '/assets/img/fondo.jfif',
    '/assets/icons/calendario.svg',
    '/assets/icons/candado.svg',
    '/assets/icons/check.svg',
    '/assets/icons/documento.svg',
    '/assets/icons/escudo.svg',
    '/assets/icons/llave.svg',
    '/assets/icons/monitor.svg',
    '/assets/icons/sobre.svg',
    '/assets/icons/telefono.svg',
    '/assets/icons/usuario.svg'
];

// Instalación: cachear assets estáticos
self.addEventListener('install', (event) => {
    console.log('[SW] Instalando Service Worker...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Cacheando assets estáticos');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
            .catch((error) => {
                console.warn('[SW] Error al cachear algunos assets:', error);
                // No fallar la instalación si algunos assets no se pueden cachear
                return self.skipWaiting();
            })
    );
});

// Activación: limpiar caches antiguas
self.addEventListener('activate', (event) => {
    console.log('[SW] Service Worker activado');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => {
                        console.log('[SW] Eliminando cache antigua:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch: estrategia Network First con fallback a cache
self.addEventListener('fetch', (event) => {
    // Solo interceptar peticiones GET
    if (event.request.method !== 'GET') return;

    // No interceptar peticiones a la API
    if (event.request.url.includes('/api/')) return;

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Si la respuesta es válida, clonar y guardar en cache
                if (response && response.status === 200) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Si falla la red, servir desde cache
                return caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // Si no está en cache y es una navegación, servir index.html
                    if (event.request.mode === 'navigate') {
                        return caches.match('/index.html');
                    }
                    return new Response('Offline', { status: 503, statusText: 'Sin conexión' });
                });
            })
    );
});
