# -*- coding: utf-8 -*-
"""Avaliador de Processo 360 — o processo COMO UM TODO: cada fase e cada despacho que importam.

Costura (sem reimplementar) as peças que existiam soltas:
  manifesto_norm (shape único + gate captura_integra) → fases.lacunas (ausência com gravidade)
  → cadeia_processo (ordem dos marcos) → triagem pericial A1–A5 (3 baldes) → execucao_fatos +
  rodar_execucao (X) → analisar_processo_sei (P/E/J) → rodar_fornecedor (C6–C9, CNPJ vencedor)
  → auditar_acatamento + suficiencia_parecer (escalada de emissor na CONTRATAÇÃO DIRETA)
  → **score_processo** (base.py — o agregador oficial, aqui pela 1ª vez em produção)
  → grau_flag + escalada.recomendar + matriz S×V (verossimilhança com teto 3 sem base de pares).

Honestidade estrutural: cada motor que falha vira entrada em `cobertura.indisponiveis`
(INDISPONÍVEL ≠ 0); lacuna só pesa contra o PROCESSO sob `captura_integra` (lição dos 874 FP);
o dict de saída é versionado (`versao: 360.1`).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from pathlib import Path

from compliance_agent import sei_recomendacoes
from compliance_agent.cadeia_processo import analisar_cadeia
from compliance_agent.detectores import PESOS_DETECTOR
from compliance_agent.detectores.base import ResultadoDetector, score_processo
from compliance_agent.editais.escalada import recomendar
from compliance_agent.editais.flags import grau_flag
from compliance_agent.execucao_fatos import contexto_x1, contexto_x3
from compliance_agent.sei import acervo_texto, fases, manifesto_norm

VERSAO = "360.1"
_DB = Path(__file__).resolve().parents[1] / "data" / "compliance.db"

# tipos canônicos que entram na auditoria de acatamento/suficiência (pareceres + decisórios)
_TIPOS_ACATAMENTO = {"parecer", "orgao_controle", "despacho", "oficio", "homologacao",
                     "adjudicacao", "contratacao_direta", "contrato", "aditivo"}
# âncoras dos sinais estruturais (regras da casa, determinísticas)
_ANCORA_GRAVIDADE = {"critica": 0.85, "alta": 0.6, "media": 0.3, "baixa": 0.3}
_ANCORA_TRIAGEM = {"alto": 0.85, "medio": 0.6, "baixo": 0.3}
# pesos dos sinais sintéticos do 360 (família: acatamento/suficiência = violacao_legal 1.0)
_PESOS_360 = {"P360-fases.lacunas": 0.6, "P360-cadeia": 0.8, "P360-triagem": 0.8,
              "P360-suficiencia_emissor": 1.0, "P360-acatamento": 1.0}


# ── indireções finas (monkeypatch em teste; motores pesados ficam fora do orquestrador) ──
async def _analisar_pej(numero: str, leitura: dict | None = None) -> dict:
    from compliance_agent.detectores.coletor_edital import analisar_processo_sei

    async def _ler(_n: str) -> dict:
        return leitura or {}
    return await analisar_processo_sei(numero, ler_fn=_ler)


def _rodar_execucao(numero: str, contexto: dict) -> list[ResultadoDetector]:
    from compliance_agent.detectores import rodar_execucao
    return rodar_execucao(numero, contexto=contexto)


def _rodar_fornecedor(cnpj: str) -> list[ResultadoDetector]:
    from compliance_agent.detectores import rodar_fornecedor
    return rodar_fornecedor(cnpj)


def _vereditos_por_doc(numero: str) -> dict:
    """Juízo por documento já pago (doc_veredito) na rubrica vigente — entra na ficha de cada doc."""
    try:
        from compliance_agent.sei.doc_juizo import RUBRICA_VERSAO
        if not _DB.exists():
            return {}
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            return {int(i): json.loads(v) for i, v in con.execute(
                "select doc_i, veredito_json from doc_veredito where numero_sei=? "
                "and rubrica_versao=?", (numero, RUBRICA_VERSAO))}
        finally:
            con.close()
    except (sqlite3.Error, ValueError, TypeError, ImportError):
        return {}


def achados_de_fornecedor(resultados) -> list[dict]:
    """Detectores de perfil do CONTRATADO que pontuam viram achado VISÍVEL.

    Medido em 2026-08-03: 14 processos ficaram EXTREMO com ZERO achados porque C9 (score 1,0) e
    C3/C5 (0,85) entravam no `score_processo` sem aparecer em lugar nenhum. O fiscal abria o topo
    da fila e não via nada escrito — e o processo cujos nove achados eu confirmei lendo os autos
    ficava ABAIXO de processos com um achado só. O que não aparece no entregável não existe.

    O achado declara que é do FORNECEDOR: confundir perfil da empresa com vício do processo seria
    imputar ao gestor o que é característica de quem ele contratou.
    """
    saida = []
    for r in resultados or []:
        if r.status != "confirmado" or r.refutada:
            continue
        s = float(r.score or 0)
        grav = "critica" if s >= 0.9 else "alta" if s >= 0.6 else "media"
        # `explicacao_inocente` é o CONTRA-argumento do detector, não o achado. Usá-la como texto
        # principal fazia o item ler "FALSO POSITIVO a descartar" no lugar da acusação — o oposto
        # do que se quer dizer. Ela entra em campo próprio, rotulada, como a doutrina da casa pede.
        inocente = (r.explicacao_inocente or "").strip()
        # A PROVA É O `trecho`, não o repr do dicionário. `str(e)[:120]` serializava
        # `{'fonte': ..., 'trecho': ...}` inteiro e cortava nos 120 caracteres — sobrava a chave
        # `fonte` e meia frase da prova. Medido no SEI-080002/019028/2024 (2026-08-04), o achado
        # C3/C5 de R$ 92,37 mi chegava ao painel escrito "Situação cadastral 'INAPTA' na Receita
        # Federal. Pagamento/contra" — truncado no meio da palavra. Mesma extração das outras três
        # famílias (`achados_de_detector`), inclusive o teto de 220.
        trechos = [str((e or {}).get("trecho") if isinstance(e, dict) else e)[:220]
                   for e in (r.evidencia or [])[:2]]
        saida.append({
            "origem": "fornecedor", "codigo": r.detector, "gravidade": grav,
            # o `diz` carrega a prova quando ela existe: "C9 confirmado (intensidade 1.00)" sozinho
            # é score sem explicação, que é o que a família C foi corrigida para não ser.
            "diz": (f"perfil do fornecedor contratado: detector {r.detector} confirmado "
                    f"(intensidade {s:.2f})" + (f" — {trechos[0]}" if trechos else "")),
            "explicacao_inocente": inocente,
            "evidencia": "; ".join(trechos),
            "ressalva": ("Indício sobre a EMPRESA contratada, não sobre a conduta do gestor "
                         "neste processo."),
        })
    return saida


def achados_de_detector(resultados, *, origem: str, rotulo: str, ressalva: str) -> list[dict]:
    """Resultado CONFIRMADO de detector vira achado VISÍVEL, com a prova literal.

    Forma única para as famílias que pontuam no `score_processo`. A regra é uma só e já custou
    três correções separadas (C em 2026-08-03, X e P/E/J em 2026-08-04): **o que entra no score
    entra na lista de achados**, senão a fila mostra processo vazio no topo.
    """
    saida = []
    for r in resultados or []:
        if r.status != "confirmado" or r.refutada:
            continue
        s = float(r.score or 0)
        trechos = [str((e or {}).get("trecho") if isinstance(e, dict) else e)[:220]
                   for e in (r.evidencia or [])[:2]]
        razao = (r.motivo_refutacao or "").strip()
        if not trechos and not razao:
            continue                      # sem prova literal, não entra
        saida.append({
            "origem": origem, "codigo": r.detector,
            "gravidade": "critica" if s >= 0.9 else "alta" if s >= 0.6 else "media",
            "diz": (f"{rotulo}: {r.detector} confirmado (intensidade {s:.2f})"
                    + f" — {trechos[0] if trechos else razao[:220]}"),
            "explicacao_inocente": (r.explicacao_inocente or "").strip(),
            "evidencia": "; ".join(trechos) or razao[:220],
            "ressalva": ressalva,
        })
    return saida


def achados_de_execucao(resultados) -> list[dict]:
    """Detectores da FASE DE EXECUÇÃO (X) que pontuam viram achado VISÍVEL.

    A mesma falha que `achados_de_fornecedor` corrigiu para a família C ficou aberta aqui, e é
    pior: os X medem o que aconteceu com o CONTRATO — aditivo que engorda, execução financeira
    anômala, reequilíbrio indevido, supressão que esvazia o objeto. Medido em 2026-08-04 nos 120
    processos de maior risco: **X3 confirmado em 29, X7 em 14, X1 em 4, X9 em 3**, todos
    pontuando no `score_processo` e nenhum aparecendo em lugar nenhum. Um deles (070002/013553/
    2024) estava em EXTREMO com score 80 e ZERO achados — o fiscal abria o topo da fila e não
    havia nada escrito.

    Ao contrário do fornecedor, aqui o achado É sobre este processo: a execução do contrato é
    conduta do gestor, não característica de quem ele contratou. Por isso não leva a ressalva de
    "indício sobre a empresa" — leva a ressalva de sempre, que indício não é acusação.
    """
    return achados_de_detector(
        resultados, origem="execucao", rotulo="execução do contrato",
        ressalva=("Indício a verificar nos autos, não acusação: o detector lê o texto dos "
                  "termos e pode ter colhido número de documento diverso."))


def _cnpj_vencedor(numero: str) -> str | None:
    """Maior favorecido do processo em `sei_arvore.fornecedores` (fallback barato e honesto)."""
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            norm = re.sub(r"\D", "", numero)
            row = con.execute(
                "select fornecedores from sei_arvore where replace(replace(replace("
                "numero_sei,'-',''),'/',''),'SEI','')=? or numero_sei=?",
                (norm, numero)).fetchone()
        finally:
            con.close()
        if not row or not row[0]:
            return None
        forn = sorted(json.loads(row[0]), key=lambda f: -(f.get("valor") or 0))
        return re.sub(r"\D", "", str(forn[0].get("cnpj") or "")) or None
    except (sqlite3.Error, json.JSONDecodeError, ValueError, KeyError, TypeError, IndexError):
        return None


_RX_CNPJ = re.compile(r"\b(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})\b")
# raízes de entes públicos que nunca são "o contratado" (Estado do RJ, Município do Rio)
_RAIZES_PUBLICAS = {"42498600", "42498733"}
_P1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_P2 = [6] + _P1


def _cnpj_valido(c: str) -> bool:
    if len(c) != 14 or len(set(c)) == 1:
        return False
    for pesos, n in ((_P1, 12), (_P2, 13)):
        r = sum(int(c[i]) * pesos[i] for i in range(n)) % 11
        if int(c[n]) != (0 if r < 2 else 11 - r):
            return False
    return True


def _cnpj_do_texto(pasta: Path, docs: list[dict]) -> str | None:
    """Fallback: CNPJ do contratado extraído do TEXTO dos docs de contrato/homologação
    (mais frequente, DV válido, excluídas raízes de ente público)."""
    from collections import Counter
    cont: Counter = Counter()
    alvo = [d for d in docs if d.get("tipo") in
            ("contrato", "homologacao", "ata_rp", "contratacao_direta", "adjudicacao")][:12]
    for d in alvo:
        for m in _RX_CNPJ.finditer(_texto_de(pasta, d, teto=30_000)):
            c = "".join(m.groups())
            # 00394… = base da União (ministérios); nunca é o contratado
            if _cnpj_valido(c) and c[:8] not in _RAIZES_PUBLICAS and not c.startswith("00394"):
                cont[c] += 1
    return cont.most_common(1)[0][0] if cont else None


# LER TUDO é o ponto do projeto (diretriz do dono, 2026-08-03). O corte de 20.000 caracteres
# alimentava o acatamento, a execução e a triagem: o Parecer 462 tem 54.900 e a CONCLUSÃO — onde o
# parecerista impõe as condicionantes — ficava fora. Conclusão de parecer mora no fim.
# A separação que importa: regex sobre disco não tem custo por token; LLM tem, e janela finita.
TETO_CHARS_DETERMINISTICO = int(os.environ.get("JFN_360_TETO_CHARS", "400000"))
TETO_CHARS_LLM = int(os.environ.get("JFN_360_TETO_CHARS_LLM", "20000"))


def _texto_de(pasta: Path, doc: dict, teto: int | None = None) -> str:
    """O texto que o SEI serviu para este documento — sem a etiqueta que o ARQUIVO escreveu.

    A etiqueta (`[título] (fase: … · tipo: …)`) punha a NOSSA classificação dentro do texto: o
    detector que perguntava "isto é manifestação jurídica?" recebia de volta o próprio rótulo, e
    o teto de leitura era gasto com ele (mediana 71 chars, máximo medido 478 — 36,5% de uma
    janela de 200). Quem precisa do rótulo pede `acervo_texto.etiqueta()` explicitamente; é o
    caso da `conferencia_captura`, e só dele. Ver `compliance_agent/sei/acervo_texto.py`.
    """
    return acervo_texto.ler(pasta, doc,
                            TETO_CHARS_DETERMINISTICO if teto is None else teto)


def _rd(origem: str, numero: str, score: float, detalhe: str) -> ResultadoDetector:
    r = ResultadoDetector(detector=f"P360-{origem}", processo=numero,
                          score=score, status="confirmado")
    r.explicacao_inocente = detalhe[:300]
    return r


def faixa_com_captura(score100: float, *, integra: bool) -> str:
    """Faixa de risco só se emite sobre processo LIDO. Sem captura íntegra: NAO_AVALIAVEL.

    Medido em 2026-08-03: 199 processos do acervo têm ZERO caractere capturado e 25 deles
    carregavam score >= 70 — um estava gravado como 89,0 EXTREMO. Faixa é afirmação sobre o
    processo; sobre o que não se leu, a única afirmação honesta é que não se leu.
    """
    return _faixa(score100) if integra else "NAO_AVALIAVEL"


def grau_com_captura(grau: dict, *, integra: bool) -> dict:
    """O grau (🟡 FLAG SUSPEITO etc.) também é afirmação — não se emite sem captura íntegra."""
    if integra:
        return grau
    return {"grau": "-", "rotulo": "NÃO AVALIÁVEL", "emoji": "⚪",
            "pode_fundamentar_peca": False,
            "motivo": ("captura do processo abaixo do mínimo utilizável — não se afirma risco "
                       "sobre o que não foi lido (INDISPONÍVEL ≠ irregular)")}


def _faixa(score100: float) -> str:
    return ("EXTREMO" if score100 >= 75 else "ALTO" if score100 >= 50
            else "MEDIO" if score100 >= 25 else "BAIXO")


def avaliar(numero_sei: str, *, com_llm: bool = False, teto_docs_llm: int | None = None) -> dict:
    man = manifesto_norm.carregar(numero_sei)
    if man is None:
        return {"numero_sei": numero_sei, "status": "INDISPONIVEL", "versao": VERSAO,
                "motivo": ("processo não está no arquivo compacto (data/sei_arquivo) — "
                           "capturar antes: tools/sei_arquivar.py ou fila sei_fila_captura")}
    return avaliar_pasta(Path(man["_pasta"]), com_llm=com_llm, teto_docs_llm=teto_docs_llm)


def avaliar_pasta(pasta: Path, *, com_llm: bool = False, teto_docs_llm: int | None = None) -> dict:
    man_cru = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    man_cru["_pasta"] = str(pasta)
    man = manifesto_norm.normalizar(man_cru)
    docs = man["docs"]
    numero = str(man.get("processo") or pasta.name)
    modalidade = str(man.get("modalidade") or "")
    integra, ev_captura = manifesto_norm.captura_integra(man, pasta)

    achados: list[dict] = []
    indisponiveis: list[str] = []
    rodados: list[str] = []
    resultados: list[ResultadoDetector] = []

    # 1) fases + lacunas (ausência só pesa contra o processo sob captura íntegra E quando a
    # NATUREZA é de contratação — processo de pagamento/repasse não carrega ETP/edital/contrato;
    # eles vivem no processo-pai. Lição da triagem: "observação ≠ achado"; sem isto, todo
    # processinho de OB de 3 docs saía "ALTO" por lacunas estruturalmente esperadas.)
    try:
        from tools.sei_triagem_pericia import natureza as _natureza
        nat = _natureza(man, docs)
    except Exception:  # noqa: BLE001
        nat = "indefinido"
    fases_presentes = {d["fase"] for d in docs} - {"indefinida"}
    com_pagamento = any(d["tipo"] in ("ordem_bancaria", "programacao_desembolso") for d in docs)
    lac = fases.lacunas(fases_presentes, modalidade, com_pagamento=com_pagamento, natureza=nat)
    lacunas_processo = lac if integra else []
    lacunas_captura = [] if integra else lac
    if not integra:
        lacunas_captura = list(lacunas_captura) + [
            {"falta": "captura íntegra do processo (texto no disco abaixo do mínimo)",
             "gravidade": "captura", **ev_captura}]
    for item in lacunas_processo:
        # `aditivo` é espécie de contratação para efeito de cobrança (só a seleção sai, e já saiu
        # em `fases.lacunas`) — sem isto o aditivo perderia também as lacunas que lhe cabem.
        if nat in ("contratacao", "aditivo") or item["gravidade"] == "critica":
            achados.append({"origem": "fases.lacunas", "diz": item["falta"],
                            "gravidade": item["gravidade"]})

    # 2) ordem dos marcos (a inversão contrato→parecer também é a A1 da triagem: dedup por
    # código para não contar o MESMO fato duas vezes no score de convergência)
    cadeia = analisar_cadeia([{"titulo": d["titulo"], "tipo": d["tipo"]} for d in docs])
    inversoes_cadeia = list(cadeia.get("inversoes", []))

    # 3) triagem pericial A1–A5 (gate próprio; mesmos 3 baldes)
    codigos_triagem: set[str] = set()
    try:
        from tools.sei_triagem_pericia import periciar as _periciar
        tri = _periciar(pasta) or {}
        rodados.append("triagem_A1-A5")
        for a in tri.get("achados", []):
            codigos_triagem.add(str(a.get("codigo") or ""))
            achados.append({"origem": "triagem", **a})
    except Exception as e:  # noqa: BLE001
        indisponiveis.append(f"triagem: {e}")
    for inv in inversoes_cadeia:
        if (inv.get("tipo") == "contrato_antes_do_parecer"
                and "A1_CONTRATO_ANTES_DO_PARECER" in codigos_triagem):
            continue  # mesmo fato já pontuado pela A1
        achados.append({"origem": "cadeia", "diz": inv.get("observacao", inv.get("tipo")),
                        "gravidade": "alta", "detalhe": inv})

    # 4) execução (X) — fatos extraídos do TEXTO dos docs de contratação/execução/despesa
    try:
        t_contrato = "\n".join(_texto_de(pasta, d) for d in docs
                               if d["tipo"] in ("contrato", "aditivo", "ordem_inicio"))
        t_despesa = "\n".join(_texto_de(pasta, d) for d in docs
                              if d["fase"] in ("despesa", "execucao"))
        ctx_exec = {**(contexto_x1(t_contrato) if t_contrato.strip() else {}),
                    **(contexto_x3(t_despesa) if t_despesa.strip() else {})}
        res_exec = _rodar_execucao(numero, ctx_exec)
        resultados.extend(res_exec)
        # PONTUAR SEM APARECER é a falha que já custou 14 processos EXTREMO sem achado nenhum na
        # família C. Aqui ela seguia aberta para a família X — ver `achados_de_execucao`.
        achados += achados_de_execucao(res_exec)
        rodados += sorted({r.detector for r in res_exec})
    except Exception as e:  # noqa: BLE001
        indisponiveis.append(f"execucao: {e}")

    # 4b) instrumento × assinatura — três achados que moram no TEXTO e não nos títulos, nascidos
    #     da leitura integral do SEI-270131/000548/2023 confrontada com o veredito da casa:
    #     minuta aprovada que não corresponde ao instrumento assinado (e ordinal repetido),
    #     autorização de despesa anterior ao parecer, e ato do ordenador sem a assinatura de quem
    #     ele nomeia como decisor. Determinístico e offline — lê o texto já em disco.
    try:
        from compliance_agent.sei import instrumento_assinatura as _ia
        # teto ALTO de propósito: o rodapé de assinatura mora no FIM do documento, e o Parecer 462
        # tem 54.900 caracteres — com o teto padrão de 20.000 a data da assinatura ficava fora do
        # texto lido e o I2 nunca disparava. É varredura por regex, custo desprezível.
        # `etiqueta` vai junto e SEPARADA: o texto chega limpo do rótulo do arquivo (que fazia o
        # documento provar a si mesmo), e a `conferencia_captura` — a única que legitimamente
        # precisa do rótulo, para achar o número do documento quando o manifesto foi reconstruído
        # do nome do arquivo — o recebe explicitamente, sem depender de resíduo dentro do texto.
        docs_txt = [{"ref": d.get("titulo", ""), "tipo": d.get("tipo", ""),
                     "texto": _texto_de(pasta, d, teto=400_000),
                     "etiqueta": acervo_texto.etiqueta_de(pasta, d)} for d in docs]
        achados += _ia.avaliar(docs_txt)
        rodados.append("instrumento_assinatura")
        # C · a lista de documentos do próprio parecer confere a NOSSA captura. Entra como lacuna
        # de CAPTURA (nunca vício do processo): mede o que a coleta ainda não trouxe.
        from compliance_agent.sei import conferencia_captura as _cc
        for a in _cc.avaliar(docs_txt):
            lacunas_captura.append({"falta": a["diz"], "gravidade": "captura",
                                    "codigo": a["codigo"], "evidencia": a["evidencia"],
                                    "ausentes": a["ausentes"]})
        rodados.append("conferencia_captura")
    # O módulo é determinístico e já trata o que é dele; aqui só restam falha de import e de
    # leitura do texto em disco — por isso a captura é específica, e não genérica. (A catraca da
    # casa conta a string literal, então nem o comentário pode citá-la: foi assim que este
    # arquivo subiu 1 na contagem sem ter ganhado nenhum handler novo.)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        indisponiveis.append(f"instrumento_assinatura: {e}")

    # 5) P/E/J sobre a leitura do ARQUIVO (nunca browser aqui)
    try:
        leitura = {"texto": "", "documentos": [d["titulo"] for d in docs],
                   "conteudo_documentos": [
                       {"doc": d["titulo"], "conteudo": _texto_de(pasta, d, TETO_CHARS_LLM)}
                       for d in docs if d.get("texto")]}
        pej = asyncio.run(_analisar_pej(numero, leitura=leitura))
        if pej.get("status") == "OK":
            res_pej: list[ResultadoDetector] = []
            for rd in pej.get("resultados", []):
                if isinstance(rd, dict):
                    # A prova ia embora na conversão: `evidencia` e `explicacao_inocente` eram
                    # descartadas, e o resultado nunca virava achado. Terceira vez que a mesma
                    # falha aparece (C, X e agora P/E/J) — 4 processos ficaram EXTREMO/ALTO com
                    # ZERO achados por E1 e E7 pontuando invisíveis. (2026-08-04)
                    r = ResultadoDetector(
                        detector=str(rd.get("detector") or "?"), processo=numero,
                        score=float(rd.get("score") or 0),
                        status=str(rd.get("status") or "nao_avaliavel"))
                    r.evidencia = list(rd.get("evidencia") or [])
                    r.explicacao_inocente = str(rd.get("explicacao_inocente") or "")
                    r.motivo_refutacao = str(rd.get("motivo_refutacao") or "")
                    r.refutada = bool(rd.get("refutada"))
                    res_pej.append(r)
                    resultados.append(r)
                    rodados.append(str(rd.get("detector")))
            achados += achados_de_detector(
                res_pej, origem="edital", rotulo="planejamento/edital/julgamento",
                ressalva=("Indício a verificar nos autos, não acusação: o detector lê o texto do "
                          "edital e das peças de julgamento."))
        else:
            indisponiveis.append(f"pej: {pej.get('motivo')}")
    except Exception as e:  # noqa: BLE001
        indisponiveis.append(f"pej: {e}")

    # 6) perfil do contratado (C) — CNPJ vencedor/maior favorecido; fallback = texto dos autos
    cnpj = _cnpj_vencedor(numero) or _cnpj_do_texto(pasta, docs)
    if cnpj:
        try:
            res_forn = _rodar_fornecedor(cnpj)
            resultados.extend(res_forn)
            achados += achados_de_fornecedor(res_forn)
            rodados += sorted({r.detector for r in res_forn})
        except Exception as e:  # noqa: BLE001
            indisponiveis.append(f"fornecedor: {e}")
    else:
        indisponiveis.append("fornecedor: CNPJ vencedor não identificado (sei_arvore)")

    # 7) acatamento (art. 53) + suficiência do emissor (lição IDESI)
    docs_ac = [{"ref": d["titulo"], "tipo": d["tipo"], "texto": _texto_de(pasta, d)}
               for d in docs if d["tipo"] in _TIPOS_ACATAMENTO][:40]
    ac = sei_recomendacoes.auditar_acatamento(docs_ac)
    tipos = {d["tipo"] for d in docs}
    ato = ("contratacao_direta" if "contratacao_direta" in tipos
           or any(k in modalidade.lower() for k in ("dispensa", "inexigibil", "emergenc"))
           else "contrato" if "contrato" in tipos
           else "aditivo" if "aditivo" in tipos else "geral")
    suf = sei_recomendacoes.suficiencia_parecer(docs_ac, ato)
    ac["suficiencia"] = suf
    if ac.get("veredito") == "IGNORADO_INDICIO":
        achados.append({"origem": "acatamento", "gravidade": "alta",
                        "diz": "ressalva de parecer com sinal de não-atendimento e sem "
                               "acolhimento/motivação posterior (art. 53 / LINDB art. 22)"})
    if (ac.get("veredito") == "SEM_PARECER_LOCALIZADO" and integra
            and nat == "contratacao" and "contrato" in tipos):
        achados.append({"origem": "acatamento", "gravidade": "media",
                        "diz": "contratação com contrato nos autos e NENHUM parecer jurídico "
                               "localizado entre os documentos lidos (art. 53 exige análise "
                               "prévia; captura íntegra — indício a confirmar na íntegra)"})
    if suf["veredito"] == "PARECER_DE_EMISSOR_INSUFICIENTE" and integra:
        achados.append({"origem": "suficiencia_emissor", "gravidade": "alta",
                        "diz": (f"ato '{ato}' exige parecer de nível {suf['exigido']} "
                                f"(PGE/CGE) e os autos só têm emissores de nível "
                                f"{suf['max_nivel']} ({', '.join(suf['emissores']) or '—'}) "
                                "— a análise do art. 53 é do órgão de assessoramento jurídico "
                                "da Administração; a manifestação da PGE-RJ é exigida nas "
                                "hipóteses das normas estaduais e pode ter sido dispensada por "
                                "declaração de conformidade com a minuta-padrão, que se confere "
                                "nos autos")})

    # 8) sinais estruturais → ResultadoDetector sintéticos + agregador OFICIAL
    for a in achados:
        origem = a["origem"]
        # o achado de FORNECEDOR e o de EXECUÇÃO já vieram do próprio detector, que JÁ está em
        # `resultados`: convertê-los em sinal sintético os contaria duas vezes e inflaria o score.
        if origem in ("fornecedor", "execucao", "edital"):
            continue
        if origem == "triagem":
            s = _ANCORA_TRIAGEM.get(str(a.get("grau")), 0.3)
        else:
            s = _ANCORA_GRAVIDADE.get(str(a.get("gravidade")), 0.3)
        resultados.append(_rd(origem, numero, s, str(a.get("diz") or "")))
    score = score_processo(resultados, pesos={**PESOS_DETECTOR, **_PESOS_360})
    score100 = round(score * 100, 1)
    faixa = faixa_com_captura(score100, integra=integra)

    # 9) grau/escalada/matriz (verossimilhança: nº de origens independentes; teto 3 sem pares)
    origens = {r.detector.split("-")[0] if r.detector.startswith("P360") else r.detector[:1]
               for r in resultados if r.status == "confirmado" and not r.refutada}
    n_familias = len(origens)
    teste_violado = any((r.valores or {}).get("teste_objetivo") == "violado" for r in resultados)
    grau = grau_flag(origem="deterministico", score=score,
                     teste_status="violado" if teste_violado else None,
                     familias_convergentes=max(0, n_familias - 1))
    grau = grau_com_captura(grau, integra=integra)

    # SÍNTESE GLOBAL: o olhar de conjunto sobre TODOS os documentos (map-reduce sobre as fichas,
    # nunca sobre o texto cru). É o que responde "o que este processo mostra" — a lista de achados
    # responde "o que há de errado", que é outra pergunta.
    try:
        from compliance_agent.sei import sintese_global as _sg
        _fichas = _sg.fichas(
            [{"i": d.get("i"), "ref": d.get("titulo", ""), "tipo": d.get("tipo", ""),
              "fase": d.get("fase", ""), "texto": _texto_de(pasta, d)} for d in docs],
            _vereditos_por_doc(numero))
        sintese = _sg.sintetizar(_fichas, lacunas_captura=len(lacunas_captura), numero=numero)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        sintese = {"indisponivel": True, "motivo": str(e)[:140]}
        indisponiveis.append(f"sintese_global: {e}")
    # NAO_AVALIAVEL entra como a severidade MÍNIMA da matriz: sem leitura não se afirma gravidade,
    # e deixar a chave de fora quebrava a avaliação inteira do processo (KeyError).
    sev = {"EXTREMO": 5, "ALTO": 4, "MEDIO": 3, "BAIXO": 2}.get(faixa, 1)
    ver = min(3, 2 + (1 if n_familias >= 2 else 0))  # teto 3: não há base de pares por processo
    escalada = recomendar(sev * ver, teste_objetivo_violado=teste_violado,
                          familias_independentes=n_familias)

    docs_chave = [{"i": d["i"], "titulo": d["titulo"], "tipo": d["tipo"], "fase": d["fase"]}
                  for d in docs
                  if d["tipo"] in ("contratacao_direta", "parecer", "homologacao", "despacho",
                                   "aceite", "medicao", "contrato", "aditivo", "edital")][:60]

    out = {
        "numero_sei": numero, "versao": VERSAO, "status": "OK",
        "modalidade": modalidade, "ato_principal": ato, "natureza": nat,
        "fases": {f: len(ix) for f, ix in man["linha_do_tempo"].items() if ix},
        "docs_chave": docs_chave,
        "achados": achados,
        "lacunas_processo": lacunas_processo,
        "lacunas_captura": lacunas_captura,
        "cadeia": {k: cadeia.get(k) for k in ("grau", "inversoes", "resumo")},
        "acatamento": ac,
        "cnpj_vencedor": cnpj,
        "score": float(score), "score100": score100, "faixa": faixa, "grau": grau,
        "sintese": sintese,
        "matriz_sv": {"severidade": sev, "verossimilhanca": ver, "produto": sev * ver},
        "escalada": escalada,
        "cobertura": {"captura_integra": integra, **ev_captura,
                      "detectores_rodados": sorted(set(rodados)),
                      "indisponiveis": indisponiveis},
        "llm": None,
    }
    if com_llm:
        try:
            from compliance_agent.sei.doc_juizo import julgar_docs
            out["llm"] = julgar_docs(man, pasta, teto=teto_docs_llm)
        except Exception as e:  # noqa: BLE001
            out["llm"] = {"status": "INDISPONIVEL", "motivo": str(e)}
    return out


_DDL_AVALIACAO = """
CREATE TABLE IF NOT EXISTS processo_avaliacao (
  numero_sei TEXT PRIMARY KEY, score REAL, score100 REAL, grau TEXT, faixa TEXT,
  achados_json TEXT, lacunas_json TEXT, docs_chave_json TEXT, acatamento_json TEXT,
  escalada_json TEXT, cnpj_vencedor TEXT, confianca REAL, cobertura_json TEXT,
  sintese_json TEXT,
  avaliado_em TEXT DEFAULT (datetime('now')), versao TEXT
);
"""


def gravar(out: dict, con: sqlite3.Connection | None = None) -> bool:
    """Persiste a avaliação (upsert por numero_sei). Só grava status OK."""
    if out.get("status") != "OK":
        return False
    own = con is None
    con = con or sqlite3.connect(str(_DB), timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.executescript(_DDL_AVALIACAO)
        cob = out.get("cobertura") or {}
        n_rod = len(cob.get("detectores_rodados") or [])
        confianca = round(n_rod / (n_rod + len(cob.get("indisponiveis") or []) or 1), 3)
        con.execute(
            "insert into processo_avaliacao (numero_sei, score, score100, grau, faixa, "
            "achados_json, lacunas_json, docs_chave_json, acatamento_json, escalada_json, "
            "cnpj_vencedor, confianca, cobertura_json, sintese_json, avaliado_em, versao) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?) "
            "on conflict(numero_sei) do update set score=excluded.score, "
            "score100=excluded.score100, grau=excluded.grau, faixa=excluded.faixa, "
            "achados_json=excluded.achados_json, lacunas_json=excluded.lacunas_json, "
            "docs_chave_json=excluded.docs_chave_json, acatamento_json=excluded.acatamento_json, "
            "escalada_json=excluded.escalada_json, cnpj_vencedor=excluded.cnpj_vencedor, "
            "confianca=excluded.confianca, cobertura_json=excluded.cobertura_json, "
            "sintese_json=excluded.sintese_json, "
            "avaliado_em=excluded.avaliado_em, versao=excluded.versao",
            (out["numero_sei"], out["score"], out["score100"], out["grau"]["grau"],
             out["faixa"], json.dumps(out["achados"], ensure_ascii=False, default=str),
             json.dumps({"processo": out["lacunas_processo"],
                         "captura": out["lacunas_captura"]}, ensure_ascii=False, default=str),
             json.dumps(out["docs_chave"], ensure_ascii=False, default=str),
             json.dumps(out["acatamento"], ensure_ascii=False, default=str),
             json.dumps(out["escalada"], ensure_ascii=False, default=str),
             out.get("cnpj_vencedor"), confianca,
             json.dumps(cob, ensure_ascii=False, default=str),
             json.dumps(out.get("sintese") or {}, ensure_ascii=False, default=str), VERSAO))
        con.commit()
        return True
    finally:
        if own:
            con.close()
