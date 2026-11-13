from flask import Flask
import asyncio
import os
import threading
from urllib.parse import urlsplit
import websockets
from lib.functions import get_ip_address
import json
from collections import deque
from lib.log_setup import logger

UPLOAD_FOLDER = 'Songs/'

webinterface = Flask(__name__,
                     static_folder='static',
                     template_folder='templates')
webinterface.config['TEMPLATES_AUTO_RELOAD'] = True
webinterface.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
webinterface.config['MAX_CONTENT_LENGTH'] = 32 * 1000 * 1000
webinterface.json.sort_keys = False

WEBSOCKET_SEND_TIMEOUT_S = 2.0  # a client that cannot take a batch within this delay is dropped
BROADCAST_POLL_INTERVAL_S = 0.01  # fallback poll, still needed for the learning outbox


class WakeableDeque(deque):
    """deque whose appends wake the websocket broadcast loop immediately.

    The loop used to sleep 10 ms between polls, adding up to 10 ms to every
    practice-mode echo. Appends now schedule a single event.set() on the
    websocket loop (coalesced while a wake-up is already pending).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wake_loop = None
        self._wake_event = None
        self._wake_pending = False

    def attach_wakeup(self, loop, event):
        self._wake_pending = False
        self._wake_event = event
        self._wake_loop = loop

    def detach_wakeup(self):
        self._wake_loop = None
        self._wake_event = None
        self._wake_pending = False

    def consume_wakeup(self):
        """Called by the consumer right before it drains the queue."""
        self._wake_pending = False

    def append(self, item):
        super().append(item)
        loop = self._wake_loop
        if loop is None or self._wake_pending:
            return
        self._wake_pending = True
        try:
            loop.call_soon_threadsafe(self._wake_event.set)
        except RuntimeError:  # loop already closed (shutdown)
            self._wake_pending = False


webinterface.socket_input = []
webinterface.websocket_midi_send = WakeableDeque(maxlen=100)  # Thread-safe queue for MIDI messages to send to websocket clients
webinterface.websocket_midi_send_lock = None  # Lock for synchronizing async consumers (initialized in start_server)


# State container to hold app components
class AppState:
    def __init__(self):
        self.usersettings = None
        self.ledsettings = None
        self.ledstrip = None
        self.learning = None
        self.saving = None
        self.midiports = None
        self.menu = None
        self.hotspot = None
        self.platform = None
        self.state_manager = None
        self.playback_scheduler = None
        self.ledemu_clients = set()  # Track active LED emulator clients
        self.ledemu_pause = False
        self.current_profile_id = None
        # Currently selected profile id (set by web UI); None if not selected
        self.practice_active = False  # Track when practice tab is active
        self.websocket_midi_clients = set()  # Track active websocket MIDI clients


# Create a single instance of AppState
app_state = AppState()


def websocket_origin_allowed(headers):
    """Browsers always send Origin on a WebSocket handshake; refuse other sites.

    Any web page can open ws://<pi>:8765, which would let it inject MIDI notes
    and read the live feed. Clients that send no Origin (scripts, native apps)
    are unaffected. PLV_ALLOW_CROSS_SITE=1 disables the check.
    """
    if os.environ.get("PLV_ALLOW_CROSS_SITE") == "1":
        return True
    origin = headers.get("Origin")
    if not origin:
        return True
    origin_host = urlsplit(origin).hostname
    request_host = urlsplit("//" + headers.get("Host", "")).hostname
    return origin_host is not None and origin_host == request_host


async def reject_foreign_origin(websocket):
    """Close the connection and return True if it comes from another site."""
    request = getattr(websocket, "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        headers = getattr(websocket, "request_headers", None)
    if headers is None or websocket_origin_allowed(headers):
        return False
    logger.warning("Refused websocket connection from origin %s", headers.get("Origin"))
    try:
        await websocket.close(code=1008, reason="origin not allowed")
    except Exception:
        pass
    return True


_closing_tasks = set()


async def _close_quietly(websocket):
    try:
        await asyncio.wait_for(websocket.close(), timeout=WEBSOCKET_SEND_TIMEOUT_S)
    except Exception:
        pass


async def broadcast_midi_to_clients(wake_event=None, send_timeout=WEBSOCKET_SEND_TIMEOUT_S):
    """Background task to broadcast MIDI messages to all connected clients."""
    logger.info("Starting MIDI broadcast task")

    async def send_batch(websocket, messages):
        async def send_all():
            for message in messages:
                await websocket.send(str(message))

        # One stalled client must not freeze the broadcast for everybody else.
        await asyncio.wait_for(send_all(), timeout=send_timeout)

    while True:
        try:
            queue = webinterface.websocket_midi_send
            if wake_event is not None:
                try:
                    await asyncio.wait_for(wake_event.wait(), timeout=BROADCAST_POLL_INTERVAL_S)
                except asyncio.TimeoutError:
                    pass
                wake_event.clear()
                consume = getattr(queue, "consume_wakeup", None)
                if consume is not None:
                    consume()
            else:
                await asyncio.sleep(BROADCAST_POLL_INTERVAL_S)

            clients = list(app_state.websocket_midi_clients)
            if clients:
                messages = []
                if app_state.practice_active:
                    while queue:
                        messages.append(queue.popleft())

                learning = getattr(app_state, "learning", None)
                learning_outbox = getattr(learning, "socket_send", None)
                if learning_outbox is not None:
                    if hasattr(learning_outbox, "drain"):
                        messages.extend(learning_outbox.drain())
                    elif learning_outbox:
                        messages.extend(learning_outbox[:])
                        del learning_outbox[:]

                if messages:
                    results = await asyncio.gather(
                        *(send_batch(ws, messages) for ws in clients),
                        return_exceptions=True,
                    )
                    for ws, result in zip(clients, results):
                        if isinstance(result, BaseException):
                            app_state.websocket_midi_clients.discard(ws)
                            if isinstance(result, asyncio.TimeoutError):
                                logger.warning("Dropping websocket MIDI client that stopped receiving")
                                task = asyncio.ensure_future(_close_quietly(ws))
                                _closing_tasks.add(task)
                                task.add_done_callback(_closing_tasks.discard)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in MIDI broadcast task: {e}")
            await asyncio.sleep(1)


def start_server(loop):
    loop._plv_server_thread = threading.current_thread()
    if getattr(loop, "_plv_stop_requested", False):
        loop.close()
        return

    async def learning(websocket):
        try:
            app_state.websocket_midi_clients.add(websocket)
            logger.info(f"WebSocket MIDI client connected. Active clients: {len(app_state.websocket_midi_clients)}")
            
            async def receive_messages():
                """Receive incoming MIDI messages from client."""
                try:
                    async for message in websocket:
                        try:
                            # Check if it's a MIDI message string
                            if isinstance(message, str) and message.startswith("midi_event"):
                                # Forward to midiports for processing
                                if app_state.midiports:
                                    app_state.midiports.add_websocket_midi_message(message)
                            # Could also handle JSON format: {"type": "midi_message", "data": "..."}
                            elif isinstance(message, str):
                                try:
                                    data = json.loads(message)
                                    if data.get("type") == "midi_message" and "data" in data:
                                        if app_state.midiports:
                                            app_state.midiports.add_websocket_midi_message(data["data"])
                                except (json.JSONDecodeError, KeyError):
                                    # Not a JSON MIDI message, ignore
                                    pass
                        except Exception as e:
                            logger.warning(f"Error processing websocket MIDI message: {e}")
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    logger.warning(f"Error receiving websocket message: {e}")
            
            await receive_messages()
        except Exception as e:
            logger.warning(f"WebSocket learning handler error: {e}")
        finally:
            app_state.websocket_midi_clients.discard(websocket)
            logger.info(f"WebSocket MIDI client disconnected. Active clients: {len(app_state.websocket_midi_clients)}")

    def is_connection_closed(ws):
        if hasattr(ws, "closed"):
            return ws.closed
        state = getattr(ws, "state", None)
        if state is not None:
            return state.name in ("CLOSED", "CLOSING")
        return False

    async def ledemu_recv(websocket):
        async for message in websocket:
            try:
                if isinstance(message, str):
                    msg = json.loads(message)
                else:
                    msg = {}
                cmd = msg.get("cmd") if isinstance(msg, dict) else None
                if cmd == "pause":
                    app_state.ledemu_pause = True
                elif cmd == "resume":
                    app_state.ledemu_pause = False
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.WebSocketException):
                break
            except Exception as e:
                logger.warning(f"LED emulator receive error: {e}")
                return

    async def ledemu(websocket):
        try:
            app_state.ledemu_clients.add(websocket)
            logger.info(f"LED emulator client connected. Active clients: {len(app_state.ledemu_clients)}")

            await websocket.send(json.dumps({"settings":
                                                 {"gamma": app_state.ledstrip.led_gamma,
                                                  "reverse": app_state.ledstrip.reverse}}))

            previous_leds = None
            while not is_connection_closed(websocket) and websocket in app_state.ledemu_clients:  # Check both conditions
                try:
                    ledstrip = app_state.ledstrip
                    await asyncio.sleep(1 / ledstrip.WEBEMU_FPS)

                    if app_state.ledemu_pause:
                        continue

                    # Check connection is still open before sending
                    if is_connection_closed(websocket):
                        break

                    current_leds = ledstrip.strip.getPixels()
                    if previous_leds != current_leds:  # Only send if LED state has changed
                        try:
                            await websocket.send(json.dumps({"leds": current_leds}))
                            previous_leds = list(current_leds)  # Create a copy of the list
                        except websockets.exceptions.ConnectionClosed:
                            break

                except websockets.exceptions.ConnectionClosed:
                    break
                except websockets.exceptions.WebSocketException:
                    break
                except Exception as e:
                    logger.warning(f"LED emulator error: {str(e)}")
                    break
        finally:
            if websocket in app_state.ledemu_clients:
                app_state.ledemu_clients.remove(websocket)
                logger.info(f"LED emulator client disconnected. Active clients: {len(app_state.ledemu_clients)}")
            try:
                await websocket.close()
            except:
                pass

    async def handler(websocket):
        try:
            if await reject_foreign_origin(websocket):
                return
            # Support both newer (websocket.request.path) and older (websocket.path) versions
            try:
                path = websocket.request.path
            except AttributeError:
                path = websocket.path
            
            if path == "/learning":
                await learning(websocket)
            elif path == "/ledemu":
                await asyncio.gather(ledemu(websocket), ledemu_recv(websocket))
            else:
                # No handler for this path; close the connection.
                return
        except Exception as e:
            logger.warning(f"WebSocket handler error: {str(e)}")
        finally:
            if websocket in app_state.ledemu_clients:
                app_state.ledemu_clients.remove(websocket)
                logger.info(
                    f"LED emulator client disconnected (handler cleanup). Active clients: {len(app_state.ledemu_clients)}")

    async def main():
        # Initialize the global broadcast task, woken as soon as MIDI is queued
        wake_event = asyncio.Event()
        webinterface.websocket_midi_send.attach_wakeup(loop, wake_event)
        broadcast_task = asyncio.create_task(broadcast_midi_to_clients(wake_event))
        
        listen_ip = app_state.usersettings.get_setting_value("web_listen_ip")

        if listen_ip and listen_ip != "0.0.0.0":
            show_ip = listen_ip
        else:
            show_ip = str(get_ip_address())
            listen_ip = "0.0.0.0"

        logger.info("WebSocket listening on: " + show_ip + ":8765")
        try:
            async with websockets.serve(handler, listen_ip, 8765):
                await asyncio.Future()
        finally:
            broadcast_task.cancel()
            await asyncio.gather(broadcast_task, return_exceptions=True)

    asyncio.set_event_loop(loop)
    task = loop.create_task(main())
    loop._plv_server_task = task
    if getattr(loop, "_plv_stop_requested", False):
        task.cancel()
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass  # An explicit stop cancels the owner and exits websockets.serve.
    finally:
        webinterface.websocket_midi_send.detach_wakeup()
        pending = asyncio.all_tasks(loop)
        for pending_task in pending:
            pending_task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


# Stop the WebSocket server and cancel pending tasks on shutdown
def stop_server(loop):
    if loop.is_closed():
        return True
    if not getattr(loop, "_plv_stop_requested", False):
        loop._plv_stop_requested = True

        def cancel_owner():
            task = getattr(loop, "_plv_server_task", None)
            if task is not None:
                task.cancel()

        try:
            loop.call_soon_threadsafe(cancel_owner)
        except RuntimeError:
            if not loop.is_closed():
                raise
    owner = getattr(loop, "_plv_server_thread", None)
    if owner is not None and owner is not threading.current_thread():
        owner.join(timeout=5)
        return not owner.is_alive()
    return loop.is_closed()


# Import views after app is defined to avoid circular imports
from webinterface import views, views_api

# Attach profile manager without modifying existing AppState.__init__
try:
    from lib.profile_manager import ProfileManager
    if not hasattr(app_state, 'profile_manager'):
        app_state.profile_manager = ProfileManager()
except Exception as e:
    # Silent-ish failure keeps app running
    logger.warning(f"ProfileManager init failed: {e}")
