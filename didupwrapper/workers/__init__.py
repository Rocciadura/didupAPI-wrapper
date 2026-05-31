"""Worker di background per didupwrapper."""

from __future__ import annotations

from .poller import DashboardPoller, EventoPoller

__all__ = ["DashboardPoller", "EventoPoller"]
