"""Endpoint assenze / appello (assenze, ritardi, uscite)."""

from __future__ import annotations

from . import BaseEndpoint
from ..models import EventoAppello

__all__ = ["AssenzeEndpoint"]


class AssenzeEndpoint(BaseEndpoint):
    """Accesso agli eventi di appello: assenze, ritardi e uscite anticipate."""

    async def lista(self, *, forza_refresh: bool = False) -> list[EventoAppello]:
        """Tutti gli eventi di appello."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.appello

    async def assenze(self) -> list[EventoAppello]:
        """Solo le assenze (``codEvento == "A"``)."""
        return [e for e in await self.lista() if e.is_assenza]

    async def ritardi(self) -> list[EventoAppello]:
        """Solo i ritardi (``codEvento == "I"``)."""
        return [e for e in await self.lista() if e.is_ritardo]

    async def uscite(self) -> list[EventoAppello]:
        """Solo le uscite anticipate (``codEvento == "U"``)."""
        return [e for e in await self.lista() if e.is_uscita]

    async def da_giustificare(self) -> list[EventoAppello]:
        """Eventi che risultano ancora da giustificare."""
        return [e for e in await self.lista() if e.da_giustificare]
