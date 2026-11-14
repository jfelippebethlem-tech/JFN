# -*- coding: utf-8 -*-
"""Retratos do JFN no vault — pedido do dono, 14/11/2026: "obsidian atualizado, todo nosso segundo cérebro com as
informações dos contratos".

Gerador DETERMINÍSTICO (sem modelo): lê as MESMAS rotas que o painel serve (`/api/pericia_contabil`,
`/api/governo_couto`, `/api/cge_confronto`, `/api/orcamento_orgao`, `/api/territorio/*`, `/api/intel/sobrepreco`,
`/api/comparador/economia`, `/api/periodo/*`) e escreve notas-retrato em `~/vault/jfn/`. O jfn-brain indexa o vault a
cada 10 min, então o que entra aqui chega aos agentes sem outro passo.

Regras da casa aplicadas aqui (e cobertas por `tests/test_vault_retratos.py`):
  · todo número sai com fonte e estado (VERIFICADO / PENDENTE / INDISPONÍVEL). O estado é o que a ROTA declara;
    onde a rota não declara, o retrato escreve PENDENTE — nunca promove a VERIFICADO;
  · INDISPONÍVEL ≠ 0: valor ausente (`None`) vira a palavra INDISPONÍVEL, nunca "R$ 0,00"; valor que a rota marca
    INDISPONÍVEL mas traz número é soma PARCIAL e sai rotulado "parcial";
  · empenho ≠ pagamento: pago do Estado = OB do SIAFE com status Contabilizado (é o que as rotas somam);
  · CPF nunca aparece inteiro (`mascarar`), e nome de pessoa física de ato de pessoal não é copiado;
  · fonte que não respondeu → a nota NÃO é regravada (fica a última boa) e a rotina sai com código 1, para o
    despachante tentar de novo;
  · escrita atômica (temporário FORA do vault — o Syncthing apaga arquivo de trabalho ali) e idempotente: mesmo
    conteúdo ⇒ nenhum byte regravado. Nenhum carimbo de execução entra na nota; o frescor é a data da própria fonte.

O repositório é público: nenhum dado de contrato fica aqui — só no vault. O estado da rodada (contagens, sem nome)
vai para `data/vault_retratos_estado.json` (fora do git), que é o efeito medido pela propagação e a origem das
manchetes que ela manda ao segundo cérebro. Cada ponto 🔴/🟡 VERIFICADO da gestão Couto e cada sobrepreço conferido
no PNCP entra também na fila do cérebro (`cerebro_compartilhado.registrar`, chave estável — sem memória duplicada).

    python -m compliance_agent.vault_retratos            # gera/atualiza
    python -m compliance_agent.vault_retratos --seco     # só diz o que mudaria
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from compliance_agent import cerebro_compartilhado as cerebro
from compliance_agent.qualidade.verificadores import cpf_valido, mascarar_cpf

RAIZ = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data")
VAULT = Path(os.environ.get("JFN_VAULT") or Path.home() / "vault")
BASE = os.environ.get("JFN_BASE", "http://127.0.0.1:8000")
PASTA = "jfn"
ESTADO = "vault_retratos_estado.json"
IND = "INDISPONÍVEL"
ANO_MENSAL_DESDE = 2021          # antes disso o SIAFE tem ~2 mil OB por ano: quebra mensal do orçamento não informa
ESTADOS = {"VERIFICADO": "VERIFICADO", "PENDENTE": "PENDENTE", "INDISPONIVEL": IND, "INDISPONÍVEL": IND,
           "REFUTADO": "REFUTADO", "DIVERGENTE": "DIVERGENTE"}
RESSALVA = ("Indício não é acusação: cada linha é sinal para requerer documentos, com presunção de regularidade. "
            f"{IND} não é zero. Empenho não é pagamento — pago do Estado é só OB do SIAFE com status Contabilizado.")


class FonteIndisponivel(RuntimeError):
    """A rota não respondeu ou respondeu erro — a nota que depende dela não é regravada."""


# ───────────────────────────── formatação ─────────────────────────────
def brl(v) -> str:
    """R$ com milhar e duas casas. Ausente é INDISPONÍVEL — nunca zero."""
    if v is None or isinstance(v, bool):
        return IND
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return IND


def num(n) -> str:
    if n is None or isinstance(n, bool):
        return IND
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return IND


def pct(v) -> str:
    return IND if v is None else f"{float(v):.1f}%".replace(".", ",")


def estado(e) -> str:
    """Normaliza o estado declarado pela rota; o que não é do vocabulário vira PENDENTE (nunca VERIFICADO)."""
    chave = str(e or "").strip().split(" ")[0].split("—")[0].strip().upper()
    return ESTADOS.get(chave, "PENDENTE")


_RE_CPF_FMT = re.compile(r"(?<![\d.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?!\d)")
_RE_11 = re.compile(r"(?<![\d./-])(\d{11})(?![\d/])")


def mascarar(texto: str) -> str:
    """CPF formatado sempre mascarado; sequência crua de 11 dígitos com dígito verificador válido também."""
    texto = _RE_CPF_FMT.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", texto or "")
    return _RE_11.sub(lambda m: mascarar_cpf(m.group(1)) if cpf_valido(m.group(1)) else m.group(0), texto)


def doc(d) -> str:
    """CNPJ formatado (dado público); CPF mascarado; outro tamanho sai como veio, já passado pela máscara."""
    dig = re.sub(r"\D", "", str(d or ""))
    if len(dig) == 14:
        return f"{dig[:2]}.{dig[2:5]}.{dig[5:8]}/{dig[8:12]}-{dig[12:]}"
    if len(dig) == 11:
        return mascarar_cpf(dig)
    return mascarar(str(d or "")) or "—"


def cel(v, teto: int = 0) -> str:
    """Texto seguro para célula de tabela Markdown."""
    s = " ".join(str("—" if v in (None, "") else v).split()).replace("|", "/")
    return s if not teto or len(s) <= teto else s[: teto - 1].rstrip() + "…"


def tabela(cab: list[str], linhas: list[list], direita: tuple = ()) -> str:
    if not linhas:
        return "_Nenhuma linha na fonte._"
    sep = ["---:" if i in direita else "---" for i in range(len(cab))]
    out = ["| " + " | ".join(cab) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(cel(c) for c in ln) + " |" for ln in linhas]
    return "\n".join(out)


def data_br(iso) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", str(iso or ""))
    if not m:
        return IND
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" + (f" {m.group(4)}:{m.group(5)}" if m.group(4) else "")


# ───────────────────────────── casos do vault (links) ─────────────────────────────
_RE_SEI = re.compile(r"\d{6}/\d{6}/\d{4}")
_RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")


def indice_casos(vault: Path) -> dict[str, list[str]]:
    """chave (CNPJ só dígitos | nº SEI sem prefixo) → notas de `casos/` que a citam, da mais específica à mais ampla
    (nota que cita poucas chaves vem antes de lista de trabalho que cita centenas)."""
    por_nota: dict[str, set[str]] = {}
    for p in sorted((vault / "casos").glob("*.md")):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chaves = set(_RE_SEI.findall(t)) | {re.sub(r"\D", "", c) for c in _RE_CNPJ.findall(t)}
        if chaves:
            por_nota[p.stem] = chaves
    idx: dict[str, list[str]] = {}
    for slug in sorted(por_nota, key=lambda s: (len(por_nota[s]), s)):
        for c in por_nota[slug]:
            idx.setdefault(c, []).append(slug)
    return idx


def casos_de(idx: dict, cnpj=None, processo=None, teto: int = 2) -> str:
    achados: list[str] = []
    m = _RE_SEI.search(str(processo or ""))
    for chave in ((m.group(0) if m else None), re.sub(r"\D", "", str(cnpj or "")) or None):
        for slug in idx.get(chave or "", []):
            if slug not in achados:
                achados.append(slug)
    return " · ".join(f"[[casos/{s}]]" for s in achados[:teto]) or "—"


# ───────────────────────────── moldura da nota ─────────────────────────────
def nota(titulo: str, resumo: str, fontes: str, fonte_de: str, corpo: list[str], tags: tuple = ()) -> str:
    """Frontmatter do vault + capa. `fonte_de` é a data da PRÓPRIA fonte (não a hora desta execução)."""
    fm = ["---", "tipo: retrato", f"tags: [{', '.join(('jfn', 'retrato') + tuple(tags))}]",
          f"fonte: {json.dumps(fontes, ensure_ascii=False)}", f"fonte_de: {json.dumps(fonte_de, ensure_ascii=False)}",
          f"resumo: {json.dumps(resumo, ensure_ascii=False)}", "gerado_por: compliance_agent/vault_retratos.py",
          "---", "", f"# {titulo}", "",
          "> [!info] Retrato gerado pelo JFN — não editar (a próxima mudança da fonte regrava a nota)",
          f"> **Fonte:** {fontes}", f"> **Posição da fonte:** {fonte_de} · índice: [[{PASTA}/00-retratos]]", "",
          "> [!warning] Leitura", f"> {RESSALVA}", ""]
    return mascarar("\n".join(fm + corpo).rstrip() + "\n")


# ───────────────────────────── 1. perícia contábil ─────────────────────────────
def nota_pericia(d: dict, idx: dict) -> tuple[str, str]:
    c = [f"**Régua:** `{d.get('regua', IND)}` · **tolerância:** {d.get('tolerancia', IND)}", ""]
    c += ["## 1. Placar por esfera", ""]
    for nome, e in (d.get("esferas") or {}).items():
        ver = e.get("verificacao") or {}
        st = estado(ver.get("placar"))
        prov = e.get("proveniencia") or {}
        c += [f"### 1.{list(d['esferas']).index(nome) + 1} {nome}", "",
              f"- **Contratos avaliados:** {num(e.get('n'))} · estado **{st}** · corte {data_br(e.get('corte') or e.get('corte_max'))}",
              f"- **Fonte do pago:** {e.get('fonte_pago', IND)}",
              f"- **Fonte dos contratos:** {prov.get('fonte_contratos', IND)}",
              f"- **Cobertura:** {prov.get('cobertura', IND)}", ""]
        rot = e.get("rotulos") or {}
        c += [tabela(["Categoria", "O que significa", "Contratos", "Estado"],
                     [[k, rot.get(k, k), num(v), st] for k, v in (e.get("placar") or {}).items()], direita=(2,)), ""]
        c += [tabela(["Soma", "Valor", "Estado"],
                     [["Pago nos contratos com veredito", brl(e.get("pago_determinado")), st],
                      ["Devido nos contratos com veredito", brl(e.get("devido_determinado")), st],
                      ["Pago acima do valor contratado (A_MAIOR)", brl(e.get("excesso_a_maior")), st],
                      ["Pago à frente do pró-rata, dentro do contrato", brl(e.get("adiantado")), st],
                      ["Pago abaixo do devido em contrato encerrado", brl(e.get("deficit_encerrado")), st]],
                     direita=(1,)), ""]
    c += ["## 2. Pago acima do valor contratado (A_MAIOR) — lista da rota", ""]
    for nome, e in (d.get("esferas") or {}).items():
        lst = e.get("a_maior") or []
        tot = (e.get("placar") or {}).get("A_MAIOR")
        st_l = estado((e.get("verificacao") or {}).get("listas"))
        c += [f"### {nome} — {num(len(lst))} listados de {num(tot)} no placar", "",
              f"Estado das linhas: **{st_l}**. {cel(str((e.get('verificacao') or {}).get('listas') or '').partition('—')[2].strip(), 260)}", ""]
        por_ano: dict[str, list] = {}
        for x in lst:
            por_ano.setdefault(str(x.get("vig_inicio") or "")[:4] or "sem data", []).append(x)
        c += [tabela(["Início da vigência (ano)", "Contratos", "Soma da diferença", "Estado"],
                     [[a, num(len(v)), _soma_dif(v), st_l] for a, v in sorted(por_ano.items())], direita=(1, 2)), ""]
        linhas = []
        for i, x in enumerate(lst, 1):
            linhas.append([i, cel(str(x.get("orgao") or "").split(" - ")[0], 30), cel(x.get("fornecedor"), 46),
                           doc(x.get("fornecedor_doc")), x.get("processo") or x.get("contrato"),
                           f"{data_br(x.get('vig_inicio'))} → {data_br(x.get('vig_fim'))}",
                           brl(x.get("valor_atualizado")), cel(x.get("fonte_valor") or "valor registrado na fonte do contrato", 60),
                           brl(x.get("pago")), brl(x.get("diferenca")), num(x.get("n_obs")), estado(x.get("verificacao")),
                           casos_de(idx, x.get("fornecedor_doc"), x.get("processo"))])
        c += [tabela(["#", "Órgão", "Fornecedor", "CNPJ", "Processo / contrato", "Vigência", "Valor do contrato",
                      "Fonte do valor / aditivo", "Pago", "Diferença", "OB", "Estado", "Caso"], linhas,
                     direita=(6, 8, 9, 10)), ""]
        if lst:
            c += ["**Ressalva e prova primária de cada linha**", ""]
            c += [f"{i}. {cel(x.get('ressalvas') or 'sem ressalva registrada pela rota')} — _prova:_ "
                  f"{cel(x.get('prova_primaria') or IND)}" for i, x in enumerate(lst, 1)]
            c += [""]
    c += ["## 3. Motivos do INDETERMINADO", "",
          "Indeterminado é contrato **sem base para afirmar** a maior ou a menor — não foi absolvido nem condenado.", ""]
    for nome, e in (d.get("esferas") or {}).items():
        c += [f"### {nome} — {num((e.get('placar') or {}).get('INDETERMINADO'))} contratos", "",
              tabela(["Motivo", "Explicação", "Contratos"],
                     [[m.get("motivo"), m.get("texto"), num(m.get("n"))] for m in e.get("motivos_indeterminado") or []],
                     direita=(2,)), ""]
    c += ["## 4. Duplicidade (mesma NL, mesmo valor, dias distintos)", ""]
    for nome, e in (d.get("esferas") or {}).items():
        du = e.get("duplicidades") or {}
        if not du.get("aferivel"):
            c += [f"- **{nome}:** {IND} — a fonte não permite aferir (não é zero)."]
        else:
            c += [f"- **{nome}:** {num(du.get('n_contratos'))} contrato(s), {num(du.get('n_obs_repetidas'))} OB repetida(s), "
                  f"{brl(du.get('valor_repetido'))} · OB sem crédito confirmado (fora da conta): "
                  f"{num(du.get('n_obs_nao_confirmadas'))}, {brl(du.get('valor_nao_confirmado'))} · estado PENDENTE"]
    c += ["", "## 5. Definições da régua", ""] + [f"- **{k}:** {v}" for k, v in (d.get("definicoes") or {}).items()]
    return nota("Perícia contábil — devido × pago por contrato",
                "Placar da perícia contábil por esfera, contratos pagos acima do valor (com fonte do valor, ressalva e "
                "prova), motivos dos indeterminados.",
                "rota /api/pericia_contabil (data/pericia_contabil_resumo.json) — SIAFE-Rio OB Contabilizada × contratos "
                "TCE-RJ/PNCP; Prefeitura: Contas Rio", f"rotina de {data_br(d.get('gerado_em'))}", c,
                ("pericia-contabil", "fonte/siafe", "fonte/tce")), str(d.get("gerado_em") or "")


def _soma_dif(v: list[dict]) -> str:
    """Soma das diferenças do grupo; linha sem diferença não conta como zero — a soma sai rotulada parcial."""
    vals = [x.get("diferenca") for x in v]
    ok = [float(d) for d in vals if isinstance(d, (int, float)) and not isinstance(d, bool)]
    if not ok:
        return IND
    return brl(sum(ok)) + (f" (parcial: {num(len(vals) - len(ok))} sem valor)" if len(ok) < len(vals) else "")


# ───────────────────────────── 2. gestão Couto ─────────────────────────────
def _verificado(x: dict) -> bool:
    v = x.get("verificacao")
    return v == "VERIFICADO" or (isinstance(v, dict) and v.get("estado") == "VERIFICADO")


def nota_couto(d: dict, idx: dict) -> tuple[str, str]:
    g, p, pa = d.get("gestao") or {}, d.get("placar") or {}, d.get("pontos_atencao") or {}
    ex, ct, at = d.get("execucao") or {}, d.get("contratacoes") or {}, d.get("atos") or {}
    c = [f"**Período:** {data_br(g.get('inicio'))} a {data_br(g.get('ate'))} · **marco:** {cel(g.get('fonte'))}", "",
         "## 1. Placar do período", "",
         "Contagens e somas da casa sobre a fonte citada; a rota não as declara conferidas uma a uma — estado PENDENTE.", "",
         tabela(["Indicador", "Valor", "Fonte", "Estado"], [
             ["Pago (OB Contabilizada)", brl(p.get("pago")), "SIAFE-Rio (OB Contabilizada)", "PENDENTE"],
             ["OB contabilizadas", num(p.get("n_obs")), "idem", "PENDENTE"],
             ["Pago na mesma janela do ano anterior", brl(p.get("pago_anterior")), "idem", "PENDENTE"],
             ["Variação", pct(p.get("variacao_pct")), "idem", "PENDENTE"],
             ["Contratações (valor CONTRATADO, não pago)", f"{num(p.get('contratacoes'))} · {brl(p.get('valor_contratado'))}",
              "TCE-RJ (espelho de contratações)", "PENDENTE"],
             ["Contratações diretas (valor CONTRATADO)", f"{num(p.get('diretas'))} · {brl(p.get('valor_diretas'))}", "idem", "PENDENTE"],
             ["Decretos (orçamentários)", f"{num(p.get('decretos'))} ({num(p.get('decretos_orcamentarios'))})",
              "DOERJ", "PENDENTE"],
             ["Nomeações / exonerações publicadas", f"{num(p.get('nomeacoes'))} / {num(p.get('exoneracoes'))}", "idem", "PENDENTE"],
             ["Auditorias do Decreto 50.254/2026", num(p.get("auditorias_50254")), "DOERJ", "PENDENTE"],
             ["Penalidades do TCE-RJ no período", num(p.get("penalidades_tce")), "TCE-RJ", "PENDENTE"],
         ], direita=(1,)), "",
         f"- **Fonte da execução:** {cel(ex.get('fonte'))}",
         f"- **Cobertura da execução:** {cel(ex.get('cobertura'))}",
         f"- **Fonte das contratações:** {cel(ct.get('fonte'))}",
         f"- **Cobertura das contratações:** {cel(ct.get('cobertura'))}",
         f"- **Fonte dos atos:** {cel(at.get('fonte'))} — {cel(at.get('cobertura'))}", ""]
    itens = pa.get("itens") or []
    ver = [x for x in itens if _verificado(x)]
    ordem = {"🔴": 0, "🟡": 1}
    ver.sort(key=lambda x: (ordem.get(x.get("grau"), 2), -(x.get("valor_ob") or 0), str(x.get("id"))))
    pv: dict[str, int] = {}
    for x in itens:                    # contado nos itens que a rota serve (o resumo do arquivo pode estar defasado)
        v = x.get("verificacao")
        k = estado(v.get("estado") if isinstance(v, dict) else v)
        pv[k] = pv.get(k, 0) + 1
    c += ["## 2. Pontos de atenção VERIFICADOS", "",
          f"{num(len(ver))} de {num(len(itens))} pontos têm prova primária citada e conferida "
          f"(por estado, contado nos itens: {', '.join(f'{k} {num(v)}' for k, v in sorted(pv.items())) or IND}). "
          f"Os demais não entram nesta nota. Posição da análise: {data_br(pa.get('gerado_em'))}.", "",
          f"> {cel(pa.get('verificacao_definicao'))}", "",
          tabela(["#", "Grau", "Ponto", "Órgão", "OB contabilizada", "Estado", "Caso"],
                 [[i, x.get("grau"), cel(x.get("regra_ou_hipotese"), 200), cel(x.get("orgao"), 40), brl(x.get("valor_ob")),
                   "VERIFICADO", casos_de(idx, x.get("cnpj"), x.get("processo"))] for i, x in enumerate(ver, 1)],
                 direita=(4,)), ""]
    if ver:
        c += ["### Prova primária, explicação inocente e próximo passo", ""]
        for i, x in enumerate(ver, 1):
            provas = x.get("prova_primaria") or []
            provas = provas if isinstance(provas, list) else [provas]
            c += [f"**{i}. `{cel(x.get('id'))}`** — fonte: {cel(x.get('fonte'))}"]
            c += [f"- prova: {cel(pr)}" for pr in provas] or [f"- prova: {IND}"]
            c += [f"- explicação inocente possível: {cel(x.get('explicacao_inocente') or IND)}",
                  f"- próximo passo: {cel(x.get('proximo_passo') or IND)}", ""]
    lista = sorted(ct.get("lista") or [], key=lambda x: (-(x.get("valor") or 0), str(x.get("processo"))))
    c += ["## 3. Maiores contratações do período (valor CONTRATADO, não pago)", "",
          f"As {num(min(20, len(lista)))} maiores entre as {num(len(lista))} que a rota lista, de {num(ct.get('n'))} "
          f"contratações no período. Estado PENDENTE.", "",
          tabela(["Data", "Órgão", "Fornecedor", "CNPJ", "Processo", "Valor contratado", "Modalidade", "Caso"],
                 [[data_br(x.get("data")), cel(str(x.get("orgao") or "").split(" - ")[0], 26), cel(x.get("fornecedor"), 44),
                   doc(x.get("doc")), x.get("processo"), brl(x.get("valor")), cel(x.get("modalidade"), 40),
                   casos_de(idx, x.get("doc"), x.get("processo"))] for x in lista[:20]], direita=(5,)), "",
          "## 4. Contratações por órgão (valor CONTRATADO)", "",
          tabela(["Órgão", "Contratações", "Valor contratado", "Diretas"],
                 [[cel(o.get("orgao"), 70), num(o.get("n")), brl(o.get("valor")), num(o.get("n_diretas"))]
                  for o in (ct.get("por_orgao") or [])[:20]], direita=(1, 2, 3)), "",
          f"> {cel(d.get('ressalva'))}", "", "Análise curada: [[casos/gestao-couto-analise-2026-11-13]]."]
    fonte_de = f"análise de {data_br(pa.get('gerado_em'))}; OB até {data_br(ex.get('fim'))}"
    return nota("Gestão Couto — placar e pontos verificados",
                "Placar da gestão do governador em exercício (desde 23/03/2026) e os pontos de atenção com prova "
                "primária conferida.",
                "rota /api/governo_couto — SIAFE-Rio (OB Contabilizada), DOERJ, TCE-RJ, CEIS/CNEP", fonte_de, c,
                ("governo-couto", "fonte/siafe", "fonte/doerj")), f"{pa.get('gerado_em')}|{ex.get('fim')}"


# ───────────────────────────── 3. CGE × JFN ─────────────────────────────
def nota_cge(d: dict, idx: dict) -> tuple[str, str]:
    rg, met = d.get("rotulo_grau") or {}, d.get("metricas") or {}
    c = [f"**Cobertura:** {cel(d.get('cobertura'))}", "", f"**Fonte:** {cel(d.get('fonte'))}", ""]
    ind = d.get("fontes_indisponiveis") or []
    if ind:
        c += [f"> [!danger] Fontes {IND} nesta rodada (não é zero): {cel(', '.join(map(str, ind)))}", ""]
    c += ["## 1. Cobertura do JFN por grau da CGE", "",
          "Medida interna de desempenho do JFN contra a auditoria da CGE — contagem da rotina, estado PENDENTE.", "",
          tabela(["Grau", "Significado", "Contratações", "Valor CONTRATADO", "Autos lidos", "Com artefato", "Com sinal", "Com OB no SIAFE"],
                 [[k, rg.get(k, "—"), num(m.get("n")), brl(m.get("valor_contratado")), num(m.get("autos_lidos")),
                   num(m.get("com_artefato")), num(m.get("com_sinal")), num(m.get("com_ob"))] for k, m in met.items()],
                 direita=(2, 3, 4, 5, 6, 7)), ""]
    linhas = d.get("linhas") or []

    def pago(x):
        return (f"{num(x.get('ob_n'))} OB · {brl(x.get('ob_pago'))}" if x.get("ob_n")
                else "nenhuma OB localizada (não prova ausência de pagamento)")

    def caso(x):
        proprios = [s if isinstance(s, str) else str((s or {}).get("slug") or "") for s in x.get("casos") or []]
        proprios = " · ".join(f"[[casos/{s}]]" for s in proprios if s)
        return proprios or casos_de(idx, None, x.get("processo"))
    graves = [x for x in linhas if x.get("grau") in ("G1", "G2")]
    c += [f"## 2. Contratações com apontamento G1 ou G2 da CGE — {num(len(graves))}", "",
          "O apontamento é da CGE (relatório lido no SEI), não do JFN.", "",
          tabela(["Grau", "Órgão", "Processo", "Fornecedor", "Valor CONTRATADO", "OB Contabilizada (SIAFE)", "Autos lidos", "Caso"],
                 [[x.get("grau"), x.get("orgao"), x.get("processo"), cel(x.get("fornecedor"), 44), brl(x.get("valor_contratado")),
                   pago(x), "sim" if x.get("autos_lidos") else "não", caso(x)] for x in graves], direita=(4,)), ""]
    c += [f"- **{x.get('processo')}** ({x.get('grau')}): {cel(x.get('irregularidade'))}" for x in graves] + [""]
    resto = [x for x in linhas if x.get("grau") not in ("G1", "G2")]
    c += [f"## 3. Demais contratações examinadas (G3 e G0) — {num(len(resto))}", "",
          tabela(["Grau", "Órgão", "Processo", "Fornecedor", "Valor CONTRATADO", "OB Contabilizada (SIAFE)", "Caso"],
                 [[x.get("grau"), x.get("orgao"), x.get("processo"), cel(x.get("fornecedor"), 44), brl(x.get("valor_contratado")),
                   pago(x), caso(x)] for x in resto], direita=(4,)), "",
          "## 4. Histórico da medição", "",
          tabela(["Data", "Contratações", "Com artefato", "G1+G2 com sinal", "Autos lidos", "Relatórios no acervo"],
                 [[data_br(h.get("data")), num(h.get("n")), num(h.get("com_artefato")), num(h.get("com_sinal_g12")),
                   num(h.get("autos_lidos")), num(h.get("relatorios_no_acervo"))] for h in d.get("historico") or []],
                 direita=(1, 2, 3, 4, 5)), "", f"> {cel(d.get('ressalva'))}", "",
          "Relacionado: [[casos/auditorias-gsi-decreto-50254-2026]]."]
    return nota("CGE × JFN — confronto com as auditorias do Decreto 50.254/2026",
                "O que a CGE apontou em cada contratação auditada e o que o JFN tem dos mesmos autos (leitura, artefato, OB).",
                "rota /api/cge_confronto (data/cge_confronto.json) — relatórios AGE/CGE lidos no SEI; OB do SIAFE",
                f"rotina de {data_br(d.get('gerado_em'))}; lista curada em {data_br(d.get('curado_em'))}", c,
                ("cge", "fonte/sei", "fonte/siafe")), str(d.get("gerado_em") or "")


# ───────────────────────────── 4. contratos por município ─────────────────────────────
_BALDES = (("atribuido", "Atribuídos a um município"), ("atribuido_explicito", "… por menção explícita no objeto"),
           ("atribuido_unidade", "… por unidade de endereço conhecido"), ("atribuido_sede", "… pela sede do órgão"),
           ("estado_inteiro", "Estado inteiro"), ("multimunicipio", "Vários municípios"), ("regiao", "Região"),
           ("sem_municipio", "Sem município identificado"), ("total", "Total"))


def nota_territorio(est: dict, pcrj: dict, baldes: dict) -> tuple[str, str]:
    def bloco(b: dict) -> str:
        return tabela(["Balde", "Contratos", "Valor CONTRATADO"],
                      [[r, num((b.get(k) or {}).get("n")), brl((b.get(k) or {}).get("valor"))] for k, r in _BALDES if k in b],
                      direita=(1, 2))
    bv, bt = est.get("baldes") or {}, (baldes.get("estado") or {})
    cp = bv.get("com_pago") or {}
    c = [f"**Fonte:** {cel(est.get('fonte'))} · **base:** {data_br(est.get('atualizado_em'))} · "
         f"**pago apurado em:** {data_br(est.get('pago_apurado_em'))}", "",
         "Atribuição territorial é inferência da casa sobre o texto do contrato — estado PENDENTE em toda a nota. "
         "Valor é CONTRATADO; pago só onde há OB vinculada.", "",
         f"## 1. Cobertura — contratos {cel(est.get('periodo'))}", "", bloco(bv), "",
         f"- **Com pago apurado:** {num(cp.get('n'))} contratos · contratado {brl(cp.get('valor'))} · pago {brl(cp.get('pago'))}",
         f"- **Como o pago é apurado:** {cel(est.get('nota_pago'))}", f"- **Em execução:** {cel(est.get('nota_execucao'))}", ""]
    if bt:
        c += [f"## 2. Cobertura — toda a base ({cel(baldes.get('periodo'))})", "", bloco(bt), ""]
    fe = est.get("fora_do_escopo") or {}
    if fe:
        c += ["Fora do escopo do mapa: " + " · ".join(f"{k.replace('_', ' ')} {num(v)}" for k, v in fe.items()) + ".", ""]
    mun = sorted(est.get("municipios") or [], key=lambda m: (-(m.get("valor_contratado") or 0), str(m.get("nome"))))
    c += [f"## 3. Municípios por valor contratado — {num(len(mun))}", "",
          tabela(["#", "Município", "Contratos", "Em execução", "Valor CONTRATADO", "Pago (OB SIAFE)", "Com pago", "Indícios da perícia"],
                 [[i, m.get("nome"), num(m.get("n_contratos")), num(m.get("n_em_execucao")), brl(m.get("valor_contratado")),
                   brl(m.get("pago")), num(m.get("n_com_pago")), num(m.get("n_alertas"))] for i, m in enumerate(mun, 1)],
                 direita=(2, 3, 4, 5, 6, 7)), "", f"- **Indício:** {cel(est.get('nota_alertas'))}", ""]
    c += ["## 4. Prefeitura do Rio — por Área de Planejamento", "",
          f"**Fonte:** {cel(pcrj.get('fonte'))}", "",
          tabela(["AP", "Regiões administrativas", "Contratos", "Valor CONTRATADO", "Pago (declarado no portal)", "Executado"],
                 [[a.get("nome"), cel(", ".join(a.get("ras") or []), 90), num(a.get("n_contratos")), brl(a.get("valor_contratado")),
                   brl(a.get("pago")), IND if a.get("pct_executado") is None else pct(100 * a["pct_executado"])]
                  for a in pcrj.get("aps") or []], direita=(2, 3, 4, 5))]
    return nota("Contratos por município — cobertura e ranking",
                "Quanto da base de contratos do Estado tem município atribuído, os municípios por valor contratado e as "
                "Áreas de Planejamento da Prefeitura do Rio.",
                "rotas /api/territorio/estado, /api/territorio/baldes, /api/territorio/pcrj (data/territorio.db) — PNCP, "
                "TCE-RJ/SIGA, DOERJ, Contas Rio", f"base de {data_br(est.get('atualizado_em'))}", c,
                ("territorio", "fonte/tce")), f"{est.get('atualizado_em')}|{est.get('pago_apurado_em')}"


# ───────────────────────────── 5. sobrepreço conferido ─────────────────────────────
def nota_sobrepreco(eco: dict, por_esfera: dict[str, dict], idx: dict) -> tuple[str, str]:
    c = ["## 1. Soma conferida (número-herói do painel)", "",
         tabela(["Indicador", "Valor", "Estado"], [
             ["Excesso estimado nas compras conferidas no PNCP, fora de ata", f"{brl(eco.get('economia_total'))} em "
              f"{num(eco.get('n_compras_acima_mediana'))} compra(s)", "VERIFICADO"],
             ["Em ata de registro de preços (teto, quantidade estimada)", f"{brl(eco.get('economia_ata_teto'))} em "
              f"{num(eco.get('n_compras_ata'))} compra(s)", "PENDENTE"],
             ["Ainda sem conferência no PNCP", f"{brl(eco.get('economia_pendente'))} em {num(eco.get('n_compras_pendentes'))} compra(s)", "PENDENTE"],
             ["Divergente do PNCP (fora da soma)", f"{brl(eco.get('economia_divergente'))} em {num(eco.get('n_compras_divergentes'))} compra(s)", "DIVERGENTE"],
         ], direita=(1,)), "", f"- {cel(eco.get('explicacao'))}", f"- **Ressalva:** {cel(eco.get('ressalva'))}", "",
         "O valor é quantidade homologada × diferença de preço unitário — **não é pagamento**; o efetivamente pago a "
         f"mais é {IND} sem a OB.", ""]
    ultimo = ""
    for i, (rot, d) in enumerate(por_esfera.items(), 2):
        ach = d.get("achados") or []
        ultimo = max([ultimo] + [str(x.get("verificado_em") or "") for x in ach])
        c += [f"## {i}. {rot} — {num(d.get('n'))} indício(s), {num(d.get('n_verificados'))} conferido(s), "
              f"{num(d.get('n_divergentes'))} divergente(s)", "",
              f"Base: {num(d.get('itens_com_preco'))} itens com preço, {num(d.get('grupos_comparaveis'))} grupos comparáveis, "
              f"{num(d.get('sem_par'))} itens sem par.", "",
              tabela(["Data", "Item", "Unidade", "Órgão", "Fornecedor", "CNPJ", "Preço", "Mediana", "Razão", "Excesso estimado",
                      "Ata", "Estado", "PNCP", "Caso"],
                     [[data_br(x.get("data")), cel(x.get("item"), 50), cel(x.get("unidade_normalizada") or x.get("unidade_medida"), 22),
                       cel(x.get("orgao"), 40), cel(x.get("fornecedor"), 40), doc(x.get("fornecedor_cnpj")), brl(x.get("preco_normalizado")),
                       brl(x.get("mediana")), IND if x.get("razao") is None else f"{x['razao']}×".replace(".", ","),
                       brl(x.get("excesso_total_est")), {True: "sim", False: "não"}.get(x.get("ata_registro_precos"), IND),
                       estado(x.get("verificacao")), f"[edital]({x['link_pncp']})" if x.get("link_pncp") else "—",
                       casos_de(idx, x.get("fornecedor_cnpj"))] for x in ach], direita=(6, 7, 8, 9)), ""]
        indet = d.get("indeterminados") or {}
        c += [f"**Indeterminados — {num(indet.get('n'))} itens fora da conta** (sem comparação segura; não foram absolvidos):", "",
              tabela(["Motivo", "Itens"], [[m.get("motivo"), num(m.get("n"))] for m in indet.get("por_motivo") or []],
                     direita=(1,)), ""]
    return nota("Sobrepreço conferido — mesmo item, mesma unidade",
                "Indícios de sobrepreço unitário conferidos no PNCP, por esfera, com o que ficou indeterminado.",
                "rotas /api/comparador/economia e /api/intel/sobrepreco — preço unitário homologado do PNCP",
                f"última conferência no PNCP em {data_br(ultimo)}", c, ("sobrepreco", "fonte/pncp")), ultimo


# ───────────────────────────── 6. sinais críticos ─────────────────────────────
def sinais(couto: dict, per: dict) -> list[dict]:
    """A MESMA seleção do bloco "Sinais críticos" do painel (static/js: `_couto`, `_pericia`): só o que tem prova
    primária conferida. Devolve lista de sinais; lista vazia = nenhum sinal verificado agora."""
    out = []
    ver = [x for x in (couto.get("pontos_atencao") or {}).get("itens") or [] if _verificado(x)]
    verm, amar = [x for x in ver if x.get("grau") == "🔴"], [x for x in ver if x.get("grau") == "🟡"]
    if verm or amar:
        top = (verm or amar)[0]
        nome = re.sub(r"^[A-Z]\d+\s*·\s*", "", str(top.get("regra_ou_hipotese") or ""))
        out.append({"grau": "🔴" if verm else "🟡", "valor": f"{num(len(verm))} grave(s) · {num(len(amar))} em atenção",
                    "titulo": "Pontos de atenção na gestão Couto (desde 23/03/2026)",
                    "texto": f"Mais grave: {nome}"
                             + (f" — {brl(top['valor_ob'])} em OB contabilizada" if top.get("valor_ob") else "")
                             + f". Explicação inocente possível: {top.get('explicacao_inocente') or 'ver a nota'}.",
                    "fonte": "SIAFE (OB Contabilizado), CEIS/CNEP, DOERJ, TCE-RJ — só os pontos com prova primária conferida",
                    "nota": f"{PASTA}/gestao-couto", "n_graves": len(verm), "n_atencao": len(amar)})
    e = (per.get("esferas") or {}).get("Estado do RJ") or {}
    if (e.get("placar") or {}).get("A_MAIOR") and estado((e.get("verificacao") or {}).get("placar")) == "VERIFICADO":
        lst = sorted([x for x in e.get("a_maior") or [] if (x.get("diferenca") or 0) > 0], key=lambda x: -x["diferenca"])
        conc = ""
        if lst and e.get("excesso_a_maior"):
            p = round(100 * lst[0]["diferenca"] / e["excesso_a_maior"])
            if p >= 25:
                conc = (f" O maior caso ({lst[0].get('fornecedor') or '—'}, {str(lst[0].get('orgao') or '').split(' - ')[0]}) "
                        f"responde por {p}% da soma.")
        out.append({"grau": "🟡", "valor": brl(e.get("excesso_a_maior")),
                    "titulo": f"Pago acima do valor contratado — {num(e['placar']['A_MAIOR'])} contratos do Estado",
                    "texto": "Soma das OB contabilizadas no SIAFE que passam do valor registrado do contrato. O TCE-RJ não "
                             "publica os termos aditivos: é indício a conferir nos aditivos, não dano apurado." + conc
                             + f" Em contratos já encerrados, ficaram {brl(e.get('deficit_encerrado'))} abaixo do devido.",
                    "fonte": "SIAFE (OB Contabilizado) × contratos do TCE-RJ, régua determinística reproduzível",
                    "nota": f"{PASTA}/pericia-contabil"})
    return out


def nota_sinais(couto: dict, per: dict) -> tuple[str, str]:
    ss = sinais(couto, per)
    c = ["O mesmo recorte do bloco **Sinais críticos** da tela inicial do painel: só entra o que tem prova primária "
         "conferida por código.", ""]
    if not ss:
        c += ["_Nenhum sinal verificado para mostrar agora._ Isso não é atestado de regularidade: diz só que nenhum "
              "item passou na conferência de prova primária nesta posição da fonte."]
    for i, s in enumerate(ss, 1):
        c += [f"## {i}. {s['grau']} {s['titulo']}", "", f"- **Valor:** {s['valor']} · estado **VERIFICADO**",
              f"- **Fonte:** {s['fonte']}", f"- {cel(s['texto'])}", f"- Detalhe: [[{s['nota']}]]", ""]
    pa = (couto.get("pontos_atencao") or {}).get("gerado_em")
    return nota("Sinais críticos — o que tem prova primária conferida",
                "Os sinais que a tela inicial do painel destaca: pontos verificados da gestão Couto e pago acima do "
                "valor contratado no Estado.", "rotas /api/governo_couto e /api/pericia_contabil",
                f"perícia de {data_br(per.get('gerado_em'))}; análise Couto de {data_br(pa)}", c,
                ("sinais-criticos",)), f"{per.get('gerado_em')}|{pa}"


# ───────────────────────────── descobertas VERIFICADAS → segundo cérebro ─────────────────────────────
def descobertas(couto: dict | None, sobre: dict[str, dict] | None) -> list[tuple[str, str, str]]:
    """(chave, texto, assunto) de cada item VERIFICADO que vira memória: ponto 🔴/🟡 da gestão Couto com prova primária
    conferida e indício de sobrepreço conferido no PNCP. A chave é estável (id do ponto; certame+item) e o texto não
    leva data de execução: recálculo que não muda o fato dá 'igual' no registro (nenhuma memória duplicada); fato que
    muda (ex.: valor da OB) vai como correção (`supersedes`)."""
    out = []
    for x in ((couto or {}).get("pontos_atencao") or {}).get("itens") or []:
        if not _verificado(x) or x.get("grau") not in ("🔴", "🟡") or not x.get("id"):
            continue
        provas = x.get("prova_primaria") or []
        provas = provas if isinstance(provas, list) else [provas]
        out.append((f"couto:{x['id']}",
                    f"JFN — ponto de atenção {x['grau']} VERIFICADO na gestão Couto (prova primária conferida por código): "
                    f"{cel(x.get('regra_ou_hipotese'), 400)}. Órgão: {cel(x.get('orgao'))}. OB contabilizada (SIAFE): "
                    f"{brl(x.get('valor_ob'))}. Fonte: {cel(x.get('fonte'))}. Prova: {cel('; '.join(map(str, provas[:3])), 450) or IND}. "
                    f"Explicação inocente possível: {cel(x.get('explicacao_inocente') or IND)}. Próximo passo: "
                    f"{cel(x.get('proximo_passo') or IND)}. Indício interno, não acusação. Retrato: {PASTA}/gestao-couto.",
                    "gestão Couto — ponto verificado"))
    for esf, d in (sobre or {}).items():
        for x in d.get("achados") or []:
            if estado(x.get("verificacao")) != "VERIFICADO" or not x.get("certame"):
                continue
            out.append((f"sobrepreco:{x['certame']}:{x.get('item_n')}",
                        f"JFN — indício de sobrepreço unitário CONFERIDO no PNCP ({esf}): {cel(x.get('item'), 120)} a "
                        f"{brl(x.get('preco_normalizado'))} por {cel(x.get('unidade_normalizada') or x.get('unidade_medida'))} "
                        f"contra mediana {brl(x.get('mediana'))} do mesmo item e unidade; fornecedor {cel(x.get('fornecedor'))} "
                        f"(CNPJ {doc(x.get('fornecedor_cnpj'))}); órgão {cel(x.get('orgao'))}; certame {x['certame']}, item "
                        f"{x.get('item_n')}. Excesso estimado {brl(x.get('excesso_total_est'))} = quantidade homologada × "
                        f"diferença — não é pagamento. Indício interno, não acusação. Retrato: {PASTA}/sobrepreco-conferido.",
                        "sobrepreço conferido"))
    vistos: set[str] = set()                # mesma chave duas vezes na rodada alternaria o texto (correção falsa a cada ciclo)
    return [(k, mascarar(t), a) for k, t, a in out if not (k in vistos or vistos.add(k))]


# ───────────────────────────── 7. por exercício (ano e mês) ─────────────────────────────
_COLS = (("dotacao_inicial", "Dotação inicial (LOA)"), ("dotacao_atualizada", "Dotação atualizada"),
         ("empenhado", "Empenhado (não é pagamento)"), ("liquidado", "Liquidado (não é pagamento)"),
         ("pago_siafe", "Pago — OB Contabilizada do SIAFE"), ("pago_balancete", "Pago do balancete (referência)"))
_LETRA = {"VERIFICADO": "V", "PENDENTE": "P", IND: "I"}
_MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _valor_orc(reg: dict, col: str) -> str:
    """Valor de uma coluna do orçamento com a honestidade da rota: sem número = INDISPONÍVEL; número com estado
    INDISPONÍVEL = soma parcial (faltam UG) e sai rotulada."""
    v, st = reg.get(col), estado((reg.get("estados") or {}).get(col))
    if v is None:
        return IND
    return f"{brl(v)} (parcial)" if st == IND else brl(v)


def _letras(reg: dict) -> str:
    return "/".join(_LETRA.get(estado((reg.get("estados") or {}).get(k)), "P") for k, _ in _COLS)


def secao_orcamento(ano: int, o: dict | None, meses: dict[int, dict]) -> list[str]:
    if o is None:
        return ["## 1. Orçamento por órgão", "", f"{IND} — o exercício {ano} não está na base de orçamento (não é zero).", ""]
    t, prov, colunas = o.get("total") or {}, o.get("proveniencia") or {}, o.get("colunas") or {}
    falt = t.get("faltam") or {}
    c = ["## 1. Orçamento por órgão", "",
         f"**Período:** {cel(o.get('periodo'))} · **visão:** {cel(o.get('visao_descricao'))}", "",
         f"**Fonte:** {cel(prov.get('fonte'))}", "", f"**Cobertura:** {cel(prov.get('cobertura'))}", "",
         tabela(["Coluna", "Total", "Estado", "UG sem o dado", "O que é"],
                [[r, _valor_orc(t, k), estado((t.get("estados") or {}).get(k)), num(falt[k]) if k in falt else "—", cel(colunas.get(k), 170)]
                 for k, r in _COLS], direita=(1, 3)), "",
         "Valor marcado **(parcial)** é soma só das UG que têm o dado: é piso, não total. "
         f"Taxa de empenho {pct(t.get('taxa_empenho'))}; taxa de pago por OB {pct(t.get('taxa_pago'))}.", ""]
    if meses:
        c += ["### Acumulado até cada mês", "",
              "Estados na ordem dotação inicial / atualizada / empenhado / liquidado / pago OB / pago balancete "
              "(V = VERIFICADO, P = PENDENTE, I = INDISPONÍVEL como total).", "",
              tabela(["Até", "Empenhado", "Liquidado", "Pago — OB do SIAFE", "Pago do balancete", "Estados"],
                     [[_MESES[m - 1], _valor_orc(x.get("total") or {}, "empenhado"), _valor_orc(x.get("total") or {}, "liquidado"),
                       _valor_orc(x.get("total") or {}, "pago_siafe"), _valor_orc(x.get("total") or {}, "pago_balancete"),
                       _letras(x.get("total") or {})] for m, x in sorted(meses.items())], direita=(1, 2, 3, 4)), ""]
    orgs = sorted(o.get("orgaos") or [], key=lambda r: (-(r.get("dotacao_atualizada") or r.get("dotacao_inicial") or 0), str(r.get("orgao"))))
    c += [f"### Órgãos — {num(len(orgs))}", "",
          tabela(["Órgão", "Dotação atualizada", "Empenhado", "Liquidado", "Pago — OB do SIAFE", "Pago do balancete", "Estados"],
                 [[cel(f"{r.get('orgao')} · {r.get('nome')}", 60), _valor_orc(r, "dotacao_atualizada"), _valor_orc(r, "empenhado"),
                   _valor_orc(r, "liquidado"), _valor_orc(r, "pago_siafe"), _valor_orc(r, "pago_balancete"), _letras(r)]
                  for r in orgs], direita=(1, 2, 3, 4, 5)), "", f"> {cel(o.get('ressalva'))}", ""]
    return c


def _estado_periodo(status) -> str:
    s = str(status or "").lower()
    if s.startswith("indispon"):
        return IND
    return "PENDENTE — piso (coleta parcial)" if s == "parcial" else "PENDENTE"


def secao_periodo(n_sec: int, ano: int, d: dict) -> list[str]:
    """Uma fonte datada (OB, contratos, aditivos, TAC) quebrada por mês no exercício."""
    f, cob = d.get("fonte") or {}, d.get("cobertura") or {}
    med, rot = f.get("medidas") or [], f.get("rotulos_medidas") or {}
    a = next((x for x in (d.get("quebra") or {}).get("anos") or [] if x.get("ano") == ano), None)
    c = [f"## {n_sec}. {f.get('rotulo', f.get('id'))}", "",
         f"**Origem:** {cel(f.get('origem'))} · **data usada:** {cel(f.get('campo_data'))} · **cobertura da fonte:** "
         f"{cel(cob.get('inicio'))} a {cel(cob.get('fim'))}", "", f"{cel(cob.get('nota'))}", ""]
    if a is None:
        return c + [f"{IND} — a fonte não tem o exercício {ano} (não é zero).", ""]

    def linha(rotulo, x):
        ind = _estado_periodo(x.get("status")) == IND
        return [rotulo, IND if ind else num(x.get("n"))] + \
               [IND if ind else brl((x.get("v") or {}).get(m)) for m in med] + [_estado_periodo(x.get("status"))]
    linhas = [linha(_MESES[m["mes"] - 1], m) for m in a.get("meses") or [] if 1 <= (m.get("mes") or 0) <= 12]
    sm = a.get("sem_mes") or {}
    if sm.get("n"):
        linhas.append(linha("sem mês na fonte", {**sm, "status": a.get("status")}))
    linhas.append(linha(f"**{ano}**", a))
    return c + [tabela(["Mês", "Registros"] + [rot.get(m, m) for m in med] + ["Estado"], linhas,
                       direita=tuple(range(1, 2 + len(med)))), ""]


def nota_ano(ano: int, orc: dict | None, meses: dict[int, dict], periodos: dict[str, dict]) -> tuple[str, str]:
    c = secao_orcamento(ano, orc, meses)
    for i, (_fid, d) in enumerate(periodos.items(), 2):
        c += secao_periodo(i, ano, d)
    ate = max([str((d.get("cobertura") or {}).get("fim") or "") for d in periodos.values()] or [""])
    fonte_de = "; ".join(filter(None, [f"orçamento: {cel((orc or {}).get('periodo'))}" if orc else None,
                                       f"séries mensais coletadas até {ate}" if ate else None]))
    return nota(f"Exercício {ano} — orçamento, pagamentos e contratações por mês",
                f"Retrato do exercício {ano}: orçamento por órgão, OB contabilizadas, contratos, aditivos e TAC, mês a mês.",
                "rotas /api/orcamento_orgao e /api/periodo/{ob_siafe, contratos_estado, aditivos_estado, tac_estado} — "
                "dados abertos do Estado (TFE), painel da CGE, SIAFE-Rio, PNCP, DOERJ", fonte_de, c,
                ("exercicio", f"ano/{ano}", "fonte/siafe")), fonte_de


# ───────────────────────────── coleta e escrita ─────────────────────────────
def obter(caminho: str, tentativas: int = 2):
    """GET na rota do painel. Erro, tempo esgotado ou `ok: false` = FonteIndisponivel (nunca payload vazio)."""
    erro = "sem resposta"
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(f"{BASE}/api/{caminho}", timeout=120) as r:
                d = json.loads(r.read().decode("utf-8"))
            if not isinstance(d, dict) or d.get("ok") is False or d.get("estado") in ("erro", "indisponivel"):
                raise FonteIndisponivel(f"/api/{caminho}: {str((d or {}).get('erro') or (d or {}).get('estado') or 'resposta inválida')[:200]}")
            return d
        except (urllib.error.URLError, OSError, ValueError) as exc:
            erro = f"{type(exc).__name__}: {exc}"
            if i + 1 < tentativas:
                time.sleep(3)
    raise FonteIndisponivel(f"/api/{caminho}: {erro[:200]}")


def gravar(destino: Path, texto: str, seco: bool = False) -> bool:
    """Grava só se o conteúdo mudou; temporário fora do vault + troca atômica. Devolve True se regravou."""
    try:
        if destino.read_text(encoding="utf-8") == texto:
            return False
    except OSError:
        pass
    if seco:
        return True
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = VAULT.parent / ".jfn_vault_tmp" if destino.is_relative_to(VAULT) else destino.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tmp_dir, suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, destino)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


_BLOCO = ("<!-- cerebro:retratos:inicio -->", "<!-- cerebro:retratos:fim -->")


def ligar_ao_hub(seco: bool = False) -> bool:
    """Uma linha no 00-INDEX (entre sentinelas próprias) — nota nova nunca fica isolada no vault."""
    hub = VAULT / "00-INDEX.md"
    try:
        t = hub.read_text(encoding="utf-8")          # relido na hora de gravar: o cerebro_sync também escreve aqui
    except OSError:
        return False
    bloco = (f"{_BLOCO[0]}\n## 📒 Retratos do JFN (gerados)\n- [[{PASTA}/00-retratos]] — perícia contábil, orçamento por "
             f"exercício, gestão Couto, CGE × JFN, contratos por município, sobrepreço, sinais críticos\n{_BLOCO[1]}")
    if _BLOCO[0] in t and _BLOCO[1] in t:
        novo = re.sub(re.escape(_BLOCO[0]) + r".*?" + re.escape(_BLOCO[1]), lambda _: bloco, t, flags=re.S)
    else:
        novo = t.rstrip() + "\n\n" + bloco + "\n"
    return gravar(hub, novo, seco)


def _situacao(r: dict) -> str:
    if r["ok"]:
        return "em dia"
    return f"{IND} nesta rodada — " + ("nota mantida na última posição boa" if r.get("fonte_de") else "nota ainda não gerada")


def nota_indice(reg: list[dict]) -> str:
    c = ["Notas-retrato do JFN, regravadas sozinhas quando a fonte muda (derivado `vault_retratos` da propagação; "
         "estado em Sistema › Propagação do painel). O conteúdo é o que o painel mostra — este vault não recalcula nada.", "",
         "## 1. Retratos", "",
         tabela(["Nota", "O que traz", "Posição da fonte", "Situação"],
                [[f"[[{r['nota']}]]", r["o_que"], r.get("fonte_de") or IND,
                  _situacao(r)]
                 for r in reg if not r["nota"].startswith(f"{PASTA}/anos/")]), "",
         "## 2. Por exercício (ano e mês)", "",
         tabela(["Exercício", "Posição da fonte", "Situação"],
                [[f"[[{r['nota']}]]", r.get("fonte_de") or IND,
                  _situacao(r)]
                 for r in reg if r["nota"].startswith(f"{PASTA}/anos/")]), "",
         "## 3. Como ler", "",
         "- **VERIFICADO** — prova primária citada e conferida por código. **PENDENTE** — saiu da régua ou de soma da "
         f"casa e ainda não foi conferido linha a linha. **{IND}** — a fonte não permite saber; nunca é zero.",
         "- **Pago** do Estado é OB do SIAFE com status Contabilizado, fora a devolvida pelo banco. Empenhado, liquidado "
         "e valor contratado **não** são pagamento.",
         "- Casos investigados à mão ficam em [[MOC-Casos]]; o funcionamento da atualização, em "
         "[[notas/propagacao-automatica-2026-11-14]]."]
    return nota("Retratos do JFN — índice", "Índice das notas-retrato geradas pelo JFN a partir das rotas do painel.",
                "rotas do painel do JFN (127.0.0.1:8000) — cada nota declara as suas", "ver cada linha", c, ("moc",))


_PERIODOS = ("ob_siafe", "contratos_estado", "aditivos_estado", "tac_estado")


def gerar(obter_=obter, seco: bool = False, registrar_=None) -> dict:
    """Uma rodada. `obter_` e `registrar_` (fila do segundo cérebro) são injetáveis (testes). Devolve o estado da rodada
    (o que foi gravado em data/)."""
    idx = indice_casos(VAULT)
    cache: dict[str, object] = {}

    def pega(cam: str):
        if cam not in cache:
            try:
                cache[cam] = obter_(cam)
            except FonteIndisponivel as exc:
                cache[cam] = exc
        if isinstance(cache[cam], FonteIndisponivel):
            raise cache[cam]
        return cache[cam]

    reg: list[dict] = []
    manchetes: dict = {}
    fontes_cerebro: dict = {}

    def faz(rel: str, o_que: str, montar) -> None:
        r = {"nota": rel, "o_que": o_que, "ok": False, "mudou": False, "fonte_de": None, "erro": None}
        try:
            texto, _ = montar()
            m = re.search(r'^fonte_de: (".*")$', texto, re.M)
            r.update(ok=True, fonte_de=json.loads(m.group(1)) if m else None,
                     mudou=gravar(VAULT / f"{rel}.md", texto, seco))
        except FonteIndisponivel as exc:
            r["erro"] = str(exc)
            ant = _fonte_de_anterior(VAULT / f"{rel}.md")
            r["fonte_de"] = ant
        reg.append(r)

    def m_sinais():
        couto, per = pega("governo_couto"), pega("pericia_contabil")
        ss = sinais(couto, per)
        cs = next((s for s in ss if "n_graves" in s), None)
        manchetes["couto_graves"] = cs["n_graves"] if cs else 0
        manchetes["couto_atencao"] = cs["n_atencao"] if cs else 0
        fontes_cerebro["couto"] = couto
        return nota_sinais(couto, per)

    def m_sobre():
        eco = pega("comparador/economia")
        esf = {"Estado": pega("intel/sobrepreco?limite=120&esfera=estado"),
               "Prefeitura do Rio": pega("intel/sobrepreco?limite=120&esfera=prefeitura")}
        manchetes["sobrepreco_compras"] = eco.get("n_compras_acima_mediana")
        manchetes["sobrepreco_excesso"] = brl(eco.get("economia_total"))
        fontes_cerebro["sobre"] = esf
        return nota_sobrepreco(eco, esf, idx)

    def m_terr():
        est = pega("territorio/estado")
        b = est.get("baldes") or {}
        manchetes["territorio_atribuidos"] = (b.get("atribuido") or {}).get("n")
        manchetes["territorio_sem_municipio"] = (b.get("sem_municipio") or {}).get("n")
        return nota_territorio(est, pega("territorio/pcrj"), pega("territorio/baldes"))

    faz(f"{PASTA}/sinais-criticos", "o que a tela inicial destaca, só com prova primária conferida", m_sinais)
    faz(f"{PASTA}/pericia-contabil", "placar por esfera, pago acima do valor contratado, motivos do indeterminado",
        lambda: nota_pericia(pega("pericia_contabil"), idx))
    faz(f"{PASTA}/gestao-couto", "placar da gestão e pontos de atenção VERIFICADOS, com prova e explicação inocente",
        lambda: nota_couto(pega("governo_couto"), idx))
    faz(f"{PASTA}/cge-x-jfn", "apontamentos da CGE por contratação e o que o JFN tem dos mesmos autos",
        lambda: nota_cge(pega("cge_confronto"), idx))
    faz(f"{PASTA}/contratos-por-municipio", "cobertura territorial, municípios por valor contratado, APs da Prefeitura", m_terr)
    faz(f"{PASTA}/sobrepreco-conferido", "indícios de sobrepreço unitário conferidos no PNCP", m_sobre)

    anos, exs = set(), {}
    try:
        exs = {e["ano"]: e for e in pega("orcamento_orgao").get("exercicios") or []}
        anos |= set(exs)
    except FonteIndisponivel:
        pass
    for fid in _PERIODOS:
        try:
            anos |= {a["ano"] for a in (pega(f"periodo/{fid}").get("quebra") or {}).get("anos") or [] if a.get("ano")}
        except FonteIndisponivel:
            pass

    def m_ano(ano: int):
        def monta():
            base = pega("orcamento_orgao")            # falhou a rota inteira → o exercício não é regravado
            orc = pega(f"orcamento_orgao?ano={ano}") if ano in {e["ano"] for e in base.get("exercicios") or []} else None
            meses = {}
            if orc and ano >= ANO_MENSAL_DESDE:
                for m in orc.get("meses_com_execucao") or []:
                    meses[m] = pega(f"orcamento_orgao?ano={ano}&mes={m}")
            return nota_ano(ano, orc, meses, {f: pega(f"periodo/{f}") for f in _PERIODOS})
        return monta

    for ano in sorted(anos, reverse=True):
        faz(f"{PASTA}/anos/{ano}", f"exercício {ano}", m_ano(ano))

    # descobertas VERIFICADAS → fila do segundo cérebro (o despachante da propagação envia; chave estável = sem duplicar)
    cer: dict[str, int] = {}
    if not seco and fontes_cerebro:
        reg_ = registrar_ or cerebro.registrar
        for chave, texto, assunto in descobertas(fontes_cerebro.get("couto"), fontes_cerebro.get("sobre")):
            try:
                st = reg_(chave, texto, "semantica", assunto).split(":")[0]
            except Exception as exc:  # noqa: BLE001 — a fila do cérebro não derruba o retrato
                st = f"erro {type(exc).__name__}"
            cer[st] = cer.get(st, 0) + 1

    anterior = _ler_estado()
    for k, v in (anterior.get("manchetes") or {}).items():      # fonte fora do ar: mantém a manchete anterior
        manchetes.setdefault(k, v)
    mudou_indice = gravar(VAULT / PASTA / "00-retratos.md", nota_indice(reg), seco) if any(r["ok"] for r in reg) else False
    mudou_hub = ligar_ao_hub(seco) if any(r["ok"] for r in reg) else False
    est = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "vault": str(VAULT), "seco": seco,
           "notas": len(reg), "em_dia": sum(r["ok"] for r in reg), "regravadas": sum(r["mudou"] for r in reg),
           "indisponiveis": [{"nota": r["nota"], "erro": r["erro"]} for r in reg if not r["ok"]],
           "indice_regravado": mudou_indice, "hub_regravado": mudou_hub, "cerebro": dict(sorted(cer.items())),
           "manchetes": {k: (IND if v is None else v) for k, v in sorted(manchetes.items())},
           "registro": [{k: r[k] for k in ("nota", "ok", "mudou", "fonte_de")} for r in reg]}
    if not seco:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = DATA / f".{ESTADO}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, DATA / ESTADO)
    return est


def _fonte_de_anterior(p: Path) -> str | None:
    try:
        m = re.search(r'^fonte_de: (".*")$', p.read_text(encoding="utf-8"), re.M)
        return json.loads(m.group(1)) if m else None
    except (OSError, ValueError):
        return None


def _ler_estado() -> dict:
    try:
        return json.loads((DATA / ESTADO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seco", action="store_true", help="não grava nada; só diz o que mudaria")
    a = ap.parse_args(argv)
    if not VAULT.is_dir():
        print(f"vault {VAULT} não existe — nada gravado", file=sys.stderr)
        return 2
    est = gerar(seco=a.seco)
    print(f"retratos: {est['em_dia']}/{est['notas']} em dia, {est['regravadas']} regravada(s)"
          + (", índice regravado" if est["indice_regravado"] else "") + (" [seco]" if a.seco else "")
          + (" · cérebro: " + ", ".join(f"{k} {v}" for k, v in est["cerebro"].items()) if est["cerebro"] else ""))
    for r in est["registro"]:
        if r["mudou"]:
            print(f"  ~ {r['nota']}")
    for i in est["indisponiveis"]:
        print(f"  ! {i['nota']}: {IND} — {i['erro']}", file=sys.stderr)
    return 1 if est["indisponiveis"] else 0


if __name__ == "__main__":
    sys.exit(main())
