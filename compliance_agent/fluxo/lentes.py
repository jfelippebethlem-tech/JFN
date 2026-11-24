# -*- coding: utf-8 -*-
"""LENTES da Esteira Única (plano mestre v2 §3.6): filtro + prioridade sobre a fila única, sem código por órgão.

`config/lentes.yaml` declara cada lente (formato documentado no próprio arquivo). Aqui:
  · `carregar()` valida o YAML e CONFERE cada UG contra o índice do SIAFE (`data/ug_index_siafe.json`, o dropdown
    selUg baixado por tools/siafe_ug_index.py): sigla diferente da escrita na lente ⇒ `ErroLente` (UG não se escreve
    de memória — houve três fundos com a mesma sigla, memória ug-index-siafe-fundos);
  · `resolver()` deriva o `orgao_sei` (prefixo de 2 dígitos do nº SEI-RJ) da coleta do SIAFE: prefixo cujas OBs com
    processo — só OB PAGA — são ≥ `posse_minima` das UGs da lente (medido 24/11/2026 no snapshot da parada; número
    no relatório da paridade, `arvore paridade --lente bombeiros`);
  · `casa()` / `bonus()` dizem se um item (UGs conhecidas + chave do processo) cai na lente e quanto soma ao escalar
    de valor da prioridade única (`fluxo.prioridade.Sinais.bonus_lente`).
Nada aqui escreve em banco: a fonte é aberta só-leitura por quem chama.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

RAIZ = Path(__file__).resolve().parents[2]
ARQ = RAIZ / "config" / "lentes.yaml"
INDICE_UG = RAIZ / "data" / "ug_index_siafe.json"


class ErroLente(ValueError):
    """Configuração de lente inválida ou UG que não confere com o índice do SIAFE."""


@dataclass(frozen=True)
class Lente:
    nome: str
    ugs: frozenset[str]
    prioridade: float
    orgao_sei: frozenset[str] = frozenset()       # preenchido por `resolver` (derivado do SIAFE)
    regra_orgao: dict | None = None
    produto: str | None = None
    alerta: str = "nenhum"


def _ler(caminho: Path | None) -> dict:
    d = yaml.safe_load(Path(caminho or ARQ).read_text(encoding="utf-8")) or {}
    if d.get("versao") != 1 or not isinstance(d.get("lentes"), dict):
        raise ErroLente("lentes.yaml: esperado versao: 1 e um mapa `lentes`")
    return d


def conferir_ugs(nome: str, conferir: dict, ugs: Iterable[str], indice: Path | None = None) -> None:
    """Cada UG da lente tem de estar no índice do SIAFE com a sigla declarada em `conferir_siafe`."""
    ugs = list(ugs)
    falta = [u for u in ugs if u not in conferir]
    if falta:
        raise ErroLente(f"lente {nome}: UG sem sigla em conferir_siafe: {falta}")
    try:
        idx = (json.loads(Path(indice or INDICE_UG).read_text(encoding="utf-8")).get("ugs") or {})
    except (OSError, ValueError) as e:
        raise ErroLente(f"lente {nome}: índice de UGs do SIAFE ilegível ({type(e).__name__}) — não confiro de memória")
    erradas = {u: (conferir[u], idx.get(u)) for u in ugs if idx.get(u) != conferir[u]}
    if erradas:
        raise ErroLente(f"lente {nome}: UG não confere com o índice do SIAFE (declarada, índice): {erradas}")


def carregar(caminho: Path | None = None, indice: Path | None = None) -> dict[str, Lente]:
    """As lentes do YAML, com as UGs conferidas (sem o `orgao_sei` derivado — ver `resolver`)."""
    out: dict[str, Lente] = {}
    for nome, c in _ler(caminho)["lentes"].items():
        filtro = (c or {}).get("filtro") or {}
        ugs = [str(u) for u in filtro.get("ug") or []]
        if not ugs:
            raise ErroLente(f"lente {nome}: filtro.ug vazio")
        conferir_ugs(nome, {str(k): v for k, v in ((c.get("conferir_siafe") or {}).items())}, ugs, indice)
        pr = c.get("prioridade", 0.0)
        if not isinstance(pr, (int, float)) or not 0 <= float(pr) <= 1:
            raise ErroLente(f"lente {nome}: prioridade fora de [0, 1]: {pr!r}")
        regra = filtro.get("orgao_sei")
        if regra is not None and not (isinstance(regra, dict) and regra.get("derivar") == "siafe"):
            raise ErroLente(f"lente {nome}: orgao_sei só aceita {{derivar: siafe, …}} (prefixo não se escreve à mão)")
        out[nome] = Lente(nome=nome, ugs=frozenset(ugs), prioridade=float(pr), regra_orgao=regra,
                          produto=c.get("produto"), alerta=str(c.get("alerta") or "nenhum"))
    return out


def derivar_orgao_sei(fonte: sqlite3.Connection, ugs: Iterable[str], posse_minima: float = 0.95,
                      minimo_obs: int = 100) -> tuple[list[str], dict]:
    """Prefixos (2 dígitos) do nº SEI-RJ que as UGs POSSUEM nas OBs do SIAFE, e a medida de cada prefixo candidato
    ({prefixo: [obs da lente, obs total, fração]}) — explicável."""
    from compliance_agent.dominio.pagamento import ob_paga_sql
    from compliance_agent.dominio.processo_id import analisar
    ugs = set(ugs)
    total: dict[str, int] = {}
    da_lente: dict[str, int] = {}
    # só OB PAGA (régua canônica): a posse do órgão é medida no que a UG de fato pagou, não em OB anulada/excluída
    for proc, ug, n in fonte.execute("SELECT processo, ug_emitente, COUNT(*) FROM ob_orcamentaria_siafe "
                                     f"WHERE COALESCE(processo, '') <> '' AND {ob_paga_sql(fonte)} GROUP BY 1, 2"):
        p = analisar(proc)
        if p is None:
            continue
        pre = p.unidade[:2]
        total[pre] = total.get(pre, 0) + n
        if ug in ugs:
            da_lente[pre] = da_lente.get(pre, 0) + n
    medida = {pre: [da_lente[pre], total[pre], round(da_lente[pre] / total[pre], 4)] for pre in da_lente}
    return sorted(pre for pre, (l, t, f) in medida.items() if t >= minimo_obs and f >= posse_minima), medida


def resolver(lentes: dict[str, Lente], fonte: sqlite3.Connection | None) -> tuple[dict[str, Lente], dict]:
    """Preenche o `orgao_sei` derivado de cada lente (sem fonte: fica vazio — só a UG filtra) e devolve a medida."""
    out, medidas = {}, {}
    for nome, l in lentes.items():
        if l.regra_orgao and fonte is not None:
            pre, med = derivar_orgao_sei(fonte, l.ugs, float(l.regra_orgao.get("posse_minima", 0.95)),
                                         int(l.regra_orgao.get("minimo_obs", 100)))
            medidas[nome] = {"orgao_sei": pre, "medida": dict(sorted(med.items(), key=lambda x: -x[1][0])[:5])}
            l = Lente(**{**l.__dict__, "orgao_sei": frozenset(pre)})
        out[nome] = l
    return out, medidas


def casa(lente: Lente, ugs: Iterable[str], processo: str | None) -> str | None:
    """Por que o item cai na lente (`ug:<código>` ou `orgao_sei:<prefixo>`), ou None."""
    comuns = sorted(set(ugs) & lente.ugs)
    if comuns:
        return f"ug:{comuns[0]}"
    if processo and not str(processo).startswith("PCRJ:") and str(processo)[:2] in lente.orgao_sei:
        return f"orgao_sei:{str(processo)[:2]}"
    return None


def bonus(lentes: dict[str, Lente], ugs: Iterable[str], processo: str | None) -> tuple[float, list[str]]:
    """Soma das prioridades das lentes que casam com o item e os nomes delas (ordem alfabética)."""
    ugs = set(ugs)
    nomes = sorted(n for n, l in lentes.items() if casa(l, ugs, processo))
    return round(sum(lentes[n].prioridade for n in nomes), 6), nomes
