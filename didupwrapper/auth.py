"""Login su Argo: il flusso OAuth2/PKCE che fa l'app, e la sessione che ne esce.

Argo non offre un'API di login "pulita": imitiamo passo passo quello che fa
l'app ufficiale, seguendo a mano i redirect del portale SSO fino a ottenere
il ``code`` da scambiare con il token.
"""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

import httpx

from .exceptions import AuthError, from_response, from_transport_error

__all__ = [
    "APP_BUNDLE_ID",
    "ArgoConfig",
    "Autenticatore",
    "Credenziali",
    "LoginLink",
    "SessioneToken",
    "formatta_data",
    "recupera_versione_app",
]

logger = logging.getLogger("didupwrapper.auth")

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
    """Fa il login OAuth2/PKCE e si ricorda la sessione ottenuta.

    ``timeout`` vale per i passaggi sul portale SSO; lo scambio del ``code``
    usa invece il client HTTP che gli viene passato.
    """

    def __init__(
        self,
        credenziali: Credenziali | None = None,
        config: ArgoConfig | None = None,
        *,
        sessione: SessioneToken | None = None,
        timeout: float | httpx.Timeout = 60.0,
    ) -> None:
        self.credenziali = credenziali
        self.config = config or ArgoConfig()
        self.sessione = sessione
        self.timeout = timeout

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
        gestiamo noi come farebbe un browser: ogni cookie torna solo all'host
        (o al dominio) che l'ha impostato. Il cookie jar di httpx li
        manderebbe anche dove il server non se li aspetta.

        Se un passaggio risponde con una pagina HTML invece che con un redirect
        (es. la pagina di consenso OAuth), la interpretiamo come un browser:
        vedi :class:`_PaginaHtml`.
        """
        assert self.credenziali is not None
        cookies = _CookieJar()

        async with httpx.AsyncClient(follow_redirects=False, timeout=self.timeout) as c:

            async def passo(
                n: int, method: str, url: str, **kwargs: Any
            ) -> httpx.Response:
                headers = dict(kwargs.pop("headers", None) or {})
                cookie = cookies.header_per(url)
                if cookie:
                    headers["cookie"] = cookie
                try:
                    r = await c.request(method, url, headers=headers, **kwargs)
                except httpx.TransportError as exc:
                    raise from_transport_error(exc, url=_senza_query(url)) from exc
                c.cookies.clear()  # i cookie li gestiamo noi, vedi sopra
                cookies.raccogli(r)
                logger.debug(
                    "OAuth passo %d: %s %s -> HTTP %d", n, method, _senza_query(url), r.status_code
                )
                return r

            # 1) Apriamo l'URL OAuth: ci rimanda alla pagina di login con un login_challenge.
            r0 = await passo(0, "GET", link.url)
            loc = _location(r0)
            if not loc:
                raise AuthError("Avvio OAuth: redirect mancante", status_code=r0.status_code)
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
                1,
                "POST",
                self.config.sso_login_url,
                content=body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            url = _location(r1)
            if not url:
                raise AuthError(
                    "Login SSO fallito: credenziali errate o flusso cambiato",
                    status_code=r1.status_code,
                )

            # 3) Dopo il login il portale fa ancora qualche passaggio prima di
            #    rimandarci al redirect_uri dell'app con il code. Di solito sono
            #    redirect, ma alcuni passaggi (es. il consenso OAuth su
            #    /auth/sso/consent/) rispondono con una pagina HTML: in quel caso
            #    facciamo quello che farebbe un browser (inviamo il form, seguiamo
            #    il link "Continua", il meta refresh, ...).
            metodo = "GET"
            extra: dict[str, Any] = {}
            for n in range(2, 2 + _MAX_REDIRECT):
                if url.startswith(self.config.redirect_uri):
                    break
                r = await passo(n, metodo, url, **extra)
                metodo, extra = "GET", {}
                prossimo = _location(r)
                if prossimo:
                    url = prossimo
                    continue
                pagina = _PaginaHtml.da_risposta(r) if r.is_success else None
                successivo = (
                    pagina.passo_successivo(url, self.config) if pagina is not None else None
                )
                if successivo is None:
                    dettaglio = f" (pagina «{pagina.titolo}»)" if pagina and pagina.titolo else ""
                    raise AuthError(
                        f"Catena OAuth interrotta (redirect {n}): "
                        f"HTTP {r.status_code} da {_senza_query(url)}{dettaglio}",
                        status_code=r.status_code,
                    )
                logger.debug(
                    "OAuth passo %d: pagina HTML, prossimo passo %s %s",
                    n,
                    successivo.metodo,
                    _senza_query(successivo.url),
                )
                url, metodo = successivo.url, successivo.metodo
                if successivo.corpo is not None:
                    extra = {
                        "content": successivo.corpo,
                        "headers": {"content-type": "application/x-www-form-urlencoded"},
                    }
            else:
                raise AuthError("Catena OAuth interrotta: troppi redirect")

        code = _query_param(url, "code")
        if not code:
            errore = _query_param(url, "error")
            if errore:
                descrizione = _query_param(url, "error_description") or ""
                raise AuthError(f"Accesso rifiutato da Argo: {errore} {descrizione}".strip())
            raise AuthError(f"Code non presente nel redirect finale: {_senza_query(url)}")
        return code

    async def _ottieni_token(
        self, http: httpx.AsyncClient, link: LoginLink, code: str
    ) -> SessioneToken:
        """Scambia il ``code`` con l'access token vero e proprio."""
        try:
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
        except httpx.TransportError as exc:
            raise from_transport_error(exc) from exc
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


