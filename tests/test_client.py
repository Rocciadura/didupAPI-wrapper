"""Test del client async con HTTP mockato (respx).

L'OAuth/PKCE viene saltato passando un ``access_token`` già pronto: si
testano così lo step di login applicativo e il parsing della dashboard.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from didupwrapper import AuthError, DashboardPoller, DiDUPClient, DiDUPClientSync, DiDUPError
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


@respx.mock
@pytest.mark.asyncio
async def test_versione_superata_410_spiega_il_problema():
    respx.post(f"{BASE_URL}login").mock(return_value=httpx.Response(410, text=""))
    with pytest.raises(DiDUPError, match="auto_versione"):
        async with _client():
            pass


@respx.mock
@pytest.mark.asyncio
async def test_dashboard_vuota_solleva_didup_error():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )
    respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"dati": []}})
    )
    async with _client() as didup:
        with pytest.raises(DiDUPError):
            await didup.get_dashboard()


@respx.mock
@pytest.mark.asyncio
async def test_risposta_non_json_solleva_didup_error():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, text="<html>manutenzione</html>")
    )
    with pytest.raises(DiDUPError):
        async with _client():
            pass


@respx.mock
@pytest.mark.asyncio
async def test_login_fallito_chiude_il_client_http():
    respx.post(f"{BASE_URL}login").mock(return_value=httpx.Response(401))
    didup = _client()
    with pytest.raises(AuthError):
        async with didup:
            pass
    assert didup._http.is_closed


@respx.mock
def test_client_sync_login_fallito_chiude_il_loop():
    respx.post(f"{BASE_URL}login").mock(return_value=httpx.Response(401))
    didup = DiDUPClientSync(config=CONFIG, access_token="fake-oauth-token")
    with pytest.raises(AuthError):
        with didup:
            pass
    assert didup._loop.is_closed()


@respx.mock
@pytest.mark.asyncio
async def test_poller_notifica_solo_le_novita():
    respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )
    route = respx.post(f"{BASE_URL}dashboard/dashboard")
    route.mock(return_value=httpx.Response(200, json=DASHBOARD_RESPONSE))

    ricevuti: list = []

    def on_voti(nuovi):
        # Restituisce un Future invece di una coroutine: va comunque atteso.
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        ricevuti.extend(nuovi)
        return fut

    async with _client() as didup:
        poller = DashboardPoller(didup, on_nuovi_voti=on_voti)
        await poller.tick()  # primo giro: prende solo nota
        assert ricevuti == []

        nuovo = {**DASHBOARD_JSON, "voti": DASHBOARD_JSON["voti"] + [
            {**DASHBOARD_JSON["voti"][0], "datEvento": "2026-05-25", "codCodice": "9"}
        ]}
        route.mock(
            return_value=httpx.Response(200, json={"success": True, "data": {"dati": [nuovo]}})
        )
        evento = await poller.tick()
        assert [v.cod_codice for v in ricevuti] == ["9"]
        assert evento.ha_novita
