# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single yaml+env loader for Clermes configuration.

Path resolution
---------------
``clermes_home()`` is the canonical accessor for the Clermes home directory.
It reads ``$CLERMES_HOME`` and falls back to ``~/.clermes``. Every other module
that needs the home path imports from here.

Environment variable overrides
-------------------------------
Any scalar setting can be overridden with an env var of the form
``CLERMES_<UPPER_SNAKE_PATH>`` where the path separates YAML levels with ``_``.
Examples:

    CLERMES_DISPATCH_TMUX_WIDTH=240      overrides dispatch.tmux_width
    CLERMES_DISPATCH_TMUX_HEIGHT=60      overrides dispatch.tmux_height
    CLERMES_DISPATCH_ANNOUNCE_GRACE_SECONDS=5
    CLERMES_DISPATCH_CONTEXT_COMPACT_THRESHOLD=0.80
    CLERMES_INSTANCE_PRINCIPAL=operator

Env overrides apply to all ``dispatch.*`` scalars and ``instance.principal``.
Overrides of nested lists (outbound.unannounced_allowed, etc.) are not
supported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def clermes_home() -> Path:
    """Return the Clermes home directory, honoring $CLERMES_HOME."""
    return Path(os.environ.get("CLERMES_HOME") or (Path.home() / ".clermes"))


def config_path() -> Path:
    """Return the canonical path to config.yaml."""
    return clermes_home() / "config.yaml"


@dataclass
class InstanceSettings:
    name: str = ""
    principal: str = ""
    description: str = ""


@dataclass
class PathSettings:
    home: str = ""
    registry: str = ""
    protocol: str = ""
    workers: str = ""
    logs: str = ""
    done: str = ""
    disputes: str = ""
    announcing: str = ""
    halt: str = ""
    locks: str = ""


@dataclass
class DispatchSettings:
    tmux_width: int = 200
    tmux_height: int = 50
    announce_grace_seconds: int = 10
    context_compact_threshold: float = 0.70


@dataclass
class RoutingSettings:
    default_worker: Optional[str] = None
    rules: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class OutboundSettings:
    email: str = "orchestrator_only"
    sms: str = "orchestrator_only"
    agency_contact: str = "orchestrator_only"
    unannounced_allowed: List[str] = field(default_factory=list)
    announce_required: List[str] = field(default_factory=list)


@dataclass
class ObservabilitySettings:
    telegram: Dict[str, Any] = field(default_factory=dict)
    log_retention_days: int = 30


@dataclass
class Settings:
    instance: InstanceSettings = field(default_factory=InstanceSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    dispatch: DispatchSettings = field(default_factory=DispatchSettings)
    routing: RoutingSettings = field(default_factory=RoutingSettings)
    outbound: OutboundSettings = field(default_factory=OutboundSettings)
    observability: ObservabilitySettings = field(default_factory=ObservabilitySettings)


def _apply_env_overrides(settings: Settings) -> None:
    """Apply CLERMES_* environment variable overrides to scalar fields."""
    dispatch_map = {
        "CLERMES_DISPATCH_TMUX_WIDTH": ("dispatch", "tmux_width", int),
        "CLERMES_DISPATCH_TMUX_HEIGHT": ("dispatch", "tmux_height", int),
        "CLERMES_DISPATCH_ANNOUNCE_GRACE_SECONDS": ("dispatch", "announce_grace_seconds", int),
        "CLERMES_DISPATCH_CONTEXT_COMPACT_THRESHOLD": ("dispatch", "context_compact_threshold", float),
        "CLERMES_INSTANCE_PRINCIPAL": ("instance", "principal", str),
    }
    for env_key, (group, attr, coerce) in dispatch_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            try:
                setattr(getattr(settings, group), attr, coerce(val))
            except (ValueError, TypeError):
                pass


def load_settings() -> Settings:
    """Read config.yaml and return a populated Settings instance.

    Missing fields get sensible defaults. Environment variable overrides
    are applied after file loading.
    """
    path = config_path()
    raw: Dict[str, Any] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    settings = Settings()

    inst = raw.get("instance") or {}
    settings.instance = InstanceSettings(
        name=str(inst.get("name") or ""),
        principal=str(inst.get("principal") or ""),
        description=str(inst.get("description") or ""),
    )

    paths = raw.get("paths") or {}
    settings.paths = PathSettings(
        home=str(paths.get("home") or ""),
        registry=str(paths.get("registry") or ""),
        protocol=str(paths.get("protocol") or ""),
        workers=str(paths.get("workers") or ""),
        logs=str(paths.get("logs") or ""),
        done=str(paths.get("done") or ""),
        disputes=str(paths.get("disputes") or ""),
        announcing=str(paths.get("announcing") or ""),
        halt=str(paths.get("halt") or ""),
        locks=str(paths.get("locks") or ""),
    )

    disp = raw.get("dispatch") or {}
    settings.dispatch = DispatchSettings(
        tmux_width=int(disp.get("tmux_width") or 200),
        tmux_height=int(disp.get("tmux_height") or 50),
        announce_grace_seconds=int(disp.get("announce_grace_seconds") or 10),
        context_compact_threshold=float(disp.get("context_compact_threshold") or 0.70),
    )

    routing = raw.get("routing") or {}
    rules_raw = routing.get("rules") or {}
    rules: Dict[str, List[str]] = {}
    for worker, kws in rules_raw.items():
        if isinstance(kws, list):
            rules[worker] = [str(k) for k in kws]
    settings.routing = RoutingSettings(
        default_worker=str(routing["default_worker"]) if routing.get("default_worker") else None,
        rules=rules,
    )

    outbound = raw.get("outbound") or {}
    settings.outbound = OutboundSettings(
        email=str(outbound.get("email") or "orchestrator_only"),
        sms=str(outbound.get("sms") or "orchestrator_only"),
        agency_contact=str(outbound.get("agency_contact") or "orchestrator_only"),
        unannounced_allowed=list(outbound.get("unannounced_allowed") or []),
        announce_required=list(outbound.get("announce_required") or []),
    )

    obs = raw.get("observability") or {}
    settings.observability = ObservabilitySettings(
        telegram=dict(obs.get("telegram") or {}),
        log_retention_days=int(obs.get("log_retention_days") or 30),
    )

    _apply_env_overrides(settings)
    return settings