_MAX_REDIRECT = 15


@dataclass
class _Passo:
    """Una richiesta da fare per proseguire la catena di login."""

    metodo: str
    url: str
    corpo: str | None = None  # form url-encoded, solo per i POST


@dataclass
class _Form:
    action: str | None
    metodo: str
    campi: list[tuple[str, str]] = field(default_factory=list)
    # (name, value, testo visibile) dei bottoni di invio
    bottoni: list[tuple[str | None, str, str]] = field(default_factory=list)
    ha_password: bool = False


# Bottoni che non vogliamo premere: negano il consenso o annullano il login.
_BOTTONE_NEGATIVO = re.compile(r"rifiut|nega|deny|reject|annull|cancel|indietro", re.IGNORECASE)
# Link che portano avanti nel flusso ("Accesso completato... Continua").
_LINK_AVANTI = re.compile(r"continu|prosegui|avanti|accedi all'app|apri", re.IGNORECASE)
_META_REFRESH_URL = re.compile(r"url\s*=\s*['\"]?([^'\";]+)", re.IGNORECASE)
_JS_LOCATION = re.compile(
    r"""location(?:\.href)?\s*=\s*["'`]([^"'`]+)["'`]"""
    r"""|location\.(?:replace|assign)\(\s*["'`]([^"'`]+)["'`]""",
    re.IGNORECASE,
)


def _decodifica_html(testo: str) -> str:
    """Toglie entità HTML ed escape JavaScript tipici, per trovare URL dentro script e attributi."""
    testo = html.unescape(testo)
    for vecchio, nuovo in (("\\/", "/"), ("\\u0026", "&"), ("\\u003d", "="), ("\\x26", "&")):
        testo = testo.replace(vecchio, nuovo)
    return testo


