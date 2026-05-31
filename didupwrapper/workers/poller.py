"""Poller che monitora la dashboard e notifica le novità.

Il :class:`DashboardPoller` interroga periodicamente la dashboard, confronta
il risultato con la rilevazione precedente e invoca le callback registrate
per ogni nuovo elemento (nuovi voti, comunicazioni, assenze, ecc.).

Esempio::

    async def on_voti(nuovi):
        for v in nuovi:
            print("Nuovo voto:", v.des_materia, v.cod_codice)

    poller = DashboardPoller(client, intervallo=600, on_nuovi_voti=on_voti)
    await poller.avvia()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Hashable, Sequence, TypeVar

from ..models import (
    ComunicazioneBacheca,
    EventoAppello,
    NotaDisciplinare,
    Promemoria,
    Voto,
)

if TYPE_CHECKING:
    from ..client import DiDUPClient

__all__ = ["DashboardPoller", "EventoPoller"]

logger = logging.getLogger("didupwrapper.poller")

T = TypeVar("T")
# Una callback può essere sync o async; riceve la lista dei nuovi elementi.
Callback = Callable[[list[T]], Awaitable[None] | None]


@dataclass
class EventoPoller:
    """Risultato di un singolo ciclo di polling: cosa è cambiato."""

    nuovi_voti: list[Voto]
    nuove_assenze: list[EventoAppello]
    nuove_comunicazioni: list[ComunicazioneBacheca]
    nuove_note: list[NotaDisciplinare]
    nuovi_promemoria: list[Promemoria]

    @property
    def ha_novita(self) -> bool:
        return any(
            (
                self.nuovi_voti,
                self.nuove_assenze,
                self.nuove_comunicazioni,
                self.nuove_note,
                self.nuovi_promemoria,
            )
        )


class DashboardPoller:
    """Monitora la dashboard a intervalli regolari ed emette eventi di novità."""

    def __init__(
        self,
        client: "DiDUPClient",
        *,
        intervallo: float = 300.0,
        on_nuovi_voti: Callback[Voto] | None = None,
        on_nuove_assenze: Callback[EventoAppello] | None = None,
        on_nuove_comunicazioni: Callback[ComunicazioneBacheca] | None = None,
        on_nuove_note: Callback[NotaDisciplinare] | None = None,
        on_nuovi_promemoria: Callback[Promemoria] | None = None,
        on_evento: Callable[[EventoPoller], Awaitable[None] | None] | None = None,
        emetti_al_primo_giro: bool = False,
    ) -> None:
        if intervallo <= 0:
            raise ValueError("intervallo deve essere > 0")
        self._client = client
        self._intervallo = intervallo
        self._on_nuovi_voti = on_nuovi_voti
        self._on_nuove_assenze = on_nuove_assenze
        self._on_nuove_comunicazioni = on_nuove_comunicazioni
        self._on_nuove_note = on_nuove_note
        self._on_nuovi_promemoria = on_nuovi_promemoria
        self._on_evento = on_evento
        self._emetti_al_primo_giro = emetti_al_primo_giro

        # Insiemi di chiavi già viste, per sezione.
        self._visti: dict[str, set[Hashable]] = {
            "voti": set(),
            "assenze": set(),
            "comunicazioni": set(),
            "note": set(),
            "promemoria": set(),
        }
        self._primo_giro = True
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Controllo del ciclo                                                #
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """Avvia il loop di polling fino a :meth:`ferma`."""
        self._stop.clear()
        logger.info("Poller avviato (intervallo=%ss)", self._intervallo)
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - il loop non deve morire
                logger.exception("Errore durante il ciclo di polling")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._intervallo)
            except asyncio.TimeoutError:
                pass
        logger.info("Poller fermato")

    def stop(self) -> None:
        """Richiede l'arresto del loop di polling."""
        self._stop.set()

    async def tick(self) -> EventoPoller:
        """Esegue un singolo ciclo: scarica la dashboard e calcola le novità."""
        dashboard = await self._client.get_dashboard(forza_refresh=True)

        emetti = self._emetti_al_primo_giro or not self._primo_giro

        nuovi_voti = self._novita("voti", dashboard.voti, _chiave_voto, emetti)
        nuove_assenze = self._novita(
            "assenze", dashboard.appello, _chiave_assenza, emetti
        )
        nuove_comunicazioni = self._novita(
            "comunicazioni", dashboard.bacheca, _chiave_comunicazione, emetti
        )
        nuove_note = self._novita(
            "note", dashboard.note_disciplinari, _chiave_nota, emetti
        )
        nuovi_promemoria = self._novita(
            "promemoria", dashboard.promemoria, _chiave_promemoria, emetti
        )

        self._primo_giro = False

        evento = EventoPoller(
            nuovi_voti=nuovi_voti,
            nuove_assenze=nuove_assenze,
            nuove_comunicazioni=nuove_comunicazioni,
            nuove_note=nuove_note,
            nuovi_promemoria=nuovi_promemoria,
        )

        if evento.ha_novita:
            await self._notifica(evento)
        return evento

    # ------------------------------------------------------------------ #
    # Interni                                                            #
    # ------------------------------------------------------------------ #
    def _novita(
        self,
        sezione: str,
        elementi: Sequence[T],
        chiave: Callable[[T], Hashable],
        emetti: bool,
    ) -> list[T]:
        """Aggiorna l'insieme dei visti e ritorna gli elementi nuovi.

        Al primo giro (se ``emetti`` è False) popola soltanto lo stato senza
        emettere nulla, così da non bombardare di notifiche allo startup.
        """
        visti = self._visti[sezione]
        nuovi: list[T] = []
        for elemento in elementi:
            k = chiave(elemento)
            if k not in visti:
                visti.add(k)
                nuovi.append(elemento)
        return nuovi if emetti else []

    async def _notifica(self, evento: EventoPoller) -> None:
        await self._chiama(self._on_nuovi_voti, evento.nuovi_voti)
        await self._chiama(self._on_nuove_assenze, evento.nuove_assenze)
        await self._chiama(self._on_nuove_comunicazioni, evento.nuove_comunicazioni)
        await self._chiama(self._on_nuove_note, evento.nuove_note)
        await self._chiama(self._on_nuovi_promemoria, evento.nuovi_promemoria)
        if self._on_evento is not None:
            await _maybe_await(self._on_evento(evento))

    @staticmethod
    async def _chiama(callback: Callback[T] | None, elementi: list[T]) -> None:
        if callback is not None and elementi:
            await _maybe_await(callback(elementi))


async def _maybe_await(risultato: Awaitable[None] | None) -> None:
    if asyncio.iscoroutine(risultato):
        await risultato


# --------------------------------------------------------------------------- #
# Funzioni-chiave per il deduplicamento                                        #
# --------------------------------------------------------------------------- #
def _chiave_voto(v: Voto) -> Hashable:
    return (v.dat_evento, v.pk_materia, v.cod_codice, v.cod_voto_pratico, v.valore)


def _chiave_assenza(e: EventoAppello) -> Hashable:
    return (e.dat_evento, e.cod_evento, e.descrizione)


def _chiave_comunicazione(c: ComunicazioneBacheca) -> Hashable:
    return (c.dat_evento, c.autore, c.messaggio)


def _chiave_nota(n: NotaDisciplinare) -> Hashable:
    return (n.dat_giorno, n.docente, n.descrizione)


def _chiave_promemoria(p: Promemoria) -> Hashable:
    return (p.dat_evento, p.des_annotazioni, p.ora_inizio)
