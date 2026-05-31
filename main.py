import asyncio
import os

from didupwrapper import DiDUPClient
from didupwrapper.auth import recupera_versione_app


async def main():
    async with DiDUPClient(
        os.environ["DIDUP_SCUOLA"],
        os.environ["DIDUP_USER"],
        os.environ["DIDUP_PASSWORD"],
        auto_versione=True,
    ) as didup:
        print("Media:", await didup.get_media_generale())
        for i in await didup.get_docenti():
            print(i.des_cognome)
            print(i.des_nome)
            print(i.des_email)
            print(i.materie)
            print("-----" * 10)
        print("Registro:", await didup.get_registro())
        print("versione app:", await recupera_versione_app())
        print("Assenze:")
        for ass in await didup.get_assenze():
            print(ass.cod_evento)
            print(ass.descrizione)
            print(ass.dat_evento)
            print(ass.is_assenza)
            print(ass.da_giustificare)
            print(ass.giustificata)
            print("-----" * 10)


asyncio.run(main())
