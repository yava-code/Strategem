import argparse
import json
import socket
import struct
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

# =====================================================================
# Design Pattern: Strategy Pattern for Telemetry Interception
# The Harvester (Context) drives one of three TelemetryStrategy backends.
# Raw samples are funnelled through a single SchemaClassifier so every
# strategy emits an identical state_map.json contract.
# =====================================================================

ACTION_BINDINGS = ["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT", "IDLE"]


def _role_from_key(key: str) -> str:
    """Heuristic role tagging used by the classifier and the env compiler."""
    k = key.lower()
    if "health" in k or "hp" in k:
        return "health"
    if "tick" in k or "time" in k or "timer" in k or "frame" in k:
        return "time"
    if k.endswith("_x") or k.endswith("_y") or "pos" in k or "coord" in k:
        return "coordinate"
    return "scalar"


class SchemaClassifier:
    """
    Schema Classifier node from the discovery pipeline.

    Ingests raw telemetry frames (flat dicts of name->value) sampled from any
    interception strategy and infers a normalized state-variable contract:
    type, observed min/max, semantic role, importance, and the access metadata
    (memory offset or JSON path) needed to re-read the value at runtime.
    """
    def __init__(self):
        self.samples: List[Dict[str, float]] = []
        self._access_meta: Dict[str, Dict[str, Any]] = {}

    def observe(self, frame: Dict[str, Any], access_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        numeric = {k: float(v) for k, v in frame.items() if isinstance(v, (int, float))}
        if numeric:
            self.samples.append(numeric)
        if access_meta:
            self._access_meta.update(access_meta)

    def classify(self) -> Dict[str, Dict[str, Any]]:
        if not self.samples:
            return {}

        keys = sorted({k for frame in self.samples for k in frame})
        state_vars: Dict[str, Dict[str, Any]] = {}
        for key in keys:
            series = [frame[key] for frame in self.samples if key in frame]
            lo, hi = min(series), max(series)
            # Pad a flat series so the normalizer never divides by zero.
            if hi - lo < 1e-6:
                hi = lo + max(1.0, abs(lo))
            role = _role_from_key(key)
            importance = 1.0 if role in ("coordinate", "health") else 0.5
            spec = {
                "type": "float",
                "min": round(lo, 4),
                "max": round(hi, 4),
                "role": role,
                "importance": importance,
                "normalize": {"method": "min_max", "low": round(lo, 4), "high": round(hi, 4)},
            }
            spec.update(self._access_meta.get(key, {}))
            state_vars[key] = spec
        return state_vars


class TelemetryStrategy(ABC):
    """Abstract base class defining the state extraction contract."""
    @abstractmethod
    def discover_telemetry(self, target: str) -> Dict[str, Any]:
        """Inspect the target and return a mapping of discovered state variables."""

    @staticmethod
    def _assemble(target: str, state_vars: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "game_name": target,
            "observation_dimensions": len(state_vars),
            "state_variables": state_vars,
            "actions": {
                "discrete_actions_count": len(ACTION_BINDINGS),
                "bindings": list(ACTION_BINDINGS),
            },
        }


# ---------------------------------------------------------------------
# Strategy 1: Frida Dynamic Injection Hooks
# ---------------------------------------------------------------------
class FridaHookingStrategy(TelemetryStrategy):
    """
    Hooks into game executables using frida-python to intercept native
    method calls (UnityEngine.Transform::get_position, Unreal AActor::GetActorLocation)
    and stream the float fields read off the instance pointer.
    """
    # Offsets are the Transform field layout used by the injected reader below.
    FIELD_OFFSETS = {
        "frida_agent_x": 16,
        "frida_agent_y": 20,
        "frida_player_x": 24,
        "frida_player_y": 28,
        "frida_health": 48,
    }

    FRIDA_JS = """
    rpc.exports = {
        hookEngineTransform: function(moduleName, offsetAddress) {
            var baseAddress = Module.findBaseAddress(moduleName);
            if (baseAddress === null) {
                return { "status": "ERROR", "message": "Base module not found" };
            }
            var targetPtr = baseAddress.add(offsetAddress);
            Interceptor.attach(targetPtr, {
                onEnter: function(args) { this.transformInstance = args[0]; },
                onLeave: function(retval) {
                    if (this.transformInstance) {
                        try {
                            send({
                                type: "telemetry",
                                frida_agent_x: Memory.readFloat(this.transformInstance.add(16)),
                                frida_agent_y: Memory.readFloat(this.transformInstance.add(20)),
                                frida_player_x: Memory.readFloat(this.transformInstance.add(24)),
                                frida_player_y: Memory.readFloat(this.transformInstance.add(28)),
                                frida_health:  Memory.readFloat(this.transformInstance.add(48))
                            });
                        } catch (e) { /* page not mapped, skip frame */ }
                    }
                }
            });
            return { "status": "SUCCESS", "message": "Hooks injected at offset: " + offsetAddress };
        }
    };
    """

    def discover_telemetry(self, target: str) -> Dict[str, Any]:
        print(f"[Strategy: Frida] Attempting dynamic library injection into process: '{target}'...")
        classifier = SchemaClassifier()
        captured = 0

        try:
            import frida
            print("[Strategy: Frida] Frida bindings loaded. Attaching to runtime...")
            session = frida.attach(target)
            script = session.create_script(self.FRIDA_JS)

            def on_message(message, _data):
                nonlocal captured
                if message.get("type") == "send":
                    payload = message["payload"]
                    if payload.get("type") == "telemetry":
                        frame = {k: v for k, v in payload.items() if k != "type"}
                        classifier.observe(frame, self._access_meta())
                        captured += 1

            script.on("message", on_message)
            script.load()
            # IL2CPP modules vary; the caller wires the real offset via RPC.
            script.exports_sync.hook_engine_transform("GameAssembly.dll", 0x0)
            time.sleep(2.0)
            session.detach()
            print(f"[Strategy: Frida] Captured {captured} live transform frames.")
        except ImportError:
            print("[Strategy: Frida] WARNING: 'frida' not installed. Emitting layout-based fallback schema.")
        except Exception as e:
            print(f"[Strategy: Frida] WARNING: Could not hook '{target}' ({e}). Emitting fallback schema.")

        state_vars = classifier.classify() or self._fallback_schema()
        return self._assemble(target, state_vars)

    def _access_meta(self) -> Dict[str, Dict[str, Any]]:
        return {k: {"offset": hex(off), "source": "frida"} for k, off in self.FIELD_OFFSETS.items()}

    def _fallback_schema(self) -> Dict[str, Dict[str, Any]]:
        meta = self._access_meta()
        vars_: Dict[str, Dict[str, Any]] = {}
        for key in self.FIELD_OFFSETS:
            role = _role_from_key(key)
            vars_[key] = {
                "type": "float", "min": 0.0, "max": 100.0, "role": role,
                "importance": 1.0 if role in ("coordinate", "health") else 0.6,
                "normalize": {"method": "min_max", "low": 0.0, "high": 100.0},
                **meta[key],
            }
        return vars_


# ---------------------------------------------------------------------
# Strategy 2: Memory scraping via Pymem
# ---------------------------------------------------------------------
class MemoryScrapingStrategy(TelemetryStrategy):
    """
    Attaches to Windows game processes with Pymem, runs a float signature scan,
    and treats the most frequently mutating addresses as candidate state slots.
    """
    CANDIDATES = {
        "pymem_agent_x": 0x0,
        "pymem_agent_y": 0x4,
        "pymem_player_hp": 0x10,
        "pymem_step_timer": 0x14,
    }

    def discover_telemetry(self, target: str) -> Dict[str, Any]:
        print(f"[Strategy: Pymem] Scanning RAM partitions for process: '{target}'...")
        classifier = SchemaClassifier()
        base_addr: Optional[int] = None

        try:
            import pymem
            from pymem.pattern import pattern_scan_all

            pm = pymem.Pymem(target)
            print(f"[Strategy: Pymem] Attached handle {pm.process_handle}. Scanning heap segments...")
            # 10.0f little-endian signature; brackets stay literal bytes.
            pattern = b"\x00\x00\x20\x41"
            hit = pattern_scan_all(pm.process_handle, pattern, return_multiple=False)
            if hit:
                base_addr = hit
                # Two passes so the classifier sees a range, not a constant.
                for _ in range(8):
                    frame = {name: pm.read_float(base_addr + off) for name, off in self.CANDIDATES.items()}
                    classifier.observe(frame, self._access_meta(base_addr))
                    time.sleep(0.05)
                print(f"[Strategy: Pymem] Resolved base pointer 0x{base_addr:x}; sampled live floats.")
        except ImportError:
            print("[Strategy: Pymem] WARNING: 'pymem' not installed. Emitting offset-based fallback schema.")
        except Exception as e:
            print(f"[Strategy: Pymem] WARNING: Could not read RAM for '{target}' ({e}). Emitting fallback schema.")

        state_vars = classifier.classify() or self._fallback_schema()
        return self._assemble(target, state_vars)

    def _access_meta(self, base: int) -> Dict[str, Dict[str, Any]]:
        return {name: {"offset": hex(base + off), "source": "pymem"} for name, off in self.CANDIDATES.items()}

    def _fallback_schema(self) -> Dict[str, Dict[str, Any]]:
        vars_: Dict[str, Dict[str, Any]] = {}
        for name, off in self.CANDIDATES.items():
            role = _role_from_key(name)
            hi = 300.0 if role == "time" else 100.0
            vars_[name] = {
                "type": "float", "min": 0.0, "max": hi, "role": role,
                "importance": 1.0 if role in ("coordinate", "health") else 0.5,
                "normalize": {"method": "min_max", "low": 0.0, "high": hi},
                "offset": hex(off), "source": "pymem",
            }
        return vars_


# ---------------------------------------------------------------------
# Strategy 3: Network proxy WebSocket sniffer
# ---------------------------------------------------------------------
class NetworkProxyStrategy(TelemetryStrategy):
    """
    Intercepts local WebSocket telemetry. Prefers a passive Scapy sniff; falls
    back to a short-lived loopback proxy on :8080 that decodes RFC 6455 frames
    and flattens nested JSON state objects into observation channels.
    """
    PROXY_PORT = 8080
    SNIFF_TIMEOUT = 1.5

    def discover_telemetry(self, target: str) -> Dict[str, Any]:
        print(f"[Strategy: Network] Intercepting WebSocket telemetry for: '{target}'...")
        classifier = SchemaClassifier()

        self._scapy_sniff(classifier)
        if not classifier.samples:
            self._loopback_capture(classifier)

        state_vars = classifier.classify() or self._fallback_schema()
        return self._assemble(target, state_vars)

    def _scapy_sniff(self, classifier: SchemaClassifier) -> None:
        try:
            from scapy.all import sniff, Raw  # noqa: F401
        except ImportError:
            print("[Strategy: Network] Scapy unavailable; skipping passive sniff.")
            return
        try:
            from scapy.all import sniff, Raw

            def handle(pkt):
                if pkt.haslayer(Raw):
                    frame = self._decode_ws_frame(bytes(pkt[Raw].load))
                    if frame:
                        classifier.observe(self._flatten(frame), self._access_meta(frame))

            print(f"[Strategy: Network] Passive Scapy sniff on loopback ({self.SNIFF_TIMEOUT}s)...")
            sniff(filter="tcp port 8080", prn=handle, store=False, timeout=self.SNIFF_TIMEOUT)
        except Exception as e:
            print(f"[Strategy: Network] Sniff fell back ({e}).")

    def _loopback_capture(self, classifier: SchemaClassifier) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self.PROXY_PORT))
            srv.listen(1)
            srv.settimeout(self.SNIFF_TIMEOUT)
            print(f"[Strategy: Network] Proxy listening on :{self.PROXY_PORT} for one client...")
            conn, _addr = srv.accept()
            with conn:
                conn.settimeout(self.SNIFF_TIMEOUT)
                buf = conn.recv(65536)
                frame = self._decode_ws_frame(buf)
                if frame:
                    classifier.observe(self._flatten(frame), self._access_meta(frame))
                    print("[Strategy: Network] Decoded one WS state frame from proxy client.")
        except (socket.timeout, OSError):
            print("[Strategy: Network] No live client connected; emitting fallback schema.")
        finally:
            srv.close()

    @staticmethod
    def _decode_ws_frame(buf: bytes) -> Optional[Dict[str, Any]]:
        """Minimal RFC 6455 text-frame decoder. Returns parsed JSON payload."""
        if len(buf) < 2:
            return None
        try:
            second = buf[1]
            masked = second & 0x80
            length = second & 0x7F
            idx = 2
            if length == 126:
                length = struct.unpack(">H", buf[idx:idx + 2])[0]
                idx += 2
            elif length == 127:
                length = struct.unpack(">Q", buf[idx:idx + 8])[0]
                idx += 8
            if masked:
                mask = buf[idx:idx + 4]
                idx += 4
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(buf[idx:idx + length]))
            else:
                payload = buf[idx:idx + length]
            text = payload.decode("utf-8", errors="ignore").strip()
            if text.startswith("{"):
                return json.loads(text)
        except (struct.error, json.JSONDecodeError, IndexError):
            return None
        return None

    @staticmethod
    def _flatten(obj: Dict[str, Any], prefix: str = "net") -> Dict[str, float]:
        flat: Dict[str, float] = {}
        for k, v in obj.items():
            key = f"{prefix}_{k}"
            if isinstance(v, dict):
                flat.update(NetworkProxyStrategy._flatten(v, key))
            elif isinstance(v, (int, float)):
                flat[key] = float(v)
        return flat

    @staticmethod
    def _access_meta(obj: Dict[str, Any], prefix: str = "net") -> Dict[str, Dict[str, Any]]:
        meta: Dict[str, Dict[str, Any]] = {}
        for k, v in obj.items():
            key = f"{prefix}_{k}"
            if isinstance(v, dict):
                meta.update(NetworkProxyStrategy._access_meta(v, key))
            elif isinstance(v, (int, float)):
                meta[key] = {"json_path": key.replace("_", "."), "source": "network"}
        return meta

    def _fallback_schema(self) -> Dict[str, Dict[str, Any]]:
        layout = {
            "net_x": 1.0, "net_y": 1.0, "net_player_x": 0.8, "net_player_y": 0.8,
            "net_health": 1.0, "net_tick": 0.5,
        }
        vars_: Dict[str, Dict[str, Any]] = {}
        for name, imp in layout.items():
            role = _role_from_key(name)
            hi = 500.0 if role == "time" else 100.0
            vars_[name] = {
                "type": "float", "min": 0.0, "max": hi, "role": role, "importance": imp,
                "normalize": {"method": "min_max", "low": 0.0, "high": hi},
                "json_path": name.replace("net_", "state."), "source": "network",
            }
        return vars_


