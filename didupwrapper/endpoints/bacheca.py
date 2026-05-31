"""Endpoint bacheca (comunicazioni e file per l'alunno)."""

from __future__ import annotations

from . import BaseEndpoint
from ..models import ComunicazioneBacheca, FileBachecaAlunno

__all__ = ["BachecaEndpoint"]


class BachecaEndpoint(BaseEndpoint):
    """Accesso alle comunicazioni di bacheca e ai file dedicati all'alunno."""

    async def lista(self, *, forza_refresh: bool = False) -> list[ComunicazioneBacheca]:
        """Tutte le comunicazioni di bacheca."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.bacheca

    async def da_leggere(self) -> list[ComunicazioneBacheca]:
        """Comunicazioni con presa visione richiesta e non ancora data."""
        return [c for c in await self.lista() if c.da_leggere]

    async def con_allegati(self) -> list[ComunicazioneBacheca]:
        """Comunicazioni che includono almeno un allegato."""
        return [c for c in await self.lista() if c.lista_allegati]

    async def per_categoria(self, categoria: str) -> list[ComunicazioneBacheca]:
        """Comunicazioni di una specifica categoria."""
        cat = categoria.casefold()
        return [c for c in await self.lista() if c.categoria.casefold() == cat]

    async def file_alunno(
        self, *, forza_refresh: bool = False
    ) -> list[FileBachecaAlunno]:
        """File pubblicati nella bacheca personale dell'alunno."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.bacheca_alunno
