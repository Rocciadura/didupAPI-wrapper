"""Endpoint promemoria (annotazioni dei docenti)."""

from __future__ import annotations

from . import BaseEndpoint
from ..models import Promemoria

__all__ = ["PromemoriaEndpoint"]


class PromemoriaEndpoint(BaseEndpoint):
    """Accesso ai promemoria/annotazioni inseriti dai docenti."""

    async def lista(self, *, forza_refresh: bool = False) -> list[Promemoria]:
        """Tutti i promemoria."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.promemoria

    async def visibili_famiglia(self) -> list[Promemoria]:
        """Solo i promemoria visibili alla famiglia."""
        return [p for p in await self.lista() if p.flg_visibile_famiglia]

    async def del_giorno(self, dat_giorno: str) -> list[Promemoria]:
        """Promemoria di un dato giorno."""
        return [p for p in await self.lista() if p.dat_giorno == dat_giorno]
