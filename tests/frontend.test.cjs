const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = file => fs.readFileSync(path.join(root, file), 'utf8');

function csrfContext() {
    const calls = [];
    const window = {
        location: { href: 'http://localhost:5000/', origin: 'http://localhost:5000' },
        fetch: async (resource, config) => { calls.push({ resource, config }); return { ok: true }; }
    };
    vm.runInNewContext(source('static/js/csrf.js'), {
        window, URL, Headers, Request,
        document: { querySelector: () => ({ getAttribute: () => 'csrf-value' }) }
    });
    return { window, calls };
}

test('CSRF headers are added to application mutations without changing reusable options', async () => {
    const { window, calls } = csrfContext();
    const headers = { 'Content-Type': 'application/json' };
    await window.fetch('/api/rate_comic', { method: 'POST', headers });
    assert.equal(calls[0].config.headers.get('X-CSRFToken'), 'csrf-value');
    assert.equal(headers['X-CSRFToken'], undefined);
});

test('CSRF tokens never go to another origin or a read-only request', async () => {
    const { window, calls } = csrfContext();
    await window.fetch('https://elsewhere.example/api', { method: 'POST' });
    await window.fetch('/api/comics/random');
    assert.equal(calls[0].config.headers, undefined);
    assert.equal(calls[1].config.headers, undefined);
});

test('Request objects retain their method and headers while receiving CSRF protection', async () => {
    const { window, calls } = csrfContext();
    const request = new Request('http://localhost:5000/api/comments/1', {
        method: 'DELETE', headers: { 'X-Example': 'value' }
    });
    await window.fetch(request);
    assert.equal(calls[0].config.headers.get('X-CSRFToken'), 'csrf-value');
    assert.equal(calls[0].config.headers.get('X-Example'), 'value');
    assert.equal(request.headers.get('X-CSRFToken'), null);
});

function workerContext() {
    const listeners = {};
    const deleted = [];
    let installed = [];
    const cache = { addAll: async assets => { installed = assets; }, match: async () => undefined, put: async () => {} };
    vm.runInNewContext(source('static/js/sw.js'), {
        URL,
        self: {
            location: { origin: 'http://localhost:5000' },
            addEventListener: (name, listener) => { listeners[name] = listener; },
            skipWaiting: async () => {},
            clients: { claim: async () => {} }
        },
        caches: {
            open: async () => cache,
            keys: async () => ['comicvault-v1', 'comicvault-static-v1', 'another-application'],
            delete: async name => { deleted.push(name); }
        },
        fetch: async () => ({ ok: true, type: 'basic', clone() { return this; } })
    });
    return { listeners, deleted, installed: () => installed };
}

test('The service worker never intercepts API, private media, or page navigation', () => {
    const { listeners } = workerContext();
    for (const pathname of ['/api/reading-lists', '/api/activity/user', '/profile', '/', '/static/uploads/pages/1/page_001.jpg']) {
        let intercepted = false;
        listeners.fetch({ request: { url: 'http://localhost:5000' + pathname, method: 'GET' }, respondWith() { intercepted = true; } });
        assert.equal(intercepted, false, pathname);
    }
});

test('Service worker installation uses only existing public assets', async () => {
    const context = workerContext();
    let promise;
    context.listeners.install({ waitUntil(value) { promise = value; } });
    await promise;
    assert.ok(context.installed().length > 0);
    for (const asset of context.installed()) {
        assert.ok(asset.startsWith('/static/'));
        assert.ok(!asset.includes('/uploads/'));
        assert.ok(fs.existsSync(path.join(root, asset.slice(1))), asset);
    }
});

test('Activation removes old private-data caches while preserving unrelated caches', async () => {
    const context = workerContext();
    let promise;
    context.listeners.activate({ waitUntil(value) { promise = value; } });
    await promise;
    assert.deepEqual(context.deleted, ['comicvault-v1', 'comicvault-static-v1']);
});

