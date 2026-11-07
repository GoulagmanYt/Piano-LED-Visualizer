const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const ui = fs.readFileSync(path.join(root, 'webinterface/static/js/ui.js'), 'utf8');
const template = fs.readFileSync(path.join(root, 'webinterface/templates/ports.html'), 'utf8');
const translations = fs.readFileSync(path.join(root, 'webinterface/static/translations.js'), 'utf8');

test('Learning bridge settings show selected ports and save all fields', async () => {
    const dom = new JSDOM(template, {runScripts: 'outside-only', url: 'http://localhost/'});
    try {
        const {window} = dom;
        window.getCookie = () => 'fr';
        const ports = {learning_piano_input: 'Piano 20:0', learning_piano_output: 'Piano 20:0',
            learning_computer_input: 'PC 30:0', learning_computer_output: 'PC 30:0'};
        let sent = null;
        window.fetch = async (url, options = {}) => {
            if (options.method === 'POST') {
                sent = JSON.parse(options.body);
                return {ok: true, json: async () => ({success: true, restart_required: true})};
            }
            return {ok: true, json: async () => ({mode: 'off', ports, block_control: true,
                inputs: ['Piano 20:0', 'PC 30:0'], outputs: ['Piano 20:0', 'PC 30:0'], active: false})};
        };
        window.eval(translations);
        window.eval(ui);
        await window.initialize_learning_bridge();
        assert.equal(window.document.getElementById('learning_piano_input').value, 'Piano 20:0');
        window.document.getElementById('learning_bridge_mode').value = 'learning';
        await window.document.getElementById('learning_bridge_save').onclick();
        assert.equal(sent.mode, 'learning');
        assert.deepEqual(sent.ports, ports);
        assert.equal(sent.block_control, true);
        assert.match(window.document.getElementById('learning_bridge_status').textContent, /Redémarrez/);
    } finally { dom.window.close(); }
});
