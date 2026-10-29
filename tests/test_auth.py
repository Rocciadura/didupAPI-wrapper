"""Test del login OAuth2/PKCE con il portale SSO mockato (respx)."""

from __future__ import annotations

import time
from datetime import datetime

import httpx
import pytest
import respx

from didupwrapper import AuthError
from didupwrapper.auth import (
    ArgoConfig,
    Autenticatore,
    Credenziali,
    SessioneToken,
    _pkce_challenge,
    _query_param,
    formatta_data,
    recupera_versione_app,
)

CONFIG = ArgoConfig()
CREDENZIALI = Credenziali("SC12345", "mario.rossi", "pa&ss word")

URL_LOGIN_PAGE = "https://www.portaleargo.it/auth/sso/login?login_challenge=chal-1"
URL_2 = "https://auth.portaleargo.it/oauth2/auth?login_verifier=v1"
URL_3 = "https://www.portaleargo.it/auth/sso/consent?consent_challenge=c1"
URL_4 = "https://auth.portaleargo.it/oauth2/auth?consent_verifier=v2"
URL_FINALE = f"{CONFIG.redirect_uri}?code=il-code&scope=openid&state=x"


def _redirect(location: str, cookie: str | None = None) -> httpx.Response:
    headers = [("location", location)]
    if cookie:
        headers.append(("set-cookie", f"{cookie}; Path=/; HttpOnly"))
    return httpx.Response(302, headers=headers)


def _mock_flusso_sso() -> dict[str, respx.Route]:
    """Mocka la catena di redirect del portale come la vede l'app."""
    return {
        "auth": respx.get(url__startswith=CONFIG.oauth_auth_url + "?redirect_uri").mock(
            return_value=_redirect(URL_LOGIN_PAGE, "oauth2_csrf=abc")
        ),
        "sso": respx.post(CONFIG.sso_login_url).mock(return_value=_redirect(URL_2)),
        "r2": respx.get(URL_2).mock(return_value=_redirect(URL_3, "consent_csrf=def")),
        "r3": respx.get(URL_3).mock(return_value=_redirect(URL_4)),
        "r4": respx.get(URL_4).mock(return_value=_redirect(URL_FINALE)),
    }


def _mock_token() -> respx.Route:
    return respx.post(CONFIG.oauth_token_url).mock(
        return_value=httpx.Response(200, json={"access_token": "acc-1", "expires_in": 3600})
    )


def test_pkce_challenge_vettore_rfc7636():
    # Esempio dell'appendice B della RFC 7636.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert _pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_formatta_data_millisecondi():
    assert formatta_data(datetime(2026, 3, 4, 5, 6, 7, 89_000)) == "2026-03-04 05:06:07.089"


def test_sessione_scaduta_con_margine():
    assert not SessioneToken("t").is_scaduto
    assert not SessioneToken("t", expires_at=time.time() + 120).is_scaduto
    # Entro i 30 secondi di margine la consideriamo già scaduta.
    assert SessioneToken("t", expires_at=time.time() + 10).is_scaduto


def test_login_link_contiene_parametri_pkce():
    link = Autenticatore(CREDENZIALI)._genera_login_link()
    assert link.url.startswith(CONFIG.oauth_auth_url + "?")
    assert _query_param(link.url, "code_challenge") == _pkce_challenge(link.code_verifier)
    assert _query_param(link.url, "code_challenge_method") == "S256"
    assert _query_param(link.url, "state") == link.state
    assert _query_param(link.url, "scope") == " ".join(CONFIG.scopes)
    assert len(link.code_verifier) == 43


@respx.mock
@pytest.mark.asyncio
async def test_login_completo():
    rotte = _mock_flusso_sso()
    token = respx.post(CONFIG.oauth_token_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "acc-1",
                "refresh_token": "ref-1",
                "expires_in": 3600,
                "scope": "openid argo",
                "token_type": "bearer",
            },
        )
    )
    auth = Autenticatore(CREDENZIALI)

    async with httpx.AsyncClient() as http:
        sessione = await auth.login(http)

    assert sessione.access_token == "acc-1"
    assert sessione.refresh_token == "ref-1"
    assert sessione.expires_at is not None and sessione.expires_at > time.time() + 3500
    assert auth.autenticato

    # Le credenziali arrivano url-encoded nel form di login.
    form = rotte["sso"].calls.last.request.content.decode()
    assert "challenge=chal-1" in form
    assert "famiglia_customer_code=SC12345" in form
    assert "password=pa%26ss%20word" in form

    # I cookie raccolti vengono rimandati solo nei passi in cui li manda l'app.
    assert rotte["r2"].calls.last.request.headers["cookie"] == "oauth2_csrf=abc"
    assert "cookie" not in rotte["r3"].calls.last.request.headers
    assert (
        rotte["r4"].calls.last.request.headers["cookie"] == "oauth2_csrf=abc; consent_csrf=def"
    )

    # Il code finale viene scambiato insieme al verifier PKCE.
    corpo = token.calls.last.request.content.decode()
    assert "code=il-code" in corpo
    assert "grant_type=authorization_code" in corpo
    assert "code_verifier=" in corpo


