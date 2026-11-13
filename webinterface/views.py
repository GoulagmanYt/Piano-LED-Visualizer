from webinterface import webinterface, app_state
from flask import render_template, request, jsonify
import os
import uuid
from urllib.parse import urlsplit

import time
from lib.log_setup import logger
from lib.song_file_security import SongFileError, resolve_song_path, validate_song_filename

ALLOWED_EXTENSIONS = {'mid', 'musicxml', 'mxl', 'xml', 'abc'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# State-changing actions (reboot, shutdown, Wi-Fi, updates, uploads...) are plain
# GET/POST requests without authentication. A web page the user merely visits
# could trigger them with an <img> or a form, so requests that a browser says
# come from another site are refused. Non-browser clients send none of these
# headers and are unaffected. Set PLV_ALLOW_CROSS_SITE=1 to disable the guard
# (for example behind a reverse proxy that rewrites the Host header).
GUARDED_PATH_PREFIXES = ("/api/", "/upload")


def is_cross_site_request(req):
    """True when the browser reports that `req` was triggered by another site."""
    fetch_site = req.headers.get("Sec-Fetch-Site")
    if fetch_site in ("same-origin", "none"):
        return False
    if fetch_site == "cross-site":
        return True
    # "same-site" (another port on this host), an unknown value, or an older
    # browser without Fetch Metadata: fall back to Origin / Referer.
    origin = req.headers.get("Origin") or req.headers.get("Referer")
    if not origin:
        return False
    if origin == "null":
        return True
    return urlsplit(origin).netloc != req.host


@webinterface.before_request
def block_cross_site_requests():
    if os.environ.get("PLV_ALLOW_CROSS_SITE") == "1":
        return None
    if request.path.startswith(GUARDED_PATH_PREFIXES) and is_cross_site_request(request):
        logger.warning("Blocked cross-site request to %s", request.path)
        return jsonify(success=False, error="cross-site request blocked"), 403
    return None


@webinterface.before_request
def before_request():
    excluded_routes = ['/api/get_homepage_data', '/api/get_system_time', '/api/get_led_power']

    # Check if the current request path is in the excluded_routes list
    if request.path not in excluded_routes:
        app_state.menu.last_activity = time.time()
        app_state.menu.is_idle_animation_running = False
        # Update state manager for user activity
        if app_state.state_manager:
            app_state.state_manager.update_user_activity()


@webinterface.route('/')
def index():
    return render_template('index.html')


@webinterface.route('/home')
def home():
    return render_template('home.html')


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


def save_upload_atomically(file, song_path):
    """Store an uploaded file without ever leaving a truncated song behind.

    The upload is streamed to a hidden temporary file next to the target and
    then published with os.link(), which is atomic and refuses to overwrite an
    existing file. Returns False when `song_path` already exists. Any write
    error (disk full, ...) propagates after the temporary file is removed.
    """
    tmp_path = song_path.with_name(f".{song_path.name}.{uuid.uuid4().hex}.part")
    try:
        file.save(str(tmp_path))
        try:
            os.link(tmp_path, song_path)
        except FileExistsError:
            return False
        except OSError:
            # Filesystem without hard links: fall back to a checked rename.
            if song_path.exists():
                return False
            os.replace(tmp_path, song_path)
        return True
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


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

        try:
            saved = save_upload_atomically(file, song_path)
        except OSError as e:
            logger.warning("Upload of %s failed: %s", filename, e)
            return jsonify(success=False, error="could not save file: " + (e.strerror or str(e)),
                           song_name=filename)
        if not saved:
            return jsonify(success=False, error="file already exists", song_name=filename)
        return jsonify(success=True, reload_songs=True, song_name=filename)
