"""Fase 1 do módulo de Ações — `cnpj_ticker_map` (spec 14, Seção 5.4/5.5/5.6).

Fixtures reais:

- `tests/fixtures/fca/valor_mobiliario_AAAA.csv` — arquivos completos da era confiável
  (2018-2022, 2024, 2025) baixados de `dados.cvm.gov.br`, sem corte — pequenos o
  suficiente (~130-175KB cada) para versionar inteiros.
- `tests/fixtures/cnpj_ticker_map/universo_auditado_2010_2017.json` — os universos
  elegíveis EXATOS (não re-derivados) dos seis anos já auditados em rodadas anteriores
  desta spec (`changes/2026-08-20-modulo-acoes-b3-propagacao-cnpj-dois-pisos.md` e
  `changes/2026-08-20-modulo-acoes-b3-fronteira-2015-2026.md`), extraídos dos `.pkl`
  daquelas medições — não recalculados por um filtro de liquidez reimplementado nesta
  sessão (uma tentativa de reimplementar deu 164 e depois 171 tickers para 2010, dois
  números diferentes entre si e do 159 original, por bugs bobos de um script descartável
  — usar o universo congelado elimina esse risco de vez).
- `tests/fixtures/cotahist/COTAHIST_A2019_krot_cogn_real_extract.ZIP` +
  `..._A2020_cogn_real_extract.ZIP` — linhas reais da transição `KROT3`(até 2019-10-10)
  → `COGN3`(a partir de 2019-10-11), mais um punhado de linhas de `COGN3` em maio/2020
  só para empurrar a data-fim da janela observada além da tolerância de 180 dias e
  fechar a vigência de `KROT3` de verdade (sem isso, `KROT3` ficaria "ainda vigente" por
  pura falta de dado posterior, não por estar errado).

Achado de auditoria desta rodada, registrado em `cnpj_ticker_map.py`
(`_GENERIC_NAME_TOKENS`): dos 50 matches de `reconciliacao_nome` nos seis anos
auditados, 4 eram falsos positivos por token de nome que colide com empresa não
relacionada (`TELEC`, `IMOB`, `CRUZEIRO`, `RAIA`) — confirmados um a um contra
`cad_cia_aberta.csv` (registro CVM completo). Os 4 casos ficam hardcoded neste arquivo
como teste negativo, não como parte do fixture de universo (nenhum dos quatro está nos
anos 2015/2017 usados para a checagem de `reconciliacao_nome`).
"""

import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from tradingbot.acoes.cnpj_ticker_map import (
    build_cnpj_ticker_map,
    compute_vigencia,
    get_cnpj_as_of,
    load_fca_identity,
    resolve_identity,
)
from tradingbot.acoes.models import CnpjTickerMap, UnresolvedTicker
from tradingbot.acoes.persistence import get_session_factory

FCA_DIR = Path(__file__).parent / "fixtures" / "fca"
COTAHIST_DIR = Path(__file__).parent / "fixtures" / "cotahist"
FIXTURE_JSON = Path(__file__).parent / "fixtures" / "cnpj_ticker_map" / "universo_auditado_2010_2017.json"

CONFIABLE_FCA_YEARS = [2018, 2019, 2020, 2021, 2022, 2024, 2025]
FCA_PATHS = [FCA_DIR / f"valor_mobiliario_{y}.csv" for y in CONFIABLE_FCA_YEARS]

COGNA_CNPJ = "02.800.026/0001-40"  # Kroton -> Cogna Educação, mesmo CNPJ, ticker mudou

KROT2019_ZIP = COTAHIST_DIR / "COTAHIST_A2019_krot_cogn_real_extract.ZIP"
COGN2020_ZIP = COTAHIST_DIR / "COTAHIST_A2020_cogn_real_extract.ZIP"

# Falsos positivos confirmados por auditoria manual (2026-08-20) contra
# cad_cia_aberta.csv — cada um colidiu com uma empresa REAL não relacionada, não é
# apenas "token curto":
NEGATIVOS_CONFIRMADOS = [
    ("BRTO3", "BRASIL TELEC"),  # Brasil Telecom != Telebrás (mesma abreviação "TELEC")
    ("CCIM3", "CC DES IMOB"),  # CC Desenvolv. Imob. != BRPR56 Securitizadora
    ("CZRS4", "CRUZEIRO SUL"),  # Banco Cruzeiro do Sul (falido) != Cruzeiro do Sul Educacional
    ("RAIA3", "RAIA"),  # Droga Raia pré-fusão != CNPJ pós-fusão da RaiaDrogasil
]


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_cnpj_map_test.db")
    return factory()


