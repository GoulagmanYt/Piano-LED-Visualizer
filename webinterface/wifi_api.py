from webinterface import webinterface, app_state
from flask import request, jsonify
from lib.log_setup import logger

@webinterface.route('/api/get_saved_wifi_list', methods=['GET'])
def get_saved_wifi_list():
    try:
        nets = app_state.usersettings.get_saved_wifi_networks()
        return jsonify(success=True, networks=[{'ssid': n['ssid'], 'priority': n.get('priority', 0)} for n in nets])
    except Exception as e:
        logger.warning(f"get_saved_wifi_list error: {e}")
        return jsonify(success=False, error=str(e)), 500

@webinterface.route('/api/add_saved_wifi', methods=['POST'])
def add_saved_wifi():
    data = request.get_json(force=True, silent=True) or {}
    ssid = (data.get('ssid') or '').strip()
    password = (data.get('password') or '').strip()
    priority = data.get('priority')
    if not ssid or not password:
        return jsonify(success=False, error='ssid and password required'), 400
    try:
        app_state.usersettings.add_saved_wifi_network(ssid, password, priority=priority)
        nets = app_state.usersettings.get_saved_wifi_networks()
        return jsonify(success=True, networks=[{'ssid': n['ssid'], 'priority': n.get('priority', 0)} for n in nets])
    except Exception as e:
        logger.warning(f"add_saved_wifi error: {e}")
        return jsonify(success=False, error=str(e)), 500

@webinterface.route('/api/remove_saved_wifi', methods=['POST'])
def remove_saved_wifi():
    data = request.get_json(force=True, silent=True) or {}
    ssid = (data.get('ssid') or '').strip()
    if not ssid:
        return jsonify(success=False, error='ssid required'), 400
    try:
        app_state.usersettings.remove_saved_wifi_network(ssid)
        nets = app_state.usersettings.get_saved_wifi_networks()
        return jsonify(success=True, networks=[{'ssid': n['ssid'], 'priority': n.get('priority', 0)} for n in nets])
    except Exception as e:
        logger.warning(f"remove_saved_wifi error: {e}")
        return jsonify(success=False, error=str(e)), 500

@webinterface.route('/api/try_connect_saved_wifi', methods=['POST'])
def try_connect_saved_wifi():
    try:
        ok, used_ssid = app_state.platform.attempt_connect_saved_networks(app_state.hotspot, app_state.usersettings)
        return jsonify(success=ok, ssid=used_ssid or '')
    except Exception as e:
        logger.warning(f"try_connect_saved_wifi error: {e}")
        return jsonify(success=False, error=str(e)), 500
