"""Test del client async con HTTP mockato (respx).

L'OAuth/PKCE viene saltato passando un ``access_token`` già pronto: si
testano così lo step di login applicativo e il parsing della dashboard.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from didupwrapper import AuthError, DiDUPClient, DiDUPError
from didupwrapper.auth import ArgoConfig

from .test_models import DASHBOARD_JSON

BASE_URL = "https://test.local/api/rest/"
CONFIG = ArgoConfig(api_base_url=BASE_URL, version="1.24.0")

LOGIN_RESPONSE = {
    "success": True,
    "data": [{"token": "xauth-123", "codMin": "SC1", "opzioni": []}],
}
DASHBOARD_RESPONSE = {"success": True, "data": {"dati": [DASHBOARD_JSON]}}


def _client() -> DiDUPClient:
    # access_token preimpostato -> salta l'OAuth.
    return DiDUPClient(config=CONFIG, access_token="fake-oauth-token")


@respx.mock
@pytest.mark.asyncio
async def test_login_applicativo_e_get_voti():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )
    respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )

    async with _client() as didup:
        assert didup.autenticato
        voti = await didup.get_voti()
        assert len(voti) == 1
        assert voti[0].des_materia == "Matematica"


@respx.mock
@pytest.mark.asyncio
async def test_headers_auth_inviati():
    login_route = respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )
    dash_route = respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )

    async with _client() as didup:
        await didup.get_media_generale()

    # Il login usa solo il Bearer; la dashboard aggiunge x-auth-token e x-cod-min.
    assert login_route.calls.last.request.headers["authorization"] == "Bearer fake-oauth-token"
    dash_headers = dash_route.calls.last.request.headers
    assert dash_headers["x-auth-token"] == "xauth-123"
    assert dash_headers["x-cod-min"] == "SC1"
    assert dash_headers["argo-client-version"] == "1.24.0"


@respx.mock
@pytest.mark.asyncio
async def test_cache_dashboard():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )
    route = respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )

    async with _client() as didup:
        await didup.get_voti()
        await didup.get_assenze()  # stessa dashboard in cache
        assert route.call_count == 1

        await didup.get_dashboard(forza_refresh=True)
        assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_errore_http_mappato_su_auth():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(401, json={"msg": "non autorizzato"})
    )
    with pytest.raises(AuthError):
        async with _client():
            pass


@respx.mock
@pytest.mark.asyncio
async def test_auto_versione_da_store():
    respx.get("https://itunes.apple.com/lookup").mock(
        return_value=httpx.Response(200, json={"results": [{"version": "9.9.9"}]})
    )
    login_route = respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )
    respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )

    didup = DiDUPClient(config=CONFIG, access_token="fake-oauth-token", auto_versione=True)
    async with didup:
        await didup.get_media_generale()
        assert didup.versione == "9.9.9"
    assert login_route.calls.last.request.headers["argo-client-version"] == "9.9.9"


@respx.mock
@pytest.mark.asyncio
async def test_success_false_solleva_errore():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "errore lato server"})
    )
    with pytest.raises(DiDUPError):
        async with _client():
            pass
