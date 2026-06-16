from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from websockets.sync.server import ServerConnection, serve


_REPLY_PREFIX = "__bridge_maker__"


@dataclass(frozen=True)
class NoitaMessage:
    kind: str
    payload: Any


class NoitaWsSession:
    def __init__(self, host: str = "127.0.0.1", port: int = 9090, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages: list[NoitaMessage] = []
        self._server = None
        self._thread: threading.Thread | None = None
        self._conn: ServerConnection | None = None
        self._conn_lock = threading.Lock()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._replies: dict[str, queue.Queue[str]] = {}

    def start(self) -> "NoitaWsSession":
        if self._server is not None:
            return self
        self._server = serve(self._handle, self.host, self.port)
        self.port = int(self._server.socket.getsockname()[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._closed.set()
        with self._conn_lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "NoitaWsSession":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.close()

    def wait_ready(self, timeout: float | None = None) -> bool:
        return self._ready.wait(self.timeout if timeout is None else timeout)

    def exec(self, lua: str) -> None:
        self._send(lua)

    def eval_float(self, lua: str) -> float:
        return float(self._ask(self._wrap_scalar(lua)))

    def eval_bool(self, lua: str) -> bool:
        raw = self._ask(self._wrap_scalar(lua)).strip().lower()
        return raw in {"1", "true", "yes"}

    def eval_vec2(self, lua: str) -> tuple[float, float]:
        raw = self._ask(self._wrap_vec2(lua))
        x, y = [float(part.strip()) for part in raw.split(",", 1)]
        return x, y

    def _ask(self, lua: str) -> str:
        rid = f"bm_{uuid.uuid4().hex}"
        replies: queue.Queue[str] = queue.Queue(maxsize=1)
        self._replies[rid] = replies
        self._send(lua.replace("{rid}", rid))
        try:
            return replies.get(timeout=self.timeout)
        finally:
            self._replies.pop(rid, None)

    def _send(self, text: str) -> None:
        if not self.wait_ready():
            raise TimeoutError("Noita WebSocket client did not connect")
        with self._conn_lock:
            conn = self._conn
        if conn is None:
            raise ConnectionError("Noita WebSocket client disconnected")
        conn.send(text)

    def _handle(self, ws: ServerConnection) -> None:
        with self._conn_lock:
            self._conn = ws
        try:
            for msg in ws:
                self._on_message(msg.decode("utf-8") if isinstance(msg, bytes) else str(msg))
                if self._closed.is_set():
                    break
        finally:
            with self._conn_lock:
                if self._conn is ws:
                    self._conn = None
            self._ready.clear()

    def _on_message(self, msg: str) -> None:
        if msg.startswith(">"):
            text = msg[1:]
            self.messages.append(NoitaMessage("print", text))
            self._maybe_reply(text)
            return

        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            self.messages.append(NoitaMessage("raw", msg))
            self._maybe_reply(msg)
            return

        self.messages.append(NoitaMessage(str(data.get("kind", "json")), data))
        if data.get("kind") == "heartbeat" and data.get("source") == "noita":
            self._ready.set()
        elif data.get("kind") == "bridge_reply" and data.get("id") in self._replies:
            self._replies[str(data["id"])].put(str(data.get("value", "")))

    def _maybe_reply(self, text: str) -> None:
        if not text.startswith(_REPLY_PREFIX):
            return
        rid, value = text[len(_REPLY_PREFIX):].split("|", 1)
        if rid in self._replies:
            self._replies[rid].put(value)

    @staticmethod
    def _body(lua: str) -> str:
        body = lua.strip()
        return re.sub(r"^return\s+", "", body, count=1)

    @classmethod
    def _wrap_scalar(cls, lua: str) -> str:
        body = cls._body(lua)
        return (
            'local __bm_value = tostring((function() return '
            f'{body} end)())\n'
            f'print("{_REPLY_PREFIX}' + '{rid}|" .. __bm_value)'
        )

    @classmethod
    def _wrap_vec2(cls, lua: str) -> str:
        body = cls._body(lua)
        return (
            'local __bm_x, __bm_y = (function() return '
            f'{body} end)()\n'
            f'print("{_REPLY_PREFIX}'
            + '{rid}|" .. tostring(__bm_x) .. "," .. tostring(__bm_y))'
        )


session = NoitaWsSession()
