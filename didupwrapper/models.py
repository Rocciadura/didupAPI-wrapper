"""I modelli Pydantic con cui rappresentiamo le risposte di DiDUP.

Sono costruiti guardando le risposte vere di ``dashboard/dashboard`` (e gli
schemi del progetto ``portaleargo-api``). Qualche cosa da sapere prima di
usarli:

* le chiavi primarie (``pk*``) sono **stringhe** — hash esadecimali — non numeri;
* flag come ``faMenoMedia`` o ``flgVisibileFamiglia`` arrivano come ``"S"``/``"N"``
  e li trasformiamo in ``bool``;
* Argo manda spesso ``null`` al posto di stringhe vuote o liste vuote: in quei
  casi teniamo semplicemente il valore di default del campo.

Tutti i modelli ereditano da :class:`DiDUPModel`, che accetta i nomi camelCase
dell'API e ignora i campi che non conosciamo, così un campo nuovo lato server
non ci fa saltare il parsing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

__all__ = [
    "DiDUPModel",
    "Compito",
    "Allegato",
    "Voto",
    "EventoAppello",
    "RegistroLezione",
    "NotaDisciplinare",
    "Promemoria",
    "ComunicazioneBacheca",
    "FileBachecaAlunno",
    "FuoriClasse",
    "Materia",
    "Docente",
    "Periodo",
    "DettaglioPrenotazione",
    "Prenotazione",
    "DashboardResponse",
]


def _si_no_to_bool(v: Any) -> Any:
    """Trasforma i flag ``"S"``/``"N"`` di Argo in ``True``/``False``.

    Se arriva già un bool (o ``None``) lo lasciamo com'è.
    """
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, str):
        return v.strip().upper() in ("S", "SI", "TRUE", "1")
    return bool(v)


class DiDUPModel(BaseModel):
    """Base di tutti i modelli: nomi camelCase, campi extra ignorati, ``null`` tollerati."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _ignora_null(cls, dati: Any) -> Any:
        # Un campo a null equivale a "non c'è": così vale il default del modello
        # invece di far fallire la validazione su un campo tipo `str = ""`.
        if isinstance(dati, dict):
            return {k: v for k, v in dati.items() if v is not None}
        return dati


# --------------------------------------------------------------------------- #
# Sotto-modelli                                                                #
# --------------------------------------------------------------------------- #
class Compito(DiDUPModel):
    compito: str = ""
    data_consegna: str = ""


class Allegato(DiDUPModel):
    nome_file: str = ""
    url: str = ""
    path: str = ""
    descrizione_file: str | None = None
    pk: str = ""


# --------------------------------------------------------------------------- #
# Modelli principali                                                           #
# --------------------------------------------------------------------------- #
class Voto(DiDUPModel):
    dat_evento: str = ""
    dat_giorno: str = ""
    valore: float | None = None
    cod_codice: str = ""          # es. "8--"
    cod_voto_pratico: str = ""    # "S" = Scritto, "N" = Orale
    docente: str = ""
    pk_materia: str = ""
    pk_docente: str = ""
    des_materia: str = ""
    materia_light: dict[str, Any] = Field(default_factory=dict)
    descrizione_prova: str = ""
    descrizione_voto: str = ""
    des_commento: str = ""
    mese: int | None = None
    num_media: float | None = None
    prg_voto: int | None = None
    pk_periodo: str = ""
    tipo_valutazione: str | None = None
    fa_meno_media: bool = False
    cod_tipo: str = ""

    _v_fa_meno_media = field_validator("fa_meno_media", mode="before")(_si_no_to_bool)

    @property
    def is_scritto(self) -> bool:
        return self.cod_voto_pratico.upper() == "S"

    @property
    def is_orale(self) -> bool:
        return self.cod_voto_pratico.upper() == "N"


class EventoAppello(DiDUPModel):
    cod_evento: str = ""          # "A" = Assenza, "I" = Ritardo, "U" = Uscita
    data: str = ""
    dat_evento: str = ""
    giustificata: str = ""        # "S" o "N"
    da_giustificare: bool = False
    data_giustificazione: str | None = None
    commento_giustificazione: str | None = None
    docente: str = ""
    descrizione: str = ""
    nota: str | None = None

    @property
    def is_assenza(self) -> bool:
        return self.cod_evento.upper() == "A"

    @property
    def is_ritardo(self) -> bool:
        return self.cod_evento.upper() == "I"

    @property
    def is_uscita(self) -> bool:
        return self.cod_evento.upper() == "U"

    @property
    def is_giustificata(self) -> bool:
        return self.giustificata.upper() == "S"


class RegistroLezione(DiDUPModel):
    dat_giorno: str = ""
    dat_evento: str = ""
    docente: str = ""
    materia: str = ""
    pk_materia: str = ""
    pk_docente: str = ""
    ora: int | None = None
    is_firmato: bool = False
    attivita: str | None = None
    des_url: str | None = None
    compiti: list[Compito] = Field(default_factory=list)


