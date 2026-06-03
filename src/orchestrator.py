import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src.connectors.base import Connector, GameTransport
from src.connectors.dotnet_connector import DotNetConnector
from src.connectors.lua_connector import LuaBridgeConnector
from src.connectors.ghidra_connector import GhidraConnector
from src.connectors.vision_connector import VisionConnector

# =====================================================================
# Integration Orchestrator.
# Walks the connector ladder in reliability order, picks the first that detects
# the target, discovers its schema, and hands back a ready transport. Vision is
# the universal last resort, so it always terminates the ladder.
# =====================================================================


class IntegrationOrchestrator:
    def __init__(self, host: str = "127.0.0.1", port: int = 50545,
                 ghidra_url: str = "http://127.0.0.1:8080"):
        # Order matters: cleanest/most reliable connector wins.
        self.ladder: List[Connector] = [
            DotNetConnector(host=host, port=port),
            LuaBridgeConnector(host=host, port=port),
            GhidraConnector(mcp_url=ghidra_url, host=host, port=port),
            VisionConnector(host=host, port=port),
        ]

    def select(self, target: str) -> Connector:
        for connector in self.ladder:
            try:
                if connector.detect(target):
                    print(f"[Orchestrator] Engine matched -> connector '{connector.name}'")
                    return connector
            except Exception as e:
                print(f"[Orchestrator] '{connector.name}' detect error ({e}); trying next rung.")
        # VisionConnector.detect only fails if the path doesn't exist.
        raise RuntimeError(f"No connector could handle target: {target}")

    def discover(self, target: str, output_path: str = "state_map.json") -> Tuple[Connector, Dict[str, Any]]:
        connector = self.select(target)
        schema = connector.discover_schema(target)
        with open(output_path, "w") as f:
            json.dump(schema, f, indent=4)
        print(f"[Orchestrator] {connector.name}: {schema['observation_dimensions']} obs dims "
              f"-> '{output_path}' (engine: {schema.get('engine')})")
        return connector, schema

    def open_transport(self, target: str, schema: Dict[str, Any],
                       connector: Optional[Connector] = None) -> GameTransport:
        connector = connector or self.select(target)
        return connector.open_transport(target, schema)


def main():
    parser = argparse.ArgumentParser(description="Bridge-Maker Integration Orchestrator")
    parser.add_argument("--target", required=True, help="Game install dir or executable path")
    parser.add_argument("--output", default="state_map.json", help="state_map.json output path")
    parser.add_argument("--port", type=int, default=50545, help="Transport port")
    args = parser.parse_args()

    orch = IntegrationOrchestrator(port=args.port)
    if not os.path.exists(args.target):
        raise FileNotFoundError(f"Target not found: {args.target}")
    orch.discover(args.target, args.output)


if __name__ == "__main__":
    main()
