"""Test del DashboardPoller con un client finto (niente HTTP)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from didupwrapper import DashboardPoller, DashboardResponse, EventoPoller

from .test_models import DASHBOARD_JSON


class ClientFinto:
    """Restituisce le dashboard di ``risposte`` una dopo l'altra (l'ultima si ripete)."""

    def __init__(self, *risposte: dict[str, Any] | Exception) -> None:
        self.risposte = list(risposte)
        self.chiamate = 0

    async def get_dashboard(self, *, forza_refresh: bool = False) -> DashboardResponse:
        assert forza_refresh
        risposta = self.risposte[min(self.chiamate, len(self.risposte) - 1)]
        self.chiamate += 1
        if isinstance(risposta, Exception):
            raise risposta
        return DashboardResponse.model_validate(risposta)


def _con_voto_in_piu(codice: str) -> dict[str, Any]:
    voto = {**DASHBOARD_JSON["voti"][0], "datEvento": "2026-05-25", "codCodice": codice}
    return {**DASHBOARD_JSON, "voti": [*DASHBOARD_JSON["voti"], voto]}


def test_intervallo_non_valido():
    with pytest.raises(ValueError):
        DashboardPoller(ClientFinto(DASHBOARD_JSON), intervallo=0)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_emetti_al_primo_giro():
    ricevuti: list[Any] = []
    poller = DashboardPoller(
        ClientFinto(DASHBOARD_JSON),  # type: ignore[arg-type]
        on_nuovi_voti=ricevuti.extend,
        emetti_al_primo_giro=True,
    )
    evento = await poller.tick()
    assert evento.ha_novita
    assert len(ricevuti) == len(DASHBOARD_JSON["voti"])

    # Al secondo giro, con la stessa dashboard, non c'è niente di nuovo.
    ricevuti.clear()
    assert not (await poller.tick()).ha_novita
    assert ricevuti == []


@pytest.mark.asyncio
async def test_on_evento_coroutine_chiamata_solo_con_novita():
    eventi: list[EventoPoller] = []

    async def on_evento(evento: EventoPoller) -> None:
        eventi.append(evento)

    client = ClientFinto(DASHBOARD_JSON, DASHBOARD_JSON, _con_voto_in_piu("7"))
    poller = DashboardPoller(client, on_evento=on_evento)  # type: ignore[arg-type]

    await poller.tick()  # primo giro: solo presa nota
    await poller.tick()  # niente di nuovo
    assert eventi == []

    await poller.tick()
    assert len(eventi) == 1
    assert [v.cod_codice for v in eventi[0].nuovi_voti] == ["7"]
    assert eventi[0].nuove_assenze == []


@pytest.mark.asyncio
async def test_start_sopravvive_agli_errori_e_si_ferma():
    client = ClientFinto(DASHBOARD_JSON, RuntimeError("rete giù"), _con_voto_in_piu("6"))
    ricevuti: list[Any] = []
    poller = DashboardPoller(
        client,  # type: ignore[arg-type]
        intervallo=0.01,
        on_nuovi_voti=ricevuti.extend,
    )

    task = asyncio.create_task(poller.start())
    for _ in range(200):
        if ricevuti:
            break
        await asyncio.sleep(0.01)
    poller.stop()
    await asyncio.wait_for(task, timeout=1)

    # L'errore del secondo giro è stato loggato e il polling è andato avanti.
    assert client.chiamate >= 3
    assert [v.cod_codice for v in ricevuti] == ["6"]