# =====================================================================
# Context: Orchestrator Client
# =====================================================================

class TelemetryHarvester:
    """Central orchestrator that drives a strategy and persists the schema."""
    def __init__(self, strategy: TelemetryStrategy):
        self.strategy = strategy

    def execute_discovery(self, target: str, output_path: str) -> Dict[str, Any]:
        state_map = self.strategy.discover_telemetry(target)
        with open(output_path, "w") as f:
            json.dump(state_map, f, indent=4)
        print(f"[Harvester] Discovered telemetry schema ({state_map['observation_dimensions']} dims) "
              f"saved to: '{output_path}'")
        return state_map


def main():
    parser = argparse.ArgumentParser(description="Auto-Discovery Telemetry Scraper & Hook Injector")
    parser.add_argument("--strategy", choices=["frida", "memory", "network"], default="network",
                        help="frida (hook injection), memory (RAM scraper), network (WS sniffer)")
    parser.add_argument("--target", default="rpg_game_instance",
                        help="Target process name, PID or WebSocket endpoint")
    parser.add_argument("--output", default="state_map.json", help="Output path for state_map.json")
    args = parser.parse_args()

    strategy = {
        "frida": FridaHookingStrategy,
        "memory": MemoryScrapingStrategy,
        "network": NetworkProxyStrategy,
    }[args.strategy]()

    TelemetryHarvester(strategy).execute_discovery(args.target, args.output)


if __name__ == "__main__":
    main()
