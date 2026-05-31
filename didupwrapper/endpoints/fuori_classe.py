"""Endpoint "fuori classe" (eventi fuori dall'aula / DAD)."""

from __future__ import annotations

from . import BaseEndpoint
from ..models import FuoriClasse

__all__ = ["FuoriClasseEndpoint"]


class FuoriClasseEndpoint(BaseEndpoint):
    """Accesso agli eventi "fuori classe" dell'alunno."""

    async def lista(self, *, forza_refresh: bool = False) -> list[FuoriClasse]:
        """Tutti gli eventi fuori classe."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.fuori_classe

    async def online(self) -> list[FuoriClasse]:
        """Solo gli eventi con frequenza online (DAD)."""
        return [f for f in await self.lista() if f.frequenza_on_line]

    async def del_giorno(self, dat_evento: str) -> list[FuoriClasse]:
        """Eventi fuori classe di un dato giorno."""
        return [f for f in await self.lista() if f.dat_evento == dat_evento]
