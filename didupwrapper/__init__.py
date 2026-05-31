"""didupwrapper — wrapper Python (sync + async) per le API non documentate
del registro elettronico DiDUP / Argo Famiglia.

Uso rapido (async)::

    import asyncio
    from didupwrapper import DiDUPClient

    async def main():
        async with DiDUPClient("SC12345", "mario.rossi", "password") as didup:
            for voto in await didup.get_voti():
                print(voto.des_materia, voto.cod_codice)

    asyncio.run(main())

Uso rapido (sync)::

    from didupwrapper import DiDUPClientSync

    with DiDUPClientSync("SC12345", "mario.rossi", "password") as didup:
        print(didup.get_media_generale())
"""

from __future__ import annotations

from .auth import (
    ArgoConfig,
    Autenticatore,
    Credenziali,
    LoginLink,
    SessioneToken,
    recupera_versione_app,
)
from .client import DiDUPClient, DiDUPClientSync
from .exceptions import (
    AuthError,
    DiDUPError,
    NotFoundError,
    RateLimitError,
)
from .models import (
    Allegato,
    ComunicazioneBacheca,
    Compito,
    DashboardResponse,
    DettaglioPrenotazione,
    Docente,
    EventoAppello,
    FileBachecaAlunno,
    FuoriClasse,
    Materia,
    NotaDisciplinare,
    Periodo,
    Prenotazione,
    Promemoria,
    RegistroLezione,
    Voto,
)
from .workers import DashboardPoller, EventoPoller

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # client
    "DiDUPClient",
    "DiDUPClientSync",
    # auth
    "ArgoConfig",
    "Autenticatore",
    "Credenziali",
    "SessioneToken",
    "LoginLink",
    "recupera_versione_app",
    # eccezioni
    "DiDUPError",
    "AuthError",
    "RateLimitError",
    "NotFoundError",
    # modelli
    "DashboardResponse",
    "Voto",
    "EventoAppello",
    "RegistroLezione",
    "Compito",
    "NotaDisciplinare",
    "Promemoria",
    "ComunicazioneBacheca",
    "Allegato",
    "FileBachecaAlunno",
    "FuoriClasse",
    "Materia",
    "Docente",
    "Periodo",
    "Prenotazione",
    "DettaglioPrenotazione",
    # workers
    "DashboardPoller",
    "EventoPoller",
]
