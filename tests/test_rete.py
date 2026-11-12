"""Server lenti o irraggiungibili: timeout, errori di rete e nuovi tentativi."""

from __future__ import annotations

import httpx
import pytest
import respx

from didupwrapper import (
    AuthError,
    DashboardPoller,
    DiDUPClient,
    DiDUPError,
    NetworkError,
    RequestTimeoutError,
)
from didupwrapper.auth import Autenticatore, Credenziali

from .test_client import BASE_URL, CONFIG, DASHBOARD_RESPONSE, LOGIN_RESPONSE


@pytest.fixture(autouse=True)
def _niente_attese(monkeypatch: pytest.MonkeyPatch) -> None:
    # I test non devono aspettare davvero tra un tentativo e l'altro.
    monkeypatch.setattr("didupwrapper.client._ATTESA_RITENTATIVO", 0.0)


def _client(**kwargs: object) -> DiDUPClient:
    return DiDUPClient(config=CONFIG, access_token="fake-oauth-token", **kwargs)  # type: ignore[arg-type]


def _mock_login() -> respx.Route:
    return respx.post(f"{BASE_URL}login").mock(
        return_value=httpx.Response(200, json=LOGIN_RESPONSE)
    )


@respx.mock
@pytest.mark.asyncio
async def test_timeout_passeggero_viene_ritentato():
    _mock_login()
    dashboard = respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        side_effect=[
            httpx.ReadTimeout("lento"),
            httpx.Response(200, json=DASHBOARD_RESPONSE),
        ]
    )

    async with _client() as didup:
        voti = await didup.get_voti()

    assert len(voti) == 1
    assert dashboard.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_timeout_persistente_diventa_request_timeout_error():
    _mock_login()
    dashboard = respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        side_effect=httpx.ReadTimeout("lento")
    )

    async with _client(tentativi=2) as didup:
        with pytest.raises(RequestTimeoutError) as info:
            await didup.get_voti()

    # Deve essere catturabile con le eccezioni della libreria, non quelle di httpx.
    assert isinstance(info.value, NetworkError)
    assert isinstance(info.value, DiDUPError)
    assert info.value.request_url == f"{BASE_URL}dashboard/dashboard"
    assert dashboard.call_count == 3  # il primo + 2 nuovi tentativi


@respx.mock
@pytest.mark.asyncio
async def test_errore_di_connessione_diventa_network_error():
    respx.post(f"{BASE_URL}login").mock(side_effect=httpx.ConnectError("rete giù"))

    with pytest.raises(NetworkError) as info:
        async with _client(tentativi=0):
            pass

    assert not isinstance(info.value, RequestTimeoutError)
    assert "rete giù" in str(info.value)


@respx.mock
@pytest.mark.asyncio
async def test_503_viene_ritentato():
    _mock_login()
    dashboard = respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        side_effect=[
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json=DASHBOARD_RESPONSE),
        ]
    )

    async with _client() as didup:
        await didup.get_dashboard()

    assert dashboard.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_errori_non_passeggeri_non_vengono_ritentati():
    login = respx.post(f"{BASE_URL}login").mock(return_value=httpx.Response(401))

    with pytest.raises(AuthError):
        async with _client():
            pass

    assert login.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_tentativi_zero_non_riprova():
    _mock_login()
    dashboard = respx.post(f"{BASE_URL}dashboard/dashboard").mock(
        side_effect=httpx.ReadTimeout("lento")
    )

    async with _client(tentativi=0) as didup:
        with pytest.raises(RequestTimeoutError):
            await didup.get_dashboard()

    assert dashboard.call_count == 1


def test_tentativi_negativi_rifiutati():
    with pytest.raises(ValueError):
        _client(tentativi=-1)


def test_timeout_arriva_anche_al_login_oauth():
    didup = _client(timeout=123.0)
    assert didup._auth.timeout == 123.0
    assert didup._http.timeout.read == 123.0


@respx.mock
@pytest.mark.asyncio
async def test_timeout_nel_login_oauth_diventa_request_timeout_error():
    auth = Autenticatore(Credenziali("SC1", "u", "p"))
    respx.get(url__startswith=auth.config.oauth_auth_url).mock(
        side_effect=httpx.ConnectTimeout("lento")
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(RequestTimeoutError) as info:
            await auth.login(http)

    # Niente query string (state, challenge PKCE...) nel messaggio.
    assert info.value.request_url == auth.config.oauth_auth_url


@respx.mock
@pytest.mark.asyncio
async def test_poller_sopravvive_al_timeout(caplog: pytest.LogCaptureFixture):
    _mock_login()
    respx.post(f"{BASE_URL}dashboard/dashboard").mock(side_effect=httpx.ReadTimeout("lento"))

    async with _client(tentativi=0) as didup:
        poller = DashboardPoller(didup, intervallo=0.01)
        giri = 0

        async def tick_e_ferma() -> None:
            nonlocal giri
            giri += 1
            if giri == 2:
                poller.stop()
            await DashboardPoller.tick(poller)

        poller.tick = tick_e_ferma  # type: ignore[method-assign]
        await poller.start()

    assert giri == 2
    assert "Giro di polling saltato" in caplog.text
