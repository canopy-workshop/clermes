# SPDX-License-Identifier: AGPL-3.0-or-later
"""Worker routing based on keyword rules in config.yaml.

The config.yaml carries a ``routing.rules`` map of worker name to keyword list.
This module consumes that map and ranks workers by keyword matches against a
task description.

Ambiguous results (two or more workers tied for the best score with score > 0)
are returned with ``ambiguous=True`` so the caller can surface the tie to the
operator rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import load_settings


def routing_rules() -> Dict[str, List[str]]:
    """Return the routing rules as a dict of worker -> lowercased keywords."""
    settings = load_settings()
    out: Dict[str, List[str]] = {}
    for worker, kws in settings.routing.rules.items():
        if isinstance(kws, list):
            out[worker] = [str(k).lower() for k in kws]
    return out


def default_worker() -> Optional[str]:
    """Return the configured default worker name, or None if not set."""
    settings = load_settings()
    val = settings.routing.default_worker
    return str(val) if val else None


@dataclass
class RouteResult:
    worker: Optional[str]
    score: int
    ambiguous: bool
    candidates: Dict[str, int] = field(default_factory=dict)
    used_default: bool = False

    def as_dict(self) -> Dict:
        return {
            "worker": self.worker,
            "score": self.score,
            "ambiguous": self.ambiguous,
            "candidates": self.candidates,
            "used_default": self.used_default,
        }


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]+")


def pick(task: str, fallback_to_default: bool = True) -> RouteResult:
    """Score workers against the task by keyword match.

    Returns the best-scoring worker, or signals ``ambiguous=True`` when two or
    more workers tie at the top score with score > 0. When no keyword matches
    at all, falls back to ``routing.default_worker`` if available.
    """
    rules = routing_rules()
    words = {w.lower() for w in _WORD_RE.findall(task or "")}
    scores: Dict[str, int] = {}
    for worker, kws in rules.items():
        score = sum(1 for kw in kws if kw in words)
        if score:
            scores[worker] = score
    dw = default_worker() if fallback_to_default else None
    if not scores:
        if dw:
            return RouteResult(
                worker=dw,
                score=0,
                ambiguous=False,
                candidates={},
                used_default=True,
            )
        return RouteResult(worker=None, score=0, ambiguous=False, candidates={})
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top_score = ranked[0][1]
    tied = [w for w, s in ranked if s == top_score]
    if len(tied) > 1:
        return RouteResult(
            worker=None,
            score=top_score,
            ambiguous=True,
            candidates=dict(ranked),
        )
    return RouteResult(
        worker=tied[0],
        score=top_score,
        ambiguous=False,
        candidates=dict(ranked),
    )