@respx.mock
@pytest.mark.asyncio
async def test_cookie_del_login_tornano_solo_al_portale():
    rotte = _mock_flusso_sso()
    # Il login su www.portaleargo.it imposta un cookie di sessione: come in un
    # browser va rimandato solo a www (passo 3), non ad auth (passi 2 e 4).
    rotte["sso"].mock(return_value=_redirect(URL_2, "sso_session=s1"))
    _mock_token()

    async with httpx.AsyncClient() as http:
        await Autenticatore(CREDENZIALI).login(http)

    assert rotte["r2"].calls.last.request.headers["cookie"] == "oauth2_csrf=abc"
    assert rotte["r3"].calls.last.request.headers["cookie"] == "sso_session=s1"
    assert "sso_session" not in rotte["r4"].calls.last.request.headers["cookie"]


@respx.mock
@pytest.mark.asyncio
async def test_cookie_con_domain_valgono_per_i_sottodomini():
    rotte = _mock_flusso_sso()
    rotte["sso"].mock(
        return_value=httpx.Response(
            302,
            headers=[
                ("location", URL_2),
                ("set-cookie", "condiviso=1; Domain=.portaleargo.it; Path=/"),
            ],
        )
    )
    _mock_token()

    async with httpx.AsyncClient() as http:
        await Autenticatore(CREDENZIALI).login(http)

    assert "condiviso=1" in rotte["r2"].calls.last.request.headers["cookie"]
    assert rotte["r3"].calls.last.request.headers["cookie"] == "condiviso=1"


@respx.mock
@pytest.mark.asyncio
async def test_redirect_in_piu_e_location_relativa():
    rotte = _mock_flusso_sso()
    # Un passo in più nella catena, con un Location relativo.
    rotte["r3"].mock(return_value=_redirect("/auth/sso/extra?x=1"))
    extra = respx.get("https://www.portaleargo.it/auth/sso/extra").mock(
        return_value=_redirect(URL_4)
    )
    _mock_token()

    async with httpx.AsyncClient() as http:
        sessione = await Autenticatore(CREDENZIALI).login(http)

    assert sessione.access_token == "acc-1"
    assert extra.called


@respx.mock
@pytest.mark.asyncio
async def test_catena_interrotta_spiega_dove():
    rotte = _mock_flusso_sso()
    rotte["r3"].mock(return_value=httpx.Response(200, text="<html>consenso</html>"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError) as info:
            await Autenticatore(CREDENZIALI).login(http)

    messaggio = str(info.value)
    assert "Catena OAuth interrotta (redirect 3)" in messaggio
    assert "HTTP 200 da https://www.portaleargo.it/auth/sso/consent" in messaggio
    # La query (con challenge e code) non finisce nel messaggio.
    assert "consent_challenge" not in messaggio


@respx.mock
@pytest.mark.asyncio
async def test_credenziali_errate():
    rotte = _mock_flusso_sso()
    # Con credenziali sbagliate il portale risponde 200 con la pagina di errore.
    rotte["sso"].mock(return_value=httpx.Response(200, text="<html>errore</html>"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError, match="credenziali errate"):
            await Autenticatore(CREDENZIALI).login(http)


@respx.mock
@pytest.mark.asyncio
async def test_errore_oauth_nel_token():
    _mock_flusso_sso()
    respx.post(CONFIG.oauth_token_url).mock(
        return_value=httpx.Response(
            200, json={"error": "invalid_grant", "error_description": "code scaduto"}
        )
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError, match="invalid_grant: code scaduto"):
            await Autenticatore(CREDENZIALI).login(http)


@pytest.mark.asyncio
async def test_login_senza_credenziali():
    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError, match="Credenziali assenti"):
            await Autenticatore().login(http)


@pytest.mark.asyncio
async def test_assicura_sessione_riusa_token_valido():
    sessione = SessioneToken("ancora-buono", expires_at=time.time() + 3600)
    auth = Autenticatore(sessione=sessione)
    async with httpx.AsyncClient() as http:
        assert await auth.assicura_sessione(http) is sessione


@respx.mock
@pytest.mark.asyncio
async def test_recupera_versione_app():
    respx.get("https://itunes.apple.com/lookup").mock(
        return_value=httpx.Response(200, json={"results": [{"version": "1.30.0"}]})
    )
    assert await recupera_versione_app() == "1.30.0"


@respx.mock
@pytest.mark.asyncio
async def test_recupera_versione_app_errore_restituisce_none():
    respx.get("https://itunes.apple.com/lookup").mock(return_value=httpx.Response(503))
    assert await recupera_versione_app() is None
