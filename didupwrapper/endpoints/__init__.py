"""Endpoint della libreria.

Ogni endpoint incapsula l'accesso a una sezione della dashboard DiDUP.
La maggior parte dei dati arriva infatti da un'unica risposta aggregata
(:class:`~didupwrapper.models.DashboardResponse`); gli endpoint si occupano
di estrarre e filtrare la porzione di propria competenza.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import DiDUPClient
    from ..models import DashboardResponse


class BaseEndpoint:
    """Classe base per tutti gli endpoint.

    Mantiene un riferimento al client async e offre l'accesso comodo alla
    dashboard (con cache gestita dal client).
    """

    def __init__(self, client: "DiDUPClient") -> None:
        self._client = client

    async def _dashboard(self, *, forza_refresh: bool = False) -> "DashboardResponse":
        return await self._client.get_dashboard(forza_refresh=forza_refresh)


from .assenze import AssenzeEndpoint  # noqa: E402
from .bacheca import BachecaEndpoint  # noqa: E402
from .fuori_classe import FuoriClasseEndpoint  # noqa: E402
from .promemoria import PromemoriaEndpoint  # noqa: E402
from .registro import RegistroEndpoint  # noqa: E402
from .voti import VotiEndpoint  # noqa: E402

__all__ = [
    "BaseEndpoint",
    "VotiEndpoint",
    "AssenzeEndpoint",
    "RegistroEndpoint",
    "BachecaEndpoint",
    "PromemoriaEndpoint",
    "FuoriClasseEndpoint",
]
