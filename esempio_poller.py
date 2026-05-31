"""Esempio: monitoraggio della dashboard con DashboardPoller."""

from __future__ import annotations

import asyncio
import logging
import os

from didupwrapper import DiDUPClient
from didupwrapper.models import ComunicazioneBacheca, Voto
from didupwrapper.workers import DashboardPoller

logging.basicConfig(level=logging.INFO)


async def on_nuovi_voti(voti: list[Voto]) -> None:
    for v in voti:
        print(f"🆕 Nuovo voto: {v.des_materia} -> {v.cod_codice}")


async def on_nuove_comunicazioni(comunicazioni: list[ComunicazioneBacheca]) -> None:
    for c in comunicazioni:
        print(f"📢 Nuova comunicazione da {c.autore}: {c.messaggio[:80]}")


async def main() -> None:
    async with DiDUPClient(
        codice_scuola=os.environ["DIDUP_SCUOLA"],
        username=os.environ["DIDUP_USER"],
        password=os.environ["DIDUP_PASSWORD"],
    ) as didup:
        poller = DashboardPoller(
            didup,
            intervallo=600,  # ogni 10 minuti
            on_nuovi_voti=on_nuovi_voti,
            on_nuove_comunicazioni=on_nuove_comunicazioni,
        )
        try:
            await poller.start()
        except KeyboardInterrupt:
            poller.stop()


if __name__ == "__main__":
    asyncio.run(main())
