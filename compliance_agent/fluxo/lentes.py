# -*- coding: utf-8 -*-
"""LENTES da Esteira Única (plano mestre v2 §3.6): filtro + prioridade sobre a fila única, sem código por órgão.

`config/lentes.yaml` declara cada lente (formato documentado no próprio arquivo). Aqui:
  · `carregar()` valida o YAML e CONFERE cada UG contra o índice do SIAFE (`data/ug_index_siafe.json`, o dropdown
    selUg baixado por tools/siafe_ug_index.py): sigla diferente da escrita na lente ⇒ `ErroLente` (UG não se escreve
    de memória — houve três fundos com a mesma sigla, memória ug-index-siafe-fundos). Data e cota NÃO se escrevem:
    `data_fato_desde` e `cota_esforco` só aceitam a REFERÊNCIA à constante única (`governo_couto.INICIO`,
    `foco.periodo_couto.fracao`) — data literal é recusada (a constante copiada vira falso positivo quando muda);
  · `resolver()` DERIVA da fonte o que a lente não pode escrever à mão: o `orgao_sei` (prefixo de 2 dígitos do nº
    SEI-RJ cujas OBs PAGAS são ≥ `posse_minima` das UGs da lente), os processos de obra (`contratos_obra`, critério
    de tools/pericia_obras sem os falsos positivos medidos) e — só com `externas=True`, porque lê o pcrj_benef.db —
    os credores com sócio em benefício (`socios_com_beneficio`, a MESMA `analisar()` de
    compliance_agent/pcrj/pericia_socios_beneficio); confere os órgãos da Prefeitura contra o ContasRio e os
    recortes de emendas contra a tabela;
  · `casa()` / `bonus()` dizem se um item (UGs, processo, credores, data do fato) cai na lente e quanto soma ao escalar
    de valor da prioridade única (`fluxo.prioridade.Sinais.bonus_lente`).

Semântica do filtro (estado): as dimensões de ALCANCE — `ug`, `orgao_sei`, `processo`, `credor` — combinam por OU
(qualquer uma basta); `data_fato_desde` é RESTRIÇÃO (E): sem data do fato conhecida, o item não casa. Lente de outra
esfera (`prefeitura`, `emendas`) nunca casa com item do SEI-RJ do Estado — o recorte dela vive no resumo
(`compliance_agent/aplicacao/lentes_resumo.py`), não na fila de captura.
Nada aqui escreve em banco: a fonte é aberta só-leitura por quem chama.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import yaml

RAIZ = Path(__file__).resolve().parents[2]
ARQ = RAIZ / "config" / "lentes.yaml"
INDICE_UG = RAIZ / "data" / "ug_index_siafe.json"
ESFERAS = ("estado", "prefeitura", "emendas")

# Referências aceitas (constante única; nunca o valor copiado). Valor = (módulo, nome) ou leitor do foco.
_REF_DATA = {"governo_couto.INICIO": ("compliance_agent.governo_couto", "INICIO")}
_REF_COTA = ("foco.periodo_couto.fracao",)
_DERIVA_PROCESSO = ("contratos_obra",)
_DERIVA_CREDOR = ("socios_com_beneficio",)


class ErroLente(ValueError):
    """Configuração de lente inválida, UG/órgão que não confere com a fonte, ou lente usada sem derivação."""


@dataclass(frozen=True)
class Lente:
    nome: str
    ugs: frozenset[str]
    prioridade: float
    orgao_sei: frozenset[str] = frozenset()       # preenchido por `resolver` (derivado do SIAFE)
    regra_orgao: dict | None = None
    produto: str | None = None
    alerta: str = "nenhum"
    descricao: str = ""
    esfera: str = "estado"
    desde: str | None = None                      # data_fato_desde resolvida da constante (AAAA-MM-DD)
    desde_ref: str | None = None
    regra_processo: dict | None = None
    processos: frozenset[str] | None = None       # None = ainda não derivado (`resolver`)
    regra_credor: dict | None = None
    credores: frozenset[str] | None = None        # CNPJ de 14 dígitos; None = ainda não derivado
    orgaos_pcrj: tuple[str, ...] = ()
    conferir_pcrj: tuple[tuple[str, str], ...] = ()
    emendas_recortes: tuple[str, ...] = ()
    cota_esforco: float | None = None
    cota_ref: str | None = None
    eixos_extra: tuple[str, ...] = ()
    paridade: str = ""

    @property
    def derivada(self) -> bool:
        """Tudo o que a lente pede da fonte já foi derivado (senão `casa` não pode responder)."""
        return not ((self.regra_processo and self.processos is None) or (self.regra_credor and self.credores is None))

    def alcance(self) -> bool:
        return bool(self.ugs or self.regra_orgao or self.regra_processo or self.regra_credor)


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


def _ref_data(nome: str, valor) -> tuple[str | None, str | None]:
    if valor is None:
        return None, None
    if not isinstance(valor, str) or valor not in _REF_DATA:
        raise ErroLente(f"lente {nome}: data_fato_desde só aceita a referência à constante única "
                        f"({', '.join(_REF_DATA)}), nunca a data escrita: {valor!r}")
    import importlib
    mod, attr = _REF_DATA[valor]
    data = str(getattr(importlib.import_module(mod), attr))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
        raise ErroLente(f"lente {nome}: {valor} não é AAAA-MM-DD ({data!r})")
    return data, valor


def _ref_cota(nome: str, valor) -> tuple[float | None, str | None]:
    if valor is None:
        return None, None
    if valor not in _REF_COTA:
        raise ErroLente(f"lente {nome}: cota_esforco só aceita a referência {_REF_COTA[0]} (o ponto único é "
                        f"config/foco.yaml), nunca o número escrito: {valor!r}")
    from compliance_agent import foco
    cfg = foco.config()
    return (cfg["fracao"] if cfg["ligado"] else 0.0), valor


def _derivacao(nome: str, regra, aceitas: tuple[str, ...], campo: str) -> dict | None:
    if regra is None:
        return None
    if not (isinstance(regra, dict) and regra.get("derivar") in aceitas):
        raise ErroLente(f"lente {nome}: {campo} só aceita {{derivar: {'|'.join(aceitas)}}} (derivado da fonte, "
                        f"nunca a lista escrita à mão)")
    return dict(regra)


def carregar(caminho: Path | None = None, indice: Path | None = None) -> dict[str, Lente]:
    """As lentes do YAML, com UGs conferidas e referências resolvidas (o derivado da fonte vem em `resolver`)."""
    out: dict[str, Lente] = {}
    for nome, c in _ler(caminho)["lentes"].items():
        c = c or {}
        filtro = c.get("filtro") or {}
        esfera = str(c.get("esfera") or "estado")
        if esfera not in ESFERAS:
            raise ErroLente(f"lente {nome}: esfera {esfera!r} fora de {ESFERAS}")
        ugs = [str(u) for u in filtro.get("ug") or []]
        if ugs:
            conferir_ugs(nome, {str(k): v for k, v in ((c.get("conferir_siafe") or {}).items())}, ugs, indice)
        pr = c.get("prioridade", 0.0)
        if not isinstance(pr, (int, float)) or not 0 <= float(pr) <= 1:
            raise ErroLente(f"lente {nome}: prioridade fora de [0, 1]: {pr!r}")
        regra = filtro.get("orgao_sei")
        if regra is not None and not (isinstance(regra, dict) and regra.get("derivar") == "siafe"):
            raise ErroLente(f"lente {nome}: orgao_sei só aceita {{derivar: siafe, …}} (prefixo não se escreve à mão)")
        desde, desde_ref = _ref_data(nome, filtro.get("data_fato_desde"))
        cota, cota_ref = _ref_cota(nome, c.get("cota_esforco"))
        r_proc = _derivacao(nome, filtro.get("processo"), _DERIVA_PROCESSO, "filtro.processo")
        r_cred = _derivacao(nome, filtro.get("credor"), _DERIVA_CREDOR, "filtro.credor")
        orgaos = tuple(str(o) for o in filtro.get("orgao_pcrj") or [])
        conf_pcrj = {str(k): str(v) for k, v in (c.get("conferir_pcrj") or {}).items()}
        if orgaos and sorted(orgaos) != sorted(conf_pcrj):
            raise ErroLente(f"lente {nome}: cada órgão da Prefeitura precisa do nome em conferir_pcrj (e só eles)")
        recortes = tuple(str(r) for r in ((filtro.get("emendas") or {}).get("recorte") or []))
        if esfera == "estado" and (orgaos or recortes):
            raise ErroLente(f"lente {nome}: órgão da Prefeitura/recorte de emendas exige a esfera própria")
        if esfera == "prefeitura" and not orgaos:
            raise ErroLente(f"lente {nome}: esfera prefeitura sem filtro.orgao_pcrj")
        if esfera == "emendas" and not recortes:
            raise ErroLente(f"lente {nome}: esfera emendas sem filtro.emendas.recorte")
        if esfera == "estado" and not (ugs or regra or desde or r_proc or r_cred):
            raise ErroLente(f"lente {nome}: filtro vazio")
        eixos = tuple(str(x) for x in c.get("eixos_extra") or [])
        out[nome] = Lente(nome=nome, ugs=frozenset(ugs), prioridade=float(pr), regra_orgao=regra,
                          produto=c.get("produto"), alerta=str(c.get("alerta") or "nenhum"),
                          descricao=str(c.get("descricao") or ""), esfera=esfera, desde=desde, desde_ref=desde_ref,
                          regra_processo=r_proc, regra_credor=r_cred, orgaos_pcrj=orgaos,
                          conferir_pcrj=tuple(sorted(conf_pcrj.items())), emendas_recortes=recortes,
                          cota_esforco=cota, cota_ref=cota_ref, eixos_extra=eixos,
                          paridade=str(c.get("paridade") or "").strip())
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


# ── obras: o critério de tools/pericia_obras, sem os falsos positivos medidos (24/11/2026, snapshot da parada) ──
# O antigo é substring SQL (`LOWER(objeto) LIKE '%obra%' OR …`): casa "mão de obra" (334 dos 1.167 contratos — locação
# de mão de obra, limpeza, vigilância) e palavras que CONTÊM "obra" (petrobras, cobrança, dobra, manobra, sobra,
# desdobramento: 40). Aqui "obra(s)" só vale como PALAVRA e fora de "mão de obra"; os demais radicais seguem iguais.
_OBRA_RADICAIS = re.compile(r"constru|reforma|pavimenta|edifica|drenagem", re.I)
_MAO_DE_OBRA = re.compile(r"m[aã]o[\s\-]*de[\s\-]*obras?", re.I)
_OBRA_PALAVRA = re.compile(r"(?<![a-zà-ÿ])obras?(?![a-zà-ÿ])|(?<![a-zà-ÿ])obrasp[uú]blic", re.I)


def e_obra(objeto: str | None) -> bool:
    o = objeto or ""
    return bool(_OBRA_RADICAIS.search(o) or _OBRA_PALAVRA.search(_MAO_DE_OBRA.sub(" ", o)))


def motivo_fora_de_obra(objeto: str | None) -> str:
    """Por que um contrato do critério antigo NÃO é obra no novo (a diferença explicada da paridade)."""
    o = objeto or ""
    if _MAO_DE_OBRA.search(o):
        return "mão de obra"
    m = re.search(r"[a-zà-ÿ]*obra[a-zà-ÿ]*", o, re.I)
    return f"substring:{m.group(0).lower()}" if m else "outro"


def derivar_contratos_obra(fonte: sqlite3.Connection) -> tuple[frozenset[str], dict]:
    """Processos (chave canônica) dos contratos do TCE-RJ que são obra; a medida diz o que saiu do critério antigo."""
    from compliance_agent.dominio import processo_id as PI
    from tools.pericia_obras import OBRA
    procs: set[str] = set()
    n_antigo = n_novo = 0
    fora: dict[str, int] = {}
    for proc, objeto in fonte.execute(f"SELECT processo, objeto FROM contratos_tcerj WHERE {OBRA} "
                                      "AND COALESCE(valor_contrato,0) > 0"):
        n_antigo += 1
        if not e_obra(objeto):
            m = motivo_fora_de_obra(objeto)
            fora[m] = fora.get(m, 0) + 1
            continue
        n_novo += 1
        k = PI.chave_processo(proc or "")
        if k:
            procs.add(k)
    return frozenset(procs), {"contratos_criterio_antigo": n_antigo, "contratos_obra": n_novo,
                              "processos": len(procs), "fora_do_criterio_novo": dict(sorted(fora.items(),
                                                                                         key=lambda x: -x[1]))}


def derivar_socios_com_beneficio() -> tuple[frozenset[str], dict]:
    """CNPJs (14 dígitos) com sócio casado a beneficiário (BF/BPC no Rio) pela MESMA `analisar()` do relatório antigo
    (compliance_agent/pcrj/pericia_socios_beneficio) — paridade por construção; lê pcrj_benef.db e compliance.db."""
    from compliance_agent.pcrj.pericia_socios_beneficio import analisar
    d = analisar()
    cnpjs = frozenset(r["cnpj_raw"] for r in d["registros"] if len(r.get("cnpj_raw") or "") == 14)
    return cnpjs, {"registros": len(d["registros"]), "n_alta": d["n_alta"], "n_sem_fragmento": d["n_sem_fragmento"],
                   "empresas": d["n_empresas"], "cnpjs": len(cnpjs), "ultima_competencia": d.get("ultima")}


def conferir_orgaos_pcrj(lente: Lente, fonte_pcrj: sqlite3.Connection) -> dict:
    """Cada órgão declarado tem de existir no ContasRio (`contasrio_contrato.orgao` = 'código - NOME') com o nome
    declarado. Devolve {código: nº de contratos}."""
    vistos: dict[str, tuple[str, int]] = {}
    for orgao, n in fonte_pcrj.execute("SELECT orgao, COUNT(*) FROM contasrio_contrato GROUP BY 1"):
        cod, _, nome = str(orgao or "").partition(" - ")
        if cod.strip():
            vistos[cod.strip()] = (nome.strip(), int(n))
    erradas = {c: (n, (vistos.get(c) or ("<ausente>",))[0]) for c, n in lente.conferir_pcrj
               if (vistos.get(c) or ("",))[0] != n}
    if erradas:
        raise ErroLente(f"lente {lente.nome}: órgão não confere com o ContasRio (declarado, fonte): {erradas}")
    return {c: vistos[c][1] for c, _ in lente.conferir_pcrj}


def conferir_recortes_emendas(lente: Lente, fonte: sqlite3.Connection) -> dict:
    """Cada recorte declarado existe na tabela `emendas` (coletor do Portal da Transparência). {recorte: nº}."""
    n = {r: int(c) for r, c in fonte.execute("SELECT recorte, COUNT(*) FROM emendas GROUP BY 1")}
    falta = [r for r in lente.emendas_recortes if r not in n]
    if falta:
        raise ErroLente(f"lente {lente.nome}: recorte de emendas ausente na tabela: {falta} (há: {sorted(n)})")
    return {r: n[r] for r in lente.emendas_recortes}


def _tem(fonte, tabela: str) -> bool:
    return fonte.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone() is not None


def resolver(lentes: dict[str, Lente], fonte: sqlite3.Connection | None, *, externas: bool = False,
             fonte_pcrj: sqlite3.Connection | None = None) -> tuple[dict[str, Lente], dict]:
    """Preenche o que cada lente deriva da fonte e devolve a medida (explicável). Sem fonte: nada é derivado (só a UG
    filtra; lente que exige derivação fica `derivada=False` e `casa` recusa). `externas=True` deriva também o que lê
    outro banco (benefícios: pcrj_benef.db) — caro, só no materializador e na CLI."""
    out, medidas = {}, {}
    for nome, l in lentes.items():
        med: dict = {}
        if l.regra_orgao and fonte is not None:
            pre, m = derivar_orgao_sei(fonte, l.ugs, float(l.regra_orgao.get("posse_minima", 0.95)),
                                       int(l.regra_orgao.get("minimo_obs", 100)))
            med.update({"orgao_sei": pre, "medida": dict(sorted(m.items(), key=lambda x: -x[1][0])[:5])})
            l = replace(l, orgao_sei=frozenset(pre))
        if l.regra_processo and fonte is not None and _tem(fonte, "contratos_tcerj"):
            procs, m = derivar_contratos_obra(fonte)
            med["processo"] = m
            l = replace(l, processos=procs)
        if l.regra_credor and externas:
            cnpjs, m = derivar_socios_com_beneficio()
            med["credor"] = m
            l = replace(l, credores=cnpjs)
        if l.orgaos_pcrj and fonte_pcrj is not None:
            med["orgao_pcrj"] = conferir_orgaos_pcrj(l, fonte_pcrj)
        if l.emendas_recortes and fonte is not None and _tem(fonte, "emendas"):
            med["emendas"] = conferir_recortes_emendas(l, fonte)
        if med:
            medidas[nome] = med
        out[nome] = l
    return out, medidas


def casa(lente: Lente, ugs: Iterable[str], processo: str | None, credores: Iterable[str] = (),
         data_fato: str | None = None) -> str | None:
    """Por que o item do Estado cai na lente (`ug:…`, `orgao_sei:…`, `processo:obra`, `credor:…`, `data:…`) ou None.
    Lente que exige derivação ainda não feita ⇒ `ErroLente` (nunca um "não casa" silencioso)."""
    if lente.esfera != "estado" or (processo and str(processo).startswith("PCRJ:")):
        return None
    if not lente.derivada:
        raise ErroLente(f"lente {lente.nome}: derivação pendente — chame resolver(..., externas=True) com a fonte")
    if lente.desde and not (data_fato and str(data_fato)[:10] >= lente.desde):
        return None
    comuns = sorted(set(ugs) & lente.ugs)
    if comuns:
        return f"ug:{comuns[0]}"
    if processo and str(processo)[:2] in lente.orgao_sei:
        return f"orgao_sei:{str(processo)[:2]}"
    if lente.processos and processo and processo in lente.processos:
        return "processo:obra"
    if lente.credores:
        c = sorted(set(credores) & lente.credores)
        if c:
            return f"credor:{c[0]}"
    if lente.desde and not lente.alcance():
        return f"data:{str(data_fato)[:10]}≥{lente.desde}"
    return None


def bonus(lentes: dict[str, Lente], ugs: Iterable[str], processo: str | None, credores: Iterable[str] = (),
          data_fato: str | None = None) -> tuple[float, list[str]]:
    """Soma das prioridades das lentes que casam com o item e os nomes delas (ordem alfabética). Lente com derivação
    pendente não rotula (não há como saber) — quem precisa dela resolve com `externas=True`."""
    ugs, credores = set(ugs), set(credores)
    nomes = sorted(n for n, l in lentes.items() if l.derivada and casa(l, ugs, processo, credores, data_fato))
    return round(sum(lentes[n].prioridade for n in nomes), 6), nomes
