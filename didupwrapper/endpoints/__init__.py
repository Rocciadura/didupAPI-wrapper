"""Gli endpoint: un modo comodo per filtrare le varie sezioni della dashboard.

Argo manda quasi tutto in un'unica risposta
(:class:`~didupwrapper.models.DashboardResponse`). Ogni endpoint si occupa di
una sezione — voti, assenze, bacheca... — e aggiunge qualche filtro già
pronto, così non devi scriverteli a mano.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import DiDUPClient
    from ..models import DashboardResponse


class BaseEndpoint:
    """La base comune degli endpoint: tiene il client e sa come chiedergli la dashboard."""

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
