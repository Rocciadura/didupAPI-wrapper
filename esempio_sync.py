"""Esempio d'uso sincrono di didupwrapper."""

from __future__ import annotations

import os

from didupwrapper import DiDUPClientSync


def main() -> None:
    with DiDUPClientSync(
        codice_scuola=os.environ["DIDUP_SCUOLA"],
        username=os.environ["DIDUP_USER"],
        password=os.environ["DIDUP_PASSWORD"],
    ) as didup:
        print("Media generale:", didup.get_media_generale())

        for materia in didup.get_materie():
            print(f"- {materia.materia} ({materia.abbreviazione})")

        for voto in didup.get_voti():
            print(f"{voto.dat_evento} | {voto.des_materia} | {voto.cod_codice}")


if __name__ == "__main__":
    main()