def _fixture():
    return json.loads(FIXTURE_JSON.read_text())


def test_regressao_712_matches_auditados_fca_raiz_propagacao():
    """Trava a precisão já auditada (712 identificações, zero erros, seis anos
    2010/2012/2014/2015/2016/2017 — `changes/2026-08-20-modulo-acoes-b3-fronteira-
    2015-2026.md`) usando o universo elegível EXATO daquela auditoria (congelado no
    fixture, não re-derivado) contra o resultado do módulo hoje. O fixture aqui tem 713,
    não 712: `DMMO3`/2017 resolve via `raiz_propagacao` (raiz `DMMO`, CNPJ único da FCA,
    `08.926.302/0001-05` = Dommo Energia) e não resolvia na auditoria original — não é
    regressão de precisão (raiz de ticker é o caminho de maior confiança, 100% auditado à
    parte, e o CNPJ resolvido está confirmado contra a FCA), é uma identificação nova que
    a rodada anterior não tinha por não ter carregado exatamente o mesmo conjunto de anos
    FCA. Isolado no primeiro assert para ficar auditável, não escondido dentro do total."""
    identity = load_fca_identity(FCA_PATHS)
    fixture = _fixture()

    assert fixture["2017"]["resolvidos_fca_raiz"]["DMMO3"] == {
        "cnpj": "08.926.302/0001-05", "fonte": "raiz_propagacao",
    }

    total = 0
    for year, data in fixture.items():
        obtido = {}
        for ticker in data["universo"]:
            resolved = resolve_identity(ticker, "", identity)
            if resolved and resolved[1] in ("fca", "raiz_propagacao"):
                obtido[ticker] = {"cnpj": resolved[0], "fonte": resolved[1]}

        assert obtido == dict(data["resolvidos_fca_raiz"]), f"divergência em {year}"
        total += len(obtido)

    assert total == 713


def test_reconciliacao_nome_krot3_resolve_para_cnpj_da_cogna():
    """O caso central do teste de aceite: `KROT3` nunca aparece como `Codigo_Negociacao`
    em nenhum ano FCA confiável (o código real só virou `COGN3` em 2019-10-11, antes da
    era confiável de 2018+ começar a ser observada com esse ticker) — só resolve pela
    reconciliação por nome histórico, usando `Nome_Empresarial='KROTON'` (nome antigo,
    ainda presente no histórico do CNPJ apesar da empresa ter mudado de nome)."""
    identity = load_fca_identity(FCA_PATHS)
    fixture = _fixture()

    assert identity.ticker_to_cnpj.get("KROT3") is None

    nomres = fixture["2017"]["nomres"]["KROT3"]
    assert nomres == "KROTON"

    resolved = resolve_identity("KROT3", nomres, identity)
    assert resolved == (COGNA_CNPJ, "reconciliacao_nome")


def test_reconciliacao_nome_tokens_falsos_positivos_ficam_nao_resolvidos():
    """Os 4 casos confirmados por auditoria manual (ver docstring do módulo e do arquivo)
    devem devolver `None`, não a empresa errada. Antes da correção desta rodada
    (`_GENERIC_NAME_TOKENS` sem estes 4 tokens), todos os quatro resolviam para um CNPJ
    de empresa não relacionada."""
    identity = load_fca_identity(FCA_PATHS)

    for ticker, nomres in NEGATIVOS_CONFIRMADOS:
        assert resolve_identity(ticker, nomres, identity) is None, f"{ticker} deveria ficar não resolvido"


