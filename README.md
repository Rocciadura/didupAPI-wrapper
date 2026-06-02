# didupwrapper

Un wrapper Python per le API del registro elettronico **DiDUP / Argo Famiglia**,
con client sia sincrono che asincrono.

Le API di Argo non sono pubbliche né documentate: questa libreria nasce dal
reverse-engineering del traffico dell'app ufficiale. Funziona oggi, potrebbe
smettere domani se Argo cambia qualcosa. Usala con le **tue** credenziali e con
buon senso.

Una nota sulla versione del client: il login imita l'app reale, quindi mandiamo
un header `argo-client-version` che deve combaciare con l'ultima versione
pubblicata sugli store (al momento **1.29.2**). Se diventa troppo vecchio, il
server risponde `410` e non ti fa entrare. Più sotto trovi come gestirla.

## Installazione

```bash
pip install didupwrapper
```

Serve Python 3.10 o successivo.

## Come si usa

Il login vuole tre cose: il **codice scuola** (es. `SC12345`), lo **username** e
la **password** — le stesse che useresti nell'app.

### Versione asincrona

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

### Versione sincrona

Se non ti serve l'async, c'è la stessa identica interfaccia senza `await`:

```python
from didupwrapper import DiDUPClientSync

with DiDUPClientSync("SC12345", "mario.rossi", "password") as didup:
    for voto in didup.get_voti():
        print(voto.des_materia, voto.cod_codice)
```

Un consiglio ovvio ma importante: **non scrivere le credenziali nel codice**.
Tienile in variabili d'ambiente, tipo `os.environ["DIDUP_PASSWORD"]`.

## La versione del client (`argo-client-version`)

Hai tre modi per gestirla, dal più semplice al più a prova di futuro:

```python
# 1) Lascia il default (1.29.2) — il più semplice, finché regge
DiDUPClient("SC12345", "user", "pwd")

# 2) Fissala tu, se sai quale versione usare
DiDUPClient("SC12345", "user", "pwd", version="1.29.2")

# 3) Lasciala scoprire dallo store al login — sempre aggiornata
DiDUPClient("SC12345", "user", "pwd", auto_versione=True)
```

Se ti serve solo sapere qual è l'ultima versione sullo store:

```python
from didupwrapper import recupera_versione_app
print(await recupera_versione_app())  # es. "1.29.2"
```

## Cosa puoi chiedere

Questi metodi ci sono sia sul client async (con `await`) che su quello sync:

| Metodo | Cosa ti dà |
|---|---|
| `get_dashboard()` | tutti i dati in un colpo solo (`DashboardResponse`) |
| `get_voti()` | i voti (`list[Voto]`) |
| `get_assenze()` | assenze, ritardi, uscite (`list[EventoAppello]`) |
| `get_registro()` | il registro delle lezioni (`list[RegistroLezione]`) |
| `get_bacheca()` | le comunicazioni in bacheca (`list[ComunicazioneBacheca]`) |
| `get_bacheca_alunno()` | gli allegati per l'alunno (`list[FileBachecaAlunno]`) |
| `get_promemoria()` | i promemoria (`list[Promemoria]`) |
| `get_fuori_classe()` | le attività fuori classe (`list[FuoriClasse]`) |
| `get_note_disciplinari()` | le note (`list[NotaDisciplinare]`) |
| `get_materie()` | l'elenco materie (`list[Materia]`) |
| `get_docenti()` | i docenti (`list[Docente]`) |
| `get_periodi()` | i periodi/quadrimestri (`list[Periodo]`) |
| `get_prenotazioni()` | i colloqui prenotati (`list[Prenotazione]`) |
| `get_media_generale()` | la media complessiva (`float \| None`) |

I dati tornano come modelli **Pydantic v2**, quindi hai autocompletamento e
validazione gratis.

### Scorciatoie con i filtri

Sul client async ci sono anche degli endpoint con metodi pronti, così non devi
filtrare a mano:

```python
await didup.voti.per_materia(101)
await didup.voti.media_per_materia(101)
await didup.assenze.da_giustificare()
await didup.bacheca.da_leggere()
await didup.registro.compiti()
await didup.fuori_classe.online()
```

### Quando qualcosa va storto

Gli errori sono tipizzati, così li gestisci per quello che sono:
`AuthError` (credenziali o sessione), `RateLimitError` (troppe richieste),
`NotFoundError`, e `DiDUPError` come base di tutti.

## Tenere d'occhio le novità (poller)

Se vuoi essere avvisato quando arriva qualcosa di nuovo — un voto, un avviso in
bacheca — c'è il `DashboardPoller` che fa polling a intervalli e ti chiama
indietro solo sulle novità:

```python
from didupwrapper.workers import DashboardPoller

async def on_voti(nuovi):
    for v in nuovi:
        print("Nuovo voto:", v.des_materia, v.cod_codice)

poller = DashboardPoller(didup, intervallo=600, on_nuovi_voti=on_voti)
await poller.start()   # poller.stop() per fermarlo
```

## Licenza

MIT — vedi [LICENSE](LICENSE).
