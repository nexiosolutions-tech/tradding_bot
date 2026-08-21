"""Classificação setorial real da B3 — spec 14, Seção 6.1/13.

Fixture `tests/fixtures/b3_setor/getdetail_real_samples.json`: quatro respostas reais do
endpoint `GetDetail` capturadas em 2026-08-21 — Petrobras e Itaú (cobertura real, com
classificação completa) e dois `codeCVM` genuinamente sem cobertura hoje (registro antigo
do Itaú pré-reestruturação, cancelado, e Banco Cruzeiro do Sul, falido) — os dois devolvem
payload vazio de verdade, não fabricado, confirmando empiricamente que a fonte só cobre
empresa listada hoje (spec 14, Seção 13).
"""

import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from tradingbot.acoes.b3_setor import (
    _normalize_cnpj,
    ingest_classification_snapshot,
    parse_industry_classification,
)
from tradingbot.acoes.models import B3IndustryClassification
from tradingbot.acoes.persistence import get_session_factory

FIXTURE = Path(__file__).parent / "fixtures" / "b3_setor" / "getdetail_real_samples.json"


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_b3_setor_test.db")
    return factory()


def _load_fixture():
    return json.loads(FIXTURE.read_text())


def test_normalize_cnpj_real_format():
    assert _normalize_cnpj("33000167000101") == "33.000.167/0001-01"
    assert _normalize_cnpj("60872504000123") == "60.872.504/0001-23"


def test_parse_industry_classification_tres_niveis_reais():
    """Petrobras real: setor e subsetor idênticos (só um subsetor dentro do setor),
    segmento diferente — confirma que o parser não assume que os três níveis são sempre
    distintos entre si."""
    setor, subsetor, segmento = parse_industry_classification(
        "Petróleo. Gás e Biocombustíveis / Petróleo. Gás e Biocombustíveis / "
        "Exploração. Refino e Distribuição"
    )
    assert setor == "Petróleo. Gás e Biocombustíveis"
    assert subsetor == "Petróleo. Gás e Biocombustíveis"
    assert segmento == "Exploração. Refino e Distribuição"

    setor, subsetor, segmento = parse_industry_classification(
        "Financeiro / Intermediários Financeiros / Bancos"
    )
    assert (setor, subsetor, segmento) == ("Financeiro", "Intermediários Financeiros", "Bancos")


def test_parse_industry_classification_vazio_devolve_none():
    assert parse_industry_classification("") is None
    assert parse_industry_classification(None) is None


def test_ingest_classification_snapshot_cobertura_real(tmp_path):
    """Duas empresas com classificação real (Petrobras, Itaú) e duas sem cobertura hoje
    (registro antigo cancelado do Itaú, Banco Cruzeiro do Sul falido) — a mesma amostra
    real que expôs o achado de cobertura de 85% sobre o universo de 2016."""
    session = _session(tmp_path)
    fixture = _load_fixture()
    raw_entries = [v["raw"] | {"codeCVM": v["codeCVM"]} for v in fixture.values()]

    stats = ingest_classification_snapshot(session, raw_entries, date(2026, 8, 21))

    assert stats.inserted == 2
    assert stats.sem_cobertura == 2

    petr = session.execute(
        select(B3IndustryClassification).where(
            B3IndustryClassification.cnpj == "33.000.167/0001-01"
        )
    ).scalar_one()
    assert petr.setor == "Petróleo. Gás e Biocombustíveis"
    assert petr.segmento == "Exploração. Refino e Distribuição"

    itau = session.execute(
        select(B3IndustryClassification).where(
            B3IndustryClassification.cnpj == "60.872.504/0001-23"
        )
    ).scalar_one()
    assert itau.setor == "Financeiro"
    assert itau.segmento == "Bancos"


def test_ingest_classification_snapshot_e_append_only(tmp_path):
    session = _session(tmp_path)
    fixture = _load_fixture()
    raw_entries = [v["raw"] | {"codeCVM": v["codeCVM"]} for v in fixture.values()]

    first = ingest_classification_snapshot(session, raw_entries, date(2026, 8, 21))
    assert first.inserted == 2

    second = ingest_classification_snapshot(session, raw_entries, date(2026, 8, 21))
    assert second.inserted == 0
    assert second.rejected_duplicate == 2

    # nova data_coleta: mesma empresa, snapshot novo, nao e duplicata
    third = ingest_classification_snapshot(session, raw_entries, date(2026, 9, 1))
    assert third.inserted == 2
