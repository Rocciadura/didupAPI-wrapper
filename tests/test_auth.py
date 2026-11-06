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
    rotte["r2"].mock(
        return_value=httpx.Response(
            200, text="<html><title>Manutenzione</title><p>Riprova più tardi</p></html>"
        )
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError) as info:
            await Autenticatore(CREDENZIALI).login(http)

    messaggio = str(info.value)
    assert "Catena OAuth interrotta (redirect 2)" in messaggio
    assert "HTTP 200 da https://auth.portaleargo.it/oauth2/auth" in messaggio
    assert "«Manutenzione»" in messaggio
    # La query (con challenge e verifier) non finisce nel messaggio.
    assert "login_verifier" not in messaggio


# --------------------------------------------------------------------- #
# Pagina di consenso che risponde 200 invece di un redirect (issue #3)  #
# --------------------------------------------------------------------- #
URL_CONSENT_PAGE = "https://www.portaleargo.it/auth/sso/consent/?consent_challenge=c1"
URL_CONSENT_POST = "https://www.portaleargo.it/auth/sso/consent/"


def _mock_consenso(pagina: str) -> dict[str, respx.Route]:
    rotte = _mock_flusso_sso()
    rotte["r2"].mock(return_value=_redirect(URL_CONSENT_PAGE))
    rotte["consent"] = respx.get(URL_CONSENT_PAGE).mock(
        return_value=httpx.Response(
            200,
            text=pagina,
            headers=[
                ("content-type", "text/html"),
                ("set-cookie", "consent_csrf=def; Path=/; HttpOnly"),
            ],
        )
    )
    rotte["consent_post"] = respx.post(URL_CONSENT_POST).mock(return_value=_redirect(URL_4))
    return rotte


def _form_inviato(rotta: respx.Route) -> dict[str, list[str]]:
    from urllib.parse import parse_qs

    return parse_qs(rotta.calls.last.request.content.decode())


@respx.mock
@pytest.mark.asyncio
async def test_consenso_con_form_viene_accettato():
    pagina = """
    <html><head><title>Autorizza</title></head><body>
    <form action="/auth/sso/consent/" method="post">
      <input type="hidden" name="challenge" value="c1">
      <input type="hidden" name="_csrf" value="tok&amp;en">
      <input type="checkbox" name="grant_scope" value="openid" checked>
      <input type="checkbox" name="grant_scope" value="argo">
      <input type="checkbox" name="remember" value="true">
      <button type="submit" name="submit" value="deny">Rifiuta</button>
      <button type="submit" name="submit" value="accept">Accetta</button>
    </form></body></html>
    """
    rotte = _mock_consenso(pagina)
    _mock_token()

    async with httpx.AsyncClient() as http:
        sessione = await Autenticatore(CREDENZIALI).login(http)

    assert sessione.access_token == "acc-1"
    form = _form_inviato(rotte["consent_post"])
    assert form["challenge"] == ["c1"]
    assert form["_csrf"] == ["tok&en"]
    assert form["grant_scope"] == ["openid", "argo"]
    assert form["submit"] == ["accept"]
    assert "remember" not in form  # casella non spuntata: il browser non la manda
    # Il POST del consenso porta i cookie di www, come farebbe il browser.
    assert "consent_csrf=def" in rotte["consent_post"].calls.last.request.headers["cookie"]
    assert rotte["consent_post"].calls.last.request.headers["content-type"] == (
        "application/x-www-form-urlencoded"
    )


@respx.mock
@pytest.mark.asyncio
async def test_consenso_senza_form_accetta_gli_scope_richiesti():
    rotte = _mock_consenso("<html><body><div id='app'></div></body></html>")
    _mock_token()

    async with httpx.AsyncClient() as http:
        sessione = await Autenticatore(CREDENZIALI).login(http)

    assert sessione.access_token == "acc-1"
    form = _form_inviato(rotte["consent_post"])
    assert form["challenge"] == ["c1"]
    assert form["grant_scope"] == list(CONFIG.scopes)
    assert form["consent"] == ["Accetta"]


@respx.mock
@pytest.mark.asyncio
async def test_pagina_accesso_completato_con_link_continua():
    pagina = (
        "<h1>Accesso completato</h1>"
        f'<a class="btn" href="{CONFIG.redirect_uri}?code=il-code&amp;state=x">Continua</a>'
    )
    rotte = _mock_consenso(pagina)
    token = _mock_token()

    async with httpx.AsyncClient() as http:
        await Autenticatore(CREDENZIALI).login(http)

    assert not rotte["consent_post"].called
    assert "code=il-code" in token.calls.last.request.content.decode()


@respx.mock
@pytest.mark.asyncio
async def test_pagina_intermedia_con_redirect_javascript():
    pagina = (
        "<script>window.location.href = "
        "'https:\\/\\/auth.portaleargo.it\\/oauth2\\/auth?consent_verifier=v2';</script>"
    )
    rotte = _mock_consenso(pagina)
    _mock_token()

    async with httpx.AsyncClient() as http:
        sessione = await Autenticatore(CREDENZIALI).login(http)

    assert sessione.access_token == "acc-1"
    assert rotte["r4"].called


@respx.mock
@pytest.mark.asyncio
async def test_pagina_intermedia_con_meta_refresh():
    pagina = '<meta http-equiv="refresh" content="0; url=/auth/sso/fine?x=1">'
    rotte = _mock_consenso(pagina)
    fine = respx.get("https://www.portaleargo.it/auth/sso/fine?x=1").mock(
        return_value=_redirect(URL_4)
    )
    _mock_token()

    async with httpx.AsyncClient() as http:
        await Autenticatore(CREDENZIALI).login(http)

    assert fine.called
    assert rotte["r4"].called


@respx.mock
@pytest.mark.asyncio
async def test_ritorno_al_form_di_login_non_viene_inviato():
    pagina = """
    <title>Accedi</title>
    <form method="post"><input name="username"><input type="password" name="password">
    <button type="submit">Entra</button></form>
    """
    rotte = _mock_flusso_sso()
    rotte["r2"].mock(return_value=httpx.Response(200, text=pagina))

    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError, match="«Accedi»"):
            await Autenticatore(CREDENZIALI).login(http)


@respx.mock
@pytest.mark.asyncio
async def test_errore_oauth_nel_redirect_finale():
    rotte = _mock_flusso_sso()
    rotte["r4"].mock(
        return_value=_redirect(f"{CONFIG.redirect_uri}?error=access_denied&error_description=no")
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthError, match="access_denied no"):
            await Autenticatore(CREDENZIALI).login(http)


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
