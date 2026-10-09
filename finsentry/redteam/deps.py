"""
What an execution needs from the running gateway: the same rail objects real
requests use, not copies. The gateway builds this lazily per call (see
finsentry/gateway/main.py) so a rail that failed to initialise shows up as None
and the executor reports it as unavailable instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from finsentry.gateway.rails import InputRailsAdapter
from finsentry.rails.output.faithfulness import FaithfulnessRail
from finsentry.rails.output.guardrails_schema import SchemaEnforcementRail
from finsentry.rails.output.regulated_phrases import RegulatedPhraseRail
from finsentry.rails.retrieval.rail import RetrievalRail


class ScenarioSetupError(RuntimeError):
    """The harness could not build the scenario's input. Recorded as execution_failed,
    because nothing was learned about any defense. Raise it only before anything is sent:
    the runner treats it as proof that no gateway request went out."""


@dataclass
class Deps:
    app: FastAPI
    database_url: str
    input_adapter: InputRailsAdapter | None
    retrieval_rail: RetrievalRail | None
    schema_rail: SchemaEnforcementRail | None
    phrase_rail: RegulatedPhraseRail | None
    faithfulness_rail: FaithfulnessRail | None
    # The gateway's existing client for the dashboard trace routes.
    metrics_client: httpx.AsyncClient | None
