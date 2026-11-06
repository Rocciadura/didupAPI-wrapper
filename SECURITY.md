# Sicurezza

## Versioni supportate

Le correzioni di sicurezza vengono rilasciate solo per l'ultima versione
pubblicata su [PyPI](https://pypi.org/project/didupwrapper/).

| Versione | Supportata |
| -------- | ---------- |
| ultima 0.x | ✅ |
| precedenti | ❌ |

## Segnalare una vulnerabilità

**Non aprire una issue pubblica** per problemi di sicurezza.

Segnalali in privato tramite la
[segnalazione riservata su GitHub](https://github.com/Rocciadura/didupAPI-wrapper/security/advisories/new)
(scheda *Security* → *Report a vulnerability*).

Nella segnalazione indica, se puoi:

- la versione di `didupwrapper` e di Python;
- una descrizione del problema e del suo impatto;
- i passi per riprodurlo.

**Non includere mai credenziali reali** (codice scuola, username, password),
token o dati personali di studenti: se servono esempi, usa dati inventati.

Riceverai una risposta appena possibile. Una volta confermato il problema,
verrà rilasciata una correzione e, se opportuno, pubblicato un advisory.

## Ambito

Rientrano in questa policy i problemi del codice di questa libreria, ad
esempio:

- credenziali, token o dati personali esposti in log, messaggi di errore o
  eccezioni;
- gestione errata di cookie o token durante il login;
- dipendenze vulnerabili usate dalla libreria.

Se rappresenti **Argo Software** e ritieni che questa libreria non debba
essere pubblica, scrivimi tramite la
[segnalazione riservata](https://github.com/Rocciadura/didupAPI-wrapper/security/advisories/new):
il repository e il pacchetto su PyPI verranno rimossi immediatamente.