class _PaginaHtml(HTMLParser):
    """Legge una pagina intermedia del portale e capisce come andare avanti.

    Il parser è volutamente tollerante: raccoglie form, link, meta refresh e
    titolo, senza pretendere HTML valido.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.testo = ""
        self.titolo = ""
        self.forms: list[_Form] = []
        self.link: list[tuple[str, str]] = []  # (href, testo)
        self.meta_refresh: str | None = None
        self._form: _Form | None = None
        self._link: tuple[str, list[str]] | None = None
        self._bottone: tuple[str | None, str, list[str]] | None = None
        self._in_titolo = False

    @classmethod
    def da_risposta(cls, response: httpx.Response) -> _PaginaHtml:
        pagina = cls()
        pagina.testo = response.text or ""
        try:
            pagina.feed(pagina.testo)
            pagina.close()
        except Exception:  # pragma: no cover - HTMLParser è già molto tollerante
            logger.debug("Pagina HTML non interpretabile", exc_info=True)
        return pagina

    # -- raccolta ------------------------------------------------------- #
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        presenti = {k.lower() for k, _ in attrs}
        if tag == "form":
            self._form = _Form(action=a.get("action"), metodo=(a.get("method") or "get").upper())
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            self._input(a, presenti)
        elif tag == "button" and self._form is not None:
            if (a.get("type") or "submit").lower() == "submit":
                self._bottone = (a.get("name") or None, a.get("value", ""), [])
        elif tag == "a" and a.get("href"):
            self._link = (a["href"], [])
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            m = _META_REFRESH_URL.search(a.get("content", ""))
            if m and self.meta_refresh is None:
                self.meta_refresh = m.group(1).strip()
        elif tag == "title":
            self._in_titolo = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "button":
            self.handle_endtag(tag)

    def _input(self, a: dict[str, str], presenti: set[str]) -> None:
        assert self._form is not None
        tipo = (a.get("type") or "text").lower()
        nome = a.get("name") or ""
        valore = a.get("value", "")
        if tipo in ("submit", "image"):
            self._form.bottoni.append((nome or None, valore, valore))
        elif tipo == "password":
            self._form.ha_password = True
        elif tipo in ("checkbox", "radio"):
            # Come il browser mandiamo le caselle spuntate; le caselle degli
            # scope le spuntiamo comunque (sono quelli che abbiamo chiesto).
            if nome and ("checked" in presenti or "scope" in nome.lower()):
                self._form.campi.append((nome, valore or "on"))
        elif tipo in ("button", "reset", "file"):
            return
        elif nome:
            self._form.campi.append((nome, valore))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._form = None
        elif tag == "button" and self._bottone is not None and self._form is not None:
            nome, valore, testo = self._bottone
            self._form.bottoni.append((nome, valore, " ".join(testo).strip()))
            self._bottone = None
        elif tag == "a" and self._link is not None:
            href, testo = self._link
            self.link.append((href, " ".join(testo).strip()))
            self._link = None
        elif tag == "title":
            self._in_titolo = False

    def handle_data(self, data: str) -> None:
        if self._in_titolo:
            self.titolo = (self.titolo + " " + data.strip()).strip()
        if self._link is not None:
            self._link[1].append(data.strip())
        if self._bottone is not None:
            self._bottone[2].append(data.strip())

    # -- decisione ------------------------------------------------------ #
    def passo_successivo(self, url: str, config: ArgoConfig) -> _Passo | None:
        """Il passo con cui un browser andrebbe avanti da questa pagina, o ``None``."""
        testo = _decodifica_html(self.testo)

        # a) La pagina contiene già il redirect verso l'app, con il code.
        app = re.search(re.escape(config.redirect_uri) + r"\?[^\s\"'<>\\`]+", testo)
        if app:
            return _Passo("GET", app.group(0))

        # b) Meta refresh o redirect via JavaScript.
        if self.meta_refresh:
            return _Passo("GET", urljoin(url, self.meta_refresh))
        js = _JS_LOCATION.search(testo)
        if js:
            destinazione = js.group(1) or js.group(2)
            if destinazione and not destinazione.startswith(("#", "javascript:")):
                return _Passo("GET", urljoin(url, destinazione))

        # c) Un form da inviare (tipicamente la pagina di consenso OAuth).
        for form in self.forms:
            passo = self._invia_form(form, url)
            if passo is not None:
                return passo

        # d) Un link "Continua".
        for href, etichetta in self.link:
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if _LINK_AVANTI.search(etichetta):
                return _Passo("GET", urljoin(url, href))

        # e) Pagina di consenso senza form riconoscibile: accettiamo come fa l'app.
        challenge = _query_param(url, "consent_challenge")
        if challenge:
            campi = [("challenge", challenge)]
            campi += [("grant_scope", s) for s in config.scopes]
            campi.append(("consent", "Accetta"))
            return _Passo("POST", _senza_query(url), urlencode(campi))
        return None

    @staticmethod
    def _invia_form(form: _Form, url: str) -> _Passo | None:
        if form.ha_password:
            # È di nuovo il form di login: inviarlo vuoto non serve a nulla.
            return None
        campi = list(form.campi)
        if form.bottoni:
            buoni = [
                (nome, valore, testo)
                for nome, valore, testo in form.bottoni
                if not _BOTTONE_NEGATIVO.search(f"{nome or ''} {valore} {testo}")
            ]
            if not buoni:
                return None
            nome, valore, _ = buoni[0]
            if nome:
                campi.append((nome, valore))
        if not campi and not form.action:
            return None
        action = urljoin(url, form.action) if form.action else url
        if form.metodo == "POST":
            return _Passo("POST", action, urlencode(campi))
        base = urlparse(action)
        return _Passo("GET", base._replace(query=urlencode(campi)).geturl())


class _CookieJar:
    """Un cookie jar minimale: rimanda ogni cookie solo all'host o al dominio giusto.

    Senza attributo ``Domain`` un cookie vale solo per l'host che l'ha
    impostato; con ``Domain=portaleargo.it`` vale anche per i sottodomini.
    """

    def __init__(self) -> None:
        # (dominio, solo_host) -> {nome: valore}, in ordine di arrivo
        self._cookie: dict[tuple[str, bool], dict[str, str]] = {}

    def raccogli(self, response: httpx.Response) -> None:
        host = response.request.url.host
        for header in response.headers.get_list("set-cookie"):
            coppia, *attributi = (parte.strip() for parte in header.split(";"))
            nome, sep, valore = coppia.partition("=")
            if not sep or not nome:
                continue
            dominio, solo_host, cancella = host, True, False
            for attributo in attributi:
                chiave, _, val = attributo.partition("=")
                chiave = chiave.strip().lower()
                if chiave == "domain" and val.strip():
                    dominio, solo_host = val.strip().lstrip(".").lower(), False
                elif chiave == "max-age" and val.strip().lstrip("-").isdigit():
                    cancella = int(val) <= 0
            jar = self._cookie.setdefault((dominio, solo_host), {})
            jar.pop(nome, None)
            if not cancella:
                jar[nome] = valore

    def header_per(self, url: str) -> str:
        host = httpx.URL(url).host
        coppie = [
            f"{nome}={valore}"
            for (dominio, solo_host), jar in self._cookie.items()
            if host == dominio or (not solo_host and host.endswith("." + dominio))
            for nome, valore in jar.items()
        ]
        return "; ".join(coppie)


def _location(response: httpx.Response) -> str | None:
    """Il ``Location`` di un redirect, reso assoluto se il server lo manda relativo."""
    if not response.is_redirect:
        return None
    loc = response.headers.get("location")
    return urljoin(str(response.request.url), loc) if loc else None


def _senza_query(url: str) -> str:
    """L'URL senza query string, per log ed errori (la query contiene code e challenge)."""
    return url.split("?", 1)[0]


def _query_param(url: str, nome: str) -> str | None:
    valori = parse_qs(urlparse(url).query).get(nome)
    return valori[0] if valori else None
