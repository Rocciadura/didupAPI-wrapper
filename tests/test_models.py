"""Test di parsing dei modelli Pydantic dalla risposta dashboard."""

from __future__ import annotations

from didupwrapper.models import DashboardResponse

DASHBOARD_JSON = {
    "mediaGenerale": 7.85,
    "msg": "",
    "ricaricaDati": False,
    "profiloDisabilitato": False,
    "rimuoviDatiLocali": False,
    "classiExtra": False,
    "dataAggiornamento": "2026-05-31 08:00:00",
    "voti": [
        {
            "datEvento": "2026-05-20",
            "datGiorno": "2026-05-20",
            "valore": 8.0,
            "codCodice": "8--",
            "codVotoPratico": "S",
            "docente": "Rossi Mario",
            "pkMateria": "101",
            "pkDocente": "55",
            "desMateria": "Matematica",
            "materiaLight": {"codMateria": "MAT"},
            "descrizioneProva": "Verifica scritta",
            "descrizioneVoto": "Otto",
            "desCommento": "Bene",
            "mese": 5,
            "numMedia": 8.0,
            "prgVoto": 1,
            "pkPeriodo": "2",
            "tipoValutazione": None,
            "faMenoMedia": "N",
            "codTipo": "V",
        }
    ],
    "appello": [
        {
            "codEvento": "A",
            "data": "2026-05-18",
            "datEvento": "2026-05-18",
            "giustificata": "N",
            "daGiustificare": True,
            "docente": "Bianchi Anna",
            "descrizione": "Assenza",
        }
    ],
    "registro": [
        {
            "datGiorno": "2026-05-20",
            "datEvento": "2026-05-20",
            "docente": "Rossi Mario",
            "materia": "Matematica",
            "pkMateria": "101",
            "pkDocente": "55",
            "ora": 1,
            "isFirmato": True,
            "attivita": "Ripasso",
            "compiti": [{"compito": "Esercizi pag. 50", "dataConsegna": "2026-05-22"}],
        }
    ],
    "listaPeriodi": [
        {
            "pkPeriodo": "2",
            "codPeriodo": "2Q",
            "descrizione": "Secondo Quadrimestre",
            "datInizio": "2026-01-15",
            "dataInizio": "2026-01-15",
            "datFine": "2026-06-08",
            "dataFine": "2026-06-08",
            "votoUnico": True,
        }
    ],
}


def test_parsing_dashboard():
    dashboard = DashboardResponse.model_validate(DASHBOARD_JSON)
    assert dashboard.media_generale == 7.85
    assert len(dashboard.voti) == 1
    assert len(dashboard.appello) == 1
    assert len(dashboard.registro) == 1


def test_alias_camelcase_e_proprieta():
    dashboard = DashboardResponse.model_validate(DASHBOARD_JSON)
    voto = dashboard.voti[0]
    assert voto.pk_materia == "101"
    assert voto.des_materia == "Matematica"
    assert voto.is_scritto is True
    assert voto.is_orale is False
    assert voto.fa_meno_media is False  # "N" -> False

    evento = dashboard.appello[0]
    assert evento.is_assenza is True
    assert evento.is_giustificata is False
    assert evento.da_giustificare is True

    lezione = dashboard.registro[0]
    assert lezione.is_firmato is True
    assert lezione.compiti[0].data_consegna == "2026-05-22"

    periodo = dashboard.lista_periodi[0]
    assert periodo.cod_periodo == "2Q"


def test_campi_mancanti_usano_default():
    """La risposta minimale non deve far esplodere il parsing."""
    dashboard = DashboardResponse.model_validate({"msg": "ok"})
    assert dashboard.voti == []
    assert dashboard.media_generale is None


def test_campi_extra_ignorati():
    dashboard = DashboardResponse.model_validate(
        {"msg": "ok", "campoSconosciuto": 123}
    )
    assert dashboard.msg == "ok"
