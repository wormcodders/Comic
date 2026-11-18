/** Add CSRF protection only to requests to this application. */
(function () {
    const originalFetch = window.fetch;
    window.fetch = function (resource, options) {
        const config = { ...(options || {}) };
        const isRequest = typeof Request !== 'undefined' && resource instanceof Request;
        const method = (config.method || (isRequest ? resource.method : 'GET')).toUpperCase();
        const destination = new URL(isRequest ? resource.url : String(resource), window.location.href);
        if (destination.origin === window.location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
            const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            if (token) {
                const headers = new Headers(config.headers || (isRequest ? resource.headers : undefined));
                headers.set('X-CSRFToken', token);
                config.headers = headers;
            }
        }
        return originalFetch.call(this, resource, config);
    };
})();
