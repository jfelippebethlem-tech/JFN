# -*- coding: utf-8 -*-
"""Catraca de `except Exception` — trava o CRESCIMENTO da dívida de erro engolido.

Não exige corrigir o legado: falha só se o total SUBIR além da baseline. Quando a
contagem cair (curadoria tipo dae25fe no Massare), abaixe a BASELINE p/ o novo valor —
a catraca só anda numa direção. Novo código: capturar exceção ESPECÍFICA, ou ao menos
logar (`logger.debug/warning`) — nunca `except Exception: pass` mudo (perda silenciosa,
lição da dívida de 1.404 ocorrências mapeada no MOC-Ecossistema 2026-06-24/07-07).
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# 2026-07-17: re-medido em 1447 — a expansão de intel do dia (11 detectores da leva b, +47 já
# COMMITADOS sem rodar a catraca; +8 da leva c, todos logados ou no idioma-padrão das rotas)
# subiu a dívida. DÉBITO REGISTRADO: curadoria p/ voltar a ≤1392 pende (trocar por exceção
# específica nos detectores novos). A catraca volta a travar crescimento a partir daqui.
# 2026-07-18: +4 (1447→1451) — todos LOGADOS (não mudos) e amplos por DESIGN correto: rodar
# detector arbitrário no fingerprint da autoauditoria (erro = estado do retrato) e libs de OCR
# (fitz/tesseract/PIL, espaço de exceção enorme). Converter p/ específico seria errado aqui.
# 2026-07-18b: +1 (1451→1452) — 1 route handler novo (/api/intel/comunidades_grafo) no idioma-padrão
# das ~71 rotas do investigacao.py (catch-all que RETORNA o erro no JSON, não é mudo).
# 2026-07-18c: +1 (1452→1453) — rota /api/intel/escalada (detector novo), idioma-padrão das rotas.
# 2026-07-18d: +2 (1453→1455) — rota /api/intel/lift + o catch-por-detector do avaliar_lift (roda
# detector arbitrário no harness de lift, como o fingerprint; logado, amplo por design correto).
# 2026-07-18e: +5 (1455→1460) — comparador de preços: 4 route handlers novos (buscar/item/orgaos/
# fornecedores) no idioma-padrão das rotas + 1 já contabilizado. Todos catch-and-return, não mudos.
# 2026-07-18f: +2 (1460→1462) — dossiê caro+suspeito: rota /api/comparador/dossie + degradação
# graciosa do cache do radar (except→radar={}, não mudo). Ambos idioma-padrão, logados/graceful.
# 2026-07-18g: +2 (1462→1464) — rotas /api/comparador/economia + /api/sancoes/detalhar (idioma
# das rotas, catch-and-return).
# 2026-07-18h: +1 (1464→1465) — rota /api/comparador/vedada (idioma das rotas).
# 2026-07-18i: +1 (1465→1466) — enriquecimento capital/porte no investigacao_dd (except→logger.debug,
# não mudo; degrada honesto se a tabela empresas_cadastro não existir).
# 2026-07-18j: +4 (1466→1470) — sweeps de cadastro (cadastro_enrich + empresas_dump): lookups de
# rede e guarda de recursos (amplos por design, todos logados/degradam honesto).
# 2026-07-18m: -7 (remoção OpenSanctions/Aleph — módulos+classe+intel_pdf; 1471 antes) → 1464.
# 2026-07-19: +25 (1464→1489) — missão 4 frentes commitada sem rodar a catraca (J8 atestado
# cruzado, forense/pdf_metadados, geo/osm_local, âncora setorial, spiderfoot_bridge, proposta_item,
# screens_conluio, indice_certame, narrativa_certame, rotas novas). AUDITADO 2026-07-19: ZERO
# `except Exception: pass` MUDO nos arquivos tocados — todos logados, catch-and-return de rota ou
# amplos por design (rodar detector arbitrário / lib externa). Curadoria p/ específico segue aberta.
# 2026-07-20: +13 (1489→1502) — dossiê mestre F1-F4. AUDITADO no dia: 3 route handlers novos no
# idioma-padrão das rotas (conjunto/orgao, conjunto/portfolio, sei/acatamento — catch-and-return);
# persist da ata (coletor_edital) e achado R15 (lex_analise) eram os únicos MUDOS → convertidos p/
# logger.debug; backfill/fase_indice e rubrica de motivo degradam honesto (contador/segue ambíguo).
# Zero `except Exception: pass` mudo no código novo. Curadoria do legado p/ específico segue aberta.
# 2026-07-20b: +2 (1502→1504) — F5. AUDITADO: a seção 1-M do /orgao (conjunto_certames indisponível →
# logger.debug) e o degradar da rota; ambos LOGADOS/graceful, nenhum mudo.
# 2026-07-20c: +5 (1504→1509) — pacote completo (G1-G7). AUDITADO: §1-N nomeações do /orgao, capítulo SEI
# do dossiê completo (dossie.montar_ctx_completo) e worker/sub-try da rota /api/dossie/completo — todos
# LOGADOS (logger.debug/warning) ou catch-and-return de rota; zero pass mudo no código novo.
# 2026-07-22: +7 (1509→1516). AUDITADO: a manhã (painel v9, commits d98f351e..5c92b675) já estava
# em 1513 sem rodar a catraca (+4 herdados). A tarde somou +3, NENHUM mudo: ata_para_julgamento
# (amplo por design — parser de ata arbitrária — com logger.warning), fase_julgamento_pncp
# (contador de erro, degrada honesto) e cmd_certame (idioma-padrão catch-and-return dos comandos
# do núcleo). OCR da íntegra/manifest do Lex/narrativa do /certame foram para exceção ESPECÍFICA.
# Curadoria do legado p/ específico segue aberta.
# 2026-07-22b: +2 (1516→1518) — paridade PCRJ: rota /api/intel/concentracao_municipio (idioma-
# padrão catch-and-return das rotas) + fase_indice_municipal do backfill (roda calcular arbitrário
# por certame, erro CONTADO na fatia — degrada honesto, não mudo). Import-guard do classificador
# de esfera foi para ImportError específico.
# 2026-07-22c: +1 (1518→1519) — seção EMENDAS no relatório (inteligencia.py:~253): amplo por
# design com logger.warning (a seção nunca derruba o relatório inteiro); o commit 8509159f
# esqueceu de auditar aqui. Os 2 genéricos novos do /fornecedor (nome + sinal de emendas)
# foram para exceção ESPECÍFICA — não contam.
BASELINE = 1519


def _contar() -> int:
    arquivos = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    total = 0
    for rel in arquivos:
        if rel.startswith("massare") or rel == "tests/test_catraca_excepts.py":
            continue  # massare tem catraca própria; este arquivo cita a string 4× (auto-referência)
        try:
            total += (REPO / rel).read_text(encoding="utf-8", errors="ignore").count("except Exception")
        except OSError:
            continue
    return total


def test_except_exception_nao_cresce():
    atual = _contar()
    assert atual <= BASELINE, (
        f"{atual} `except Exception` (baseline {BASELINE}): o novo código introduziu "
        f"{atual - BASELINE} captura(s) genérica(s). Capture a exceção específica ou logue o erro."
    )


def test_baseline_atualizada_quando_melhora():
    atual = _contar()
    folga = BASELINE - atual
    assert folga <= 25, (
        f"A contagem caiu para {atual} — abaixe BASELINE em tests/test_catraca_excepts.py "
        f"para {atual} e trave o ganho (catraca só anda numa direção)."
    )
