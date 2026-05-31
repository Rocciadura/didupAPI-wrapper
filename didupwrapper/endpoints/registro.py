"""Endpoint registro di classe (lezioni, attività, compiti)."""

from __future__ import annotations

from . import BaseEndpoint
from ..models import Compito, RegistroLezione

__all__ = ["RegistroEndpoint"]


class RegistroEndpoint(BaseEndpoint):
    """Accesso alle lezioni del registro di classe."""

    async def lista(self, *, forza_refresh: bool = False) -> list[RegistroLezione]:
        """Tutte le lezioni del registro."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.registro

    async def del_giorno(self, dat_giorno: str) -> list[RegistroLezione]:
        """Lezioni di un dato giorno (formato ``datGiorno`` dell'API)."""
        return [r for r in await self.lista() if r.dat_giorno == dat_giorno]

    async def per_materia(self, pk_materia: str) -> list[RegistroLezione]:
        """Lezioni di una specifica materia."""
        return [r for r in await self.lista() if r.pk_materia == pk_materia]

    async def compiti(self) -> list[Compito]:
        """Elenco appiattito di tutti i compiti assegnati nel registro."""
        compiti: list[Compito] = []
        for lezione in await self.lista():
            compiti.extend(lezione.compiti)
        return compiti
