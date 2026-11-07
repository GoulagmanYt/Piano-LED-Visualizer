const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const ui = fs.readFileSync(path.join(root, 'webinterface/static/js/ui.js'), 'utf8');
const translations = fs.readFileSync(path.join(root, 'webinterface/static/translations.js'), 'utf8');
const data = { available: true, led_current_a: 10.74, led_power_w: 53.7, led_current_max_a: 10.74,
    led_ma_per_channel: 20, led_idle_ma: 1, led_supply_voltage: 5 };

function fixture() {
    const dom = new JSDOM('<details id="led_power_card"><summary>Power</summary>' +
        '<span id="led_power_current"></span><span id="led_power_watts"></span>' +
        '<span id="led_power_max"></span><span id="led_power_status"></span>' +
        '<input name="led_idle_ma" id="led_idle_ma" type="number">' +
        '<input name="led_ma_per_channel" id="led_ma_per_channel" type="number">' +
        '<input name="led_supply_voltage" id="led_supply_voltage" type="number"></details>',
        { runScripts: 'outside-only', url: 'http://localhost/' });
    const w = dom.window, requests = [], timers = new Map();
    let timerId = 0;
    w.getCookie = () => 'en';
    w.setInterval = callback => { timers.set(++timerId, callback); return timerId; };
    w.clearInterval = id => timers.delete(id);
    w.XMLHttpRequest = class {
        open(method, url) { this.url = url; }
        send() { if (this.url === '/api/get_led_power') requests.push(this); }
        abort() { this.aborted = true; }
        respond(payload) {
            this.readyState = 4; this.status = 200; this.responseText = JSON.stringify(payload);
            this.onreadystatechange();
        }
    };
    w.eval(translations);
    w.eval(ui);
    const card = w.document.getElementById('led_power_card');
    return { dom, w, card, requests, timers, close: () => { w.stop_led_power_loop?.(); w.close(); } };
}

test('power polling starts only on expansion and never overlaps requests', () => {
    const f = fixture();
    try {
        f.w.toggle_led_power();
        assert.equal(f.requests.length, 0);
        f.card.open = true;
        f.w.toggle_led_power();
        f.w.toggle_led_power();
        assert.equal(f.requests.length, 1);
        assert.equal(f.timers.size, 1);
        [...f.timers.values()][0]();
        assert.equal(f.requests.length, 1);
        f.requests[0].respond(data);
        assert.equal(f.w.document.getElementById('led_power_current').textContent, '10.74 A');
        assert.equal(f.w.document.getElementById('led_power_watts').textContent, '53.7 W');
        [...f.timers.values()][0]();
        assert.equal(f.requests.length, 2);
        f.card.open = false;
        f.w.toggle_led_power();
        assert.equal(f.timers.size, 0);
        assert.equal(f.requests[1].aborted, true);
    } finally { f.close(); }
});

test('leaving the page stops polling and a late response cannot update a new card', () => {
    const f = fixture();
    try {
        f.card.open = true;
        f.w.toggle_led_power();
        f.card.remove();
        [...f.timers.values()][0]();
        assert.equal(f.timers.size, 0);
        assert.equal(f.requests[0].aborted, true);
        f.w.document.body.innerHTML = '<details id="led_power_card" open><span id="led_power_current">new page</span></details>';
        f.requests[0].respond(data);
        assert.equal(f.w.document.getElementById('led_power_current').textContent, 'new page');
    } finally { f.close(); }
});

test('unavailable samples clear stale numbers and polling can recover', () => {
    const f = fixture();
    try {
        f.card.open = true; f.w.toggle_led_power();
        f.requests[0].respond(data);
        [...f.timers.values()][0]();
        f.requests[1].respond({ available: false });
        assert.ok(!f.w.document.getElementById('led_power_current').textContent.includes('10.74'));
        assert.match(f.w.document.getElementById('led_power_status').textContent, /unavailable/i);
        [...f.timers.values()][0]();
        f.requests[2].respond(data);
        assert.equal(f.w.document.getElementById('led_power_current').textContent, '10.74 A');
    } finally { f.close(); }
});

test('all twelve languages include power labels and status text', () => {
    const dom = new JSDOM('', { runScripts: 'outside-only' });
    try {
        const labels = dom.window.eval(translations + '\nObject.values(translations);');
        assert.equal(labels.length, 12);
        for (const language of labels) {
            for (const key of ['led_power_title','led_power_note','led_power_current','led_power_max',
                'led_ma_per_channel','led_idle_ma','led_supply_voltage','led_power_unavailable','led_power_invalid']) {
                assert.ok(typeof language[key] === 'string' && language[key].length > 0, key);
            }
        }
    } finally { dom.window.close(); }
});

test('malformed JSON values show unavailable and release the pending request', () => {
    const f = fixture();
    try {
        f.card.open = true; f.w.toggle_led_power();
        f.requests[0].respond(null);
        assert.match(f.w.document.getElementById('led_power_status').textContent, /unavailable/i);
        [...f.timers.values()][0]();
        assert.equal(f.requests.length, 2);
        f.requests[1].ontimeout();
        [...f.timers.values()][0]();
        assert.equal(f.requests.length, 3);
    } finally { f.close(); }
});

test('calibration saves zero current but rejects zero voltage before making a request', async () => {
    const f = fixture();
    try {
        const calls = [];
        f.w.fetch = async url => {
            calls.push(new URL(url, 'http://localhost'));
            return { ok: true, json: async () => ({ success: true }) };
        };
        const idle = f.w.document.getElementById('led_idle_ma');
        idle.value = '0';
        await f.w.save_led_power_setting(idle);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].searchParams.get('setting_name'), 'led_idle_ma');
        assert.equal(calls[0].searchParams.get('value'), '0');
        assert.equal(idle.disabled, false);
        const voltage = f.w.document.getElementById('led_supply_voltage');
        voltage.value = '0';
        await f.w.save_led_power_setting(voltage);
        assert.equal(calls.length, 1);
        assert.equal(voltage.checkValidity(), false);
    } finally { f.close(); }
});

test('rejected calibration is visible and the input remains usable', async () => {
    const f = fixture();
    try {
        f.w.fetch = async () => ({ ok: false, json: async () => ({ success: false }) });
        const idle = f.w.document.getElementById('led_idle_ma');
        idle.value = '1';
        await f.w.save_led_power_setting(idle);
        assert.match(f.w.document.getElementById('led_power_status').textContent, /finite nonnegative/);
        assert.equal(idle.disabled, false);
    } finally { f.close(); }
});
