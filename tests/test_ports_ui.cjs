// Run with jsdom available in NODE_PATH (see README.md#development).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const ui = fs.readFileSync(path.join(root, 'webinterface/static/js/ui.js'), 'utf8');
const translations = fs.readFileSync(path.join(root, 'webinterface/static/translations.js'), 'utf8');
const piano = 'USB Piano:USB Piano MIDI 1 24:0';

function renderPorts(configured, actual, available, language = 'en') {
    const dom = new JSDOM(
        '<select id="active_input"></select><select id="secondary_input"></select>' +
        '<select id="playback_input"></select>',
        { runScripts: 'outside-only', url: 'http://localhost/' },
    );
    const { window } = dom;
    window.getCookie = () => language;
    window.XMLHttpRequest = class {
        open(method, url) { this.url = url; }
        send() {
            if (this.url !== '/api/get_ports') return;
            this.readyState = 4;
            this.status = 200;
            this.responseText = JSON.stringify({
                input_ports: available,
                output_ports: [],
                input_port: configured,
                actual_input_port: actual,
                secondary_input_port: 'default',
                play_port: 'None',
            });
            this.onreadystatechange();
        }
    };
    window.eval(translations);
    window.eval(ui);
    window.get_ports();
    return dom;
}

test('Auto is first and stays selected while showing the connected device', () => {
    const dom = renderPorts('default', piano, [piano, piano]);
    try {
        const select = dom.window.document.getElementById('active_input');
        assert.equal(select.value, 'default');
        assert.equal(select.options[0].value, 'default');
        assert.match(select.options[0].textContent, /Auto/);
        assert.ok(select.options[0].textContent.includes(piano));
        assert.equal(select.options.length, 2);
        dom.window.get_ports();
        assert.equal(select.options.length, 2);
        const secondary = dom.window.document.getElementById('secondary_input');
        assert.ok(!Array.from(secondary.options).some(option => option.value === 'default'));
    } finally { dom.window.close(); }
});

test('Auto without a device displays a translated waiting state', () => {
    const dom = renderPorts('default', null, [], 'fr');
    try {
        const select = dom.window.document.getElementById('active_input');
        assert.equal(select.value, 'default');
        assert.equal(select.options.length, 1);
        assert.match(select.options[0].textContent, /en attente d'un appareil/);
        assert.doesNotMatch(select.options[0].textContent, /Disconnected/);
    } finally { dom.window.close(); }
});

test('an explicit input stays selected alongside the Auto option', () => {
    const dom = renderPorts(piano, piano, [piano]);
    try {
        const select = dom.window.document.getElementById('active_input');
        assert.equal(select.value, piano);
        assert.equal(select.options[0].value, 'default');
        assert.equal(select.selectedOptions[0].textContent, piano);
    } finally { dom.window.close(); }
});

test('an unavailable explicit input stays visible and selected', () => {
    const dom = renderPorts(piano, null, []);
    try {
        const select = dom.window.document.getElementById('active_input');
        assert.equal(select.value, piano);
        assert.equal(select.options[0].value, 'default');
        assert.equal(select.selectedOptions[0].textContent, piano + ' (Disconnected)');
    } finally { dom.window.close(); }
});

test('Auto and waiting labels are translated in all twelve languages', () => {
    const dom = new JSDOM('', { runScripts: 'outside-only' });
    try {
        const labels = dom.window.eval(translations + '\nObject.entries(translations).map(([lang, text]) => [lang, text.input_auto, text.input_auto_waiting]);');
        assert.equal(labels.length, 12);
        for (const [lang, auto, waiting] of labels) {
            assert.ok(typeof auto === 'string' && auto.length > 0, lang + ': Auto');
            assert.ok(typeof waiting === 'string' && waiting.length > 0, lang + ': waiting');
        }
    } finally { dom.window.close(); }
});
