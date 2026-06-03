import json
import socket
import struct
import time
from typing import Optional

from src.connectors.base import GameTransport, StateFrame

# =====================================================================
# Length-prefixed JSON transport (4-byte big-endian length + UTF-8 body).
# Same framing as the Unreal bridge in src/engine_bridges.py, lifted here as
# the canonical wire format shared by the CoQ mod and the mock server.
# =====================================================================


class SocketTransport(GameTransport):
    def __init__(self, host: str = "127.0.0.1", port: int = 50545,
                 connect_timeout: float = 10.0, io_timeout: float = 15.0,
                 retries: int = 30):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.io_timeout = io_timeout
        self.retries = retries
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        last_err = None
        # The game/mod may still be spinning up its listener; retry briefly.
        for _ in range(self.retries):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self.connect_timeout)
                s.connect((self.host, self.port))
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.settimeout(self.io_timeout)
                self._sock = s
                return
            except OSError as e:
                last_err = e
                time.sleep(0.2)
        raise ConnectionError(f"Could not reach game transport at "
                              f"{self.host}:{self.port} ({last_err})")

    def _exchange(self, payload: dict) -> StateFrame:
        if self._sock is None:
            raise RuntimeError("Transport not connected. Call connect() first.")
        body = json.dumps(payload).encode("utf-8")
        self._sock.sendall(struct.pack(">I", len(body)) + body)
        (length,) = struct.unpack(">I", self._recv_exact(4))
        return StateFrame.from_wire(json.loads(self._recv_exact(length).decode("utf-8")))

    def _recv_exact(self, n: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < n:
            part = self._sock.recv(n - len(chunks))
            if not part:
                raise ConnectionError("Game transport closed the connection mid-frame.")
            chunks.extend(part)
        return bytes(chunks)

    def reset(self) -> StateFrame:
        return self._exchange({"cmd": "reset"})

    def step(self, action: int) -> StateFrame:
        return self._exchange({"cmd": "step", "action": int(action)})

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.sendall(struct.pack(">I", len(b'{"cmd":"bye"}')) + b'{"cmd":"bye"}')
            except OSError:
                pass
            self._sock.close()
            self._sock = None
