import argparse
import json
import random
import socketserver
import struct
from typing import Dict, Any, Tuple

# =====================================================================
# Protocol-accurate stand-in for the CoQ QA Bridge mod.
# Simulates an 80x25 zone with a wandering player so the entire Python pipeline
# (transport -> LiveGameEnv -> swarm -> dashboard -> anomaly logging) is testable
# headlessly. Speaks the exact length-prefixed JSON contract of SocketTransport.
# Injected hazards give the QA swarm real anomalies to discover.
# =====================================================================

# CoQ zones are 80x25, but the player starts inside a compact room. The mock
# simulates that explorable room so the QA sweep is tractable in a short budget.
GRID_W, GRID_H = 80, 25
ROOM_W, ROOM_H = 28, 16       # walls beyond this; spawn is the room center
SPAWN = (ROOM_W // 2, ROOM_H // 2)

# Action layout matches DotNetConnector.ACTION_BINDINGS.
# 0 MOVE_N, 1 MOVE_S, 2 MOVE_E, 3 MOVE_W, 4 WAIT, 5 INTERACT
DELTAS = {0: (0, -1), 1: (0, 1), 2: (1, 0), 3: (-1, 0), 4: (0, 0), 5: (0, 0)}

# Injected fault zones (the bugs a tester should find), spread in different
# directions. Lava/softlock are wide mid-distance bands (reliably swept); crash
# sits in a far corner so it's the rare find that ends a run.
SOFTLOCK = (2, 7, 5, 11)      # x0,x1,y0,y1 — west band; freezes the player (stuck)
LAVA = (20, 25, 5, 11)        # east band; chip damage (non-terminating)
CRASH = (24, 27, 0, 2)        # NE corner; numeric overflow crash (terminating)


def _in(box: Tuple[int, int, int, int], x: int, y: int) -> bool:
    x0, x1, y0, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


class _Player:
    __slots__ = ("x", "y", "hp", "hunger", "level", "turn")

    def __init__(self):
        self.reset()

    def reset(self):
        self.x, self.y = SPAWN
        self.hp = 100.0
        self.hunger = 0.0
        self.level = 1
        self.turn = 0


class CoQMockHandler(socketserver.BaseRequestHandler):
    def handle(self):
        player = _Player()
        while True:
            header = self._recv_exact(4)
            if header is None:
                return
            (length,) = struct.unpack(">I", header)
            body = self._recv_exact(length)
            if body is None:
                return
            req = json.loads(body.decode("utf-8"))
            cmd = req.get("cmd")
            if cmd == "bye":
                return
            if cmd == "reset":
                player.reset()
                self._send(self._frame(player, anomaly=None))
            elif cmd == "step":
                self._send(self._frame(player, action=int(req.get("action", 4))))
            else:
                self._send(self._frame(player, anomaly=None))

    def _frame(self, p: "_Player", action: int = None, anomaly: str = None) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        if action is not None:
            p.turn += 1
            p.hunger = min(120.0, p.hunger + 0.5)

            dx, dy = DELTAS.get(action, (0, 0))
            stuck = _in(SOFTLOCK, p.x, p.y)
            if stuck:
                # Softlock: input ignored, position frozen for this visit.
                anomaly = "SOFTLOCK_SUSPECTED"
            else:
                nx, ny = p.x + dx, p.y + dy
                if not (0 <= nx < ROOM_W):
                    info["hit_boundary"] = True
                    nx = p.x
                if not (0 <= ny < ROOM_H):
                    info["hit_boundary"] = True
                    ny = p.y
                p.x, p.y = nx, ny

            if _in(LAVA, p.x, p.y):
                p.hp = max(0.0, p.hp - 15.0)
                anomaly = anomaly or "HAZARD_DAMAGE"
            if p.hunger >= 100.0:
                p.hp = max(0.0, p.hp - 1.0)  # starving

            if _in(CRASH, p.x, p.y):
                anomaly = "CRASH_NUMERIC"
                return self._payload(p, anomaly, terminated=True, info=info)

        terminated = p.hp <= 0.0
        return self._payload(p, anomaly, terminated=terminated, info=info)

    def _payload(self, p: "_Player", anomaly, terminated: bool, info: Dict[str, Any]) -> Dict[str, Any]:
        threats = sum(1 for _ in range(0))  # no live NPCs in the mock
        if _in(LAVA, p.x, p.y):
            threats = random.randint(1, 3)
        return {
            "obs": {
                "coq_hp": round(p.hp, 2), "coq_hp_max": 100.0,
                "coq_x": float(p.x), "coq_y": float(p.y),
                "coq_depth": 0.0, "coq_hunger": round(p.hunger, 2),
                "coq_level": float(p.level), "coq_turn": float(p.turn),
                "coq_threats": float(threats),
            },
            "reward_hint": 0.0,
            "terminated": bool(terminated),
            "truncated": False,
            "anomaly": anomaly,
            "info": info,
        }

    def _send(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.request.sendall(struct.pack(">I", len(body)) + body)

    def _recv_exact(self, n: int):
        buf = bytearray()
        while len(buf) < n:
            part = self.request.recv(n - len(buf))
            if not part:
                return None
            buf.extend(part)
        return bytes(buf)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 50545) -> _Server:
    server = _Server((host, port), CoQMockHandler)
    print(f"[MockCoQ] Zone simulator listening on {host}:{port}")
    return server


def main():
    parser = argparse.ArgumentParser(description="Protocol-accurate Caves of Qud mock server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50545)
    args = parser.parse_args()
    server = serve(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[MockCoQ] Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
