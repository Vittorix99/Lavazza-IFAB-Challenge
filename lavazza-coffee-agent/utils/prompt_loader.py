"""Loader minimale per prompt esterni degli agenti."""

from __future__ import annotations

from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parents[1] / "agent_prompts"


def load_prompt(relative_path: str, fallback: str) -> str:
    """
    Carica un prompt da agent_prompts/.

    Il fallback mantiene gli agenti robusti se un file prompt non e' presente
    in un ambiente locale o durante un merge incompleto.
    """
    path = PROMPT_DIR / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return fallback
