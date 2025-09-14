from flask import Flask
import asyncio
import websockets
from lib.functions import get_ip_address
import json
from lib.log_setup import logger

UPLOAD_FOLDER = 'Songs/'

webinterface = Flask(__name__,
                     static_folder='static',
                     template_folder='templates')
webinterface.config['TEMPLATES_AUTO_RELOAD'] = True
webinterface.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
webinterface.config['MAX_CONTENT_LENGTH'] = 32 * 1000 * 1000
webinterface.json.sort_keys = False

webinterface.socket_input = []


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
        self.ledemu_clients = set()  # Track active LED emulator clients
        self.ledemu_pause = False


# Create a single instance of AppState
app_state = AppState()


def start_server(loop):
    async def learning(websocket):
        try:
            while True:
                await asyncio.sleep(0.01)
                for msg in app_state.learning.socket_send[:]:
                    await websocket.send(str(msg))
                    app_state.learning.socket_send.remove(msg)
        except:
            pass

    async def ledemu(websocket):
        try:
            # Register the client
            app_state.ledemu_clients.add(websocket)
            logger.info(f"LED emulator client connected. Active clients: {len(app_state.ledemu_clients)}")

            await websocket.send(json.dumps({"settings":
                                                 {"gamma": app_state.ledstrip.led_gamma,
                                                  "reverse": app_state.ledstrip.reverse}}))

            previous_leds = None
            while not websocket.closed and websocket in app_state.ledemu_clients:
                try:
                    ledstrip = app_state.ledstrip
                    await asyncio.sleep(1 / ledstrip.WEBEMU_FPS)

                    if app_state.ledemu_pause:
                        continue

                    if websocket.closed:
                        break

                    current_leds = ledstrip.strip.getPixels()
                    if previous_leds != current_leds:
                        try:
                            await websocket.send(json.dumps({"leds": current_leds}))
                            previous_leds = list(current_leds)
                        except websockets.exceptions.ConnectionClosed:
                            break

                except websockets.exceptions.ConnectionClosed:
                    break
                except websockets.exceptions.WebSocketException:
                    break
                except Exception as e:
                    logger.warning("Unhandled exception in ledemu:", exc_info=e)
                    break

            if websocket in app_state.ledemu_clients:
                app_state.ledemu_clients.remove(websocket)
                logger.info(f"LED emulator client disconnected. Active clients: {len(app_state.ledemu_clients)}")

        except websockets.exceptions.ConnectionClosed:
            pass
        except websockets.exceptions.WebSocketException:
            pass
        except Exception as e:
            logger.warning("Unexpected error in ledemu handler:", exc_info=e)

    async def main_async():
        server_learning = await websockets.serve(learning, get_ip_address(), 5678)
        server_ledemu = await websockets.serve(ledemu, get_ip_address(), 5679)
        try:
            await asyncio.Future()  # run forever
        finally:
            server_learning.close()
            server_ledemu.close()
            await server_learning.wait_closed()
            await server_ledemu.wait_closed()

    loop.create_task(main_async())

def stop_server(loop):
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.stop()


# Import views after app is defined to avoid circular imports
from webinterface import views, views_api

# NEW: register extra Wi-Fi management endpoints
import webinterface.wifi_api