def test_compute_vigencia_fecha_krot3_e_mantem_cogn3_vigente():
    """`KROT3` para de negociar em 2019-10-10 (real); sem dado posterior a
    2020-05-08 (a fixture de 2020 existe só para isso), a janela de 211 dias entre a
    última linha de `KROT3` e a data máxima observada excede a tolerância de 180 dias —
    fecha a vigência exatamente na última data real de pregão. `COGN3` segue vigente
    (sua própria última linha real, 2020-05-08, É a data máxima observada — gap zero)."""
    vigencia = compute_vigencia([KROT2019_ZIP, COGN2020_ZIP])

    assert vigencia["KROT3"] == (date(2019, 10, 1), date(2019, 10, 10))
    assert vigencia["COGN3"] == (date(2019, 10, 11), None)


def test_get_cnpj_as_of_fronteira_krot3_cogn3_sem_sobreposicao_sem_vao(tmp_path):
    """O teste de aceite completo da Seção 5.6: consulta por ticker na data de decisão,
    mesma convenção de fronteira inclusiva-inclusiva de `get_filing_as_of`. `KROT3`
    resolve até 2019-10-10 (inclusive); a partir de 2019-10-11 já não existe mais como
    código — quem quer o CNPJ daquela data consulta `COGN3`, que passa a resolver a
    partir de 2019-10-11 (inclusive), nunca antes."""
    session = _session(tmp_path)
    identity = load_fca_identity(FCA_PATHS)
    vigencia = compute_vigencia([KROT2019_ZIP, COGN2020_ZIP])

    tickers_by_year = {2019: {"KROT3": "KROTON", "COGN3": "COGNA ON"}}
    stats = build_cnpj_ticker_map(session, identity, vigencia, tickers_by_year, date(2026, 8, 20))

    assert stats.resolved_inserted == 2
    assert stats.unresolved_inserted == 0

    assert get_cnpj_as_of(session, "KROT3", date(2019, 10, 10)) == COGNA_CNPJ
    assert get_cnpj_as_of(session, "KROT3", date(2019, 10, 11)) is None

    assert get_cnpj_as_of(session, "COGN3", date(2019, 10, 11)) == COGNA_CNPJ
    assert get_cnpj_as_of(session, "COGN3", date(2019, 10, 10)) is None

    assert get_cnpj_as_of(session, "COGN3", date(2020, 5, 8)) == COGNA_CNPJ
    assert get_cnpj_as_of(session, "COGN3", date(2026, 1, 1)) == COGNA_CNPJ  # data_fim None = ainda vigente


def test_unresolved_ticker_e_contabilizado_nao_silencioso(tmp_path):
    """Um ticker líquido sem CNPJ resolvido (`BRTO3`, um dos 4 falsos-positivos
    bloqueados) precisa virar `UnresolvedTicker`, não desaparecer do universo em
    silêncio — o mecanismo de exclusão contável que impede o survivorship de voltar
    pela porta dos fundos quando a identidade falha."""
    session = _session(tmp_path)
    identity = load_fca_identity(FCA_PATHS)
    vigencia = {"BRTO3": (date(2010, 1, 4), date(2010, 12, 30))}

    tickers_by_year = {2010: {"BRTO3": "BRASIL TELEC"}}
    stats = build_cnpj_ticker_map(session, identity, vigencia, tickers_by_year, date(2026, 8, 20))

    assert stats.resolved_inserted == 0
    assert stats.unresolved_inserted == 1

    row = session.execute(select(UnresolvedTicker)).scalar_one()
    assert row.ticker == "BRTO3"
    assert row.checked_year == 2010
    assert row.reason == "cnpj_nao_resolvido"


def test_build_cnpj_ticker_map_e_append_only(tmp_path):
    session = _session(tmp_path)
    identity = load_fca_identity(FCA_PATHS)
    vigencia = compute_vigencia([KROT2019_ZIP, COGN2020_ZIP])
    tickers_by_year = {2019: {"KROT3": "KROTON", "COGN3": "COGNA ON"}}

    first = build_cnpj_ticker_map(session, identity, vigencia, tickers_by_year, date(2026, 8, 20))
    assert first.resolved_inserted == 2

    second = build_cnpj_ticker_map(session, identity, vigencia, tickers_by_year, date(2026, 8, 20))
    assert second.resolved_inserted == 0
    assert second.resolved_rejected_duplicate == 2

    rows = session.execute(select(CnpjTickerMap)).scalars().all()
    assert len(rows) == 2
