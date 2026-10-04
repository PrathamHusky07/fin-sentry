"""
Shared process state for the MCP server: one RisingWavePool instance,
opened/closed by server.py's lifespan, imported by any tool module that
needs RisingWave access. A single module (rather than defining the pool in
server.py) avoids a circular import between server.py and the tool modules
it registers.
"""
from __future__ import annotations

from finsentry.risingwave.dao import RisingWavePool

dao = RisingWavePool()
