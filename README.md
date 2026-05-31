# didupwrapper

Wrapper Python **open-source** (sync + async) per le API **non documentate** del
registro elettronico **DiDUP / Argo Famiglia**.

> Le API non sono pubbliche né documentate da Argo. Questa libreria è basata
> su reverse-engineering del traffico dell'app. Usala in modo responsabile e
> solo con le tue credenziali.
>
> Il login usa il vero flusso **OAuth2/PKCE** dell'app DidUP Famiglia. L'header
> `argo-client-version` deve combaciare con l'ultima versione dell'app sugli
> store (attualmente **1.29.2**): se diventa obsoleto il server risponde `410`.

## Caratteristiche

- Python 3.10+
- Client **async** (`DiDUPClient`) e **sync** (`DiDUPClientSync`)
- Modelli **Pydantic v2** con alias camelCase automatici
- Eccezioni tipizzate: `AuthError`, `RateLimitError`, `NotFoundError`, `DiDUPError`
- Worker `DashboardPoller` per ricevere notifiche di novità (voti, bacheca, ...)
- Packaging con `hatchling` + `pyproject.toml`

## Installazione

```bash
pip install didupwrapper
```

## Uso rapido

### Async

```python
import asyncio
from didupwrapper import DiDUPClient

async def main():
    async with DiDUPClient("SC12345", "mario.rossi", "password") as didup:
        print("Media:", await didup.get_media_generale())
        for voto in await didup.get_voti():
            print(voto.des_materia, voto.cod_codice)

asyncio.run(main())
```

### Sync

```python
from didupwrapper import DiDUPClientSync

with DiDUPClientSync("SC12345", "mario.rossi", "password") as didup:
    for voto in didup.get_voti():
        print(voto.des_materia, voto.cod_codice)
```

> Suggerimento: non mettere mai le credenziali in chiaro nel codice. Usa le
> variabili d'ambiente, ad esempio `os.environ["DIDUP_PASSWORD"]`.

### Versione client (`argo-client-version`)

Tre modi, in ordine di priorità:

```python
# 1) Versione fissa di default (1.29.2)
DiDUPClient("SC12345", "user", "pwd")

# 2) Versione fissa esplicita
DiDUPClient("SC12345", "user", "pwd", version="1.29.2")

# 3) Auto-rilevamento dall'App Store al login (sempre aggiornata)
DiDUPClient("SC12345", "user", "pwd", auto_versione=True)
```

Puoi anche solo interrogare lo store:

```python
from didupwrapper import recupera_versione_app
print(await recupera_versione_app())  # es. "1.29.2"
```

## Metodi principali

Tutti disponibili sia sul client async (con `await`) che su quello sync:

| Metodo | Ritorna |
|---|---|
| `get_dashboard()` | `DashboardResponse` (dati aggregati) |
| `get_voti()` | `list[Voto]` |
| `get_assenze()` | `list[EventoAppello]` |
| `get_registro()` | `list[RegistroLezione]` |
| `get_bacheca()` | `list[ComunicazioneBacheca]` |
| `get_bacheca_alunno()` | `list[FileBachecaAlunno]` |
| `get_promemoria()` | `list[Promemoria]` |
| `get_fuori_classe()` | `list[FuoriClasse]` |
| `get_note_disciplinari()` | `list[NotaDisciplinare]` |
| `get_materie()` | `list[Materia]` |
| `get_docenti()` | `list[Docente]` |
| `get_periodi()` | `list[Periodo]` |
| `get_prenotazioni()` | `list[Prenotazione]` |
| `get_media_generale()` | `float \| None` |

### Endpoint con filtri

Il client async espone anche oggetti endpoint con metodi di filtro:

```python
await didup.voti.per_materia(101)
await didup.voti.media_per_materia(101)
await didup.assenze.da_giustificare()
await didup.bacheca.da_leggere()
await didup.registro.compiti()
await didup.fuori_classe.online()
```

## Monitoraggio (poller)

```python
from didupwrapper.workers import DashboardPoller

async def on_voti(nuovi):
    for v in nuovi:
        print("Nuovo voto:", v.des_materia, v.cod_codice)

poller = DashboardPoller(didup, intervallo=600, on_nuovi_voti=on_voti)
await poller.start()   # ferma con poller.stop()
```

## Licenza

MIT — vedi [LICENSE](LICENSE).
