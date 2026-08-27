// Espelha os dicts devolvidos por `acoes/api.py` (spec 14, Seção 11) — tipagem manual,
// mesmo padrão do módulo cripto (../../api/types.ts), sem geração automática.

export type MotivoCelulaVazia = "inaplicavel" | "indefinido" | "sem_dado" | "versao_indisponivel";

export interface Carimbo {
  data_publicacao: string;
  versao: number;
}

export interface DetalheFator {
  valor: number | null;
  percentil: number | null;
  carimbo: Carimbo | null;
  motivo: MotivoCelulaVazia | null;
}

export type SeloIdentidade = "alta_confianca" | "reconciliada";

export interface EmpresaRanking {
  ticker: string;
  cnpj: string;
  setor_b3: string | null;
  subsetor_b3: string | null;
  segmento_b3: string | null;
  selo_identidade: SeloIdentidade;
  earnings_yield: DetalheFator;
  divida_liquida_ebitda: DetalheFator;
  roe: DetalheFator;
  score_composto: number | null;
}

export interface DistribuicaoSetor {
  setor: string;
  contagem: number;
  pct: number;
  amostra_pequena: boolean;
}

export interface MudancasDoMes {
  entraram: number;
  sairam: number;
  balancos_novos: number;
  retificacoes: number;
}

export interface ExclusaoDetalhe {
  ticker: string;
  motivo: string;
}

export interface MesAtual {
  data_decisao: string;
  elegiveis: number;
  com_score: number;
  excluidas: number;
  cobertura_pct: number;
  ranking: EmpresaRanking[];
  distribuicao_setorial: DistribuicaoSetor[];
  mudancas_do_mes: MudancasDoMes;
  excluidas_detalhe: ExclusaoDetalhe[];
}

export interface VigenciaTicker {
  ticker: string;
  data_inicio_vigencia: string;
  data_fim_vigencia: string | null;
  fonte: string;
}

export interface EntregaCvm {
  dt_refer: string;
  versao: number;
  dt_receb: string;
}

export interface PontoLinhaDoTempo {
  data_decisao: string;
  earnings_yield: number | null;
  divida_liquida_ebitda: number | null;
  roe: number | null;
}

export interface EmpresaDetalhe {
  ticker: string;
  cnpj: string;
  setor_b3: string | null;
  subsetor_b3: string | null;
  segmento_b3: string | null;
  selo_identidade: SeloIdentidade;
  vigencia_ticker: VigenciaTicker[];
  fatores_hoje: {
    earnings_yield: DetalheFator;
    divida_liquida_ebitda: DetalheFator;
    roe: DetalheFator;
  };
  linha_do_tempo_conhecimento: PontoLinhaDoTempo[];
  historico_entregas_cvm: EntregaCvm[];
  retificacoes_ultimos_5_anos: number;
}

export interface StatusFonte {
  ultima_coleta: string | null;
  idade_dias?: number;
  status: "ok" | "atrasado" | "sem_dado";
}

export interface CoberturaAno {
  ano: number;
  data_decisao: string;
  elegiveis: number;
  com_score: number;
  cobertura_pct: number;
  era: "confiavel" | "reconciliada";
}

export interface BacktestResultado {
  data_computado: string;
  periodo: { inicio: string; fim: string; anos_avaliados: number };
  candidato_top20: {
    total_return_pct: number;
    volatility_pct: number;
    max_drawdown_pct: number;
    return_over_drawdown: number;
    return_over_volatility: number;
    turnover_medio: number;
  };
  equal_weight_universo: {
    total_return_pct: number;
    return_over_volatility: number;
    return_over_drawdown: number;
  };
  ponderada_liquidez_universo: {
    total_return_pct: number;
    return_over_volatility: number;
    return_over_drawdown: number;
  };
  cdi: { total_return_pct: number };
  nulidade: {
    metrica_real: number;
    p_valor: number;
    fora_da_nuvem_nula: boolean;
    n_permutacoes: number;
  };
  criterios_pre_registrados: {
    criterio_1_bate_equal_weight_risco_ajustado: boolean;
    criterio_2_fora_da_nuvem_nula_p_menor_0_05: boolean;
    resultado_final: string;
  };
  achado_adicional: string;
}

export interface SaudeDoDado {
  data_decisao: string;
  fontes: {
    cvm_dfp_itr: StatusFonte;
    cotahist: StatusFonte;
    cdi: StatusFonte;
    ipca: StatusFonte;
  };
  todas_fontes_ok: boolean;
  cobertura_por_ano: CoberturaAno[];
  exclusoes_do_mes: {
    total: number;
    por_motivo: Record<string, number>;
    detalhe: ExclusaoDetalhe[];
  };
  backtest: BacktestResultado | null;
}

export interface HistoricoLista {
  datas_decisao: string[];
}

export interface HistoricoDetalhe {
  data_decisao: string;
  elegiveis: number;
  com_score: number;
  ranking: EmpresaRanking[];
  retorno_subsequente_topo_10: Record<string, number | null>;
  retorno_subsequente_base_10: Record<string, number | null>;
}
