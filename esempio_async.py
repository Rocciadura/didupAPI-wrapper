"""Esempio d'uso asincrono di didupwrapper."""

from __future__ import annotations

import asyncio
import os

from didupwrapper import DiDUPClient


async def main() -> None:
    async with DiDUPClient(
        codice_scuola=os.environ["DIDUP_SCUOLA"],
        username=os.environ["DIDUP_USER"],
        password=os.environ["DIDUP_PASSWORD"],
    ) as didup:
        print("Media generale:", await didup.get_media_generale())

        print("\n== Ultimi voti ==")
        for voto in await didup.get_voti():
            tipo = "Scritto" if voto.is_scritto else "Orale"
            print(f"{voto.dat_evento} | {voto.des_materia:20} | {voto.cod_codice} ({tipo})")

        print("\n== Assenze da giustificare ==")
        for evento in await didup.assenze.da_giustificare():
            print(f"{evento.dat_evento} | {evento.descrizione}")

        print("\n== Bacheca da leggere ==")
        for com in await didup.bacheca.da_leggere():
            print(f"{com.data} | {com.autore} | {com.messaggio[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
