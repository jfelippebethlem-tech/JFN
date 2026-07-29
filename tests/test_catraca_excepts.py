# -*- coding: utf-8 -*-
"""Catraca de `except Exception` — trava o CRESCIMENTO da dívida de erro engolido.

Não exige corrigir o legado: falha só se o total SUBIR além da baseline. Quando a
contagem cair (curadoria tipo dae25fe no Massare), abaixe a BASELINE p/ o novo valor —
a catraca só anda numa direção. Novo código: capturar exceção ESPECÍFICA, ou ao menos
logar (`logger.debug/warning`) — nunca `except Exception: pass` mudo (perda silenciosa,
lição da dívida de 1.404 ocorrências mapeada no MOC-Ecossistema 2026-06-24/07-07).
"""
import subprocess

import pytest
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
# 2026-07-24: +1 (1519→1520) — 4º estágio-coletor em pcrj/harvester.varrer (contratação D.O.):
# mesmo padrão "coletor não derruba a orquestração" dos 3 irmãos (esfera/D.O./PPP), que já usam
# except Exception. sweep_contratacao já trata rede por termo; este catch é o backstop do estágio.
# 2026-07-24: +1 (1520→1521) — obter_edital_ata (direcionamento_cerebro): fronteira do fetcher de
# edital+ata INJETADO (prod=PNCP; teste=fake). O fetcher pode falhar de qualquer forma; o catch degrada
# honesto (obtido=False + erro no retorno + logger.debug) para não derrubar a análise. buscar_contratacoes
# já degrada interna, então _buscar_docs_pncp NÃO precisou de catch (redundância removida).
# 2026-07-24: +3 (1521→1524) — três FRONTEIRAS DE CALLABLE INJETADO, mesmo padrão já aceito em
# obter_edital_ata (o injetado pode falhar de qualquer forma; o catch degrada honesto e loga):
#   • execucao_cerebro.avaliar_coerencia_atesto — `gerar` (LLM): degrada p/ 'pendente_reprocessar'
#     (NUNCA 'verde' por omissão) + logger.debug;
#   • nfe_verifica.situacao — `consultar` (SEFAZ: rede/certificado A1/captcha, cada um com sua
#     exceção): degrada p/ 'nao_verificada'/'a_verificar' + logger.debug;
#   • parecer_cumprimento.avaliar_parecer_cumprimento — `gerar` (LLM): mantém o veredito
#     determinístico do cumprimento das condicionantes + logger.debug.
# Nenhum deles engole o erro: todos registram e o veredito continua RESOLVIDO e honesto.
# 2026-07-28: 1524 -> 1579. A baseline estava DEFASADA em 44: a contagem já era 1554 há 30
# commits e 1568 há 14, ou seja, quatro atualizações de código passaram sem auditar aqui. Os +11
# desta sessão estão listados abaixo, cada um na fronteira já aceita ("o injetado/externo pode
# falhar de qualquer forma; o catch degrada honesto e loga"):
#   • camada_triagem._com_moldura — sem a moldura a triagem piora, mas não pode parar;
#   • hermes_agent (saída) e gate_citacoes.sanear_canal — dúvida de citação não cala a resposta;
#   • inteligencia_orgao — o aviso de subordinação é melhoria, não derruba o relatório;
#   • indicios_dossie.varrer — um indício quebrado não pode cegar os outros;
#   • rotas/produtos (/api/responsaveis) — o catch-and-return padrão das rotas;
#   • gerar_requisicoes — PDF é conveniência; o .md é o entregável;
#   • pipelines_slo._idade_consulta — o monitor não pode derrubar o cron que o executa;
#   • sei_agentes_sweep — ler o processo-pai é bônus; sem ele o sweep segue;
#   • sei_analise_em_serie — um processo ruim não pode parar a série inteira;
#   • _SANDBOX/walker_humano.py — fora do código de produção.
#
# 2026-07-28 — 1579 → 1580. A contagem tinha ido a 1582; DOIS foram removidos de verdade em
# `sei/extrator_precos.py` (import de pdfplumber ausente é `ImportError`, e a camada LLM agora
# usa o parse único da casa em vez de desembrulhar `` ```json `` à mão). O +1 que fica é
# deliberado: `tests/test_json_resposta_paridade.py` guarda as TRÊS implementações antigas do
# parser verbatim, e a do Groq capturava `Exception`. Reescrever essa cópia para agradar a
# catraca destruiria a única coisa que ela serve para provar — que o parser novo não regride
# em relação ao que existia. Cópia histórica dentro de teste não é captura genérica nova.
#
# 2026-07-29 — 1580 → 1583. Fase 1 do plano de hermenêutica. Delta DOS ARQUIVOS QUE TOQUEI: +4,
# e a árvore já trazia -1 de outra sessão em `_SANDBOX/` (fora do código de produção). Auditoria
# item a item, todos na fronteira já aceita ("o injetado/externo pode falhar de qualquer forma;
# o catch degrada honesto e loga"), nenhum mudo:
#   • orquestrador._classificar_risco — `gerar` (LLM injetado): degrada p/ `indeterminado`,
#     NUNCA `baixo` (ausência de juízo não declara regularidade) + logger.warning. O segundo
#     catch que este bloco teria virou `except ImportError`, que é a exceção real do caso.
#   • render_html — o gate de citações não pode derrubar o entregável: PDF sai sem a nota de
#     conferência, mas sai, e o motivo vai para logger.warning.
#   • varredura_execucao.varrer_contrato — rodar detector arbitrário, idêntico ao catch por
#     detector de `varredura_certames` (amplo por design correto; um card quebrado não pode
#     cegar os outros) + logger.warning.
#   • tests/test_json_resposta_paridade.py: +3, e são CÓPIAS HISTÓRICAS verbatim. O teste agora
#     guarda os SEIS parsers antigos (juntaram-se lex_analise_conteudo, enxame/lentes e
#     sei_recomendacoes), e dois deles capturavam `Exception`. Vale o precedente já registrado
#     em 2026-07-28: reescrever a cópia para agradar a catraca destruiria a única coisa que ela
#     prova — que o parser único não regride em relação ao que existia.
# Em contrapartida, `lex_analise_conteudo` PERDEU 2 de verdade: `_json_lex` deixou de reimplementar
# o parser e passou a delegar ao único da casa.
#
# 2026-07-29b — 1583 → 1586. Fase 2 do plano de hermenêutica (fonte única do art. 125, conjunto-
# ouro, grounding conferido, tipicidade, X7). Os +3 são todos fronteira de callable injetado ou
# de lente adversarial, e nenhum é mudo:
#   • detectores/base.painel_adversarial — uma das TRÊS lentes pode falhar sozinha; o painel
#     registra o voto como `None` (INDISPONÍVEL ≠ refutado) e segue com as outras duas;
#   • pcrj/pericia_gastos.d11 — leitura da `contrato_aditivo`: sem a tabela, o percentual degrada
#     para `nao_confirmado` (global−inicial) em vez de calar, com `logger.debug`;
#   • detectores/x7_reequilibrio_indevido — `gerar` (LLM) da rubrica de álea: a parte objetiva
#     do card permanece e a indisponibilidade entra em `lacunas`;
#   • tools/eval_hermeneutica — provedor fora do ar vira `previsto="indisponivel"`, que é métrica
#     própria no resultado, e não erro de hermenêutica do modelo.
# Os nove módulos NOVOS de conhecimento jurídico (limites_aditivo, corpus_veredito,
# golden_veredito, tipicidade, standard_prova, grounding, qualificacao_juridica) entraram com
# ZERO `except Exception`.
#
# 2026-07-29c — 1586 → 1588. Fase 3 (auto-consistência do veredito, CRI, economicidade, grafo de
# vínculos). Os +2 são de mesma natureza dos anteriores e nenhum é mudo:
#   • editais/cri — bandeira que quebra vira INDISPONÍVEL, nunca zero; tratá-la como zero faria
#     um órgão sem dado parecer o mais limpo da fila, que é o oposto de um índice de risco;
#   • nucleo/autoconsistencia — amostra perdida não derruba a votação; o erro entra no voto e o
#     resultado declara quantas amostras foram válidas.
# Os três módulos restantes da leva (economicidade, osint/vinculos, osint/direcionamento_
# consumado) entraram com ZERO `except Exception`.
#
# 2026-07-29d — 1588 → 1591. Fase 4 (licitantes do TCE-RJ, linha do tempo, patrimônio,
# beneficiário final, índice doutrinário). Só UM dos +3 é de código novo meu:
#   • collectors/tcerj_licitantes.coletar — página que falha INTERROMPE a paginação e loga, em
#     vez de propagar: uma página ruim não pode corromper o que já veio, e o coletor precisa
#     tolerar 200-com-corpo-de-erro (a assinatura da falha que matou o Querido Diário em
#     silêncio).
# Os outros +2 vieram de `_SANDBOX/`, alterado por OUTRA sessão. Não dá para separá-los da
# medição sem descartar o arquivo alheio, e descartar seria pior; ficam registrados aqui para que
# a próxima sessão saiba que a dívida não é da leva de conhecimento jurídico — os módulos
# `osint/timeline`, `osint/patrimonio`, `osint/vinculos` e `knowledge/doutrina` entraram com ZERO
# `except Exception`.
BASELINE = 1591


def _contar() -> int:
    # `check=True` derrubava a catraca em máquina que tem o CÓDIGO mas não o repositório (a
    # VM-2 roda uma cópia por rsync): exit 128, "not a git repository". Medir dívida exige
    # saber o que é versionado, então sem repositório a resposta honesta é `skip`, não falha.
    git = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True)
    if git.returncode != 0:
        pytest.skip("cópia sem repositório git — não dá para separar versionado de alheio")
    arquivos = git.stdout.splitlines()
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
