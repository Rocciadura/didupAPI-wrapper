# didupwrapper

[![PyPI](https://img.shields.io/pypi/v/didupwrapper.svg)](https://pypi.org/project/didupwrapper/)
[![Python](https://img.shields.io/pypi/pyversions/didupwrapper.svg)](https://pypi.org/project/didupwrapper/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Libreria Python, sincrona e asincrona, per accedere ai dati del registro
elettronico **DiDUP / Argo Famiglia**: voti, assenze, registro di classe,
bacheca, promemoria e altro, restituiti come modelli tipizzati Pydantic v2.

> [!IMPORTANT]
> Progetto **non ufficiale**, sviluppato in modo indipendente e **non
> affiliato, approvato o supportato da Argo Software S.r.l.** Le API
> utilizzate non sono pubbliche né documentate: sono state ricostruite
> osservando il traffico dell'app ufficiale e possono cambiare in qualsiasi
> momento senza preavviso. Leggi la sezione [Note legali](#note-legali) prima
> dell'uso.

## Indice

- [Caratteristiche](#caratteristiche)
- [Requisiti e installazione](#requisiti-e-installazione)
- [Guida rapida](#guida-rapida)
- [Versione del client](#versione-del-client)
- [Riferimento API](#riferimento-api)
- [Gestione degli errori](#gestione-degli-errori)
- [Notifiche sulle novità](#notifiche-sulle-novità)
- [Sviluppo](#sviluppo)
- [Note legali](#note-legali)
- [Contatti e richieste di rimozione](#contatti-e-richieste-di-rimozione)
- [Licenza](#licenza)

## Caratteristiche

- Client **asincrono** (`DiDUPClient`) e **sincrono** (`DiDUPClientSync`) con la
  stessa interfaccia.
- Login completo OAuth2/PKCE, identico a quello dell'app ufficiale.
- Risposte validate e tipizzate con **Pydantic v2**, tolleranti a campi
  mancanti, `null` e campi aggiunti in futuro dal server.
- Cache della dashboard: più chiamate consecutive generano una sola richiesta.
- Eccezioni dedicate per autenticazione, rate limit, risorse non trovate e
  versione del client superata.
- `DashboardPoller` per ricevere callback solo quando compaiono nuovi dati.
- Pacchetto completamente tipizzato (`py.typed`).

## Requisiti e installazione

Serve Python **3.10** o successivo.

```bash
pip install didupwrapper
```

## Guida rapida

Per il login servono il **codice scuola** (es. `SC12345`), lo **username** e la
**password**, gli stessi usati nell'app DiDUP Famiglia.

### Client asincrono

```python
import asyncio
import os

from didupwrapper import DiDUPClient

async def main() -> None:
    async with DiDUPClient(
        os.environ["DIDUP_SCUOLA"],
        os.environ["DIDUP_USERNAME"],
        os.environ["DIDUP_PASSWORD"],
    ) as didup:
        print("Media generale:", await didup.get_media_generale())
        for voto in await didup.get_voti():
            print(voto.des_materia, voto.cod_codice)

asyncio.run(main())
```

### Client sincrono

```python
import os

from didupwrapper import DiDUPClientSync

with DiDUPClientSync(
    os.environ["DIDUP_SCUOLA"],
    os.environ["DIDUP_USERNAME"],
    os.environ["DIDUP_PASSWORD"],
) as didup:
    for voto in didup.get_voti():
        print(voto.des_materia, voto.cod_codice)
```

> [!TIP]
> Non inserire mai le credenziali nel codice sorgente: usa variabili d'ambiente
> o un gestore di segreti, come negli esempi.

## Versione del client

Per essere accettato dal server, ogni richiesta include l'header
`argo-client-version`, che deve corrispondere a una versione recente dell'app
pubblicata sugli store (il default attuale è **1.29.2**). Se la versione è
troppo vecchia il server risponde `410` e la libreria solleva un `DiDUPError`
che lo spiega.

Ci sono tre modi per gestirla:

```python
# 1. Default della libreria
DiDUPClient("SC12345", "user", "pwd")

# 2. Versione fissata a mano
DiDUPClient("SC12345", "user", "pwd", version="1.29.2")

# 3. Versione letta dall'App Store al momento del login (consigliato)
DiDUPClient("SC12345", "user", "pwd", auto_versione=True)
```

Per conoscere solo l'ultima versione pubblicata:

```python
from didupwrapper import recupera_versione_app

print(await recupera_versione_app())  # es. "1.29.2", oppure None se non raggiungibile
```

## Riferimento API

### Metodi del client

Disponibili sia su `DiDUPClient` (con `await`) sia su `DiDUPClientSync`.

| Metodo | Restituisce |
|---|---|
| `get_dashboard(forza_refresh=False)` | Tutti i dati aggregati (`DashboardResponse`) |
| `get_voti()` | Voti (`list[Voto]`) |
| `get_assenze()` | Assenze, ritardi e uscite (`list[EventoAppello]`) |
| `get_registro()` | Registro delle lezioni (`list[RegistroLezione]`) |
| `get_bacheca()` | Comunicazioni in bacheca (`list[ComunicazioneBacheca]`) |
| `get_bacheca_alunno()` | File della bacheca alunno (`list[FileBachecaAlunno]`) |
| `get_promemoria()` | Promemoria dei docenti (`list[Promemoria]`) |
| `get_fuori_classe()` | Attività fuori classe (`list[FuoriClasse]`) |
| `get_note_disciplinari()` | Note disciplinari (`list[NotaDisciplinare]`) |
| `get_materie()` | Materie (`list[Materia]`) |
| `get_docenti()` | Docenti della classe (`list[Docente]`) |
| `get_periodi()` | Periodi / quadrimestri (`list[Periodo]`) |
| `get_prenotazioni()` | Colloqui prenotati (`list[Prenotazione]`) |
| `get_media_generale()` | Media complessiva (`float \| None`) |
| `invalida_cache()` | Svuota la cache della dashboard |

La dashboard viene scaricata una volta e riutilizzata dalle chiamate
successive. Per dati aggiornati usa `get_dashboard(forza_refresh=True)` oppure
`invalida_cache()`.

### Filtri pronti (solo client asincrono)

```python
await didup.voti.per_materia(pk_materia)        # pk_materia è una stringa, es. voto.pk_materia
await didup.voti.media_per_materia(pk_materia)
await didup.voti.scritti()
await didup.assenze.da_giustificare()
await didup.bacheca.da_leggere()
await didup.registro.compiti()
await didup.fuori_classe.online()
```

Le chiavi primarie restituite da Argo (`pk_materia`, `pk_periodo`, ...) sono
**stringhe**, non numeri.

## Gestione degli errori

Tutte le eccezioni derivano da `DiDUPError`, che espone `status_code`,
`payload` e `request_url`.

| Eccezione | Quando |
|---|---|
| `AuthError` | Credenziali errate, sessione scaduta (HTTP 401/403) |
| `RateLimitError` | Troppe richieste (HTTP 429); vedi `retry_after` |
| `NotFoundError` | Risorsa inesistente (HTTP 404) |
| `DiDUPError` | Qualsiasi altro errore, incluso il `410` per versione superata |

```python
from didupwrapper import AuthError, DiDUPError

try:
    async with DiDUPClient(scuola, username, password) as didup:
        voti = await didup.get_voti()
except AuthError:
    print("Credenziali non valide")
except DiDUPError as errore:
    print("Errore:", errore)
```

## Notifiche sulle novità

`DashboardPoller` interroga la dashboard a intervalli regolari e chiama le
callback (normali funzioni o coroutine) solo per gli elementi nuovi. Al primo
giro registra lo stato iniziale senza notificare nulla, a meno di passare
`emetti_al_primo_giro=True`.

```python
from didupwrapper import DashboardPoller

async def on_nuovi_voti(nuovi):
    for voto in nuovi:
        print("Nuovo voto:", voto.des_materia, voto.cod_codice)

poller = DashboardPoller(didup, intervallo=600, on_nuovi_voti=on_nuovi_voti)
await poller.start()  # blocca finché non viene chiamato poller.stop()
```

Sono disponibili anche `on_nuove_assenze`, `on_nuove_comunicazioni`,
`on_nuove_note`, `on_nuovi_promemoria` e `on_evento` (riceve un `EventoPoller`
con tutte le novità del giro).

Usa intervalli ragionevoli (almeno qualche minuto): il servizio è pensato per
l'uso da parte di famiglie e studenti, non per interrogazioni continue.

## Sviluppo

```bash
git clone https://github.com/Rocciadura/didupAPI-wrapper.git
cd didupAPI-wrapper
pip install -e ".[dev]"

pytest            # test (HTTP simulato con respx, nessuna richiesta reale)
ruff check .      # lint
mypy didupwrapper # type checking
```

Contributi e segnalazioni sono benvenuti tramite
[issue](https://github.com/Rocciadura/didupAPI-wrapper/issues) e pull request.

## Note legali

- **Nessuna affiliazione.** Questo progetto non è affiliato, approvato né
  sostenuto da Argo Software S.r.l. "Argo", "DiDUP" e "Argo Famiglia" sono
  marchi dei rispettivi titolari e sono citati solo per indicare il servizio
  con cui la libreria è compatibile.
- **Uso consentito.** La libreria è pensata per accedere esclusivamente ai
  **propri** dati (o a quelli dei propri figli), con le **proprie**
  credenziali. Non usarla per accedere ad account altrui, raccogliere dati di
  terzi o sovraccaricare i server.
- **Termini del servizio.** L'utente è responsabile del rispetto dei termini
  d'uso di Argo e della normativa sulla protezione dei dati personali (GDPR).
- **Nessuna garanzia.** Il software è fornito "così com'è", senza garanzie di
  alcun tipo, come previsto dalla [licenza MIT](LICENSE).

## Contatti e richieste di rimozione

Se sei un rappresentante di **Argo Software** e ritieni che questo progetto
non debba essere pubblico, o vuoi che venga modificato, contattami: **il
repository e il pacchetto su PyPI verranno rimossi o modificati subito**, senza
bisogno di ulteriori formalità.

Puoi scrivermi:

- in privato, tramite una
  [segnalazione riservata su GitHub](https://github.com/Rocciadura/didupAPI-wrapper/security/advisories/new);
- in pubblico, aprendo una
  [issue](https://github.com/Rocciadura/didupAPI-wrapper/issues).

Lo stesso vale per eventuali problemi di sicurezza: segnalali in privato
tramite il primo canale, non con una issue pubblica.

## Licenza

Distribuito con licenza MIT. Vedi [LICENSE](LICENSE).