class NotaDisciplinare(DiDUPModel):
    data: str = ""
    dat_giorno: str = ""
    dat_evento: str = ""
    docente: str = ""
    descrizione: str = ""


class Promemoria(DiDUPModel):
    dat_evento: str = ""
    dat_giorno: str = ""
    des_annotazioni: str = ""
    docente: str = ""
    pk_docente: str = ""
    ora_inizio: str = ""
    ora_fine: str = ""
    flg_visibile_famiglia: bool = True

    _v_flg = field_validator("flg_visibile_famiglia", mode="before")(_si_no_to_bool)


class ComunicazioneBacheca(DiDUPModel):
    dat_evento: str = ""
    data: str = ""
    messaggio: str = ""
    autore: str = ""
    categoria: str = ""
    pv_richiesta: bool = False
    is_presa_visione: bool = False
    data_conferma_presa_visione: str | None = None
    ad_richiesta: bool = False
    is_presa_adesione_confermata: bool = False
    data_conferma_adesione: str | None = None
    data_scadenza: str | None = None
    data_scad_adesione: str | None = None
    url: str | None = None
    lista_allegati: list[Allegato] = Field(default_factory=list)

    @property
    def da_leggere(self) -> bool:
        """True se è richiesta la presa visione e non è ancora stata data."""
        return self.pv_richiesta and not self.is_presa_visione


class FileBachecaAlunno(DiDUPModel):
    dat_evento: str = ""
    data: str = ""
    nome_file: str = ""
    messaggio: str = ""
    flg_download_genitore: bool = False
    is_presa_visione: bool = False

    _v_flg = field_validator("flg_download_genitore", mode="before")(_si_no_to_bool)


class FuoriClasse(DiDUPModel):
    dat_evento: str = ""
    data: str = ""
    descrizione: str = ""
    docente: str = ""
    nota: str | None = None
    frequenza_on_line: bool = False


class Materia(DiDUPModel):
    pk: str = ""
    materia: str = ""
    abbreviazione: str = ""
    fa_media: bool = False
    scrut: bool = False
    cod_tipo: str = ""


class Docente(DiDUPModel):
    pk: str = ""
    des_nome: str = ""
    des_cognome: str = ""
    des_email: str = ""
    materie: list[str] = Field(default_factory=list)

    @property
    def nome_completo(self) -> str:
        return f"{self.des_nome} {self.des_cognome}".strip()


class Periodo(DiDUPModel):
    pk_periodo: str = ""
    cod_periodo: str = ""         # "1Q", "2Q", "SF", "*"
    descrizione: str = ""
    dat_inizio: str | None = None
    data_inizio: str = ""
    dat_fine: str | None = None
    data_fine: str = ""
    voto_unico: bool = False
    media_scrutinio: float | None = None
    is_media_scrutinio: bool = False
    is_scrutinio_finale: bool = False


class DettaglioPrenotazione(DiDUPModel):
    pk: str = ""
    prg_scuola: int | None = None
    dat_prenotazione: str = ""
    num_prenotazione: int | None = None
    prg_alunno: int | None = None


class Prenotazione(DiDUPModel):
    dat_evento: str = ""
    prenotazione: DettaglioPrenotazione | None = None


# --------------------------------------------------------------------------- #
# Risposta principale della dashboard                                          #
# --------------------------------------------------------------------------- #
class DashboardResponse(DiDUPModel):
    """Tutto quello che restituisce ``dashboard/dashboard`` (il blocco ``dati[0]``).

    Argo manda quasi tutto in questa unica risposta; gli endpoint poi pescano
    e filtrano la parte che gli interessa.
    """

    media_generale: float | None = None
    msg: str = ""
    pk: str = ""
    ricarica_dati: bool = False
    profilo_disabilitato: bool = False
    rimuovi_dati_locali: bool = False
    classi_extra: bool = False
    data_aggiornamento: str = ""

    voti: list[Voto] = Field(default_factory=list)
    appello: list[EventoAppello] = Field(default_factory=list)
    registro: list[RegistroLezione] = Field(default_factory=list)
    note_disciplinari: list[NotaDisciplinare] = Field(default_factory=list)
    promemoria: list[Promemoria] = Field(default_factory=list)
    bacheca: list[ComunicazioneBacheca] = Field(default_factory=list)
    bacheca_alunno: list[FileBachecaAlunno] = Field(default_factory=list)
    fuori_classe: list[FuoriClasse] = Field(default_factory=list)
    lista_materie: list[Materia] = Field(default_factory=list)
    lista_docenti_classe: list[Docente] = Field(default_factory=list)
    lista_periodi: list[Periodo] = Field(default_factory=list)
    prenotazioni_alunni: list[Prenotazione] = Field(default_factory=list)
