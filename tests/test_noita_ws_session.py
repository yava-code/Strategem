from __future__ import annotations

import json
import re
import threading
import unittest

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from adapters.noita_ws.bridge_template import bind
from adapters.noita_ws.session import NoitaWsSession
from src.sdk.annotations import bm
from src.sdk.runtime import BridgeRuntime


def _fake_noita(port: int, seen: list[str], stop: threading.Event) -> None:
    with connect(f"ws://127.0.0.1:{port}", proxy=None) as ws:
        ws.send(json.dumps({"kind": "heartbeat", "source": "noita"}))
        while not stop.is_set():
            try:
                msg = str(ws.recv(timeout=0.2))
            except TimeoutError:
                continue
            except ConnectionClosed:
                break

            seen.append(msg)
            match = re.search(r"__bridge_maker__(bm_[a-f0-9]+)\|", msg)
            rid = match.group(1) if match else None
            if "get_player_hp" in msg and rid:
                ws.send(f">__bridge_maker__{rid}|73.5")
            elif "get_player_xy" in msg and rid:
                ws.send(f">__bridge_maker__{rid}|12.0,-4.5")
            elif "bridge_player_missing" in msg and rid:
                ws.send(f">__bridge_maker__{rid}|false")


class NoitaWsSessionTests(unittest.TestCase):
    def test_session_and_contract_binder(self):
        stop = threading.Event()
        seen: list[str] = []
        bm.reset_registry()

        with NoitaWsSession(port=0, timeout=2.0) as session:
            worker = threading.Thread(target=_fake_noita, args=(session.port, seen, stop), daemon=True)
            worker.start()

            self.assertTrue(session.wait_ready(2.0))
            self.assertEqual(session.eval_float("return get_player_hp()"), 73.5)
            self.assertEqual(session.eval_vec2("return get_player_xy()"), (12.0, -4.5))
            self.assertFalse(session.eval_bool("return bridge_player_missing()"))

            bind(session)
            runtime = BridgeRuntime()
            state = runtime.sample()
            self.assertEqual(state["hp"], 73.5)
            self.assertEqual(state["x"], 12.0)
            self.assertEqual(state["y"], -4.5)

            frame = runtime.step("move_left")
            self.assertEqual(frame.action, "move_left")
            self.assertFalse(frame.oracles)
            self.assertTrue(any("bridge_apply_action('move_left')" in msg for msg in seen))

        stop.set()


if __name__ == "__main__":
    unittest.main()
