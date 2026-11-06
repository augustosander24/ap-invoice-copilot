"""Settings for AP Invoice Copilot, read from the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "").strip() or "http://localhost:11434"
MODEL = os.getenv("MODEL", "").strip() or "llama3.1:8b"

AGENTS = ("po_investigator", "nonpo_investigator", "reply_interpreter", "communicator")

# The most tokens one model call may generate, thinking included (Ollama's num_predict); the call stops there.
# Each cap is above the longest reply in the saved runs, and the longest saved prompt plus the cap fits in
# num_ctx 8192, so a capped call never runs past its context.
MAX_TOKENS = {"po_investigator": 4096, "nonpo_investigator": 4096, "reply_interpreter": 4096, "communicator": 512}
# THINK_<AGENT> in .env: "on" or "off" sends Ollama's think setting; blank sends nothing (the model's default).
THINK = {"on": True, "off": False, "": None}


def _known(agent: str) -> None:
    """Stop on an agent name that isn't one of AGENTS."""
    if agent not in AGENTS:
        raise ValueError(f"Unknown agent {agent!r}; expected one of {', '.join(AGENTS)}")


def get_model(agent: str) -> str:
    """Return the model for one agent: its override when set, otherwise MODEL."""
    _known(agent)
    return os.getenv(f"MODEL_{agent.upper()}", "").strip() or MODEL


def get_max_tokens(agent: str) -> int:
    """The output cap for one agent."""
    _known(agent)
    return MAX_TOKENS[agent]


def get_think(agent: str) -> bool | None:
    """The reasoning setting for one agent, from THINK_<AGENT>: on (True), off (False), or blank (None: not sent)."""
    _known(agent)
    value = os.getenv(f"THINK_{agent.upper()}", "").strip().lower()
    if value not in THINK:
        raise ValueError(f"THINK_{agent.upper()} must be on, off, or blank, not {value!r}")
    return THINK[value]
