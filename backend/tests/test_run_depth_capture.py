"""Unit tests for run_depth_capture.py's decisão pura WS-vs-fallback — a captura de
2026-08-15 rodava só REST; o retorno ao WS direto em 2026-09-01 (inventário confirmou
stream.binance.com respondendo de europe-west4) introduziu essa decisão, e ela precisa
nunca deixar a captura sem amostra nem persistir dado obsoleto do WS achando que é
atual."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# scripts/ não é um pacote importável normalmente — mesmo padrão de carregar por caminho
# usado para outros scripts testados neste repositório.
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_depth_capture.py"
_spec = importlib.util.spec_from_file_location("run_depth_capture", _SCRIPT_PATH)
run_depth_capture = importlib.util.module_from_spec(_spec)
sys.modules["run_depth_capture"] = run_depth_capture
_spec.loader.exec_module(run_depth_capture)

deve_usar_ws = run_depth_capture.deve_usar_ws
WS_STALENESS_THRESHOLD_SECONDS = run_depth_capture.WS_STALENESS_THRESHOLD_SECONDS


def test_sem_nenhum_evento_do_ws_ainda_cai_no_fallback():
    assert deve_usar_ws(latest_local_ts=None, agora=1000.0) is False


def test_evento_recente_usa_ws():
    agora = 1000.0
    assert deve_usar_ws(latest_local_ts=agora - 5.0, agora=agora) is True


def test_evento_exatamente_no_limiar_ainda_conta_como_fallback():
    # "< limiar", nao "<=" — na fronteira exata, trata como obsoleto (conservador: prefere
    # o fallback a persistir algo que pode já ter passado do limiar por um triz).
    agora = 1000.0
    assert deve_usar_ws(latest_local_ts=agora - WS_STALENESS_THRESHOLD_SECONDS, agora=agora) is False


def test_evento_velho_cai_no_fallback():
    agora = 1000.0
    assert deve_usar_ws(latest_local_ts=agora - (WS_STALENESS_THRESHOLD_SECONDS + 1), agora=agora) is False


def test_limiar_customizado_e_respeitado():
    agora = 1000.0
    assert deve_usar_ws(latest_local_ts=agora - 10.0, agora=agora, limiar=5.0) is False
    assert deve_usar_ws(latest_local_ts=agora - 2.0, agora=agora, limiar=5.0) is True
