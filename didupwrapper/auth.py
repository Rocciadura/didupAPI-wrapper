"""Login su Argo: il flusso OAuth2/PKCE che fa l'app, e la sessione che ne esce.

Argo non offre un'API di login "pulita": imitiamo passo passo quello che fa
l'app ufficiale, seguendo a mano i redirect del portale SSO fino a ottenere
il ``code`` da scambiare con il token.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx

from .exceptions import AuthError, from_response

__all__ = [
    "ArgoConfig",
    "Credenziali",
    "SessioneToken",
    "LoginLink",
    "Autenticatore",
    "formatta_data",
    "recupera_versione_app",
    "APP_BUNDLE_ID",
]

APP_BUNDLE_ID = "it.argosoft.didup.famiglia.new"
_APP_LOOKUP_URL = "https://itunes.apple.com/lookup"


async def recupera_versione_app(
    http: httpx.AsyncClient | None = None, *, bundle_id: str = APP_BUNDLE_ID
) -> str | None:
    """Chiede all'App Store l'ultima versione pubblicata dell'app DiDUP.

    Ci serve per l'header ``argo-client-version``. Se qualcosa va storto
    (niente rete, risposta strana) restituisce ``None`` invece di sollevare.
    """
    chiudi = http is None
    client = http or httpx.AsyncClient(timeout=15.0)
    try:
        risposta = await client.get(_APP_LOOKUP_URL, params={"bundleId": bundle_id})
        risposta.raise_for_status()
        risultati = risposta.json().get("results") or []
        return risultati[0].get("version") if risultati else None
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return None
    finally:
        if chiudi:
            await client.aclose()


_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _random_string(length: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _pkce_challenge(code_verifier: str) -> str:
    """La code challenge PKCE (metodo S256): SHA-256 del verifier in base64url, senza ``=``."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def formatta_data(dt: datetime) -> str:
    """Scrive una data nel formato che usa l'API: ``YYYY-MM-DD HH:MM:SS.mmm``."""
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


@dataclass(frozen=True)
class ArgoConfig:
    """Indirizzi e parametri dell'app ufficiale che usiamo per parlare con Argo.

    Di solito vanno bene i default; l'unico valore che potresti voler
    cambiare è ``version``, che deve seguire gli aggiornamenti dell'app.
    """

    api_base_url: str = "https://www.portaleargo.it/appfamiglia/api/rest/"
    oauth_auth_url: str = "https://auth.portaleargo.it/oauth2/auth"
    oauth_token_url: str = "https://auth.portaleargo.it/oauth2/token"
    sso_login_url: str = "https://www.portaleargo.it/auth/sso/login"
    client_id: str = "72fd6dea-d0ab-4bb9-8eaa-3ac24c84886c"
    redirect_uri: str = "it.argosoft.didup.famiglia.new://login-callback"
    scopes: tuple[str, ...] = ("openid", "offline", "profile", "user.roles", "argo")
    version: str = "1.29.2"

    def headers_base(self) -> dict[str, str]:
        """Gli header che mandiamo sempre, token esclusi."""
        return {
            "accept": "application/json",
            "argo-client-version": self.version,
            "content-type": "application/json; charset=utf-8",
        }


@dataclass
class Credenziali:
    """Codice scuola, username e password: quelli che useresti nell'app."""

    codice_scuola: str
    username: str
    password: str


@dataclass
class LoginLink:
    """L'URL di login OAuth e i valori casuali (PKCE) generati per quel tentativo."""

    url: str
    code_verifier: str
    state: str
    nonce: str


@dataclass
class SessioneToken:
    """Il token OAuth ottenuto al login, con la sua scadenza."""

    access_token: str
    refresh_token: str | None = None
    scope: str = ""
    token_type: str = "bearer"
    expires_at: float | None = None  # epoch seconds
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_scaduto(self) -> bool:
        if self.expires_at is None:
            return False
        # Lo consideriamo scaduto con 30 secondi di anticipo, per non rischiare
        # che scada proprio a metà di una richiesta.
        return time.time() >= (self.expires_at - 30)

    @property
    def expire_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.expires_at or time.time())