test('Notifications render untrusted messages as text and constrain notification styles', () => {
    class Element {
        constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; this.classList = { add() {}, remove() {} }; }
        append(...children) { this.children.push(...children); }
        addEventListener() {}
    }
    const body = { children: [], appendChild(node) { this.children.push(node); } };
    const context = {
        window: {}, setTimeout() {},
        document: { body, querySelectorAll: () => [], createElement: tag => new Element(tag) }
    };
    const code = source('static/js/main.js');
    vm.runInNewContext(code.slice(0, code.indexOf('window.showToast')), context);
    const attack = '<img src=x onerror=alert(1)>';
    context.showNotification(attack, '" onclick="alert(1)');
    const notification = body.children[0];
    assert.equal(notification.className, 'notification notification-info');
    assert.equal(notification.children[0].textContent, attack);
    assert.equal(notification.children[0].children.length, 0);
});

test('HTML escaping also protects quoted attribute values', () => {
    const code = source('static/js/main.js');
    const match = code.match(/function escapeHtml\(text\) \{[\s\S]*?\n\}/);
    const context = {};
    vm.runInNewContext(match[0], context);
    assert.equal(context.escapeHtml('<a title="x">\'&'), '&lt;a title=&quot;x&quot;&gt;&#39;&amp;');
});

function appContext(buttons = []) {
    const calls = [];
    class Element {
        constructor() { this.classList = { add() {}, remove() {} }; }
        append() {}
        addEventListener() {}
        setAttribute() {}
    }
    const context = {
        navigator: {},
        window: { location: {}, addEventListener() {} },
        document: {
            addEventListener() {},
            body: { appendChild() {} },
            createElement: () => new Element(),
            querySelector: () => null,
            querySelectorAll: selector => selector.includes('[data-comic-id=') ? buttons : []
        },
        MutationObserver: class { observe() {} },
        fetch: async (url, options) => {
            calls.push({ url, options });
            return { status: 200, json: async () => ({ success: true, in_library: true, message: 'Added to library' }) };
        },
        setTimeout() {},
        console
    };
    vm.runInNewContext(source('static/js/main.js'), context);
    return { context, calls };
}

test('Page wrappers call the exported library implementation without recursion', async () => {
    const { context, calls } = appContext();
    assert.equal(typeof context.window.ComicVault.showToast, 'function');
    assert.equal(typeof context.window.ComicVault.clearSearchHistory, 'function');
    vm.runInNewContext('async function toggleLibrary(id) { return window.ComicVault.toggleLibrary(id); }', context);
    await context.toggleLibrary(1);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/toggle_library');
    assert.equal(JSON.parse(calls[0].options.body).comic_id, 1);
});

test('Library controls update visible state and accessible labels after an API success', async () => {
    const attributes = {};
    const button = {
        disabled: false, innerHTML: '', dataset: { comicTitle: 'A comic' },
        classList: { toggle() {} },
        querySelector: () => null,
        hasAttribute: name => name === 'data-library-btn',
        setAttribute: (name, value) => { attributes[name] = value; }
    };
    const { context } = appContext([button]);
    await context.window.ComicVault.toggleLibrary(1);
    assert.equal(button.disabled, false);
    assert.equal(attributes['aria-pressed'], 'true');
    assert.equal(attributes['aria-label'], 'Remove A comic from library');
    assert.ok(button.innerHTML.includes('In Library'));
});

test('Rating buttons expose the selected value to assistive technology', async () => {
    const template = source('templates/comic/detail.html');
    const start = template.indexOf('async function rateComic(');
    const end = template.indexOf('async function toggleLibrary(', start);
    const script = template.slice(start, end).replaceAll('{{ comic.id }}', '1');
    const buttons = Array.from({ length: 5 }, () => ({
        attributes: {}, classList: { add() {}, remove() {} },
        setAttribute(name, value) { this.attributes[name] = value; }
    }));
    const context = {
        window: { USER_ID: 1 }, ComicVault: { showToast() {} }, console,
        document: { querySelectorAll: () => buttons, getElementById: () => ({ textContent: '' }) },
        fetch: async () => ({ json: async () => ({ success: true, new_average: 5, total_ratings: 1 }) })
    };
    vm.runInNewContext(script, context);
    await context.rateComic(5);
    assert.ok(buttons.every(button => button.attributes['aria-pressed'] === 'true'));
});
