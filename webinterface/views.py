from webinterface import webinterface, app_state
from flask import render_template, request, jsonify
import os

import time
from lib.song_file_security import SongFileError, resolve_song_path, validate_song_filename

ALLOWED_EXTENSIONS = {'mid', 'musicxml', 'mxl', 'xml', 'abc'}
DEFAULT_WEB_THEME_SETTINGS = {
    "web_theme_mode": "dark",
    "web_theme_preset": "aurora",
    "web_theme_accent": "#22d3ee",
    "web_theme_background_color": "#334155",
    "web_theme_surface_color": "#cbd5e1",
    "web_theme_icon_color": "#94a3b8",
    "web_theme_badge_color": "#0f766e",
    "web_theme_badge_text_color": "#f8fafc",
    "web_theme_surface": "glass",
    "web_theme_radius": "rounded",
    "web_theme_glow": "normal",
    "web_theme_contrast": "balanced",
    "web_theme_background": "ambient",
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@webinterface.before_request
def before_request():
    excluded_routes = ['/api/get_homepage_data', '/api/get_system_time']

    # Check if the current request path is in the excluded_routes list
    if request.path not in excluded_routes:
        app_state.menu.last_activity = time.time()
        app_state.menu.is_idle_animation_running = False
        # Update state manager for user activity
        if app_state.state_manager:
            app_state.state_manager.update_user_activity()


@webinterface.route('/')
def index():
    initial_theme_settings = {
        key: (app_state.usersettings.get_setting_value(key) if getattr(app_state, "usersettings", None) else None) or value
        for key, value in DEFAULT_WEB_THEME_SETTINGS.items()
    }
    return render_template(
        'index.html',
        initial_theme_settings=initial_theme_settings,
    )


@webinterface.route('/home')
def home():
    return render_template('home.html')


@webinterface.route('/appearance')
def appearance():
    return render_template('appearance.html')


@webinterface.route('/ledsettings')
def ledsettings():
    return render_template('ledsettings.html')


@webinterface.route('/ledanimations')
def ledanimations():
    return render_template('ledanimations.html')


@webinterface.route('/songs')
def songs():
    return render_template('songs.html')


@webinterface.route('/sequences')
def sequences():
    return render_template('sequences.html')


@webinterface.route('/ports')
def ports():
    return render_template('ports.html')


@webinterface.route('/network')
def network():
    return render_template('network.html')


@webinterface.route('/practice')
def practice():
    return render_template('practice.html')


@webinterface.route('/upload', methods=['POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify(success=False, error="no file")
        file = request.files['file']
        raw_filename = (file.filename or "").replace("'", "")
        try:
            filename = validate_song_filename(raw_filename)
            song_path = resolve_song_path(
                filename,
                base_dir=webinterface.config['UPLOAD_FOLDER'],
                must_exist=False,
            )
        except SongFileError as e:
            return jsonify(success=False, error=str(e), song_name=raw_filename)
        if song_path.exists():
            return jsonify(success=False, error="file already exists", song_name=filename)

        file.save(str(song_path))
        return jsonify(success=True, reload_songs=True, song_name=filename)
