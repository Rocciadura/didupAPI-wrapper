"""Voti, con filtri per materia, periodo e tipo di prova."""

from __future__ import annotations

from . import BaseEndpoint
from ..models import Voto

__all__ = ["VotiEndpoint"]


class VotiEndpoint(BaseEndpoint):
    """Accesso ai voti dell'alunno."""

    async def lista(self, *, forza_refresh: bool = False) -> list[Voto]:
        """Restituisce tutti i voti."""
        dashboard = await self._dashboard(forza_refresh=forza_refresh)
        return dashboard.voti

    async def per_materia(self, pk_materia: str) -> list[Voto]:
        """Voti relativi a una specifica materia (per chiave primaria)."""
        return [v for v in await self.lista() if v.pk_materia == pk_materia]

    async def per_periodo(self, pk_periodo: str) -> list[Voto]:
        """Voti relativi a uno specifico periodo (quadrimestre/trimestre)."""
        return [v for v in await self.lista() if v.pk_periodo == pk_periodo]

    async def scritti(self) -> list[Voto]:
        """Solo i voti scritti (``codVotoPratico == "S"``)."""
        return [v for v in await self.lista() if v.is_scritto]

    async def orali(self) -> list[Voto]:
        """Solo i voti orali (``codVotoPratico == "N"``)."""
        return [v for v in await self.lista() if v.is_orale]

    async def media_per_materia(self, pk_materia: str) -> float | None:
        """La media semplice dei voti di una materia.

        Conta solo i voti che hanno un valore numerico e che fanno media
        (quelli segnati "fa meno media" restano fuori). Se non ce n'è
        nessuno restituisce ``None``.
        """
        valori = [
            v.valore
            for v in await self.per_materia(pk_materia)
            if v.valore is not None and not v.fa_meno_media
        ]
        if not valori:
            return None
        return sum(valori) / len(valori)