class Autenticatore:
    """Fa il login OAuth2/PKCE e si ricorda la sessione ottenuta."""

    def __init__(
        self,
        credenziali: Credenziali | None = None,
        config: ArgoConfig | None = None,
        *,
        sessione: SessioneToken | None = None,
    ) -> None:
        self.credenziali = credenziali
        self.config = config or ArgoConfig()
        self.sessione = sessione

    @property
    def autenticato(self) -> bool:
        return self.sessione is not None and not self.sessione.is_scaduto

    # ------------------------------------------------------------------ #
    # Orchestrazione                                                     #
    # ------------------------------------------------------------------ #
    async def assicura_sessione(self, http: httpx.AsyncClient) -> SessioneToken:
        """Restituisce la sessione attuale, rifacendo il login se manca o è scaduta."""
        if self.autenticato:
            assert self.sessione is not None
            return self.sessione
        return await self.login(http)

    async def login(self, http: httpx.AsyncClient) -> SessioneToken:
        """Fa tutto il giro OAuth2/PKCE da capo e salva il token ottenuto."""
        if self.credenziali is None:
            raise AuthError("Credenziali assenti: impossibile effettuare il login")
        link = self._genera_login_link()
        code = await self._ottieni_code(link)
        self.sessione = await self._ottieni_token(http, link, code)
        return self.sessione

    # ------------------------------------------------------------------ #
    # Step OAuth                                                         #
    # ------------------------------------------------------------------ #
    def _genera_login_link(self) -> LoginLink:
        code_verifier = _random_string(43)
        state = _random_string(22)
        nonce = _random_string(22)
        challenge = _pkce_challenge(code_verifier)
        params = (
            f"redirect_uri={quote(self.config.redirect_uri, safe='')}"
            f"&client_id={self.config.client_id}"
            f"&response_type=code"
            f"&prompt=login"
            f"&state={state}"
            f"&nonce={nonce}"
            f"&scope={quote(' '.join(self.config.scopes), safe='')}"
            f"&code_challenge={challenge}"
            f"&code_challenge_method=S256"
        )
        return LoginLink(
            url=f"{self.config.oauth_auth_url}?{params}",
            code_verifier=code_verifier,
            state=state,
            nonce=nonce,
        )

    async def _ottieni_code(self, link: LoginLink) -> str:
        """Segue i redirect del portale SSO finché non salta fuori il ``code``.

        I redirect li seguiamo a mano (leggendo ``Location``) e i cookie li
        passiamo noi, solo dove li passa l'app: se lasciassimo fare a httpx
        manderebbe cookie in punti in cui il server non se li aspetta.
        """
        assert self.credenziali is not None
        cookies: list[str] = []

        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as c:

            async def passo(method: str, url: str, **kwargs: object) -> httpx.Response:
                r = await c.request(method, url, **kwargs)  # type: ignore[arg-type]
                c.cookies.clear()  # i cookie li gestiamo noi, vedi sopra
                return r

            # 1) Apriamo l'URL OAuth: ci rimanda alla pagina di login con un login_challenge.
            r0 = await passo("GET", link.url)
            loc = r0.headers.get("location")
            _raccogli_cookie(r0, cookies)
            if not loc:
                raise AuthError(
                    "Avvio OAuth: redirect mancante",
                    status_code=r0.status_code,
                )
            challenge = _query_param(loc, "login_challenge")
            if not challenge:
                raise AuthError("Avvio OAuth: 'login_challenge' non trovato")

            # 2) Mandiamo le credenziali, come se compilassimo il form di login.
            body = "&".join(
                [
                    f"challenge={challenge}",
                    f"client_id={self.config.client_id}",
                    "prefill=false",
                    f"famiglia_customer_code={quote(self.credenziali.codice_scuola, safe='')}",
                    f"username={quote(self.credenziali.username, safe='')}",
                    f"password={quote(self.credenziali.password, safe='')}",
                    "login=true",
                ]
            )
            r1 = await passo(
                "POST",
                self.config.sso_login_url,
                content=body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            url1 = r1.headers.get("location")
            if not url1:
                raise AuthError(
                    "Login SSO fallito: credenziali errate o flusso cambiato",
                    status_code=r1.status_code,
                )

            # 3) Dopo il login ci sono ancora tre redirect prima di arrivare al code.
            r2 = await passo("GET", url1, headers={"cookie": "; ".join(cookies)})
            url2 = r2.headers.get("location")
            _raccogli_cookie(r2, cookies)
            if not url2:
                raise AuthError("Catena OAuth interrotta (redirect 2)")

            r3 = await passo("GET", url2)
            url3 = r3.headers.get("location")
            if not url3:
                raise AuthError("Catena OAuth interrotta (redirect 3)")

            r4 = await passo("GET", url3, headers={"cookie": "; ".join(cookies)})
            url4 = r4.headers.get("location")
            if not url4:
                raise AuthError("Catena OAuth interrotta (redirect finale)")

        code = _query_param(url4, "code")
        if not code:
            raise AuthError(f"Code non presente nel redirect finale: {url4}")
        return code

    async def _ottieni_token(
        self, http: httpx.AsyncClient, link: LoginLink, code: str
    ) -> SessioneToken:
        """Scambia il ``code`` con l'access token vero e proprio."""
        risposta = await http.post(
            self.config.oauth_token_url,
            data={
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.config.redirect_uri,
                "code_verifier": link.code_verifier,
                "client_id": self.config.client_id,
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        if risposta.is_error:
            raise from_response(risposta)
        try:
            dati = risposta.json()
        except ValueError as exc:
            raise AuthError(
                "Risposta OAuth non leggibile (non è JSON)",
                status_code=risposta.status_code,
            ) from exc
        if "error" in dati:
            raise AuthError(
                f"{dati.get('error')}: {dati.get('error_description', '')}".strip(": "),
                payload=dati,
            )
        access_token = dati.get("access_token")
        if not access_token:
            raise AuthError("Token non presente nella risposta OAuth", payload=dati)

        expires_in = dati.get("expires_in")
        return SessioneToken(
            access_token=access_token,
            refresh_token=dati.get("refresh_token"),
            scope=dati.get("scope", ""),
            token_type=dati.get("token_type", "bearer"),
            expires_at=(time.time() + float(expires_in)) if expires_in else None,
            extra=dati,
        )


def _raccogli_cookie(response: httpx.Response, cookies: list[str]) -> None:
    """Aggiunge a ``cookies`` le coppie ``nome=valore`` dei ``Set-Cookie`` ricevuti."""
    for header in response.headers.get_list("set-cookie"):
        coppia = header.split(";", 1)[0].strip()
        if coppia:
            cookies.append(coppia)


def _query_param(url: str, nome: str) -> str | None:
    valori = parse_qs(urlparse(url).query).get(nome)
    return valori[0] if valori else None
