import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import webinterface as web_mod


@pytest.fixture
def running_server(monkeypatch, request):
    entered = threading.Event()
    closed = threading.Event()
    broadcast_closed = threading.Event()
    errors = []
    address = SimpleNamespace(port=None)
    real_serve = web_mod.websockets.serve
    use_network = getattr(request, "param", False)
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    class Server:
        def __init__(self, handler, host, _port):
            self.handler = handler
            self.host = host
            self.server = None

        async def __aenter__(self):
            if use_network:
                self.server = await real_serve(self.handler, self.host, 0, close_timeout=1)
                address.port = self.server.sockets[0].getsockname()[1]
            entered.set()
            return self

        async def __aexit__(self, *_args):
            if self.server is not None:
                self.server.close()
                await self.server.wait_closed()
            # Closing real WebSocket connections also needs event-loop turns.
            await asyncio.sleep(0)
            closed.set()

    async def broadcast(_event):
        try:
            await asyncio.Future()
        finally:
            broadcast_closed.set()

    queue = web_mod.WakeableDeque()
    monkeypatch.setattr(web_mod.webinterface, "websocket_midi_send", queue)
    monkeypatch.setattr(web_mod.app_state, "usersettings", SimpleNamespace(get_setting_value=lambda _key: "127.0.0.1"))
    monkeypatch.setattr(web_mod.websockets, "serve", Server)
    monkeypatch.setattr(web_mod, "broadcast_midi_to_clients", broadcast)

    def run():
        try:
            web_mod.start_server(loop)
        except (RuntimeError, asyncio.CancelledError) as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(2)
        yield SimpleNamespace(loop=loop, thread=thread, errors=errors,
                              closed=closed, broadcast_closed=broadcast_closed, queue=queue, address=address)
    finally:
        if thread.is_alive():
            web_mod.stop_server(loop)
            if not loop.is_closed():
                loop.call_soon_threadsafe(lambda: None)
            thread.join(2)
        # Recover the old implementation's stopped but unclosed loop on failure.
        if not thread.is_alive() and not loop.is_closed():
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()


def test_external_stop_waits_for_server_cleanup_without_thread_exception(running_server):
    state = running_server
    web_mod.stop_server(state.loop)
    if not state.loop.is_closed():
        state.loop.call_soon_threadsafe(lambda: None)
    state.thread.join(2)
    assert not state.thread.is_alive()
    assert state.errors == []
    assert state.closed.is_set()
    assert state.broadcast_closed.is_set()
    assert state.loop.is_closed()


def test_stop_from_server_loop_does_not_join_its_own_thread(running_server):
    state = running_server
    state.loop.call_soon_threadsafe(web_mod.stop_server, state.loop)
    state.thread.join(2)
    assert not state.thread.is_alive()
    assert state.errors == []
    assert state.closed.is_set()


def test_repeated_stop_after_loop_has_closed_is_harmless(running_server):
    state = running_server
    web_mod.stop_server(state.loop)
    if not state.loop.is_closed():
        state.loop.call_soon_threadsafe(lambda: None)
    state.thread.join(2)
    web_mod.stop_server(state.loop)
    assert state.errors == []


def test_stop_before_server_thread_starts_is_not_lost(monkeypatch):
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(web_mod.webinterface, "websocket_midi_send", Mock())
    monkeypatch.setattr(web_mod.app_state, "usersettings", SimpleNamespace(get_setting_value=lambda _key: "127.0.0.1"))
    serve = Mock(side_effect=AssertionError("a stopped server must not listen"))
    monkeypatch.setattr(web_mod.websockets, "serve", serve)
    try:
        web_mod.stop_server(loop)
        web_mod.start_server(loop)
        serve.assert_not_called()
        assert loop.is_closed()
    finally:
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize("running_server", [True], indirect=True)
def test_stop_closes_an_actual_websocket_connection(running_server):
    state = running_server

    async def connect_and_stop():
        async with web_mod.websockets.connect(f"ws://127.0.0.1:{state.address.port}/learning") as client:
            assert await asyncio.to_thread(web_mod.stop_server, state.loop)
            await asyncio.wait_for(client.wait_closed(), timeout=2)
            assert client.close_code in (1000, 1001)

    asyncio.run(connect_and_stop())
    assert state.errors == []
    assert state.closed.is_set()
    assert state.loop.is_closed()
