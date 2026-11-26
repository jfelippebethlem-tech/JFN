# -*- coding: utf-8 -*-
"""E9 `elegibilidade` — invariante 3 do plano mestre v2 (§3.10): **sem elegibilidade, não há detector** (O4.7).

⚖️ SOMBRA. Nenhum detector lê isto até o ✅ do dono no lote jurídico (O4.10): a tabela é gravada, medida e
comparada com a régua de hoje; o E10 só passa a lê-la depois da aprovação.

Para cada item — OB do SIAFE, OB do espelho TFE, contratação (TCE-RJ, SIGA, PNCP da Prefeitura, `contratos`) —
calcula UMA vez os fatos jurídico-contábeis com as funções puras do domínio:
  · regime por contrato ............ `dominio.regime.regime_contrato` (O4.4)
  · natureza do pagamento .......... `dominio.pagamento.natureza_pagamento` (O4.6; cadeia OB → NL → NE)
  · origem do exercício ............ `dominio.pagamento.origem_exercicio` (corrente / RP / DEA)
  · teto de dispensa ............... `limites_dispensa.teto_dispensa(lei=, ente=, data_fato=)` (O4.5)
  · pago ........................... `dominio.pagamento.ob_paga_sql` (= `cruzamentos_intel._ob_paga`, invariante 1)
  · natureza do credor ............. natureza jurídica da Receita (`entidades_gov.eh_administracao_publica`), nunca
                                     pelo nome; a peneira por nome de hoje (`classificador_credor`) fica gravada em
                                     `motivo_legado` só para a comparação
e, a partir deles, o veredito de cada EXIGÊNCIA (`universo`, `fornecedor`, `execucao`, `soma_art75`, `valor_liquido`, `regime`,
`dispensa_valor`): 'E' (elegível), 'I:<MOTIVO>' (inelegível) ou '?:<MOTIVO>' (indeterminado — nunca lido como
elegível; INDISPONÍVEL ≠ 0). Cada detector de domínio de contratação do `config/qualidade_detectores.yaml` declara
em `DETECTORES` que exigência faz em cada unidade; a visão `dominio.v_elegibilidade_detector` devolve
`elegivel` + `motivo` por (detector, item).

Onde grava (ADR-001, linha D9): PostgreSQL `jfn_evidencias`, schema `dominio` (deploy/vm2/postgres/dominio_001.sql).
Escritor único = este estágio. Lê a coleta bruta (D4) SEMPRE em modo só-leitura (`mode=ro&immutable=1`): na parada
de obras, o snapshot de 24/11/2026; depois, a cópia que o E15 exportar. Nunca escreve no `compliance.db`.

Idempotente pela chave natural: OB = `ug|numero_ob|exercicio`; contratação = a chave natural da fonte. A linha
carrega `entrada_hash` (hash do que foi decidido + versão): reexecução sobre a mesma entrada altera 0 linha.

Efeito conferido (`efeito`, em outro processo): recontagem no PG das linhas do escopo com a versão corrente =
declaradas, E uma amostra sorteada no PG recalculada do zero a partir da fonte (consulta por chave) bate exigência
por exigência.

CLI:
    python -m compliance_agent.aplicacao.estagios.elegibilidade schema aplicar|verificar
    python -m compliance_agent.aplicacao.estagios.elegibilidade materializar --unidade ob_siafe [--exercicio 2025]
           [--fonte <compliance.db só-leitura>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.dominio.contrato_id import contrato_id
from compliance_agent.dominio.pagamento import (NaturezaPagamento, OrigemExercicio, natureza_pagamento, ob_paga_sql,
                                                origem_exercicio)
from compliance_agent.dominio.regime import Regime, lei_declarada, regime_contrato
from compliance_agent.entidades_gov import eh_administracao_publica
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.limites_dispensa import situacao_no_teto, teto_dispensa, teto_para_valor
from compliance_agent.pericia_contabil import situacao_devolucao
from compliance_agent.siafe_gd import devolvido_por_ob

VERSAO = "e9-sombra-5"   # 2: credor = código de UG (UG_PROPRIA) e inscrição genérica do SIAFE
# 3 (decisões do dono, 24/11/2026 noite — o53-paridade-fatia2.md): OB com GD sem valor apurado =
#   `?:DEVOLUCAO_NAO_APURADA` nas exigências que dependem do valor LÍQUIDO (`valor_liquido`, nova, e `soma_art75`);
#   OS/OSC (natureza 3xxx) = fornecedor com regime próprio, `I:REGIME_PROPRIO_MROSC` em `soma_art75` e
#   `dispensa_valor`; RJPREV = `I:ENTE_PUBLICO` pela RAIZ do CNPJ (`ENTE_PUBLICO_POR_RAIZ`), nunca pelo nome
# 4 (decisões delegadas, 24/11/2026 — ~/vault/refatoracao/decisoes-delegadas-20261124.md): E9-9 — os testes
#   contábeis OB × NL exigem `universo`/`registro_liquido` (integridade do registro, Lei 4.320 art. 62, todo
#   credor); E9-1/E9-2 — ente público e UG própria em `execucao` só são `I` com a natureza provada (folha,
#   tributo, transferência, indenização), senão `?` (art. 141 da 14.133 não exclui contratado público); E9-5 —
#   ordem cronológica (14.133 art. 141) exige `execucao_14133` (OS/OSC fora: Lei 13.019 art. 84 / Lei 9.637);
#   D11 — a declaração da 13.303 por ≥ 50% das diretas da unidade é só indício: não decide regime nem teto
# 5 (O4.10, decisões delegadas — ~/vault/refatoracao/RELATORIO-JURIDICO-UNICO-20261124.md): D5 — transferência
#   a entidade sem fins lucrativos sem instrumento conhecido (mod. 50 + el. 41/43) é `?:TRANSFERENCIA_INSTRUMENTO`
#   em `fornecedor`/`execucao`; D7 — el. 37 sem vínculo é INDETERMINADO (`?` em `execucao`), mas segue
#   `I:SERVICO_CONTINUO` na `soma_art75`; D9/D10 — teto em faixa: o valor decide quando a resposta é a mesma
#   sob todos os tetos possíveis
RAIZ = Path(__file__).resolve().parents[3]
SQL_SCHEMA = RAIZ / "deploy" / "vm2" / "postgres" / "dominio_001.sql"
REGISTRO_DETECTORES = RAIZ / "config" / "qualidade_detectores.yaml"
ESQUEMA_PADRAO = "dominio"
ENV_ESQUEMA = "JFN_DOMINIO_ESQUEMA"
ENV_FONTE = "JFN_ELEGIBILIDADE_FONTE"
FONTE_PARADA = Path.home() / "snapshot-20261124" / "compliance.db"     # universo de paridade da parada de obras
_RX_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# ── unidades e exigências ─────────────────────────────────────────────────────────────────────────────────────
UNIDADES_OB = ("ob_siafe", "ob_tfe")
UNIDADES_CONTRATO = ("contrato_tcerj", "compra_direta_tcerj", "contrato_siga", "contrato_pcrj", "contrato_rules")
UNIDADES = UNIDADES_OB + UNIDADES_CONTRATO
NAO_MATERIALIZADAS = {"ne_siafe": "nota de empenho (ne_siafe/cge_ne_credor): a unidade NE entra com a coleta de NE "
                                  "por UG (O4.11); até lá o detector fica INDISPONÍVEL na E9"}
EXIGES_OB = ("universo", "fornecedor", "execucao", "soma_art75", "valor_liquido", "registro_liquido", "execucao_14133")
EXIGES_CONTRATO = ("universo", "fornecedor", "regime", "dispensa_valor")

# Tabelas BRUTAS de OB/contrato: o que define "domínio de contratação" no registro e o que a catraca Tier 1 procura.
TABELAS_BRUTAS = ("ob_orcamentaria_siafe", "ordens_bancarias", "contratos_tcerj", "compras_diretas_tcerj",
                  "siga_contratos", "pcrj_contratos", "contrato_aditivo", "contratos", "favorecido_resumo",
                  "despesa_execucao", "siafe_fracionamento", "ne_siafe", "nl_siafe", "cge_ne_credor")

GESTAO = (date(2025, 1, 1), None)            # couto.*: gestão (desde 23/03/2026) + o ano anterior de comparação
RECENTE_90D = (date(2026, 8, 26), None)      # rules.ob_*: "OB recente (janela de 90 dias)" contada do snapshot

# detector → {unidade: exigência} (+ janela de data do fato). Cobre TODO detector do registro cuja `fonte` cruza
# TABELAS_BRUTAS (teste: tests/test_estagio_elegibilidade.py::test_todo_detector_de_contratacao_tem_exigencia).
DETECTORES: dict[str, dict] = {
    "anomalias": {"ob_tfe": "fornecedor"},
    "cge_confronto": {"ob_siafe": "universo"},
    "competencia_futura": {"ob_siafe": "execucao"},
    "couto.D01": {"compra_direta_tcerj": "fornecedor", "contrato_tcerj": "fornecedor", "janela": GESTAO},
    "couto.D02": {"compra_direta_tcerj": "fornecedor", "contrato_tcerj": "fornecedor", "janela": GESTAO},
    "couto.D03": {"ob_siafe": "fornecedor", "janela": GESTAO},
    "couto.D04": {"ob_siafe": "fornecedor", "contrato_tcerj": "fornecedor", "janela": GESTAO},
    "couto.D05": {"ob_siafe": "fornecedor", "janela": GESTAO},
    "couto.D06": {"contrato_pcrj": "regime", "janela": GESTAO},
    "couto.D07": {"ob_siafe": "soma_art75", "janela": GESTAO},
    "couto.D08": {"ob_siafe": "universo", "contrato_tcerj": "universo", "janela": GESTAO},
    "couto.D09": {"ob_siafe": "fornecedor", "janela": (date(2026, 3, 16), date(2026, 3, 22))},
    "couto.D10": {"ob_siafe": "fornecedor", "ob_tfe": "fornecedor", "janela": GESTAO},
    "couto.D13": {"ob_siafe": "fornecedor", "janela": GESTAO},
    "couto.D14": {"ob_siafe": "fornecedor", "janela": GESTAO},
    "couto.D15": {"ob_siafe": "fornecedor", "janela": GESTAO},
    "couto.D17": {"compra_direta_tcerj": "fornecedor", "janela": (date(2026, 1, 1), None)},
    "couto.D18": {"ob_siafe": "fornecedor", "janela": GESTAO},
    "couto.D20": {"ob_siafe": "universo", "janela": GESTAO},
    "dea_recorrente": {"ne_siafe": "universo"},
    "det.C9TacFornecedor": {"ob_tfe": "fornecedor"},
    "det.P4Fracionamento": {"compra_direta_tcerj": "dispensa_valor", "ob_tfe": "soma_art75"},
    "det.P7DiretaDeRisco": {"ne_siafe": "universo"},
    "det.X1CrescimentoAditivo": {"contrato_pcrj": "regime"},
    "det.X2ProrrogacaoPerpetua": {"contrato_pcrj": "regime"},
    "det.X3ExecucaoFinanceira": {"ob_siafe": "execucao"},
    "det.X7ReequilibrioIndevido": {"contrato_pcrj": "regime"},
    "det.X8AditivoRetroativo": {"contrato_pcrj": "regime"},
    "duplicidade_competencia": {"ob_siafe": "execucao"},
    "iss_nao_retido": {"ob_siafe": "execucao"},
    "empresa_fantasma": {"ob_tfe": "fornecedor"},
    "fachada_doubt": {"ob_tfe": "fornecedor"},
    "fracionamento_emergencia": {"compra_direta_tcerj": "fornecedor"},
    "fracionamento_siafe": {"ob_siafe": "soma_art75", "compra_direta_tcerj": "dispensa_valor"},
    "intel.aditivos_estouro": {"contrato_pcrj": "regime"},
    "pcrj.d11_aditivo_estourado": {"contrato_pcrj": "regime"},
    "intel.capital_incompativel": {"ob_siafe": "fornecedor"},
    "intel.comunidades": {"ob_siafe": "fornecedor"},
    "intel.concentracao_municipio": {"contrato_pcrj": "fornecedor"},
    "intel.corrida_dezembro": {"ob_siafe": "fornecedor"},
    "intel.empresa_fenix": {"ob_siafe": "fornecedor"},
    "intel.fornecedor_dependente": {"ob_siafe": "fornecedor"},
    "intel.fracionamento": {"ob_siafe": "soma_art75"},
    "intel.grafo_familias": {"ob_siafe": "fornecedor"},
    "intel.hub_compartilhado": {"ob_siafe": "fornecedor"},
    "intel.perdedoras_contumazes": {"ob_siafe": "fornecedor"},
    "intel.porta_giratoria": {"ob_siafe": "fornecedor"},
    "intel.radar_risco": {"ob_siafe": "fornecedor"},
    "intel.sancionadas_contratadas": {"ob_siafe": "fornecedor"},
    "intel.sancionadas_municipio": {"contrato_pcrj": "fornecedor"},
    "intel.socio_oculto": {"ob_siafe": "fornecedor"},
    "intel.socio_servidor": {"ob_siafe": "fornecedor"},
    "conluio_participacao": {"ob_siafe": "fornecedor"},
    "ninho_sala": {"ob_siafe": "fornecedor"},
    "ordem_cronologica": {"ob_siafe": "execucao_14133"},     # art. 141: contrato da 14.133 (E9-5)
    "pericia_contabil": {"ob_siafe": "execucao", "contrato_tcerj": "regime"},
    "vinculo_ob_contrato": {"ob_siafe": "execucao", "contrato_tcerj": "universo"},
    "rules.cnpj_abertura_recente_contrato": {"contrato_rules": "fornecedor"},
    "rules.empresa_parente": {"contrato_rules": "fornecedor"},
    "rules.engine": {"contrato_rules": "fornecedor", "ob_tfe": "fornecedor"},
    "rules.fracionamento_contrato": {"contrato_rules": "dispensa_valor"},
    "rules.ob_empresa_nova": {"ob_tfe": "fornecedor", "janela": RECENTE_90D},
    "rules.ob_favorecido_doerj_cruzado": {"ob_tfe": "fornecedor", "janela": RECENTE_90D},
    "rules.ob_favorecido_multiplas_ugs": {"ob_tfe": "fornecedor", "janela": RECENTE_90D},
    "rules.ob_fracionamento": {"ob_tfe": "soma_art75", "janela": RECENTE_90D},
    "rules.ob_sem_processo_sei": {"ob_tfe": "fornecedor", "janela": RECENTE_90D},
    "rules.ob_valor_redondo": {"ob_tfe": "fornecedor", "janela": RECENTE_90D},
    "tools.contrato_acima_do_porte": {"contrato_tcerj": "fornecedor"},
    "tools.porte_declarado_certame": {"ob_siafe": "fornecedor"},
    "tools.porte_incompativel": {"ob_siafe": "fornecedor"},
    "orcamento.pg03_dea_recorrente": {"ob_siafe": "universo", "ne_siafe": "universo"},
    "orcamento.pg09_empenho_dezembro": {"ne_siafe": "universo"},
    "orcamento.pg10_ordem_cronologica": {"ob_siafe": "execucao_14133"},
    # E9-9: integridade do registro contábil (Lei 4.320 art. 62; RJ Lei 287/1979 arts. 83 e 93) vale para TODO credor
    "a_portar.lex_fatos.c_ob_antes_da_nl": {"ob_siafe": "universo"},
    "a_portar.lex_fatos.c_pago_maior_que_nl": {"ob_siafe": "registro_liquido"},
    "a_portar.p4_obra_e_lei_8666_tcerj": {"compra_direta_tcerj": "dispensa_valor"},
    "a_portar.p5_dedup_por_processo": {"compra_direta_tcerj": "fornecedor"},
    # E10 (O5.3 fatia 1): as quatro regras a_portar acima, portadas como detectores genéricos (mesma exigência)
    "e10.p4_fracionamento_objeto": {"compra_direta_tcerj": "dispensa_valor"},
    "e10.p5_emergencia_recorrente": {"compra_direta_tcerj": "fornecedor"},
    "e10.ob_paga_acima_liquidado": {"ob_siafe": "registro_liquido"},   # E9-9: todo credor, pelo valor líquido
    "e10.ob_antes_da_liquidacao": {"ob_siafe": "universo"},            # E9-9: todo credor
    # E10 (O5.3 fatia 2): mesma exigência da regra de origem (couto.D*, fracionamento_siafe), sem a janela — a
    # data de corte é parâmetro do detector (lente Couto = governo_couto.INICIO)
    "e10.candidato_p4_siafe": {"ob_siafe": "soma_art75"},
    "e10.tg_direta_salto": {"compra_direta_tcerj": "fornecedor", "contrato_tcerj": "fornecedor"},
    "e10.tg_emergencial_incumbente": {"compra_direta_tcerj": "fornecedor", "contrato_tcerj": "fornecedor"},
    "e10.tg_concentracao": {"ob_siafe": "fornecedor"},
    "e10.tg_pico_vespera": {"ob_siafe": "fornecedor"},
    "e10.tg_credor_estreante": {"ob_siafe": "fornecedor", "ob_tfe": "fornecedor"},
    "e10.tg_ob_anulada": {"ob_siafe": "universo"},
    "e10.tg_tac_aceleracao": {"ob_siafe": "fornecedor"},      # o TAC lê o veredito do credor na OB paga dele
    "e10.c_sede_fachada": {"ob_siafe": "fornecedor"},
    # emendas: o objeto É a transferência (PIX, convênio) — a exigência é o universo, não o fornecedor
    "emendas.D1": {"ob_siafe": "universo"},
    "emendas.D2": {"ob_siafe": "universo"},
    "emendas.D3": {"ob_siafe": "universo"},
    "emendas.D4": {"ob_siafe": "universo"},
    "emendas.D5": {"ob_siafe": "universo"},
    "emendas.D6": {"ob_siafe": "universo"},
    "est.aditivo_teto": {"contrato_tcerj": "regime"},
    "est.valor_excedido": {"ob_siafe": "execucao", "contrato_tcerj": "universo"},
    "padrao.atesto_antes_do_periodo": {"ob_siafe": "execucao"},
    "padrao.beneficio_para_conta_do_orgao": {"ob_siafe": "universo"},    # o alvo é o benefício pago ao órgão
    "padrao.despesa_estranha_ao_objeto": {"ob_siafe": "execucao"},
    "padrao.gestor_recebe_da_osc": {"ob_siafe": "universo"},
    "padrao.mrosc_atesto_contra_relatorio": {"ob_siafe": "execucao"},
    "padrao.mrosc_execucao_igual_limiar": {"ob_siafe": "execucao"},
    "padrao.ob_antes_da_entrega": {"ob_siafe": "execucao"},
    "padrao.reserva_tecnica_multiplicada": {"ob_siafe": "execucao"},
    "pcrj.d7_fracionamento": {"contrato_pcrj": "dispensa_valor"},
    "pcrj.d8_credor_recem_aberto": {"contrato_pcrj": "fornecedor"},
    "pcrj.d9_socio_na_folha": {"contrato_pcrj": "fornecedor"},
    "pcrj.d10_rede_concorrentes": {"contrato_pcrj": "fornecedor"},
    "pcrj.d12_coendereco_concorrentes": {"contrato_pcrj": "fornecedor"},
    # a `fonte` do registro não cita tabela bruta, mas o módulo lê (achado pela catraca Tier 1)
    "lex.redflags": {"ob_siafe": "fornecedor", "contrato_siga": "fornecedor"},
    "retro.lift": {"ob_siafe": "fornecedor"},
}


def exiges_do_detector(detector: str) -> dict[str, str]:
    return {u: x for u, x in DETECTORES[detector].items() if u != "janela"}


def detectores_de_contratacao(registro: dict) -> list[str]:
    """Detectores do registro cuja `fonte` cita uma tabela bruta de OB/contrato (o domínio da E9)."""
    out = []
    for nome, d in registro.items():
        fontes = {re.split(r"[\s(]", str(f).strip(), maxsplit=1)[0] for f in (d.get("fonte") or [])}
        if fontes & set(TABELAS_BRUTAS) or any("contrata" in str(f) and "via chamador" in str(f)
                                               for f in (d.get("fonte") or [])):
            out.append(nome)
    return sorted(out)


def carregar_registro() -> dict:
    import yaml
    return yaml.safe_load(REGISTRO_DETECTORES.read_text(encoding="utf-8"))["detectores"]


# ══ parte pura: fatos → veredito por exigência ═════════════════════════════════════════════════════════════════
@dataclass
class Fatos:
    """O que a E9 decidiu sobre UM item. Campos None = não se sabe (nunca lido como False)."""
    unidade: str
    chave: str
    ug: str | None = None
    numero_ob: str | None = None
    exercicio: int | None = None
    contrato_id: str | None = None
    data_fato: date | None = None
    valor: float | None = None
    paga: bool | None = None
    credor_classe: str = "SEM_DOC"
    credor_raiz: str | None = None
    natureza_juridica: str | None = None
    natureza_despesa: str | None = None
    vinculo_contrato: bool | None = None
    natureza_pagamento: str | None = None
    nao_e_contratacao_nova: bool | None = None
    credor_e_fornecedor: bool | None = None
    natureza_fonte: str = ""
    origem_exercicio: str | None = None
    exercicio_origem: int | None = None
    origem_fonte: str = ""
    regime: str | None = None
    regime_fonte: str = ""
    dispensa_valor: bool | None = None
    teto: float | None = None
    teto_fonte: str = ""
    motivo_legado: str = ""
    tem_par_siafe: bool | None = None       # só ob_tfe
    elemento: str | None = None
    # '' (sem devolução) · 'apurada' (GD com valor na `gd_siafe`) · 'nao_apurada' (GD na OB sem a guia coletada).
    # Não é coluna do PG: o fato vai no veredito (`?:DEVOLUCAO_NAO_APURADA`) e, por ele, no `entrada_hash`.
    devolucao: str = ""

    def exiges(self) -> dict[str, str]:
        if self.unidade in UNIDADES_OB:
            return {x: _AVALIA_OB[x](self) for x in EXIGES_OB}
        return {x: _AVALIA_CT[x](self) for x in EXIGES_CONTRATO}


# Ente público do ESTADO cuja natureza jurídica na Receita é de direito privado — decidido pela RAIZ do CNPJ (o nome
# nunca decide). Decisão do dono 24/11/2026 (o53-paridade-fatia2.md, decisão 2): "RJPREV é autarquia previdenciária
# do Estado: I:ENTE_PUBLICO". Medido no snapshot de 24/11: 17713878 (Fundação de Previdência Complementar do ERJ —
# RJPREV, Lei estadual 6.243/2012) está na Receita como 3069 (fundação privada) e caía em OS_OSC; 48307566 (Plano
# de Benefícios RJPREV CD, o plano que ela administra) como 3328. Só entra raiz conferida na fonte, uma a uma.
ENTE_PUBLICO_POR_RAIZ = {
    "17713878": "RJPREV — Fundação de Previdência Complementar do ERJ (Receita: 3069); decisão do dono 24/11/2026",
    "48307566": "Plano de Benefícios RJPREV CD, administrado pela RJPREV (Receita: 3328); decisão do dono 24/11/2026",
}


def classe_credor(doc, natureza_por_raiz: dict) -> tuple[str, str | None, str | None]:
    """(classe, raiz do CNPJ, natureza jurídica). Pela Receita (ou pelo formato do código do SIAFE), nunca pelo nome;
    a raiz de `ENTE_PUBLICO_POR_RAIZ` vence a natureza da Receita. PF não guarda documento."""
    bruto = str(doc or "").strip()
    d = re.sub(r"\D", "", bruto)
    if len(d) == 6 and bruto == d:
        return "UG_PROPRIA", None, None        # credor = código de UG do SIAFE: unidade do próprio Estado (repasse,
        #   contribuição previdenciária ou serviço intraorçamentário, modalidade 91 — PRODERJ, Santa Cabrini: E9-2)
    if re.fullmatch(r"[A-Z]{2}\d{7}", bruto):
        return "INSCRICAO_GENERICA", None, None  # CG/RP/PP…: inscrição genérica do SIAFE (folha, lista de credores)
    if len(d) == 14:
        nj = natureza_por_raiz.get(d[:8]) or None
        if d[:8] in ENTE_PUBLICO_POR_RAIZ:
            return "ENTE_PUBLICO", d[:8], nj
        if not nj:
            return "PJ_SEM_CADASTRO", d[:8], None
        if eh_administracao_publica(nj):
            return "ENTE_PUBLICO", d[:8], nj
        return ("OS_OSC" if nj.startswith("3") else "PJ_PRIVADA"), d[:8], nj
    if len(d) == 11:
        return "PF", None, None
    return "SEM_DOC", None, None


def _privado(f: Fatos) -> bool:
    return f.credor_classe in ("PJ_PRIVADA", "OS_OSC")


def _tributo_ou_divida(f: Fatos) -> bool:
    return (f.natureza_pagamento == NaturezaPagamento.INDETERMINADO.value and bool(f.nao_e_contratacao_nova)
            and f.credor_e_fornecedor is False)


def _sem_natureza(f: Fatos) -> str:
    if f.unidade == "ob_tfe" and not f.tem_par_siafe:
        return "?:TFE_SEM_PAR_SIAFE"
    return "?:SEM_NE" if not f.natureza_despesa else "?:SEM_VINCULO"


def _ob_universo(f: Fatos) -> str:
    return "E"


def _ob_fornecedor(f: Fatos) -> str:
    """Pagamento a FORNECEDOR (sanção, fênix, porte, concentração, sócio…): fora o ente público, a folha, o tributo e a
    transferência sem contraprestação; OS/OSC fica (credor_e_fornecedor). Pela natureza do credor na Receita."""
    if f.unidade == "ob_tfe" and f.tem_par_siafe is False and f.credor_classe not in ("ENTE_PUBLICO", "UG_PROPRIA"):
        return "?:TFE_SEM_PAR_SIAFE"
    if f.paga is False:
        return "I:NAO_PAGA"
    if f.credor_classe in ("ENTE_PUBLICO", "UG_PROPRIA"):
        return "I:" + f.credor_classe
    nat = f.natureza_pagamento
    if nat == NaturezaPagamento.FOLHA_BENEFICIO.value:
        return "I:FOLHA_BENEFICIO"
    if _tributo_ou_divida(f):
        return "I:TRIBUTO_DIVIDA"
    if nat == NaturezaPagamento.TRANSFERENCIA.value and f.credor_e_fornecedor is False:
        return "I:TRANSFERENCIA"
    if nat == NaturezaPagamento.TRANSFERENCIA.value and f.credor_e_fornecedor is None:
        return "?:TRANSFERENCIA_INSTRUMENTO"     # D5 (O4.10): parceria MROSC ou descentralização escolar (AAE)
    if f.credor_e_fornecedor or _privado(f):
        return "E"
    if f.credor_classe == "PF":
        return "?:PF_SEM_NE"
    if f.credor_classe in ("PJ_SEM_CADASTRO", "INSCRICAO_GENERICA"):
        return "?:CREDOR_SEM_CADASTRO" if f.credor_classe == "PJ_SEM_CADASTRO" else "?:INSCRICAO_GENERICA"
    return "?:SEM_DOC"


def _ob_execucao(f: Fatos) -> str:
    """Pagamento de EXECUÇÃO de contrato (duplicidade de competência, ordem cronológica, ISS, devido × pago).
    Ente público / UG própria (E9-1/E9-2, decisão delegada 24/11/2026): o art. 141 da 14.133 não exclui o contratado
    público (art. 75 IX) — só sai com a natureza PROVADA de não contrato (folha, tributo, transferência, indenização);
    sem ela, INDETERMINADO, nunca inelegível."""
    if f.unidade == "ob_tfe" and not f.tem_par_siafe:
        return "?:TFE_SEM_PAR_SIAFE"
    if f.paga is False:
        return "I:NAO_PAGA"
    nat = f.natureza_pagamento
    if f.credor_classe in ("ENTE_PUBLICO", "UG_PROPRIA"):
        if nat == NaturezaPagamento.FOLHA_BENEFICIO.value:
            return "I:FOLHA_BENEFICIO"
        if _tributo_ou_divida(f):
            return "I:TRIBUTO_DIVIDA"
        if nat in (NaturezaPagamento.TRANSFERENCIA.value, NaturezaPagamento.INDENIZACAO.value):
            return "I:" + nat
        if nat == NaturezaPagamento.CONTRATACAO_NOVA.value:
            return "I:SEM_CONTRATO"
        return "?:" + f.credor_classe
    if nat == NaturezaPagamento.FOLHA_BENEFICIO.value:
        return "I:FOLHA_BENEFICIO"
    if _tributo_ou_divida(f):
        return "I:TRIBUTO_DIVIDA"
    if nat == NaturezaPagamento.INDENIZACAO.value:
        return "I:INDENIZACAO"
    if nat == NaturezaPagamento.TRANSFERENCIA.value:
        if f.credor_e_fornecedor is None:
            return "?:TRANSFERENCIA_INSTRUMENTO"                          # D5 (O4.10)
        return "E" if f.credor_e_fornecedor else "I:TRANSFERENCIA"      # contrato de gestão (OS/OSC) é contrato
    if nat == NaturezaPagamento.PARCELA_CONTRATO.value:
        return "E"
    if nat == NaturezaPagamento.CONTRATACAO_NOVA.value:
        return "I:SEM_CONTRATO"
    return _sem_natureza(f)


def _ob_soma_art75(f: Fatos) -> str:
    """Soma do art. 75 §1º (fracionamento / dispensa acima do teto sobre OB): só CONTRATAÇÃO NOVA entra. Ficam fora
    transferência, serviço contínuo, parcela de contrato, DEA, ente público, folha, tributo e indenização (§4.5)."""
    if f.unidade == "ob_tfe" and not f.tem_par_siafe:
        return "?:TFE_SEM_PAR_SIAFE"
    if f.paga is False:
        return "I:NAO_PAGA"
    if f.credor_classe in ("ENTE_PUBLICO", "UG_PROPRIA"):
        return "I:" + f.credor_classe
    if f.credor_classe == "OS_OSC":
        return "I:REGIME_PROPRIO_MROSC"        # Lei 13.019 / contrato de gestão: fora do art. 75 da 14.133
    if f.origem_exercicio == OrigemExercicio.DEA.value:
        return "I:DEA"
    nat = f.natureza_pagamento
    if nat == NaturezaPagamento.FOLHA_BENEFICIO.value:
        return "I:FOLHA_BENEFICIO"
    if _tributo_ou_divida(f):
        return "I:TRIBUTO_DIVIDA"
    if nat == NaturezaPagamento.TRANSFERENCIA.value:
        return "I:TRANSFERENCIA"
    if nat == NaturezaPagamento.INDENIZACAO.value:
        return "I:INDENIZACAO"
    if nat == NaturezaPagamento.PARCELA_CONTRATO.value:
        return "I:SERVICO_CONTINUO" if f.elemento == "37" else "I:PARCELA_CONTRATO"
    if f.elemento == "37" and nat == NaturezaPagamento.INDETERMINADO.value and f.nao_e_contratacao_nova:
        return "I:SERVICO_CONTINUO"      # D7 (O4.10): sem vínculo conferido, mas locação de mão de obra é contínua
    if nat == NaturezaPagamento.CONTRATACAO_NOVA.value:
        return "?:DEVOLUCAO_NAO_APURADA" if f.devolucao == "nao_apurada" else "E"
    return _sem_natureza(f)


def _ob_valor_liquido(f: Fatos) -> str:
    """Régua que depende do valor LÍQUIDO da OB (pago × liquidado): a de execução, e a OB com Guia de Devolução sem
    valor apurado fica INDETERMINADA — o pago é a OB pelo valor cheio; a devolução é outra entrada, e sem o valor
    dela a régua não se infla nem se zera (decisão do dono 1, 24/11/2026)."""
    v = _ob_execucao(f)
    if v == "E" and f.devolucao == "nao_apurada":
        return "?:DEVOLUCAO_NAO_APURADA"
    return v


def _ob_registro_liquido(f: Fatos) -> str:
    """Integridade do REGISTRO contábil OB × NL pelo valor líquido (E9-9, decisão delegada 24/11/2026): a regra
    "pagamento só após a regular liquidação" (Lei 4.320 art. 62; Lei RJ 287/1979 arts. 83 e 93) vale para TODA
    despesa orçamentária, qualquer que seja o credor — ente público, UG, folha e transferência incluídos. Só a OB
    com Guia de Devolução sem valor apurado fica INDETERMINADA (decisão do dono 1: o líquido não se infla nem se
    zera). O peso do achado (fornecedor × repasse) é do consumidor, não da elegibilidade."""
    return "?:DEVOLUCAO_NAO_APURADA" if f.devolucao == "nao_apurada" else "E"


def _ob_execucao_14133(f: Fatos) -> str:
    """Execução de contrato da 14.133 (ordem cronológica, art. 141): a de execução, e OS/OSC fora — contrato de
    gestão (Lei 9.637) e parceria MROSC (Lei 13.019 art. 84) não são contrato de fornecimento/serviço/obra (E9-5)."""
    v = _ob_execucao(f)
    if v == "E" and f.credor_classe == "OS_OSC":
        return "I:REGIME_PROPRIO_MROSC"
    return v


def _ct_universo(f: Fatos) -> str:
    return "E"


def _ct_fornecedor(f: Fatos) -> str:
    if f.credor_classe == "ENTE_PUBLICO":
        return "I:ENTE_PUBLICO"
    if _privado(f) or f.credor_classe == "PF":
        return "E"
    if f.credor_classe == "PJ_SEM_CADASTRO":
        return "?:CREDOR_SEM_CADASTRO"
    return "?:SEM_CNPJ"


def _ct_regime(f: Fatos) -> str:
    if f.regime in (None, Regime.INDETERMINADO.value):
        return "?:REGIME_INDETERMINADO"
    if f.regime == Regime.OUTRO.value:
        return "?:REGIME_OUTRO"
    return "E"


def _ct_dispensa_valor(f: Fatos) -> str:
    if f.credor_classe == "OS_OSC":
        return "I:REGIME_PROPRIO_MROSC"        # OS/OSC: regime próprio (Lei 13.019), fora da dispensa da 14.133
    if f.dispensa_valor is None:
        return "?:MODALIDADE_DESCONHECIDA"
    if not f.dispensa_valor:
        return "I:NAO_DISPENSA_VALOR"
    if f.credor_classe == "ENTE_PUBLICO":
        return "I:ENTE_PUBLICO"
    if f.regime == Regime.L13979_COVID.value:
        return "I:COVID_SEM_TETO"
    if f.regime == Regime.OUTRO.value:
        return "I:REGIME_OUTRO"
    if f.regime in (None, Regime.INDETERMINADO.value):
        return "?:REGIME_INDETERMINADO"
    if f.teto is None:
        return "?:TETO_INDETERMINADO"
    return "E"


_AVALIA_OB = {"universo": _ob_universo, "fornecedor": _ob_fornecedor, "execucao": _ob_execucao,
              "soma_art75": _ob_soma_art75, "valor_liquido": _ob_valor_liquido,
              "registro_liquido": _ob_registro_liquido, "execucao_14133": _ob_execucao_14133}
_AVALIA_CT = {"universo": _ct_universo, "fornecedor": _ct_fornecedor, "regime": _ct_regime,
              "dispensa_valor": _ct_dispensa_valor}


# ══ adaptador da coleta bruta (SQLite só-leitura) ══════════════════════════════════════════════════════════════
def _data(s) -> date | None:
    s = str(s or "").strip()
    if not s:
        return None
    for fmt, corte in (("%d/%m/%Y", 10), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:corte], fmt).date()
        except ValueError:
            continue
    return None


_RX_INC = re.compile(r"(?i:art)\.?\s*(75|24|29)º?[\s,.\-]*(?i:inciso|inc\.?)?\s*(?<![IVXivx])(II|I)(?![A-Za-z])")


def inciso_dispensa_valor(texto) -> str | None:
    """'I' (obras) ou 'II' (compras) se o fundamento é dispensa POR VALOR (14.133 75 I/II; 8.666 24 I/II; 13.303
    29 I/II); 'II' para 'Pequenas Compras'; None se não é (inexigibilidade, emergência, licitação)."""
    t = str(texto or "")
    m = _RX_INC.search(t)
    if m:
        return m.group(2)
    return "II" if "Pequenas Compras" in t else None


def abrir_fonte(caminho: str | Path | None = None) -> sqlite3.Connection:
    """A coleta bruta em SOMENTE LEITURA (`immutable=1`: nem trava, nem WAL — o snapshot não muda)."""
    p = Path(caminho or os.environ.get(ENV_FONTE) or FONTE_PARADA)
    if not p.is_file():
        raise ErroPermanente(f"fonte da E9 ausente: {p}")
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


class Consultas:
    """Tabelas pequenas de apoio (NL→NE, NE, vínculo, natureza jurídica, estatais). `em_lote=True` carrega tudo em
    memória (materialização); False consulta por chave (conferência por amostra do `efeito`)."""

    def __init__(self, con: sqlite3.Connection, em_lote: bool = True):
        from compliance_agent.cruzamentos_intel import classificador_credor
        self.con = con
        self.em_lote = em_lote
        self.natureza = {r[0]: str(r[1] or "") for r in con.execute(
            "SELECT cnpj_basico, natureza_cod FROM empresas_cadastro WHERE natureza_cod IS NOT NULL")}
        self._legado = classificador_credor(con)
        self._cache_legado: dict = {}
        self.estatais = self._estatais()
        self.paga_sql = ob_paga_sql(con)
        # a GD da OB (coluna `gd`/`status_envio`, quando a coleta as tem) e as guias coletadas (`gd_siafe`, 6.780
        # linhas no snapshot: carregadas inteiras nos dois modos — a régua das guias válidas é a de `siafe_gd`)
        cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
        self.cols_gd = ", ".join(c if c in cols else "''" for c in ("gd", "status_envio"))
        self.devolvido = devolvido_por_ob(con)
        if em_lote:
            self.nl = {(r[0], r[1]): r[2] for r in con.execute("SELECT numero, ug_emitente, ne FROM nl_siafe")}
            self.ne = {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
                "SELECT numero, ug_emitente, natureza, ano_ne FROM ne_siafe")}
            self.vinc = {(r[0], r[1]) for r in con.execute(
                "SELECT ob, ug FROM vinculo_ob_contrato WHERE estado='VERIFICADO'")}
            self.cnpj_processo = self._cnpj_por_processo()

    def _estatais(self) -> set[str]:
        """Unidade que cita a 13.303 em ≥ 50% das contratações diretas (n ≥ 5) — decisão D11 PENDENTE do dono (a
        natureza jurídica da UG não está na base). Mesmo corte do relatório O4.4–O4.6."""
        out = set()
        for u, n, k in self.con.execute(
                "SELECT unidade, COUNT(DISTINCT processo), COUNT(DISTINCT CASE WHEN enquadramento_legal LIKE "
                "'%13.303%' OR afastamento LIKE '%13.303%' THEN processo END) FROM compras_diretas_tcerj "
                "GROUP BY unidade"):
            if n >= 5 and k / n >= 0.5 and (u or "").strip():
                out.add(u.strip())
        return out

    def _cnpj_por_processo(self) -> dict:
        """compras_diretas_tcerj só traz o NOME do fornecedor: o CNPJ vem do contrato do mesmo processo (único)."""
        por: dict = {}
        for proc, cnpj in self.con.execute("SELECT processo, cnpj FROM contratos_tcerj WHERE COALESCE(cnpj,'')<>''"):
            por.setdefault(proc, set()).add(re.sub(r"\D", "", cnpj))
        return {p: next(iter(c)) for p, c in por.items() if len(c) == 1}

    def ne_da_nl(self, nl, ug):
        if self.em_lote:
            return self.nl.get((nl, ug))
        r = self.con.execute("SELECT ne FROM nl_siafe WHERE numero=? AND ug_emitente=?", (nl, ug)).fetchone()
        return r[0] if r else None

    def dados_ne(self, ne, ug):
        if self.em_lote:
            return self.ne.get((ne, ug))
        r = self.con.execute("SELECT natureza, ano_ne FROM ne_siafe WHERE numero=? AND ug_emitente=?",
                             (ne, ug)).fetchone()
        return (r[0], r[1]) if r else None

    def vinculado(self, ob, ug) -> bool:
        if self.em_lote:
            return (ob, ug) in self.vinc
        return self.con.execute("SELECT 1 FROM vinculo_ob_contrato WHERE ob=? AND ug=? AND estado='VERIFICADO'",
                                (ob, ug)).fetchone() is not None

    def cnpj_do_processo(self, proc):
        if self.em_lote:
            return self.cnpj_processo.get(proc)
        cs = {re.sub(r"\D", "", r[0]) for r in self.con.execute(
            "SELECT cnpj FROM contratos_tcerj WHERE processo=? AND COALESCE(cnpj,'')<>''", (proc,))}
        return next(iter(cs)) if len(cs) == 1 else None

    def devolvido_da_ob(self, ob, ug) -> float | None:
        """Soma das guias válidas da OB na `gd_siafe` (régua de `siafe_gd.devolvido_por_ob`); None = não se sabe."""
        return self.devolvido.get((str(ob or "").strip(), str(ug or "").strip()))

    def legado(self, nome, doc) -> str:
        k = (nome, doc)
        if k not in self._cache_legado:
            self._cache_legado[k] = self._legado(nome, doc) or ""
        return self._cache_legado[k]


_COLS_OB = ("numero_ob, ug_emitente, ug_liquidante, nl, credor, nome_credor, tipo_ob, valor, exercicio, data_emissao")


def devolucao_ob(gd, status_envio, devolvido: float | None) -> str:
    """'' · 'apurada' · 'nao_apurada' — a GD na OB (`pericia_contabil.situacao_devolucao`, régua única) × a guia
    coletada (`gd_siafe`). Devolução posterior à coleta da OB deixa só a guia: é apurada também."""
    if devolvido is not None:
        return "apurada"
    return "nao_apurada" if situacao_devolucao(gd, status_envio) == "gd" else ""


def _fatos_ob_siafe(r, q: Consultas) -> Fatos:
    numero, ug, ugl, nl_n, credor, nome, tipo_ob, valor, ex, emissao, gd, envio, paga = r
    ne_n = q.ne_da_nl(nl_n, ug) or q.ne_da_nl(nl_n, ugl)
    nat_cod, ano_ne = q.dados_ne(ne_n, ug) or q.dados_ne(ne_n, ugl) or (None, None)
    classe, raiz, nj = classe_credor(credor, q.natureza)
    vinc = True if q.vinculado(numero, ug) else None
    d = natureza_pagamento(natureza_despesa=nat_cod, vinculo_contrato=vinc, natureza_juridica_credor=nj)
    elemento = (nat_cod or "")[4:6] or None
    o = origem_exercicio(tipo_ob=tipo_ob, elemento=elemento, exercicio_ob=ex, exercicio_empenho=ano_ne)
    return Fatos(unidade="ob_siafe", chave=f"{ug}|{numero}|{ex}", ug=ug, numero_ob=numero,
                 exercicio=int(ex) if ex is not None else None, data_fato=_data(emissao),
                 valor=round(float(valor or 0), 2), paga=bool(paga), credor_classe=classe, credor_raiz=raiz,
                 natureza_juridica=nj, natureza_despesa=nat_cod, vinculo_contrato=vinc,
                 natureza_pagamento=d.natureza.value, nao_e_contratacao_nova=d.nao_e_contratacao_nova,
                 credor_e_fornecedor=d.credor_e_fornecedor, natureza_fonte=d.fonte,
                 origem_exercicio=o.origem.value, exercicio_origem=o.exercicio_de_origem, origem_fonte=o.fonte,
                 motivo_legado=q.legado(nome, credor), elemento=elemento,
                 devolucao=devolucao_ob(gd, envio, q.devolvido_da_ob(numero, ug)))


def _sql_ob_siafe(q: Consultas, where: str = "") -> str:
    # ob-qualquer-status: a E9 classifica TODA OB e grava `paga` pelo predicado canônico (a anulada é inelegível
    # por NAO_PAGA, não some — couto.D20 lê justamente as anuladas)
    return (f"SELECT {_COLS_OB}, {q.cols_gd}, CASE WHEN {q.paga_sql} THEN 1 ELSE 0 END "
            f"FROM ob_orcamentaria_siafe {where}")


def _fatos_ob_tfe(r, q: Consultas) -> Fatos:
    numero, ug, ex, doc, nome, valor, emissao = r
    par = q.con.execute(_sql_ob_siafe(q, "WHERE numero_ob=? AND ug_emitente=?"), (numero, ug)).fetchone()
    if par is not None:
        s = _fatos_ob_siafe(par, q)
        f = Fatos(**{**s.__dict__, "unidade": "ob_tfe", "chave": f"{ug}|{numero}|{ex}",
                     "exercicio": int(ex) if ex is not None else None, "tem_par_siafe": True})
    else:
        f = Fatos(unidade="ob_tfe", chave=f"{ug}|{numero}|{ex}", ug=ug, numero_ob=numero,
                  exercicio=int(ex) if ex is not None else None, tem_par_siafe=False,
                  natureza_fonte="OB do espelho TFE sem a OB do SIAFE correspondente (numero_ob + UG): o TFE só "
                                 "serve de confronto (invariante 1)")
    if par is None or re.sub(r"\D", "", str(doc or "")):       # o TFE com documento decide a classe (Receita);
        classe, raiz, nj = classe_credor(doc, q.natureza)       # sem documento, vale a do par do SIAFE
        f.credor_classe, f.credor_raiz, f.natureza_juridica = classe, raiz, nj
    f.data_fato = _data(emissao) or f.data_fato
    f.valor = round(float(valor or 0), 2)
    f.motivo_legado = q.legado(nome, doc)
    return f


def _regime(q: Consultas, unidade_txt, lei_txt, d_ass, dispensa) -> tuple[str, str, bool]:
    """D11 (decisão delegada 24/11/2026): estatal é NATUREZA JURÍDICA (13.303 arts. 3º e 4º), não declaração. A
    unidade que cita a 13.303 em ≥ 50% das diretas é só INDÍCIO: no contrato que não declara a 13.303 o regime fica
    INDETERMINADO (a autarquia que cita a 13.303 por engano mudaria o teto); no que a declara, decide a lei declarada.
    O indício nunca liga `contratante_estatal` nem o teto de estatal."""
    est = (unidade_txt or "").strip() in q.estatais
    if est and "13303" not in lei_declarada(lei_txt):
        return (Regime.INDETERMINADO.value, "unidade com indício de estatal (≥ 50% das diretas citam a 13.303) sem a "
                "natureza jurídica da UG na base e sem a 13.303 declarada neste ato — D11", False)
    dec = regime_contrato(lei_declarada_texto=lei_txt, data_assinatura=d_ass, dispensa_por_valor=dispensa)
    fonte = ("[indício de estatal: a unidade declara a 13.303 — D11] " if est else "") + dec.fonte_da_decisao
    return dec.regime.value, fonte, False


def _teto(regime: str, inciso: str | None, ano, d_fato, estatal: bool,
          valor: float | None = None) -> tuple[float | None, str]:
    """Teto do ato. Na FAIXA (D9/D10, O4.10: exercício partido sem data do fato; 14.065 × dobro) o VALOR decide:
    dentro de todos os tetos possíveis → o menor; acima de todos → o maior; entre eles → None (INDETERMINADO)."""
    if not inciso or regime in (Regime.INDETERMINADO.value, Regime.OUTRO.value):
        return None, ""
    t = teto_dispensa(lei=regime, tipo="obras" if inciso == "I" else "compras", ano=int(ano) if ano else None,
                      data_fato=d_fato, ente="estatal" if estatal else None)
    fonte = (t.ato + (" — " + t.motivo if t.motivo else "")).strip(" —")
    if t.faixa:
        sit = situacao_no_teto(valor, t)
        fonte += (f" [faixa {t.faixa[0]:.2f}–{t.faixa[1]:.2f}: {sit}]")
        return teto_para_valor(valor, t), fonte
    return t.valor, fonte


def _fatos_contrato(unidade, chave, *, q, orgao, lei_txt, ano, d_ass, valor, doc, numero=None) -> Fatos:
    sem_lei = not str(lei_txt or "").strip(" |")
    inc = None if sem_lei else inciso_dispensa_valor(lei_txt)
    dispensa = None if sem_lei else inc is not None
    regime, rfonte, est = _regime(q, orgao, lei_txt, d_ass, True if dispensa else None)
    teto, tfonte = _teto(regime, inc, ano or (d_ass.year if d_ass else None), d_ass, est,
                         round(float(valor), 2) if valor not in (None, "") else None)
    classe, raiz, nj = classe_credor(doc, q.natureza)
    cid = contrato_id(orgao, numero, int(ano) if ano else None) if numero else None
    return Fatos(unidade=unidade, chave=chave, exercicio=int(ano) if ano else (d_ass.year if d_ass else None),
                 contrato_id="|".join(map(str, cid.chave)) if cid else None, data_fato=d_ass,
                 valor=round(float(valor), 2) if valor not in (None, "") else None, credor_classe=classe,
                 credor_raiz=raiz, natureza_juridica=nj, regime=regime, regime_fonte=rfonte,
                 dispensa_valor=dispensa, teto=teto, teto_fonte=tfonte)


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# (sql do lote, sql por chave, construtor) — o filtro de exercício entra no lote quando a fonte tem a coluna
def _fonte_contrato_tcerj(q):
    sql = ("SELECT id, processo, num_contratacao, unidade, criterio_julgamento, ano_processo, data_contratacao, "
           "valor_contrato, cnpj FROM contratos_tcerj")

    def f(r):
        _id, proc, num, uni, crit, ano, dta, valor, cnpj = r
        fa = _fatos_contrato("contrato_tcerj", f"{proc}|{num}", q=q, orgao=uni, lei_txt=None, ano=ano,
                             d_ass=_data(dta), valor=_num(valor), doc=cnpj)
        # o critério de julgamento às vezes declara a lei ("… (Lei nº 8.666/93)"): regime pela declaração
        reg, rf, est = _regime(q, uni, crit, _data(dta), None)
        fa.regime, fa.regime_fonte = reg, rf
        return fa
    return sql, ("processo || '|' || num_contratacao", "ano_processo"), f


def _fonte_compra_direta(q):
    sql = ("SELECT processo, MAX(unidade), MAX(enquadramento_legal) || ' | ' || MAX(afastamento), MAX(ano_processo), "
           "MAX(valor) FROM compras_diretas_tcerj")

    def f(r):
        proc, uni, lei, ano, valor = r
        return _fatos_contrato("compra_direta_tcerj", proc, q=q, orgao=uni, lei_txt=lei or "", ano=ano, d_ass=None,
                               valor=_num(valor), doc=q.cnpj_do_processo(proc))
    return sql, ("processo", "ano_processo", "GROUP BY processo"), f


def _fonte_siga(q):
    sql = "SELECT id_contrato, orgao, COALESCE(fundamento,'') || ' | ' || COALESCE(modalidade,''), data, valor, cnpj " \
          "FROM siga_contratos"

    def f(r):
        _id, org, lei, dta, valor, cnpj = r
        d = _data(dta)
        return _fatos_contrato("contrato_siga", str(_id), q=q, orgao=org, lei_txt=lei, ano=d.year if d else None,
                               d_ass=d, valor=_num(valor), doc=cnpj)
    return sql, ("id_contrato", None), f


def _fonte_pcrj(q):
    sql = ("SELECT numero_controle_pncp, ano, orgao_nome, data_assinatura, COALESCE(valor_global, valor_inicial), "
           "fornecedor_documento FROM pcrj_contratos")

    def f(r):
        ncp, ano, org, dta, valor, doc = r
        return _fatos_contrato("contrato_pcrj", ncp, q=q, orgao=org, lei_txt=None, ano=ano, d_ass=_data(dta),
                               valor=_num(valor), doc=doc)
    return sql, ("numero_controle_pncp", "ano"), f


def _fonte_rules(q):
    sql = "SELECT id, numero, orgao_contrat, modalidade, data_assinatura, valor_total FROM contratos"

    def f(r):
        _id, num, org, mod, dta, valor = r
        d = _data(dta)
        return _fatos_contrato("contrato_rules", f"{org}|{num}", q=q, orgao=org, lei_txt=mod,
                               ano=d.year if d else None, d_ass=d, valor=_num(valor), doc=None, numero=num)
    return sql, ("orgao_contrat || '|' || numero", None), f


_FONTES_CT = {"contrato_tcerj": _fonte_contrato_tcerj, "compra_direta_tcerj": _fonte_compra_direta,
              "contrato_siga": _fonte_siga, "contrato_pcrj": _fonte_pcrj, "contrato_rules": _fonte_rules}


def iterar(unidade: str, q: Consultas, exercicio: int | None = None):
    """Fatos de TODOS os itens da unidade (opcionalmente de um exercício). Chave repetida: vence a última linha."""
    con = q.con
    if unidade == "ob_siafe":
        where, par = ("WHERE exercicio=?", (exercicio,)) if exercicio else ("", ())
        for r in con.execute(_sql_ob_siafe(q, where), par):
            yield _fatos_ob_siafe(r, q)
        return
    if unidade == "ob_tfe":
        where, par = ("WHERE exercicio=?", (exercicio,)) if exercicio else ("", ())
        for r in con.execute("SELECT numero_ob, ug_codigo, exercicio, favorecido_cpf, favorecido_nome, valor, "
                             f"data_emissao FROM ordens_bancarias {where}", par):
            yield _fatos_ob_tfe(r, q)
        return
    if unidade not in _FONTES_CT:
        raise ErroPermanente(f"unidade desconhecida: {unidade}")
    sql, (_, col_ano, *grupo), construir = _FONTES_CT[unidade](q)
    where, par = (f" WHERE {col_ano}=?", (exercicio,)) if exercicio and col_ano else ("", ())
    if exercicio and not col_ano:
        raise ErroPermanente(f"{unidade} não tem exercício na fonte: materialize sem --exercicio")
    for r in con.execute(sql + where + (" " + grupo[0] if grupo else ""), par):
        yield construir(r)


def recalcular(unidade: str, chave: str, q: Consultas) -> Fatos | None:
    """O MESMO cálculo para UMA chave, consultando a fonte por chave (conferência independente do `efeito`)."""
    con = q.con
    if unidade in UNIDADES_OB:
        ug, numero, ex = chave.split("|")
        if unidade == "ob_siafe":
            r = con.execute(_sql_ob_siafe(q, "WHERE ug_emitente=? AND numero_ob=? AND exercicio=?"),
                            (ug, numero, int(ex))).fetchone()
            return _fatos_ob_siafe(r, q) if r else None
        r = con.execute("SELECT numero_ob, ug_codigo, exercicio, favorecido_cpf, favorecido_nome, valor, data_emissao "
                        "FROM ordens_bancarias WHERE ug_codigo=? AND numero_ob=? AND exercicio=?",
                        (ug, numero, int(ex))).fetchone()
        return _fatos_ob_tfe(r, q) if r else None
    sql, (col_chave, _, *grupo), construir = _FONTES_CT[unidade](q)
    rows = con.execute(f"{sql} WHERE {col_chave}=? " + (grupo[0] if grupo else ""), (chave,)).fetchall()
    return construir(rows[-1]) if rows else None


# ══ PostgreSQL (schema `dominio`) ══════════════════════════════════════════════════════════════════════════════
def esquema_vigente() -> str:
    e = os.environ.get(ENV_ESQUEMA) or ESQUEMA_PADRAO
    if not _RX_IDENT.match(e):
        raise ValueError(f"nome de esquema inválido: {e!r}")
    return e


def conectar(dsn: str | None = None, esquema: str | None = None):
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    dsn = dsn or dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    esquema = esquema or esquema_vigente()
    if not _RX_IDENT.match(esquema):
        raise ValueError(f"nome de esquema inválido: {esquema!r}")
    con = psycopg.connect(dsn, autocommit=True)
    con.execute(f'SET search_path TO "{esquema}"')
    return con


def aplicar_schema(con, esquema: str | None = None) -> None:
    esquema = esquema or esquema_vigente()
    if not _RX_IDENT.match(esquema):
        raise ValueError(f"nome de esquema inválido: {esquema!r}")
    con.execute(SQL_SCHEMA.read_text(encoding="utf-8").replace(':"esquema"', f'"{esquema}"'))
    con.execute(f'SET search_path TO "{esquema}"')


def verificar_schema(con) -> list[str]:
    falta = []
    for t in ("elegibilidade", "elegibilidade_fonte", "elegibilidade_detector", "v_elegibilidade_detector",
              "migracoes"):
        if con.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is None:
            falta.append(t)
    return falta


def fonte_id(texto: str) -> int | None:
    """Id estável do texto da fonte (md5 → bigint com sinal): o mesmo texto, o mesmo id, em qualquer máquina."""
    if not texto:
        return None
    return int.from_bytes(hashlib.md5(texto.encode("utf-8")).digest()[:8], "big", signed=True)


_COLS = ("unidade", "chave", "ug", "numero_ob", "exercicio", "contrato_id", "data_fato", "valor", "paga",
         "credor_classe", "credor_raiz", "natureza_juridica", "natureza_despesa", "vinculo_contrato",
         "natureza_pagamento", "nao_e_contratacao_nova", "credor_e_fornecedor", "natureza_fonte", "origem_exercicio",
         "exercicio_origem", "origem_fonte", "regime", "regime_fonte", "dispensa_valor", "teto", "teto_fonte",
         "motivo_legado", "exiges", "versao", "entrada_hash")
_FONTES_TXT = ("natureza_fonte", "origem_fonte", "regime_fonte", "teto_fonte", "motivo_legado")


def linha(f: Fatos) -> tuple[tuple, dict[int, str]]:
    """Tupla na ordem de _COLS + os textos de fonte novos {id: texto}."""
    textos = {}
    v = dict(f.__dict__)
    for k in _FONTES_TXT:
        fid = fonte_id(v[k])
        if fid is not None:
            textos[fid] = v[k]
        v[k] = fid
    v["exiges"] = json.dumps(f.exiges(), sort_keys=True)
    v["versao"] = VERSAO
    corpo = json.dumps([v[c] for c in _COLS[:-1]], default=str, sort_keys=True)
    v["entrada_hash"] = hashlib.md5(corpo.encode("utf-8")).hexdigest()
    return tuple(v[c] for c in _COLS), textos


def gravar(con, fatos, lote: int = 20000) -> dict:
    """Upsert por (unidade, chave) via COPY numa tabela temporária. Só altera a linha cujo `entrada_hash` mudou.
    Chave repetida no mesmo lote: vence a última (a fonte tem 10 duplicatas em contratos_tcerj, medido)."""
    tot = {"lidas": 0, "inseridas": 0, "alteradas": 0, "iguais": 0, "chaves": set()}
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _e9_carga (LIKE elegibilidade INCLUDING DEFAULTS)")
    buf: dict[tuple, tuple] = {}
    textos: dict[int, str] = {}

    def descarregar():
        if not buf:
            return
        with con.transaction():
            con.execute("TRUNCATE _e9_carga")
            if textos:
                with con.cursor().copy("COPY _e9_carga_fonte (fonte_id, texto) FROM STDIN") as cp:
                    for k, t in textos.items():
                        cp.write_row((k, t))
                con.execute("INSERT INTO elegibilidade_fonte SELECT DISTINCT ON (fonte_id) fonte_id, texto "
                            "FROM _e9_carga_fonte ON CONFLICT DO NOTHING")
                con.execute("TRUNCATE _e9_carga_fonte")
            with con.cursor().copy(f"COPY _e9_carga ({', '.join(_COLS)}) FROM STDIN") as cp:
                for row in buf.values():
                    cp.write_row(row)
            sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS[2:]) + ", calculado_em = now()"
            r = con.execute(
                f"WITH up AS (INSERT INTO elegibilidade ({', '.join(_COLS)}) SELECT {', '.join(_COLS)} FROM _e9_carga "
                f"ON CONFLICT (unidade, chave) DO UPDATE SET {sets} "
                f"WHERE elegibilidade.entrada_hash IS DISTINCT FROM EXCLUDED.entrada_hash "
                f"RETURNING (xmax = 0) AS novo) SELECT COUNT(*) FILTER (WHERE novo), COUNT(*) FILTER (WHERE NOT novo) "
                f"FROM up").fetchone()
        tot["inseridas"] += r[0]
        tot["alteradas"] += r[1]
        tot["iguais"] += len(buf) - r[0] - r[1]
        buf.clear()
        textos.clear()

    con.execute("CREATE TEMP TABLE IF NOT EXISTS _e9_carga_fonte (fonte_id bigint, texto text)")
    for f in fatos:
        row, tx = linha(f)
        buf[(row[0], row[1])] = row
        tot["chaves"].add((row[0], row[1]))
        textos.update(tx)
        tot["lidas"] += 1
        if len(buf) >= lote:
            descarregar()
    descarregar()
    tot["unicas"] = len(tot.pop("chaves"))
    return tot


def sincronizar_detectores(con) -> int:
    """Grava o mapa detector → (unidade, exigência, janela) da versão corrente (substitui a anterior)."""
    with con.transaction():
        con.execute("DELETE FROM elegibilidade_detector")
        n = 0
        for det, m in DETECTORES.items():
            de, ate = m.get("janela") or (None, None)
            for u, x in exiges_do_detector(det).items():
                if u in NAO_MATERIALIZADAS:
                    continue
                con.execute("INSERT INTO elegibilidade_detector VALUES (%s, %s, %s, %s, %s, %s)",
                            (det, u, x, de, ate, VERSAO))
                n += 1
    return n


def contar(con, unidade: str, exercicio: int | None) -> int:
    if exercicio:
        return con.execute("SELECT COUNT(*) FROM elegibilidade WHERE unidade=%s AND exercicio=%s AND versao=%s",
                           (unidade, exercicio, VERSAO)).fetchone()[0]
    return con.execute("SELECT COUNT(*) FROM elegibilidade WHERE unidade=%s AND versao=%s",
                       (unidade, VERSAO)).fetchone()[0]


def conferir_amostra(con, fonte_con: sqlite3.Connection, unidade: str, exercicio: int | None, n: int = 30) -> dict:
    """Sorteia `n` linhas do PG no escopo e recalcula cada uma DO ZERO pela fonte (consulta por chave)."""
    filtro, par = ("AND exercicio=%s", (exercicio,)) if exercicio else ("", ())
    amostra = con.execute(f"SELECT chave, exiges, entrada_hash FROM elegibilidade WHERE unidade=%s {filtro} "
                          f"AND versao=%s ORDER BY random() LIMIT %s", (unidade, *par, VERSAO, n)).fetchall()
    q = Consultas(fonte_con, em_lote=False)
    divergentes = []
    for chave, exiges, h in amostra:
        f = recalcular(unidade, chave, q)
        if f is None or f.exiges() != exiges or linha(f)[0][-1] != h:
            divergentes.append(chave)
    return {"amostra": len(amostra), "divergentes": divergentes}


# ══ estágio (contrato do §3.2) ═════════════════════════════════════════════════════════════════════════════════
def _escopo(payload: dict) -> tuple[str, int | None, str | None]:
    unidade = payload.get("unidade")
    if unidade not in UNIDADES:
        raise ErroPermanente(f"unidade inválida para a E9: {unidade!r} (válidas: {', '.join(UNIDADES)})")
    ex = payload.get("exercicio")
    return unidade, int(ex) if ex else None, payload.get("fonte")


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    unidade, ex, fonte = _escopo(payload)
    src = abrir_fonte(fonte)
    pg = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        aplicar_schema(pg, payload.get("esquema"))
        sincronizar_detectores(pg)
        q = Consultas(src)
        t0 = time.monotonic()
        tot = gravar(pg, iterar(unidade, q, ex))
    finally:
        pg.close()
        src.close()
    return Resultado(efeito={"unidade": unidade, "exercicio": ex, "versao": VERSAO, "linhas": tot["unicas"],
                             "inseridas": tot["inseridas"], "alteradas": tot["alteradas"], "iguais": tot["iguais"],
                             "segundos": round(time.monotonic() - t0, 1)},
                     eventos=[{"fonte": "elegibilidade", "tipo": "mudou",
                               "chave": f"{unidade}:{ex or 'todos'}"}] if tot["inseridas"] + tot["alteradas"] else [])


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    """Relê o PG (recontagem do escopo = declarado, > 0) E recalcula uma amostra pela fonte (0 divergência)."""
    unidade, ex, fonte = _escopo(payload)
    declaradas = int(resultado.efeito.get("linhas") or 0)
    pg = conectar(payload.get("dsn"), payload.get("esquema"))
    src = abrir_fonte(fonte)
    try:
        n = contar(pg, unidade, ex)
        am = conferir_amostra(pg, src, unidade, ex, int(payload.get("amostra") or 30))
    finally:
        pg.close()
        src.close()
    resultado.efeito["conferencia"] = {"contadas": n, **am}
    return declaradas > 0 and n == declaradas and am["amostra"] > 0 and not am["divergentes"]


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=35)


# ══ CLI ════════════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E9 elegibilidade (sombra O4.7)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("acao", choices=("aplicar", "verificar"))
    m = sub.add_parser("materializar")
    m.add_argument("--unidade", required=True, choices=UNIDADES)
    m.add_argument("--exercicio", type=int)
    m.add_argument("--fonte")
    m.add_argument("--amostra", type=int, default=30)
    a = ap.parse_args(argv)
    if a.cmd == "schema":
        con = conectar()
        if a.acao == "aplicar":
            aplicar_schema(con)
        falta = verificar_schema(con)
        con.close()
        print(json.dumps({"esquema": esquema_vigente(), "ok": not falta, "faltando": falta}, ensure_ascii=False))
        return 0 if not falta else 1
    payload = {"unidade": a.unidade, "exercicio": a.exercicio, "fonte": a.fonte, "amostra": a.amostra}
    ctx = Contexto(no=os.environ.get("JFN_NO", "cli"), tipo="elegibilidade",
                   chave=f"elegibilidade:{a.unidade}:{a.exercicio or 'todos'}", ficha=0, tentativa=1)
    res = _handler(payload, ctx)
    ok = _efeito(payload, ctx, res)
    print(json.dumps(res.efeito, ensure_ascii=False, default=str))
    if not ok:
        print("elegibilidade: EFEITO NÃO CONFERIDO", file=sys.stderr)
        return 1
    print(f"elegibilidade: {res.efeito['linhas']} linha(s) conferida(s) em {esquema_vigente()}.elegibilidade "
          f"({a.unidade}, exercício {a.exercicio or 'todos'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
