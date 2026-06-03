"""Connector ladder for The Bridge-Maker integration orchestrator.

Each connector knows how to (a) discover a game's state schema and (b) hand back
a live GameTransport. The orchestrator picks one per detected engine.
"""
from src.connectors.base import Connector, GameTransport, StateFrame

__all__ = ["Connector", "GameTransport", "StateFrame"]
