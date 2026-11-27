# -*- coding: utf-8 -*-
"""E16 `entregar:<produto>` — DOSSIÊ no padrão da casa com MANIFESTO DE HASHES reproduzível, VALIDADOR que BLOQUEIA a
exportação, conferência de que o PDF levou TUDO e entrega com `message_id` conferido (plano mestre v2 §3.2 E16, §8
"Dossiê (E16)" e "Entrega honesta", §3.11 RBAC; O7.5).

Absorve os 12 `relatorio_*`/`montar_*`, `relatorio_bombeiros`, `relatorio_iterj_mgs_*` e `dossie_couto` como UM
produto genérico com FILTRO (a lente): `dossie_orgao`. Nenhuma regra depende de órgão — a lente só escolhe o universo
(UG, credor, período). Paridade com 3 antigos: `~/vault/refatoracao/o75-paridade-e16.md`.

FILTRO (`resolver_filtro`): `lente` de `config/lentes.yaml` (UGs conferidas no índice do SIAFE) ou `couto` (período
desde `governo_couto.INICIO`, constante única, até a O7.2 levar a lente ao YAML) + `filtro` explícito: `ug`,
`credor`, `data_desde`, `data_ate` (data de EMISSÃO da OB, AAAA-MM-DD) e `casos` (chaves do E14).

NÚMEROS (`coletar`): só a OB que é pagamento do SIAFE (`dominio.pagamento.ob_paga_sql` = `cruzamentos_intel._ob_paga`);
o que o filtro pega e NÃO é pagamento vai, contado, a "fora da soma" com o motivo. Cada número impresso é
`<span class="n" data-n="ID">` e aponta para um item do MANIFESTO: consulta SQL + parâmetros + fonte (arquivo, tamanho,
md5 declarado) + sha256 das linhas devolvidas. ACHADOS: do E14 (casos por UG/CNPJ/chave), com status EFETIVO, tier,
contraevidências, diligências, hipóteses inocentes e histórico; as CITAÇÕES dos autos vêm do laudo v2 vigente do E11
(doc_sha, offset) e entram no manifesto com o sha256 do trecho original.

MANIFESTO reproduzível: sem relógio dentro — mesma fonte + mesmo estado do PG ⇒ mesmo `manifesto_sha256` (o rodapé do
PDF leva os 32 primeiros dígitos, pelo `render_html`).

VALIDADOR (`validar`) — qualquer defeito BLOQUEIA a exportação (`ExportacaoBloqueada`), nada é gravado como entregue:
  secao_ausente        alguma das 8 seções mínimas falta ou está vazia;
  citacao_inexistente  o documento não abre, o sha256 não confere ou `texto[inicio:fim]` ≠ citação;
  numero_sem_fonte     R$ ou % fora de um número do manifesto (ou de um bloco de achado/citação), ou `data-n` sem item;
  numero_divergente    o impresso ≠ o valor do manifesto formatado;
  cpf_exposto          CPF com DV válido no texto visível (`dominio.mascara.cpfs_expostos`);
  vocabulario          termo interno (`neutralidade.garantir_neutro`) ou de esfera penal/subjetiva (`regra_versao.texto_penal`);
  manchete_nao_tier1   destaque que não é achado vivo de detector Tier 1 no registro (`qualidade_detectores.yaml`).
PDF: `render_html` (template da casa) + Chromium com páginas numeradas "Página i de N" (`pdf_numerado`; o `html_to_pdf`
compartilhado tem 30 chamadores diretos — risco CRÍTICO no GitNexus — e segue sem numeração, como o `dossie_couto`
já fazia) + `conferir_pdf`: toda página numerada, todas as seções, todo número, toda citação e ≥ 99% das palavras.

ENTREGA (`entregar_telegram`): `ok` só com `result.message_id` inteiro; `silenciado` (silêncio de 17/11) devolve
`ok=False`. Tudo vai a `entrega` (append-only) e a exportação a `acesso_log` com justificativa (RBAC).

Efeito conferido (`_efeito`, outro processo): o manifesto gravado tem o sha declarado; TODA consulta é reexecutada na
fonte e devolve o mesmo sha256; o PDF tem o sha declarado; o validador reaprova o HTML gravado; a `entrega` existe (com
`message_id` quando foi pedido o Telegram).

CLI:
    python -m compliance_agent.aplicacao.estagios.entregar gerar --lente bombeiros --justificativa "…" [--fonte …]
           [--ug 166100] [--credor …] [--desde 2024-01-01] [--ate …] [--caso ug:166100] [--saida DIR] [--sem-pdf]
           [--enviar --chat-id …]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html as H
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import caso as E14
from compliance_agent.dominio import acesso as AC
from compliance_agent.dominio import mascara as M
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.fluxo import fonte_coleta

VERSAO = "e16-1"
PRODUTOS = ("dossie_orgao",)
RAIZ = Path(__file__).resolve().parents[3]
SAIDA_PADRAO = RAIZ / "reports" / "e16"
SECOES_MINIMAS = ("Escopo", "Metodologia", "Fontes e limitações", "Achados com status", "Contraevidências",
                  "Diligências", "Hipóteses inocentes", "Histórico")
SEM_MANCHETE = "Sem manchete: nenhum achado vivo de detector Tier 1 no escopo"
COBERTURA_PDF_MIN = 0.99
TOP_N = 15
CITACOES_MAX = 60
STATUS_VIVOS = ("triagem", "em_revisao", "confirmado")
ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"   # = cobertura_siafe.ISO_EMISSAO_SIAFE
DEFEITOS = ("secao_ausente", "citacao_inexistente", "numero_sem_fonte", "numero_divergente", "cpf_exposto",
            "vocabulario", "manchete_nao_tier1")


class ExportacaoBloqueada(RuntimeError):
    def __init__(self, defeitos: list[dict]):
        super().__init__("exportação BLOQUEADA: " + "; ".join(f"{d['classe']}: {d['detalhe']}" for d in defeitos[:8]))
        self.defeitos = defeitos


# ══ 1. formatação (a MESMA função imprime e o validador confere) ════════════════════════════════════════════════
def brl(v) -> str:
    s = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def contagem(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def pct(v) -> str:
    return f"{float(v):.1f}%".replace(".", ",")


FORMATO = {"brl": brl, "contagem": contagem, "pct": pct}


def _e(s) -> str:
    return H.escape(str(s if s is not None else ""))


def _sha(obj) -> str:
    txt = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def sha_manifesto(manifesto: dict) -> str:
    """O MESMO hash que o `render_html` põe no rodapé (json.dumps sort_keys, default=str)."""
    corpo = {k: v for k, v in manifesto.items() if k != "manifesto_sha256"}
    return hashlib.sha256(json.dumps(corpo, sort_keys=True, default=str).encode()).hexdigest()


# ══ 2. filtro (lente) e fonte ═══════════════════════════════════════════════════════════════════════════════════
def _data(v) -> str | None:
    if not v:
        return None
    t = str(v).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        raise ErroPermanente(f"data do filtro fora de AAAA-MM-DD: {v!r}")
    return t


def resolver_filtro(payload: dict, lentes: dict | None = None) -> dict:
    f = dict(payload.get("filtro") or {})
    ugs = {str(u) for u in f.get("ug") or []}
    desde = f.get("data_desde")
    lente = payload.get("lente")
    if lente == "couto":
        from compliance_agent.governo_couto import INICIO
        desde = desde or INICIO
    elif lente:
        if lentes is None:
            from compliance_agent.fluxo import lentes as L
            lentes = L.carregar()
        if lente not in lentes:
            raise ErroPermanente(f"lente inexistente: {lente!r} (config/lentes.yaml ou 'couto')")
        ugs |= set(lentes[lente].ugs) if not f.get("ug") else set()
    out = {"lente": lente or None, "ug": sorted(ugs), "credor": sorted({re.sub(r"\D", "", str(c))
                                                                          for c in f.get("credor") or []}),
           "data_desde": _data(desde), "data_ate": _data(f.get("data_ate")),
           "casos": sorted({E14.analisar_chave(c)[2] for c in payload.get("casos") or []})}
    if not (out["ug"] or out["credor"] or out["data_desde"]):
        raise ErroPermanente("filtro vazio: o dossiê precisa de UG, credor ou período (não sai do Estado inteiro "
                             "sem recorte)")
    return out


def abrir_fonte(caminho: str | Path | None) -> tuple[sqlite3.Connection, dict]:
    """A coleta em SÓ-LEITURA (`immutable=1`) e a identidade dela para o manifesto (sem relógio)."""
    p = Path(caminho or os.environ.get("JFN_ENTREGAR_FONTE") or fonte_coleta.caminho())
    if not p.exists():
        raise ErroPermanente(f"fonte inexistente: {p}")
    md5 = None
    somas = p.parent / "MD5SUMS"
    if somas.exists():
        for ln in somas.read_text(encoding="utf-8").splitlines():
            partes = ln.split()
            if len(partes) == 2 and partes[1] == p.name:
                md5 = partes[0]
    if md5 is None and p.stat().st_size < 1_500_000_000:
        h = hashlib.md5()
        with p.open("rb") as fh:
            for bloco in iter(lambda: fh.read(1 << 20), b""):
                h.update(bloco)
        md5 = h.hexdigest()
    con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
    return con, {"arquivo": p.name, "tamanho": p.stat().st_size, "md5": md5,
                 "md5_origem": "MD5SUMS" if somas.exists() and md5 else "calculado"}


# ══ 3. números com manifesto ════════════════════════════════════════════════════════════════════════════════════
@dataclass
class Coleta:
    consultas: list[dict] = field(default_factory=list)
    numeros: dict[str, dict] = field(default_factory=dict)
    linhas: dict[str, list] = field(default_factory=dict)

    def consulta(self, con: sqlite3.Connection, qid: str, sql: str, params: list) -> list[list]:
        linhas = [list(r) for r in con.execute(sql, params)]
        self.consultas.append({"id": qid, "sql": sql, "parametros": params, "linhas": len(linhas),
                               "linhas_sha256": _sha(linhas)})
        self.linhas[qid] = linhas
        return linhas

    def numero(self, nid: str, consulta: str, valor, unidade: str, rotulo: str = "") -> str:
        """Registra o número e devolve o HTML que o imprime (o validador relê exatamente isto)."""
        v = round(float(valor or 0), 2) if unidade != "contagem" else int(valor or 0)
        if nid in self.numeros and self.numeros[nid]["valor"] != v:
            raise ValueError(f"número {nid} registrado com dois valores")
        self.numeros[nid] = {"id": nid, "consulta": consulta, "valor": v, "unidade": unidade, "rotulo": rotulo}
        return f'<span class="n" data-n="{_e(nid)}">{_e(FORMATO[unidade](v))}</span>'


def _onde(filtro: dict) -> tuple[str, list]:
    partes, params = [], []
    if filtro["ug"]:
        partes.append(f"ug_emitente IN ({','.join('?' * len(filtro['ug']))})")
        params += filtro["ug"]
    if filtro["credor"]:
        partes.append(f"credor IN ({','.join('?' * len(filtro['credor']))})")
        params += filtro["credor"]
    if filtro["data_desde"]:
        partes.append(f"{ISO} >= ?")
        params.append(filtro["data_desde"])
    if filtro["data_ate"]:
        partes.append(f"{ISO} <= ?")
        params.append(filtro["data_ate"])
    return " AND ".join(partes), params


def _natureza_sql() -> str:
    """Natureza do credor da OB (a separação que só o `dossie_couto` fazia, agora genérica)."""
    return ("CASE WHEN length(credor)=14 THEN 'Pessoa jurídica (CNPJ)' WHEN length(credor)=11 THEN "
            "'Pessoa física (agregada)' WHEN credor GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]' THEN "
            "'UG do Estado (intragovernamental)' ELSE 'Credor genérico do SIAFE (folha, previdência, benefícios…)' END")


def _motivo_fora_sql() -> str:
    return ("CASE WHEN COALESCE(status,'')<>'Contabilizado' THEN 'status '||COALESCE(NULLIF(status,''),'vazio') "
            "WHEN COALESCE(status_envio,'')='Erro no Pagamento' THEN 'devolvida (erro no pagamento)' "
            "WHEN COALESCE(tipo_regularizacao,'')='Pagamento Complementar' THEN 'pagamento complementar' "
            "WHEN COALESCE(numero_ob,'')='' THEN 'sem número de OB' ELSE 'reemitida (1ª emissão)' END")


def coletar(con: sqlite3.Connection, filtro: dict) -> tuple[Coleta, dict]:
    from compliance_agent.dominio.pagamento import ob_paga_sql
    paga = ob_paga_sql(con)
    onde, p = _onde(filtro)
    col = Coleta()
    base = f"FROM ob_orcamentaria_siafe WHERE {onde}"
    d = {"regra_paga": paga}
    d["total"] = col.consulta(con, "q.total", f"SELECT COUNT(*), ROUND(SUM(valor),2) {base} AND {paga}", p)[0]
    d["ano"] = col.consulta(con, "q.ano", f"SELECT substr(data_emissao,7,4), COUNT(*), ROUND(SUM(valor),2) {base} "
                                          f"AND {paga} GROUP BY 1 ORDER BY 1", p)
    d["ug"] = col.consulta(con, "q.ug", f"SELECT ug_emitente, COUNT(*), ROUND(SUM(valor),2) {base} AND {paga} "
                                        "GROUP BY 1 ORDER BY 3 DESC, 1", p)
    d["natureza"] = col.consulta(con, "q.natureza", f"SELECT {_natureza_sql()}, COUNT(*), ROUND(SUM(valor),2) {base} "
                                                    f"AND {paga} GROUP BY 1 ORDER BY 3 DESC, 1", p)
    # favorecido = pessoa jurídica (CNPJ); folha, previdência, UG do Estado e pessoa física ficam agregados acima
    d["top"] = col.consulta(con, "q.top", f"SELECT credor, MAX(nome_credor), COUNT(*), ROUND(SUM(valor),2) {base} "
                                          f"AND {paga} AND length(credor)=14 GROUP BY credor ORDER BY 4 DESC, 1 "
                                          f"LIMIT {TOP_N}", p)
    d["fora"] = col.consulta(con, "q.fora", f"SELECT {_motivo_fora_sql()}, COUNT(*), ROUND(SUM(valor),2) {base} "
                                            f"AND NOT ({paga}) GROUP BY 1 ORDER BY 3 DESC, 1", p)
    d["coleta"] = col.consulta(con, "q.coleta", f"SELECT MIN(coletado_em), MAX(coletado_em), MIN({ISO}), MAX({ISO}) "
                                                f"{base}", p)[0]
    d["cobertura"] = cobertura(con, col, filtro)
    return col, d


def cobertura(con: sqlite3.Connection, col: Coleta, filtro: dict) -> list[dict] | str:
    """Cobertura do SIAFE por (UG, ano) contra o espelho TFE — a régua de `reporting.cobertura_siafe`
    (`estado_por_contagem`: número de OB do espelho ausente do SIAFE ⇒ parcial; SIAFE vazio ⇒ nunca coletado).
    Sem UG no filtro (recorte do Estado inteiro) ou sem o espelho na fonte: texto do motivo, nunca "coberto"."""
    from compliance_agent.reporting.cobertura_siafe import estado_por_contagem
    if not filtro["ug"]:
        return "não medida: recorte sem UG (o Estado inteiro) — a cobertura é por par UG × ano"
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ordens_bancarias'").fetchone() is None:
        return "INDISPONÍVEL: a fonte não traz o espelho TFE (ordens_bancarias) para comparar"
    ugs = ",".join("?" * len(filtro["ug"]))
    datas, pd = "", []
    for op, chave in ((">=", "data_desde"), ("<=", "data_ate")):
        if filtro[chave]:
            datas += f" AND substr(data_emissao,1,10) {op} ?"
            pd.append(filtro[chave])
    esp = col.consulta(con, "q.cobertura_espelho",
                       "SELECT ug_codigo, substr(data_emissao,1,4), COUNT(*), COALESCE(SUM(NOT EXISTS (SELECT 1 FROM "
                       "ob_orcamentaria_siafe s WHERE s.numero_ob = o.numero_ob AND s.ug_emitente = o.ug_codigo)),0) "
                       f"FROM ordens_bancarias o WHERE ug_codigo IN ({ugs}) AND numero_ob IS NOT NULL{datas} "
                       "GROUP BY 1, 2 ORDER BY 1, 2", [*filtro["ug"], *pd])
    # ob-qualquer-status: cobertura da coleta (nº de OB presente no SIAFE por UG × ano, régua de reporting.cobertura_siafe), não soma
    sia = {(u, a): n for u, a, n in col.consulta(
        con, "q.cobertura_siafe", f"SELECT ug_emitente, substr(data_emissao,7,4), COUNT(*) FROM ob_orcamentaria_siafe "
                                  f"WHERE ug_emitente IN ({ugs}) GROUP BY 1, 2 ORDER BY 1, 2", list(filtro["ug"]))}
    return [{"ug": u, "ano": a, **estado_por_contagem(n, aus, sia.get((u, a), 0))} for u, a, n, aus in esp]


# ══ 4. achados (E14) e citações (E11) ═══════════════════════════════════════════════════════════════════════════
def chaves_de_caso(filtro: dict) -> list[str]:
    if filtro["casos"]:
        return filtro["casos"]
    if filtro["credor"]:
        return [f"cnpj:{c}" for c in filtro["credor"] if len(c) == 14]
    return [f"ug:{u}" for u in filtro["ug"]]


def casos_do_pg(pg, filtro: dict, principal: AC.Principal) -> list[dict]:
    """Monta (idempotente) e lê cada caso do escopo — a montagem e a leitura ficam no acesso_log."""
    out = []
    for ch in chaves_de_caso(filtro):
        m = E14.montar(pg, ch, principal)
        out.append({"chave": ch, "caso_id": m["caso_id"], "versao": m["versao_versao"], "chave_sha": m["versao_chave"],
                    "derivado": E14.vigente(pg, m["caso_id"])["derivado"]})
    return out


def citacoes_e11(pg, processos: list[str]) -> list[dict]:
    from compliance_agent.aplicacao.estagios import periciar as E11
    esq = E11.esquema_vigente()
    if not processos or pg.execute("SELECT to_regclass(%s)", (f'"{esq}".laudos_v2',)).fetchone()[0] is None:
        return []
    out = []
    for proc, eixos in pg.execute(f'SELECT processo, laudo -> \'eixos\' FROM "{esq}".laudos_v2 WHERE vigente AND '
                                  "processo = ANY(%s) ORDER BY processo", (processos,)):
        for nome, ex in sorted((eixos or {}).items()):
            for a in ex.get("achados") or []:
                if a.get("citacao") and a.get("doc_sha") and a.get("inicio") is not None:
                    out.append({"processo": proc, "eixo": nome, "doc_id": a["doc_id"], "documento_sha256": a["doc_sha"],
                                "inicio": int(a["inicio"]), "fim": int(a["fim"]), "citacao": a["citacao"]})
    return out[:CITACOES_MAX]


def resolver_documento_acervo(processo: str, doc_id: str) -> dict | None:
    """{sha, texto} do documento no acervo (o mesmo leitor do E8/E11) ou None."""
    from compliance_agent import leitura_integral as LI
    from compliance_agent.aplicacao.estagios import fatos as E8
    pasta = E8.pasta_do(processo)
    if not (pasta / "manifest.json").exists():
        return None
    return next(({"sha": d["sha"], "texto": d["texto"]} for d in LI._docs(pasta) if d["doc_id"] == doc_id), None)


# ══ 5. montagem do dossiê ═══════════════════════════════════════════════════════════════════════════════════════
def _tabela(cab: list[str], linhas: list[list[str]]) -> str:
    th = "".join(f"<th>{c}</th>" for c in cab)
    corpo = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in ln) + "</tr>" for ln in linhas)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{corpo}</tbody></table>"


def _mascara_doc(doc: str) -> str:
    from compliance_agent.cpf_cnpj import mascarar_doc
    return mascarar_doc(doc)


def _texto_seguro(t) -> str:
    """Texto livre (observação de achado, argumento): CPF mascarado (PAD-04) e escapado."""
    from compliance_agent.cpf_cnpj import mascarar_cpf_no_texto
    return _e(mascarar_cpf_no_texto(str(t or "")))


def _descr_filtro(f: dict) -> str:
    partes = []
    if f["lente"]:
        partes.append(f"lente <b>{_e(f['lente'])}</b>")
    if f["ug"]:
        partes.append("UG " + ", ".join(_e(u) for u in f["ug"]))
    if f["credor"]:
        partes.append("credor " + ", ".join(_e(_mascara_doc(c)) for c in f["credor"]))
    if f["data_desde"] or f["data_ate"]:
        partes.append(f"emissão da OB de {_e(f['data_desde'] or 'início da série')} a {_e(f['data_ate'] or 'fim da coleta')}")
    return "; ".join(partes)


def manchetes(achados: list[dict], registro: dict) -> list[dict]:
    out = []
    for a in achados:
        e = registro.get(a["regra_id"]) or {}
        if e.get("tier") == 1 and a["status_efetivo"] in STATUS_VIVOS and a["estado"] == "INDICIO":
            out.append({"achado_id": a["id"], "regra_id": a["regra_id"],
                        "texto": f"{e.get('afirma') or a['regra_id']} — achado {a['id']}"})
    return out


def montar(fonte_con: sqlite3.Connection, fonte_id: dict, filtro: dict, *, casos: list[dict] | None,
           citacoes: list[dict] | None, registro: dict, produto: str = "dossie_orgao") -> dict:
    """O dossiê inteiro (seções + manifesto), sem I/O de escrita e sem relógio."""
    col, d = coletar(fonte_con, filtro)
    n_tot, v_tot = d["total"][0] or 0, d["total"][1] or 0.0
    mn = col.numero
    achados = [a for c in (casos or []) for a in c["derivado"]["achados"]]
    vistos: set[int] = set()
    achados = [a for a in achados if not (a["id"] in vistos or vistos.add(a["id"]))]
    der = [c["derivado"] for c in (casos or [])]
    s: list[dict] = []

    s.append({"titulo": "1. Escopo", "html":
              # número não quebra linha: célula quebrada embaralha as colunas no texto do PDF e a conferência o perde
              "<style>.n{white-space:nowrap}</style>"
              f"<p><b>Recorte:</b> {_descr_filtro(filtro)}.</p>"
              f"<p><b>Universo pago (OB do SIAFE que é pagamento):</b> {mn('total.n', 'q.total', n_tot, 'contagem')} "
              f"ordens bancárias, {mn('total.valor', 'q.total', v_tot, 'brl')}. Empenho e liquidação não são pagamento; "
              "o espelho TFE não entra na soma.</p>"
              f"<p><b>Casos do escopo:</b> {_e(', '.join(c['chave'] for c in casos) if casos else 'nenhum')}"
              f"{'' if casos is not None else ' — achados INDISPONÍVEIS (sem acesso ao banco de achados)'}.</p>"})
    s.append({"titulo": "2. Metodologia", "html":
              "<ul><li><b>Pagamento</b> = OB do SIAFE (<code>ob_orcamentaria_siafe</code>) que passa no predicado "
              "único da casa: Contabilizada, não devolvida, sem pagamento complementar, sem a 1ª emissão de OB "
              "reemitida e com número.</li>"
              "<li><b>Período</b> pela data de EMISSÃO da OB (texto DD/MM/AAAA convertido para AAAA-MM-DD).</li>"
              "<li><b>Achados</b>: hipóteses de auditoria do motor de detectores no contrato único (observação, "
              "inferência, qualificação), agrupadas em casos; o status é o da última decisão humana — a regra não "
              "decide. Tier do detector lido do registro de qualidade.</li>"
              "<li><b>Manchete</b> só de detector Tier 1 com achado vivo; os demais são sinal, não destaque.</li>"
              "<li><b>Reprodutibilidade</b>: cada número aponta para uma consulta do manifesto de hashes (anexo), "
              "com o sha256 das linhas que ela devolve; gerar de novo sobre a mesma fonte dá o mesmo manifesto.</li></ul>"})
    linhas_ano = [[_e(a), mn(f"ano.{a}.n", "q.ano", n, "contagem"), mn(f"ano.{a}.valor", "q.ano", v, "brl")]
                  for a, n, v in d["ano"]]
    linhas_ug = [[_e(u), mn(f"ug.{u}.n", "q.ug", n, "contagem"), mn(f"ug.{u}.valor", "q.ug", v, "brl")]
                 for u, n, v in d["ug"]]
    linhas_nat = [[_e(k), mn(f"natureza.{i}.n", "q.natureza", n, "contagem"),
                   mn(f"natureza.{i}.valor", "q.natureza", v, "brl"),
                   mn(f"natureza.{i}.pct", "q.natureza", 100 * float(v or 0) / v_tot if v_tot else 0, "pct")]
                  for i, (k, n, v) in enumerate(d["natureza"])]
    linhas_top = [[_e(nome or "—"), _e(_mascara_doc(doc)), mn(f"top.{i}.n", "q.top", n, "contagem"),
                   mn(f"top.{i}.valor", "q.top", v, "brl"),
                   mn(f"top.{i}.pct", "q.top", 100 * float(v or 0) / v_tot if v_tot else 0, "pct")]
                  for i, (doc, nome, n, v) in enumerate(d["top"], 1)]          # id pela POSIÇÃO, nunca o documento
    s.append({"titulo": "3. Execução financeira (OB paga)", "html":
              "<h4>Por ano de emissão</h4>" + _tabela(["Ano", "OBs pagas", "Valor pago"], linhas_ano)
              + ("<h4>Por UG emitente</h4>" + _tabela(["UG", "OBs pagas", "Valor pago"], linhas_ug)
                 if len(linhas_ug) > 1 else "")
              + "<h4>Por natureza do credor</h4>"
              + _tabela(["Natureza", "OBs pagas", "Valor pago", "% do universo"], linhas_nat)
              + f"<h4>Maiores favorecidos — pessoa jurídica ({TOP_N})</h4>"
              + _tabela(["Favorecido", "CNPJ", "OBs", "Valor", "% do universo"], linhas_top)})
    fora = [[_e(m), mn(f"fora.{i}.n", "q.fora", n, "contagem"), mn(f"fora.{i}.valor", "q.fora", v, "brl")]
            for i, (m, n, v) in enumerate(d["fora"])]
    c0 = d["coleta"]
    s.append({"titulo": "4. Fontes e limitações", "html":
              f"<p><b>Fonte:</b> coleta do SIAFE-Rio <code>{_e(fonte_id['arquivo'])}</code> "
              f"({_e(contagem(fonte_id['tamanho']))} bytes, md5 {_e(fonte_id['md5'] or 'não declarado')} — "
              f"{_e(fonte_id['md5_origem'])}); OBs do recorte coletadas de {_e(c0[0] or '—')} a {_e(c0[1] or '—')}, "
              f"emitidas de {_e(c0[2] or '—')} a {_e(c0[3] or '—')}.</p>"
              "<p><b>Fora da soma</b> (o recorte pega, mas não é pagamento):</p>"
              + (_tabela(["Motivo", "OBs", "Valor"], fora) if fora else "<p>Nenhuma OB do recorte fora da soma.</p>")
              + "<p><b>Cobertura do SIAFE por UG e ano</b> (OB do espelho TFE ausente do SIAFE; parcial = o valor do "
                "ano é piso):</p>"
              + (_tabela(["UG", "Ano", "Estado", "OBs no espelho", "Ausentes do SIAFE", "OBs no SIAFE"],
                         [[_e(c["ug"]), _e(c["ano"]), _e(c["estado"]), _e(contagem(c.get("amostra") or 0)),
                           _e(contagem(c.get("ausentes") or 0)), _e(contagem(c.get("obs_siafe") or 0))]
                          for c in d["cobertura"]])
                 if isinstance(d["cobertura"], list) and d["cobertura"] else
                 f"<p>{_e(d['cobertura'] or 'sem par UG × ano no espelho para comparar')}.</p>")
              + "<p><b>Limitações:</b> a coleta é um retrato (não acompanha OB emitida depois dela); exercício que o "
                "SIAFE da casa não tem inteiro é piso, não total; INDISPONÍVEL não equivale a zero; achado de detector "
                "Tier 2/3 é sinal a conferir, não conclusão.</p>"})
    blocos = []
    # a mesma execução (regra + entradas) gravada por mais de uma versão da regra aparece UMA vez, com os ids todos
    gemeos: dict[tuple, list[int]] = {}
    for a in achados:
        gemeos.setdefault((a["regra_id"], a["entradas_hash"]), []).append(a["id"])
    for a in achados:
        ids = gemeos[(a["regra_id"], a["entradas_hash"])]
        if a["id"] != ids[0]:
            continue
        outros = f" · mesma execução também registrada como achado {', '.join(map(str, ids[1:]))}" if ids[1:] else ""
        evid = "".join(f"<li>{_e(v['papel'])}: {_texto_seguro((v['fato'] or {}).get('descricao'))} "
                       f"({_e((v['fato'] or {}).get('fonte'))} {_e((v['fato'] or {}).get('referencia') or '')})</li>"
                       for v in a["evidencias"])
        blocos.append(
            f'<div class="achado" data-achado="{a["id"]}"><h3>Achado {a["id"]} · {_e(a["regra_id"])} · '
            f'status {_e(a["status_efetivo"])} · {_e(a["estado"])} · Tier {_e(a["tier"] or "?")}'
            f'{" · contestação pendente" if a["contestacao_pendente"] else ""}{_e(outros)}</h3>'
            f"<p><b>Observação:</b> {_texto_seguro(a['observacao'])}</p>"
            f"<p><b>Inferência:</b> {_texto_seguro(a['inferencia'])}</p>"
            + (f"<ul>{evid}</ul>" if evid else "") + "</div><!--/achado-->")
    cits = []
    for i, c in enumerate(citacoes or []):
        cits.append(f'<blockquote class="clausula" data-cit="cit.{i}">{_texto_seguro(c["citacao"])}</blockquote>'
                    f'<p class="cit">{_e(c["processo"])} · {_e(c["doc_id"])} · eixo {_e(c["eixo"])}</p>')
    st = Counter(a["status_efetivo"] for a in achados)
    s.append({"titulo": "5. Achados com status", "html":
              ("<p>Achados INDISPONÍVEIS: sem acesso ao banco de achados nesta geração (não é zero).</p>"
               if casos is None else
               f"<p>{_e(contagem(len(achados)))} registro(s) de achado nos casos do escopo "
               f"({_e(contagem(len(gemeos)))} execução(ões) distinta(s)) — "
               + _e(", ".join(f"{k}: {contagem(v)}" for k, v in sorted(st.items())) or "nenhum") + ".</p>")
              + "".join(blocos)
              + ("<h4>Citações dos autos (laudo pericial vigente)</h4>" + "".join(cits) if cits else "")})
    contra = [x for dv in der for x in dv["contraevidencias"]]
    s.append({"titulo": "6. Contraevidências", "html":
              "<ul>" + "".join(f"<li>achado {_e(x['achado_id'] or '—')} · {_e(x['origem'])}: "
                               f"{_texto_seguro(x['descricao'])}</li>" for x in contra) + "</ul>"
              if contra else "<p>Nenhuma contraevidência registrada nos casos do escopo.</p>"})
    dil = [x for dv in der for x in dv["diligencias"]]
    s.append({"titulo": "7. Diligências", "html":
              "<ol>" + "".join(f"<li>{_texto_seguro(x['texto'])}</li>" for x in dil) + "</ol>"
              if dil else "<p>Nenhuma diligência pendente nos casos do escopo.</p>"})
    hip = [x for dv in der for x in dv["hipoteses_inocentes"]]
    s.append({"titulo": "8. Hipóteses inocentes", "html":
              _tabela(["Achado", "Regra", "Hipótese", "Origem", "Excluída por"],
                      [[_e(x["achado_id"]), _e(x["regra_id"]), _texto_seguro(x["hipotese"]), _e(x["origem"]),
                        _e(x["excluida_por"] or "não excluída (a examinar)")] for x in hip])
              if hip else "<p>Nenhum achado no escopo — sem hipótese a examinar.</p>"})
    hist = [x for dv in der for x in dv["historico"]]
    s.append({"titulo": "9. Histórico", "html":
              "<p>Sem caso nem evento registrado no escopo.</p>" if not (casos or hist) else
              "<ul>" + "".join(f"<li>caso {_e(c['chave'])}: versão {_e(c['versao'])} "
                               f"(<span class=\"mono\">{_e(c['chave_sha'][:16])}</span>)</li>" for c in casos or [])
              + "".join(f"<li>{_e(x['em'])} · {_e(x['evento'])} · achado {_e(x['achado_id'] or '—')}: "
                        f"{_texto_seguro(x['detalhe'])}</li>" for x in hist) + "</ul>"})
    man_cits = [{"id": f"cit.{i}", "processo": c["processo"], "doc_id": c["doc_id"],
                 "documento_sha256": c["documento_sha256"], "inicio": c["inicio"], "fim": c["fim"],
                 "trecho_sha256": hashlib.sha256(c["citacao"].encode("utf-8")).hexdigest(),
                 "exibido": H.unescape(_texto_seguro(c["citacao"]))} for i, c in enumerate(citacoes or [])]
    manifesto = {"versao_estagio": VERSAO, "produto": produto, "filtro": filtro, "fonte": fonte_id,
                 "regra_paga": d["regra_paga"], "consultas": col.consultas,
                 "numeros": [col.numeros[k] for k in sorted(col.numeros)], "citacoes": man_cits,
                 "achados": [{"id": a["id"], "regra_id": a["regra_id"], "entradas_hash": a["entradas_hash"],
                              "status_efetivo": a["status_efetivo"], "tier": a["tier"]} for a in achados],
                 "casos": [{"chave": c["chave"], "versao": c["versao"], "chave_sha": c["chave_sha"]}
                           for c in casos or []],
                 "achados_disponiveis": casos is not None}
    manifesto["manifesto_sha256"] = sha_manifesto(manifesto)
    ms = manchetes(achados, registro)
    linhas_man = [[_e(q["id"]), _e(q["linhas"]), f'<span class="mono">{_e(q["linhas_sha256"])}</span>']
                  for q in col.consultas]
    s.append({"titulo": "Anexo — Manifesto de hashes", "page_break": True, "html":
              f"<p>sha256 do manifesto: <span class=\"mono\">{manifesto['manifesto_sha256']}</span>. "
              "Cada número do documento aponta para uma destas consultas (SQL e parâmetros no manifesto JSON "
              "entregue junto); reexecutá-las sobre a mesma fonte devolve linhas com o mesmo sha256.</p>"
              + _tabela(["Consulta", "Linhas", "sha256 das linhas"], linhas_man)})
    ctx = {"classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
           "titulo": f"Dossiê — {_descr_filtro(filtro).replace('<b>', '').replace('</b>', '')}",
           "subtitulo": "Execução financeira (OB paga), achados com status, contraevidências e diligências",
           "data": _data_ref(c0[1]), "metodologia": "OB = pagamento (SIAFE) · contrato único do achado · manifesto "
                                                    "de hashes reproduzível",
           "sem_indice": True, "top_flags": [m["texto"] for m in ms] or [SEM_MANCHETE], "secoes": s,
           "proveniencia": [{"dado": "OB paga do recorte", "estado": "REAL", "fonte": f"SIAFE ({fonte_id['arquivo']})",
                             "data": _data_ref(c0[1])},
                            {"dado": "Achados e casos", "estado": "REAL" if casos is not None else "INDISPONÍVEL",
                             "fonte": "contrato único do achado (casos versionados)", "data": _data_ref(c0[1])}],
           "_dados": {k: v for k, v in manifesto.items() if k != "manifesto_sha256"}}
    return {"produto": produto, "filtro": filtro, "ctx": ctx, "manifesto": manifesto, "manchetes": ms,
            "citacoes": citacoes or []}


def _data_ref(coletado_em) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(coletado_em or ""))
    return f"{m[3]}/{m[2]}/{m[1]}" if m else "—"


def render(dossie: dict) -> str:
    from compliance_agent.reporting.render_html import render_html
    return render_html(dossie["ctx"])


# ══ 6. validador (bloqueante) ═══════════════════════════════════════════════════════════════════════════════════
_RX_N = re.compile(r'<span class="n" data-n="([^"]+)">([^<]*)</span>')
_RX_ACHADO = re.compile(r'<div class="achado" data-achado="(\d+)">.*?</div><!--/achado-->', re.S)
_RX_CIT = re.compile(r'<blockquote class="clausula" data-cit="([^"]+)">(.*?)</blockquote>', re.S)
_RX_SEC = re.compile(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|<footer|$)", re.S)
_RX_NUM_SOLTO = re.compile(r"R\$\s?-?\d|\d+(?:,\d+)?\s?%")


def visivel(html: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", H.unescape(t)).strip()


Resolvedor = Callable[[str, str], "dict | None"]


def validar(dossie: dict, html: str, *, resolver_doc: Resolvedor | None = None, registro: dict | None = None
            ) -> list[dict]:
    """Defeitos (lista vazia = aprovado). Relê o HTML final — não confia na montagem."""
    from compliance_agent.dominio.regra_versao import texto_penal
    from compliance_agent.reporting.neutralidade import garantir_neutro
    reg = registro if registro is not None else E14._registro()
    resolver = resolver_doc or resolver_documento_acervo
    man = dossie["manifesto"]
    out: list[dict] = []

    def defeito(classe: str, detalhe: str) -> None:
        out.append({"classe": classe, "detalhe": detalhe})

    secoes = {re.sub(r"^\s*\d+\.\s*", "", visivel(t)): visivel(c) for t, c in _RX_SEC.findall(html)}
    for nome in SECOES_MINIMAS:
        if not secoes.get(nome):
            defeito("secao_ausente", nome)
    nums = {n["id"]: n for n in man["numeros"]}
    for nid, txt in _RX_N.findall(html):
        n = nums.get(H.unescape(nid))
        if n is None:
            defeito("numero_sem_fonte", f"data-n {nid!r} sem item no manifesto")
        elif H.unescape(txt) != FORMATO[n["unidade"]](n["valor"]):
            defeito("numero_divergente", f"{nid}: impresso {H.unescape(txt)!r}, manifesto "
                                         f"{FORMATO[n['unidade']](n['valor'])!r}")
    ids_ach = {str(a["id"]) for a in man["achados"]}
    for aid in _RX_ACHADO.findall(html):
        if aid not in ids_ach:
            defeito("numero_sem_fonte", f"bloco do achado {aid} sem achado no manifesto")
    cits = {c["id"]: c for c in man["citacoes"]}
    for cid, txt in _RX_CIT.findall(html):
        c = cits.get(cid)
        if c is None:
            defeito("citacao_inexistente", f"{cid} sem item no manifesto")
            continue
        doc = resolver(c["processo"], c["doc_id"])
        trecho = doc["texto"][c["inicio"]:c["fim"]] if doc else None
        if doc is None:
            defeito("citacao_inexistente", f"{cid}: documento {c['doc_id']} de {c['processo']} não abre")
        elif doc["sha"] != c["documento_sha256"]:
            defeito("citacao_inexistente", f"{cid}: sha256 do documento {c['doc_id']} não confere")
        elif hashlib.sha256(trecho.encode("utf-8")).hexdigest() != c["trecho_sha256"]:
            defeito("citacao_inexistente", f"{cid}: texto[{c['inicio']}:{c['fim']}] não é a citação")
        elif visivel(txt) != visivel(_texto_seguro(trecho)):
            defeito("citacao_inexistente", f"{cid}: o impresso não é o trecho do documento")
    sem_fonte = visivel(_RX_CIT.sub(" ", _RX_ACHADO.sub(" ", _RX_N.sub(" ", html))))
    for m in _RX_NUM_SOLTO.finditer(sem_fonte):
        defeito("numero_sem_fonte", f"…{sem_fonte[max(0, m.start() - 50): m.end() + 25]}…")
    vis = visivel(html)
    if M.cpfs_expostos(vis):
        defeito("cpf_exposto", f"{M.cpfs_expostos(vis)} CPF(s) com DV válido no texto")
    try:
        garantir_neutro(vis, "dossiê")
    except AssertionError as e:
        defeito("vocabulario", str(e))
    if texto_penal(vis):
        defeito("vocabulario", f"termos de esfera penal/subjetiva: {texto_penal(vis)}")
    vivos = {str(a["id"]): a for a in man["achados"]}
    for m in dossie["manchetes"]:
        a = vivos.get(str(m["achado_id"]))
        if a is None or (reg.get(a["regra_id"]) or {}).get("tier") != 1 or a["status_efetivo"] not in STATUS_VIVOS:
            defeito("manchete_nao_tier1", f"{m['texto']!r} (achado {m['achado_id']})")
    flags = dossie["ctx"].get("top_flags") or []
    textos = {m["texto"] for m in dossie["manchetes"]}
    for fl in flags:
        if fl != SEM_MANCHETE and fl not in textos:
            defeito("manchete_nao_tier1", f"destaque sem achado Tier 1: {fl!r}")
    return out


# ══ 7. PDF numerado + conferência de que levou TUDO ════════════════════════════════════════════════════════════
async def pdf_numerado(html: str, destino: str, timeout_s: float = 300.0) -> str:
    """O Chromium do `html_to_pdf` da casa (A4, fundo, margens) com rodapé "Página i de N"."""
    from playwright.async_api import async_playwright
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await b.new_page()
            await asyncio.wait_for(page.set_content(html, wait_until="networkidle"), timeout_s)
            await asyncio.wait_for(page.pdf(
                path=destino, format="A4", print_background=True, display_header_footer=True,
                header_template="<span></span>",
                footer_template=("<div style='font-family:Georgia,serif;font-size:7.5px;color:#888;width:100%;"
                                 "padding:0 12mm;display:flex;justify-content:space-between'>"
                                 "<span>Controle Externo — RJ · indícios, nunca acusação</span>"
                                 "<span>Página <span class='pageNumber'></span> de <span class='totalPages'></span>"
                                 "</span></div>"),
                margin={"top": "14mm", "bottom": "14mm", "left": "10mm", "right": "10mm"}), timeout_s)
        finally:
            await b.close()
    return destino


def texto_pdf(pdf: Path) -> list[str]:
    """Texto por página (pdftotext; páginas separadas por form feed)."""
    r = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise OSError(f"pdftotext falhou: {r.stderr.strip()[:200]}")
    paginas = r.stdout.split("\f")
    return paginas[:-1] if paginas and not paginas[-1].strip() else paginas


def conferir_pdf(paginas: list[str], dossie: dict, html: str) -> list[dict]:
    out = []
    n = len(paginas)
    compacto = re.sub(r"\s+", "", "".join(paginas))
    for i, p in enumerate(paginas, 1):
        if f"Página {i} de {n}" not in re.sub(r"\s+", " ", p):
            out.append({"classe": "pdf_incompleto", "detalhe": f"página {i} sem 'Página {i} de {n}'"})
    for t, _c in _RX_SEC.findall(html):
        if re.sub(r"\s+", "", visivel(t)) not in compacto:
            out.append({"classe": "pdf_incompleto", "detalhe": f"seção {visivel(t)!r} não está no PDF"})
    for nid, txt in _RX_N.findall(html):
        if re.sub(r"\s+", "", H.unescape(txt)) not in compacto:
            out.append({"classe": "pdf_incompleto", "detalhe": f"número {nid} ({H.unescape(txt)}) não está no PDF"})
    for cid, txt in _RX_CIT.findall(html):
        if re.sub(r"\s+", "", visivel(txt)) not in compacto:
            out.append({"classe": "pdf_incompleto", "detalhe": f"citação {cid} não está no PDF"})
    vis = visivel(html)
    ph = Counter(re.findall(r"[A-Za-zÀ-ÿ]{4,}", vis.lower()))                 # caixa baixa: o CSS do h4 é uppercase
    pp = Counter(re.findall(r"[A-Za-zÀ-ÿ]{4,}", "".join(paginas).lower()))
    tot = sum(ph.values())
    cob = round(sum(min(k, pp.get(w, 0)) for w, k in ph.items()) / tot, 4) if tot else 0.0
    if cob < COBERTURA_PDF_MIN:
        out.append({"classe": "pdf_incompleto", "detalhe": f"cobertura de palavras {cob:.2%} < {COBERTURA_PDF_MIN:.0%}"})
    return out


# ══ 8. entrega honesta ══════════════════════════════════════════════════════════════════════════════════════════
def resultado_telegram(resp: dict) -> dict:
    """`ok` SÓ com `result.message_id` inteiro; silenciado ⇒ ok=False (memória telegram-silencio-devolve-ok)."""
    if resp.get("silenciado"):
        return {"ok": False, "message_id": None, "motivo": "silenciado (silêncio de 17/11) — não foi entregue"}
    mid = (resp.get("result") or {}).get("message_id") if isinstance(resp.get("result"), dict) else None
    if resp.get("ok") is True and isinstance(mid, int) and not isinstance(mid, bool):
        return {"ok": True, "message_id": mid, "motivo": "entregue"}
    return {"ok": False, "message_id": None,
            "motivo": str(resp.get("description") or resp.get("error") or "sem message_id na resposta")[:300]}


def entregar_telegram(pdf: Path, legenda: str, chat_id: str = "", *, pedido_do_dono: bool = True,
                      enviar: Callable | None = None) -> dict:
    from compliance_agent.notifications import silencio
    from compliance_agent.notifications import telegram as TG
    fn = enviar or TG.enviar_arquivo

    async def _vai():
        tok = silencio.PEDIDO.set(True) if pedido_do_dono else None
        try:
            return await fn(str(pdf), caption=legenda, chat_id=chat_id)
        finally:
            if tok is not None:
                silencio.PEDIDO.reset(tok)
    return resultado_telegram(asyncio.run(_vai()) or {})


def _registrar_entrega(pg, *, produto, chave, manifesto_sha, pdf_sha, pdf_caminho, paginas, destino, ok,
                       message_id, motivo) -> int:
    return pg.execute("INSERT INTO entrega(produto, chave, manifesto_sha256, pdf_sha256, pdf_caminho, paginas, destino, "
                      "ok, message_id, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                      (produto, chave, manifesto_sha, pdf_sha, pdf_caminho, paginas, destino, ok, message_id,
                       motivo)).fetchone()[0]


def _sha_arquivo(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def exportar(pg, dossie: dict, principal: AC.Principal, justificativa: str, *, chave: str, saida: Path,
             com_pdf: bool = True, enviar: bool = False, chat_id: str = "", resolver_doc: Resolvedor | None = None,
             registro: dict | None = None, gerar_pdf: Callable | None = None, enviar_fn: Callable | None = None
             ) -> dict:
    """RBAC (acesso_log) → validador → PDF temporário → conferência do PDF → grava → entrega. Qualquer defeito
    BLOQUEIA: nada vai para `saida` e a `entrega` registra ok=False com os defeitos."""
    man = dossie["manifesto"]
    E14.autorizar(pg, principal, AC.Acao.EXPORTAR_DOSSIE, f"dossie:{chave}", justificativa=justificativa,
                  classe="interno", detalhe={"manifesto_sha256": man["manifesto_sha256"]})
    html = render(dossie)
    defeitos = validar(dossie, html, resolver_doc=resolver_doc, registro=registro)
    base = saida / f"{dossie['produto']}_{man['manifesto_sha256'][:12]}"
    pdf_sha = paginas = None
    tmp_pdf = base.with_suffix(".pdf.tmp")
    if not defeitos and com_pdf:
        saida.mkdir(parents=True, exist_ok=True)
        asyncio.run((gerar_pdf or pdf_numerado)(html, str(tmp_pdf)))
        pags = texto_pdf(tmp_pdf)
        defeitos = conferir_pdf(pags, dossie, html)
        paginas = len(pags)
        if defeitos:
            tmp_pdf.unlink(missing_ok=True)
    if defeitos:
        _registrar_entrega(pg, produto=dossie["produto"], chave=chave, manifesto_sha=man["manifesto_sha256"],
                           pdf_sha=None, pdf_caminho=None, paginas=paginas, destino="arquivo", ok=False,
                           message_id=None, motivo=json.dumps(defeitos, ensure_ascii=False)[:4000])
        raise ExportacaoBloqueada(defeitos)
    saida.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".html").write_text(html, encoding="utf-8")
    base.with_suffix(".manifesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True,
                                                              default=str), encoding="utf-8")
    pdf = None
    if com_pdf:
        pdf = base.with_suffix(".pdf")
        shutil.move(str(tmp_pdf), pdf)
        pdf_sha = _sha_arquivo(pdf)
    out = {"html": str(base.with_suffix(".html")), "manifesto": str(base.with_suffix(".manifesto.json")),
           "manifesto_sha256": man["manifesto_sha256"], "pdf": str(pdf) if pdf else None, "pdf_sha256": pdf_sha,
           "paginas": paginas, "entregas": []}
    out["entregas"].append(_registrar_entrega(
        pg, produto=dossie["produto"], chave=chave, manifesto_sha=man["manifesto_sha256"], pdf_sha=pdf_sha,
        pdf_caminho=out["pdf"], paginas=paginas, destino="arquivo", ok=True, message_id=None, motivo="gravado"))
    if enviar:
        if pdf is None:
            raise ErroPermanente("envio pedido sem PDF")
        r = entregar_telegram(pdf, f"Dossiê {dossie['produto']} · manifesto {man['manifesto_sha256'][:16]}",
                              chat_id, enviar=enviar_fn)
        out["telegram"] = r
        out["entregas"].append(_registrar_entrega(
            pg, produto=dossie["produto"], chave=chave, manifesto_sha=man["manifesto_sha256"], pdf_sha=pdf_sha,
            pdf_caminho=out["pdf"], paginas=paginas, destino="telegram", ok=r["ok"], message_id=r["message_id"],
            motivo=r["motivo"]))
    return out


# ══ 9. estágio (contrato do §3.2) ═══════════════════════════════════════════════════════════════════════════════
def _produto(payload: dict, ctx: Contexto | None) -> str:
    p = payload.get("produto") or (ctx.tipo.split(":", 1)[1] if ctx and ":" in ctx.tipo else "")
    if p not in PRODUTOS:
        raise ErroPermanente(f"produto inválido: {p!r} (válidos: {', '.join(PRODUTOS)})")
    return p


def chave_pedido(produto: str, filtro: dict) -> str:
    return f"{produto}:{_sha(filtro)[:16]}"


def gerar(payload: dict, principal: AC.Principal, *, pg=None, registro: dict | None = None,
          resolver_doc: Resolvedor | None = None, gerar_pdf: Callable | None = None,
          enviar_fn: Callable | None = None, lentes: dict | None = None) -> dict:
    produto = _produto(payload, None)
    filtro = resolver_filtro(payload, lentes)
    reg = registro if registro is not None else E14._registro()
    fonte, fid = abrir_fonte(payload.get("fonte"))
    try:
        casos = casos_do_pg(pg, filtro, principal)
        procs = sorted({p for c in casos for p in c["derivado"]["processos"]})
        dossie = montar(fonte, fid, filtro, casos=casos, citacoes=citacoes_e11(pg, procs), registro=reg,
                        produto=produto)
    finally:
        fonte.close()
    ch = chave_pedido(produto, filtro)
    res = exportar(pg, dossie, principal, str(payload.get("justificativa") or ""), chave=ch,
                   saida=Path(payload.get("saida") or SAIDA_PADRAO), com_pdf=not payload.get("sem_pdf"),
                   enviar=bool(payload.get("enviar")), chat_id=str(payload.get("chat_id") or ""),
                   resolver_doc=resolver_doc, registro=reg, gerar_pdf=gerar_pdf, enviar_fn=enviar_fn)
    return {"produto": produto, "chave": ch, "filtro": filtro, **res}


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    _produto(payload, ctx)
    pg = E14.conectar(payload)
    try:
        E14.aplicar_schema(pg, E14.esquema_vigente(payload))
        r = gerar({**payload, "produto": _produto(payload, ctx)}, AC.Principal(f"servico:fluxo@{ctx.no}",
                                                                              AC.Papel.SERVICO), pg=pg)
    finally:
        pg.close()
    return Resultado(efeito={**r, "esquema": E14.esquema_vigente(payload)},
                     eventos=[{"fonte": "entregar", "tipo": "dossie", "chave": r["chave"]}])


def conferir(pg, efeito: dict, payload: dict, *, resolver_doc: Resolvedor | None = None,
             registro: dict | None = None) -> dict:
    out = {"manifesto_ok": False, "consultas_ok": False, "pdf_ok": False, "validador_ok": False, "entrega_ok": False,
           "divergentes": []}
    arq = Path(efeito.get("manifesto") or "")
    if not arq.exists():
        return out
    man = json.loads(arq.read_text(encoding="utf-8"))
    out["manifesto_ok"] = sha_manifesto(man) == man.get("manifesto_sha256") == efeito.get("manifesto_sha256")
    fonte, fid = abrir_fonte(payload.get("fonte"))
    try:
        for q in man["consultas"]:
            linhas = [list(r) for r in fonte.execute(q["sql"], q["parametros"])]
            if _sha(linhas) != q["linhas_sha256"]:
                out["divergentes"].append(q["id"])
    finally:
        fonte.close()
    out["consultas_ok"] = not out["divergentes"] and fid == man["fonte"]
    pdf = efeito.get("pdf")
    out["pdf_ok"] = (pdf is None and payload.get("sem_pdf")) or (
        bool(pdf) and Path(pdf).exists() and _sha_arquivo(Path(pdf)) == efeito.get("pdf_sha256"))
    html = Path(efeito.get("html") or "")
    if html.exists():
        cits = {c["id"]: c for c in man["citacoes"]}
        dossie = {"manifesto": man, "manchetes": [], "ctx": {"top_flags": []}, "citacoes": list(cits.values())}
        out["validador_ok"] = not validar(dossie, html.read_text(encoding="utf-8"), resolver_doc=resolver_doc,
                                          registro=registro)
    linhas = pg.execute("SELECT destino, ok, message_id FROM entrega WHERE chave = %s AND manifesto_sha256 = %s "
                        "AND id = ANY(%s)", (efeito.get("chave"), man["manifesto_sha256"],
                                             efeito.get("entregas") or [])).fetchall()
    arquivo = any(d == "arquivo" and ok for d, ok, _m in linhas)
    tele = [m for d, ok, m in linhas if d == "telegram" and ok]
    out["entrega_ok"] = arquivo and (not payload.get("enviar") or (len(tele) == 1 and isinstance(tele[0], int)))
    return out


def efeito_ok(c: dict) -> bool:
    return all(c[k] for k in ("manifesto_ok", "consultas_ok", "pdf_ok", "validador_ok", "entrega_ok"))


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    ef = resultado.efeito or {}
    pg = E14.conectar(payload)
    try:
        c = conferir(pg, ef, payload)
    finally:
        pg.close()
    ef["conferencia"] = c
    return efeito_ok(c)


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve", "fonte_coleta"], prioridade=35)


# ══ 10. CLI ═════════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E16 entregar (O7.5)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gerar")
    g.add_argument("--produto", default="dossie_orgao", choices=PRODUTOS)
    g.add_argument("--lente")
    g.add_argument("--ug", action="append", default=[])
    g.add_argument("--credor", action="append", default=[])
    g.add_argument("--desde")
    g.add_argument("--ate")
    g.add_argument("--caso", action="append", default=[])
    g.add_argument("--fonte")
    g.add_argument("--saida")
    g.add_argument("--justificativa", required=True)
    g.add_argument("--sem-pdf", action="store_true")
    g.add_argument("--enviar", action="store_true")
    g.add_argument("--chat-id", default="")
    a = ap.parse_args(argv)
    payload = {"produto": a.produto, "lente": a.lente, "casos": a.caso, "fonte": a.fonte, "saida": a.saida,
               "justificativa": a.justificativa, "sem_pdf": a.sem_pdf, "enviar": a.enviar, "chat_id": a.chat_id,
               "filtro": {"ug": a.ug, "credor": a.credor, "data_desde": a.desde, "data_ate": a.ate}}
    pg = E14.conectar({})
    try:
        E14.aplicar_schema(pg, E14.esquema_vigente())
        r = gerar(payload, E14.principal_atual(), pg=pg)
        ok = efeito_ok(conferir(pg, r, payload))
    except AC.AcessoNegado as e:
        print(f"entregar: ACESSO NEGADO — {e.decisao.motivo} (registrado em acesso_log)", file=sys.stderr)
        return 2
    except ExportacaoBloqueada as e:
        print(f"entregar: {e}", file=sys.stderr)
        return 3
    finally:
        pg.close()
    print(json.dumps(r, ensure_ascii=False, default=str))
    if not ok:
        print("entregar: EFEITO NÃO CONFERIDO", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
