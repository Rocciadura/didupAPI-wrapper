"""Il client vero e proprio: :class:`DiDUPClient` (async) e
:class:`DiDUPClientSync` (la stessa cosa, ma sincrona).

Per arrivare ai dati servono tre passaggi, gli stessi che fa l'app:

1. login OAuth2/PKCE sul portale Argo, che ci dà un access token
   (se ne occupa :class:`~didupwrapper.auth.Autenticatore`);
2. ``POST login`` sull'API dell'app, che restituisce ``x-auth-token``,
   ``codMin`` e le ``opzioni`` del profilo;
3. ``POST dashboard/dashboard``, che manda praticamente tutti i dati in una
   volta sola. Gli endpoint poi prendono da lì la parte che serve.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar

import httpx

from .auth import (
    ArgoConfig,
    Autenticatore,
    Credenziali,
    SessioneToken,
    _random_string,
    formatta_data,
    recupera_versione_app,
)
from .endpoints import (
    AssenzeEndpoint,
    BachecaEndpoint,
    FuoriClasseEndpoint,
    PromemoriaEndpoint,
    RegistroEndpoint,
    VotiEndpoint,
)
from .exceptions import DiDUPError, from_response
from .models import (
    ComunicazioneBacheca,
    DashboardResponse,
    Docente,
    EventoAppello,
    FuoriClasse,
    Materia,
    NotaDisciplinare,
    Periodo,
    Prenotazione,
    Promemoria,
    RegistroLezione,
    Voto,
)

if TYPE_CHECKING:
    from .models import FileBachecaAlunno

__all__ = ["DiDUPClient", "DiDUPClientSync"]

T = TypeVar("T")

_LOGIN_PATH = "login"
_DASHBOARD_PATH = "dashboard/dashboard"
# Chiedendo i dati "aggiornati dal 2000" il server ci manda tutto.
_DATA_INIZIO_DEFAULT = "2000-01-01 00:00:00.000"


class DiDUPClient:
    """Client asincrono per DiDUP.

    Il modo più comodo di usarlo è come context manager: all'ingresso fa il
    login, all'uscita chiude la connessione::

        async with DiDUPClient("SC12345", "mario.rossi", "password") as didup:
            voti = await didup.get_voti()
    """

    def __init__(
        self,
        codice_scuola: str | None = None,
        username: str | None = None,
        password: str | None = None,
        *,
        config: ArgoConfig | None = None,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
        access_token: str | None = None,
        version: str | None = None,
        auto_versione: bool = False,
    ) -> None:
        self._config = config or ArgoConfig()
        if version is not None:
            self._config = replace(self._config, version=version)
        self._auto_versione = auto_versione
        self._versione_risolta = False

        credenziali = (
            Credenziali(codice_scuola, username, password)
            if codice_scuola is not None and username is not None and password is not None
            else None
        )
        sessione = SessioneToken(access_token=access_token) if access_token else None
        self._auth = Autenticatore(credenziali, self._config, sessione=sessione)

        self._proprio_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._config.api_base_url, timeout=timeout
        )

        self._login_data: dict[str, Any] | None = None
        self._dashboard_cache: DashboardResponse | None = None
        self.voti = VotiEndpoint(self)
        self.assenze = AssenzeEndpoint(self)
        self.registro = RegistroEndpoint(self)
        self.bacheca = BachecaEndpoint(self)
        self.promemoria = PromemoriaEndpoint(self)
        self.fuori_classe = FuoriClasseEndpoint(self)

    # ------------------------------------------------------------------ #
    # Ciclo di vita / context manager                                    #
    # ------------------------------------------------------------------ #
    async def __aenter__(self) -> "DiDUPClient":
        try:
            await self.login()
        except BaseException:
            # Se il login fallisce __aexit__ non viene chiamato: chiudiamo noi.
            await self.aclose()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._proprio_http:
            await self._http.aclose()

    # ------------------------------------------------------------------ #
    # Autenticazione                                                     #
    # ------------------------------------------------------------------ #
    async def login(self) -> None:
        """Fa il login completo (OAuth + login dell'app). Se sei già dentro non fa nulla."""
        await self._assicura_versione()
        await self._auth.assicura_sessione(self._http)
        if self._login_data is None:
            await self._login_applicativo()

    async def _assicura_versione(self) -> None:
        """Con ``auto_versione=True`` chiede allo store qual è l'ultima versione dell'app."""
        if not self._auto_versione or self._versione_risolta:
            return
        versione = await recupera_versione_app()
        if versione:
            self._config = replace(self._config, version=versione)
            self._auth.config = self._config
        self._versione_risolta = True

    @property
    def versione(self) -> str:
        """La versione (``argo-client-version``) attualmente in uso."""
        return self._config.version

    async def _login_applicativo(self) -> dict[str, Any] | None:
        """Il ``login`` dell'app: ci restituisce x-auth-token, codMin e opzioni."""
        dati = await self._post(
            _LOGIN_PATH,
            json={
                "lista-opzioni-notifiche": "{}",
                "lista-x-auth-token": "[]",
                "clientID": _random_string(163),
            },
        )
        self._verifica_success(dati)
        lista = (dati or {}).get("data") or []
        if not lista:
            raise DiDUPError("Login applicativo: nessun profilo restituito", payload=dati)
        self._login_data = lista[0]
        return self._login_data

    @property
    def autenticato(self) -> bool:
        return self._auth.autenticato and self._login_data is not None

    # ------------------------------------------------------------------ #
    # Richieste HTTP di basso livello                                    #
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        sessione = self._auth.sessione
        headers = self._config.headers_base()
        if sessione is not None:
            headers["authorization"] = f"Bearer {sessione.access_token}"
            if sessione.expires_at is not None:
                headers["x-date-exp-auth"] = formatta_data(sessione.expire_datetime)
        if self._login_data is not None:
            if self._login_data.get("token"):
                headers["x-auth-token"] = self._login_data["token"]
            if self._login_data.get("codMin"):
                headers["x-cod-min"] = self._login_data["codMin"]
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._auth.autenticato:
            # Il token OAuth è scaduto (o non c'è ancora): ne prendiamo uno nuovo.
            # Il vecchio x-auth-token era legato alla sessione precedente, quindi
            # rifacciamo anche il login dell'app.
            await self._auth.login(self._http)
            if self._login_data is not None and path != _LOGIN_PATH:
                self._login_data = None
                await self._login_applicativo()
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        risposta = await self._http.request(method, path, headers=headers, **kwargs)
        if risposta.is_error:
            raise from_response(risposta)
        if not risposta.content:
            return None
        try:
            return risposta.json()
        except ValueError as exc:
            # Capita per esempio con le pagine HTML di manutenzione.
            raise DiDUPError(
                "Il server ha risposto con qualcosa che non è JSON",
                status_code=risposta.status_code,
                payload=risposta.text,
                request_url=str(risposta.request.url),
            ) from exc

    async def _post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def _get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    @staticmethod
    def _verifica_success(dati: Any) -> None:
        if isinstance(dati, dict) and dati.get("success") is False:
            raise DiDUPError(dati.get("msg") or "Richiesta DiDUP non riuscita", payload=dati)

    # ------------------------------------------------------------------ #
    # Dashboard                                                          #
    # ------------------------------------------------------------------ #
    async def get_dashboard(self, *, forza_refresh: bool = False) -> DashboardResponse:
        """Scarica la dashboard e la tiene in cache.

        Le chiamate successive usano la copia in cache; passa
        ``forza_refresh=True`` se vuoi i dati freschi dal server.
        """
        if self._dashboard_cache is not None and not forza_refresh:
            return self._dashboard_cache

        if self._login_data is None:
            await self.login()

        dati = await self._post(
            _DASHBOARD_PATH,
            json={
                "dataultimoaggiornamento": _DATA_INIZIO_DEFAULT,
                "opzioni": self._opzioni_serializzate(),
            },
        )
        self._verifica_success(dati)
        contenuto = _estrai_dashboard(dati)
        if not isinstance(contenuto, dict):
            raise DiDUPError("La dashboard è arrivata vuota o in un formato inatteso", payload=dati)
        dashboard = DashboardResponse.model_validate(contenuto)
        self._dashboard_cache = dashboard
        return dashboard

    def _opzioni_serializzate(self) -> str:
        """Le ``opzioni`` del profilo, nel formato stringa JSON che vuole l'API."""
        opzioni = (self._login_data or {}).get("opzioni") or []
        mappa = {o["chiave"]: o["valore"] for o in opzioni if "chiave" in o}
        return json.dumps(mappa, separators=(",", ":"))

    def invalida_cache(self) -> None:
        """Butta la dashboard in cache: la prossima richiesta la riscarica."""
        self._dashboard_cache = None

    # ------------------------------------------------------------------ #
    # Scorciatoie                                                        #
    # ------------------------------------------------------------------ #
    async def get_voti(self) -> list[Voto]:
        return await self.voti.lista()

    async def get_assenze(self) -> list[EventoAppello]:
        return await self.assenze.lista()

    async def get_registro(self) -> list[RegistroLezione]:
        return await self.registro.lista()

    async def get_bacheca(self) -> list[ComunicazioneBacheca]:
        return await self.bacheca.lista()

    async def get_bacheca_alunno(self) -> list["FileBachecaAlunno"]:
        return await self.bacheca.file_alunno()

    async def get_promemoria(self) -> list[Promemoria]:
        return await self.promemoria.lista()

    async def get_fuori_classe(self) -> list[FuoriClasse]:
        return await self.fuori_classe.lista()

    async def get_note_disciplinari(self) -> list[NotaDisciplinare]:
        return (await self.get_dashboard()).note_disciplinari

    async def get_materie(self) -> list[Materia]:
        return (await self.get_dashboard()).lista_materie

    async def get_docenti(self) -> list[Docente]:
        return (await self.get_dashboard()).lista_docenti_classe

    async def get_periodi(self) -> list[Periodo]:
        return (await self.get_dashboard()).lista_periodi

    async def get_prenotazioni(self) -> list[Prenotazione]:
        return (await self.get_dashboard()).prenotazioni_alunni

    async def get_media_generale(self) -> float | None:
        return (await self.get_dashboard()).media_generale


def _estrai_dashboard(dati: Any) -> Any:
    """Tira fuori la dashboard dall'involucro ``{"data": {"dati": [{...}]}}`` di Argo."""
    if not isinstance(dati, dict):
        return dati
    contenuto = dati.get("data", dati)
    if isinstance(contenuto, dict) and "dati" in contenuto:
        dati_list = contenuto["dati"]
        if isinstance(dati_list, list) and dati_list:
            return dati_list[0]
        return dati_list
    return contenuto


class DiDUPClientSync:
    """La versione sincrona di :class:`DiDUPClient`, per chi non usa asyncio.

    Sotto il cofano gira il client async su un event loop tutto suo, sempre
    lo stesso, così la connessione httpx resta valida tra una chiamata e l'altra.

    Esempio::

        with DiDUPClientSync("SC12345", "mario.rossi", "password") as didup:
            print(didup.get_media_generale())
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._async = DiDUPClient(*args, **kwargs)
        except BaseException:
            self._loop.close()
            raise

    def _run(self, coro: Coroutine[Any, Any, T]) -> T:
        return self._loop.run_until_complete(coro)

    def __enter__(self) -> "DiDUPClientSync":
        try:
            self.login()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._loop.is_closed():
            return
        try:
            self._run(self._async.aclose())
        finally:
            self._loop.close()

    def login(self) -> None:
        self._run(self._async.login())

    @property
    def autenticato(self) -> bool:
        return self._async.autenticato

    @property
    def versione(self) -> str:
        return self._async.versione

    def invalida_cache(self) -> None:
        self._async.invalida_cache()

    def get_dashboard(self, *, forza_refresh: bool = False) -> DashboardResponse:
        return self._run(self._async.get_dashboard(forza_refresh=forza_refresh))

    def get_voti(self) -> list[Voto]:
        return self._run(self._async.get_voti())

    def get_assenze(self) -> list[EventoAppello]:
        return self._run(self._async.get_assenze())

    def get_registro(self) -> list[RegistroLezione]:
        return self._run(self._async.get_registro())

    def get_bacheca(self) -> list[ComunicazioneBacheca]:
        return self._run(self._async.get_bacheca())

    def get_bacheca_alunno(self) -> list["FileBachecaAlunno"]:
        return self._run(self._async.get_bacheca_alunno())

    def get_promemoria(self) -> list[Promemoria]:
        return self._run(self._async.get_promemoria())

    def get_fuori_classe(self) -> list[FuoriClasse]:
        return self._run(self._async.get_fuori_classe())

    def get_note_disciplinari(self) -> list[NotaDisciplinare]:
        return self._run(self._async.get_note_disciplinari())

    def get_materie(self) -> list[Materia]:
        return self._run(self._async.get_materie())

    def get_docenti(self) -> list[Docente]:
        return self._run(self._async.get_docenti())

    def get_periodi(self) -> list[Periodo]:
        return self._run(self._async.get_periodi())

    def get_prenotazioni(self) -> list[Prenotazione]:
        return self._run(self._async.get_prenotazioni())

    def get_media_generale(self) -> float | None:
        return self._run(self._async.get_media_generale())
