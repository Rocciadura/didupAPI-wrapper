"""Eccezioni custom della libreria didupwrapper.

Gli errori HTTP vengono mappati sulle eccezioni qui definite tramite
:func:`from_response`, in modo che il chiamante possa gestire i vari casi
(autenticazione, rate limit, risorsa non trovata...) in modo esplicito.
"""

from __future__ import annotations

from typing import Any

import httpx

__all__ = [
    "DiDUPError",
    "AuthError",
    "RateLimitError",
    "NotFoundError",
    "from_response",
]


class DiDUPError(Exception):
    """Errore generico della libreria didupwrapper.

    Tutte le altre eccezioni ereditano da questa, quindi un singolo
    ``except DiDUPError`` cattura qualunque problema sollevato dal wrapper.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
        request_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload
        self.request_url = request_url

    def __str__(self) -> str:  # pragma: no cover - cosmetico
        parti = [self.message]
        if self.status_code is not None:
            parti.append(f"(HTTP {self.status_code})")
        if self.request_url:
            parti.append(f"-> {self.request_url}")
        return " ".join(parti)


class AuthError(DiDUPError):
    """Credenziali mancanti/non valide o sessione scaduta (HTTP 401/403)."""


class RateLimitError(DiDUPError):
    """Troppe richieste verso il server DiDUP (HTTP 429)."""

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class NotFoundError(DiDUPError):
    """Risorsa o endpoint non trovato (HTTP 404)."""


def from_response(response: httpx.Response) -> DiDUPError:
    """Costruisce l'eccezione adeguata a partire da una risposta HTTP di errore."""
    status = response.status_code
    url = str(response.request.url) if response.request else None

    # Proviamo a estrarre un messaggio utile dal corpo della risposta.
    payload: Any
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        payload = response.text or None

    message = _estrai_messaggio(payload) or f"Richiesta DiDUP fallita ({status})"

    if status in (401, 403):
        return AuthError(message, status_code=status, payload=payload, request_url=url)
    if status == 404:
        return NotFoundError(message, status_code=status, payload=payload, request_url=url)
    if status == 429:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        return RateLimitError(
            message,
            status_code=status,
            payload=payload,
            request_url=url,
            retry_after=retry_after,
        )
    return DiDUPError(message, status_code=status, payload=payload, request_url=url)


def _estrai_messaggio(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for chiave in ("msg", "message", "error", "errore", "messaggio"):
            valore = payload.get(chiave)
            if isinstance(valore, str) and valore.strip():
                return valore
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
