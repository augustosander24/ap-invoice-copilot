"""Settings for AP Invoice Copilot, read from the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "").strip() or "http://localhost:11434"
MODEL = os.getenv("MODEL", "").strip() or "llama3.1:8b"

AGENTS = ("po_investigator", "nonpo_investigator", "reply_interpreter", "communicator")


def get_model(agent: str) -> str:
    """Return the model for one agent: its override when set, otherwise MODEL."""
    if agent not in AGENTS:
        raise ValueError(f"Unknown agent {agent!r}; expected one of {', '.join(AGENTS)}")
    return os.getenv(f"MODEL_{agent.upper()}", "").strip() or MODEL
