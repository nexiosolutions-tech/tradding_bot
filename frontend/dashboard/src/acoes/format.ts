// Formatação pt-BR — todo número visível no módulo passa por aqui, nunca `toString()`
// direto (Seção 11.1: face tabular em toda cifra/percentual/data).

export function formatPct(valor: number | null | undefined, casas = 1): string {
  if (valor === null || valor === undefined) return "";
  return `${(valor * 100).toFixed(casas).replace(".", ",")}%`;
}

export function formatMultiplo(valor: number | null | undefined, casas = 1): string {
  if (valor === null || valor === undefined) return "";
  return `${valor.toFixed(casas).replace(".", ",")}x`;
}

export function formatScore(valor: number | null | undefined): string {
  if (valor === null || valor === undefined) return "";
  const sinal = valor >= 0 ? "+" : "";
  return `${sinal}${valor.toFixed(1).replace(".", ",")}`;
}

export function formatDataBr(iso: string | null | undefined): string {
  if (!iso) return "";
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

export function formatMesAno(iso: string): string {
  const meses = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
  ];
  const [ano, mes] = iso.split("-");
  return `${meses[Number(mes) - 1]} ${ano}`;
}
