# -*- coding: utf-8 -*-
"""pericia_integral — UMA perícia por processo de contratação, em todos os eixos, com o Claude como co-motor.

Pedido do dono (15/11/2026): "use o poder computacional restante das máquinas para as perícias jurídicas,
contábeis, de conformidade, de compliance e anticorrupção e anti-irregularidades … batendo claude com as outras
IAs para que sejam padronizadas. prioridade é pensar profundo em cada processo de contratação com o claude."
E, no mesmo dia: "pode periciar o que mais imaginar. tudo junto, processo a processo."

COMO FUNCIONA (uma chamada por processo):
  1. `montar_entrada(pasta)` — camada DETERMINÍSTICA: `processo_360.avaliar_pasta` sem LLM (fases, lacunas,
     achados dos detectores de edital/execução/fornecedor, CNPJ vencedor), OB CONTABILIZADA no SIAFE (só a OB é
     pagamento — Empenho ≠ Liquidação ≠ OB), e as evidências que a casa já calcula (R-RAPP do Lex, sócio na
     folha, sanções SIGA, lista suja, perícia de fornecedor e de execução já gravadas, indicadores de fraude).
     O texto dos documentos entra POR VALOR (`ordenar_para_leitura`, nunca os N primeiros da árvore), com teto.
  2. O prompt pede UM JSON com todos os eixos de `EIXOS` (constante única: nome, pergunta-guia, base normativa,
     fontes determinísticas a consultar). Cada eixo: `grau` 0 ⚪ · 1 🟡 · 2 🔴 · null INDETERMINADO, `achados`
     com citação LITERAL, `fundamento`, `lacunas`.
  3. `comotor.juizo("pericia_integral")` roda o Claude (Opus, só ASSINATURA — `backend="cli"`, nunca a API paga)
     e a cascata em paralelo; o par global vai ao cruzamento e, sem o Claude, à fila do Opus.
  4. Cada resposta passa pela VERIFICAÇÃO LITERAL (`llm/verificacao.citacao_existe`): citação que não está na
     entrada derruba o achado (fica em `descartados`); grau 🟡/🔴 sem nenhum achado conferido vira INDETERMINADO.
  5. Cruzamento POR EIXO: um par Claude × cascata por eixo, tarefa `pericia_integral:<eixo>` — é a régua que
     padroniza as outras IAs contra o Claude eixo a eixo (concordância, few-shot, revisão humana do 🔴×⚪).
  6. Persistência em `compliance.db`, tabela `pericia_integral`, SÓ ACRESCENTA (histórico): uma linha por eixo
     + uma `_global` por rodada. `conferido_opus`: 0 pendente (cascata, na fila do Opus) · 1 feito/conferido
     pelo Opus · 2 substituído pela conferência do Opus. Transação curta: um commit por processo.

Indício ≠ acusação. Ausência de documento = INDETERMINADO, nunca irregularidade. Grau é indício interno.
"""
from __future__ import annotations

import argparse
import json

import httpx
import logging
import os
import random
import sqlite3
import uuid
import zlib
from datetime import datetime
from pathlib import Path
from typing import Callable

from compliance_agent.llm import claude_motor, comotor, contingencia, cruzamento
from compliance_agent.llm.verificacao import citacao_existe

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
ACERVO = _REPO / "data" / "sei_arquivo"
TAREFA = "pericia_integral"
VERSAO_PROMPT = "pi-3"   # pi-3: regras de calibração por eixo (divergências medidas Claude × cascata, 16/11)
# pi-2: pontos de controle por eixo, regime, diligência, hipótese inocente
# caracteres de documentos por processo. 80k (1º desenho) leu 8 de 198 docs no processo-prova de 15/11; o dono quer o
# Claude "pensando profundo em cada processo" — 240k (~65k tokens) cabem no Opus e no Gemini com folga.
TETO_TEXTO = int(os.environ.get("JFN_PERICIA_INTEGRAL_TETO", "240000"))
TETO_DOC = 12_000            # uma peça gigante não come a janela das outras
TETO_EVIDENCIA = 3_000       # por fonte determinística
MIN_TEXTO = 400              # bytes de texto na pasta abaixo disto: nada a periciar
# 10 eixos × até 3 achados: o JSON passa de 4.096 tokens (o teto da cascata padrão) — a lição das 87/200 fichas
# cortadas. A cascata desta tarefa chama o Gemini com teto próprio antes de cair na cascata padrão.
MAX_TOKENS_SAIDA = 16_000
TIMEOUT_CLAUDE = 600.0
TIMEOUT_CASCATA = 240.0
ESPERA_TRAVA = 120.0

_MARCA_INI = "=== ENTRADA (única fonte de fatos; cite LITERALMENTE daqui) ==="
_MARCA_FIM = "=== FIM DA ENTRADA ==="

# ── os eixos: constante ÚNICA (prompt, normalização, cruzamento e tabela iteram sobre ela) ─────────────────
# pi-2 (15/11/2026, dono: "aprimore os 10 eixos"): cada eixo virou PONTOS DE CONTROLE numerados que todo modelo
# responde um a um (conforme | desconforme | nao_se_aplica | indeterminado). Pergunta aberta deixava cada IA olhar
# coisas diferentes — os pontos fixam a régua e são cruzados um a um (padronização Claude × cascata no detalhe).
# Artigos: Lei 14.133/2021 (L14), Lei 8.666/1993 (L8), Lei 13.303/2016 (estatais), Lei 4.320/1964 (L4320).
def _p(i: str, t: str) -> dict:
    return {"id": i, "texto": t}


EIXOS: tuple[dict, ...] = (
    {"nome": "juridico",
     "pergunta": "A forma de contratação é a juridicamente correta e está fundamentada?",
     "base": "L14 arts. 53, 72, 74, 75, 92 e 107; L8 arts. 24, 25, 26, 38 VI, 55 e 57; Lei 13.303 arts. 28-30",
     "pontos": (_p("J1", "a modalidade ou a hipótese de contratação direta é compatível com o objeto e o valor"),
                _p("J2", "a dispensa/inexigibilidade cita a hipótese legal e a justifica (L14 art. 72; L8 art. 26)"),
                _p("J3", "na inexigibilidade, há prova da exclusividade/notória especialização e justificativa do preço"),
                _p("J4", "na emergência, a situação é concreta e o prazo respeita o teto legal, sem prorrogação nem "
                         "recontratação vedadas (L14 art. 75 VIII; L8 art. 24 IV)"),
                _p("J5", "há parecer jurídico PRÉVIO e a decisão o acatou ou motivou a divergência (L14 art. 53)"),
                _p("J6", "o contrato tem as cláusulas necessárias e as prorrogações têm base legal (L14 arts. 92, 107)")),
     "fontes": ("p360_achados", "p360_acatamento", "sei_ficha")},
    {"nome": "planejamento",
     "pergunta": "A contratação foi planejada e o preço estimado tem base?",
     "base": "L14 arts. 6º XX e XXIII, 18, 23, 40 e 72 I-II",
     "pontos": (_p("P1", "há documento de formalização da demanda com a necessidade descrita"),
                _p("P2", "há estudo técnico preliminar ou dispensa motivada dele"),
                _p("P3", "há termo de referência/projeto básico com especificação que não restringe a competição"),
                _p("P4", "o quantitativo é justificado por consumo, histórico ou memória de cálculo"),
                _p("P5", "a pesquisa de preços tem 3+ fontes independentes, datadas e sem cotação só de interessados")),
     "fontes": ("p360_lacunas", "rapp")},
    {"nome": "economicidade",
     "pergunta": "O preço contratado e pago é compatível com o mercado e com o próprio orçamento?",
     "base": "L14 arts. 6º LVI-LVII, 23, 124-125; L8 art. 65 §1º",
     "pontos": (_p("E1", "o preço contratado está dentro do estimado e das referências PRESENTES NA ENTRADA"),
                _p("E2", "aditivos de valor respeitam 25% (50% em reforma) do valor inicial atualizado"),
                _p("E3", "não há jogo de planilha (itens com sobrepreço aumentados e com desconto suprimidos)"),
                _p("E4", "não há pagamento de item/quantidade acima do medido ou do contratado"),
                _p("E5", "reajustes/repactuações seguem o índice e o prazo contratuais")),
     "fontes": ("rapp", "siafe_ob", "p360_achados")},
    {"nome": "orcamentario_contabil",
     "pergunta": "A despesa percorreu dotação → empenho → liquidação → OB regularmente? (só a OB é pagamento)",
     "base": "L4320 arts. 36, 37, 58-64; LC 101/2000 arts. 15-17 e 42; L14 arts. 72 IV, 141, 145 e 149; L8 arts. 5º e 59",
     "pontos": (_p("O1", "há indicação de dotação/compatibilidade orçamentária antes da contratação"),
                _p("O2", "o empenho é PRÉVIO à despesa (sem despesa sem empenho — L4320 art. 60)"),
                _p("O3", "cada OB tem liquidação prévia com atesto (L4320 arts. 62-63)"),
                _p("O4", "não há pagamento por indenização/reconhecimento de dívida/TAC sem cobertura contratual, ou, "
                         "havendo, ele está motivado e com apuração de responsabilidade"),
                _p("O5", "não há pagamento antecipado fora das hipóteses legais (L14 art. 145)"),
                _p("O6", "a ordem cronológica de pagamentos foi respeitada ou a quebra foi justificada"),
                _p("O7", "despesa de exercício anterior/restos a pagar estão reconhecidos regularmente")),
     "fontes": ("siafe_ob", "p360_cadeia")},
    {"nome": "conformidade_procedimental",
     "pergunta": "O rito foi cumprido, na ordem e com publicidade?",
     "base": "L14 arts. 17, 54, 55, 62-70, 72, 94 e 174; L8 arts. 21, 38 e 61 parágrafo único",
     "pontos": (_p("C1", "as fases obrigatórias existem e estão em ordem cronológica coerente"),
                _p("C2", "edital/aviso e contrato foram divulgados no PNCP/DOERJ (condição de eficácia — L14 art. 94)"),
                _p("C3", "prazos mínimos de propostas e de recurso foram respeitados"),
                _p("C4", "a habilitação foi verificada com documentos válidos NA DATA (fiscal, trabalhista, jurídica)"),
                _p("C5", "há autorização da autoridade competente e designação formal dos agentes"),
                _p("C6", "não há documento com data posterior ao ato que ele deveria preceder (instrução retroativa)")),
     "fontes": ("p360_lacunas", "p360_achados")},
    {"nome": "execucao_fisica",
     "pergunta": "O que foi pago foi efetivamente entregue/executado e comprovado?",
     "base": "L14 arts. 117 e 140; L8 arts. 67 e 73; L4320 art. 63",
     "pontos": (_p("X1", "há fiscal do contrato designado formalmente"),
                _p("X2", "há medição/relatório de execução compatível com o objeto e com o período pago"),
                _p("X3", "há notas fiscais compatíveis em data, valor e descrição com o pago"),
                _p("X4", "há recebimento provisório/definitivo ou atesto por quem não é o próprio demandante interessado"),
                _p("X5", "há prova material da entrega (fotos, relatórios, listas) e ela é específica, não genérica"),
                _p("X6", "não há pagamento anterior à execução ou sem atesto")),
     "fontes": ("lex_execucao", "p360_achados", "siafe_ob")},
    {"nome": "fornecedor",
     "pergunta": "O contratado tem existência, capacidade e regularidade compatíveis com o contrato?",
     "base": "L14 arts. 14, 62-70 e 156; LC 123/2006 arts. 3º e 48",
     "pontos": (_p("F1", "a atividade econômica (CNAE) é compatível com o objeto"),
                _p("F2", "a idade da empresa e o capital são compatíveis com o porte do contrato"),
                _p("F3", "o porte ME/EPP declarado é compatível com o faturamento/valores recebidos"),
                _p("F4", "a situação cadastral era ativa NA DATA da contratação e do pagamento"),
                _p("F5", "não há sanção/impedimento vigente na data (CEIS/CNEP/estado)"),
                _p("F6", "não há sinal de fachada (endereço, quadro de pessoal, capacidade operacional)")),
     "fontes": ("pericia_fornecedor", "sancoes_siga", "lista_suja")},
    {"nome": "compliance_integridade",
     "pergunta": "Há conflito de interesse ou relação imprópria entre contratado e agentes públicos?",
     "base": "L14 arts. 7º, 9º e 14 IV; Lei 12.813/2013; Súmula Vinculante 13; Lei 8.429/1992 arts. 9º-11",
     "pontos": (_p("I1", "não há sócio/administrador do contratado com vínculo com o órgão CONTRATANTE (o órgão "
                         "precisa ser o mesmo — vínculo com outro órgão é ponto de atenção, não impedimento)"),
                _p("I2", "não há parentesco entre sócios e agentes que atuaram no processo"),
                _p("I3", "o agente que demandou, cotou, julgou ou atestou não é o mesmo em fases incompatíveis"),
                _p("I4", "não há concentração/rodízio de contratos do mesmo grupo econômico no órgão"),
                _p("I5", "o contratado tem programa de integridade quando exigido por lei ou edital")),
     "fontes": ("conflito_socio_agente", "pericia_fornecedor")},
    {"nome": "anticorrupcao",
     "pergunta": "Há padrão de fraude ou corrupção na contratação?",
     "base": "Lei 12.846/2013 art. 5º IV; Lei 8.429/1992 art. 10 VIII; L14 arts. 75 §1º e 155; CP arts. 337-E a 337-L",
     "pontos": (_p("A1", "não há direcionamento (exigência restritiva, marca, atestado desproporcional, prazo exíguo)"),
                _p("A2", "não há sinal de conluio (propostas gêmeas, mesmo endereço/sócio/telefone, rodízio, cobertura)"),
                _p("A3", "não há fracionamento para fugir de modalidade ou de limite de dispensa (L14 art. 75 §1º)"),
                _p("A4", "a emergência não foi fabricada pela própria inércia administrativa"),
                _p("A5", "não há participante único ou desclassificação sistemática dos concorrentes sem motivo"),
                _p("A6", "não há sinal de pagamento/benefício indevido ou de simulação de execução")),
     "fontes": ("indicadores_fraude", "p360_achados", "rapp")},
    {"nome": "controle_interno_externo",
     "pergunta": "Os órgãos de controle atuaram e suas recomendações foram atendidas?",
     "base": "CF arts. 70, 71 e 74; L14 art. 169; LC estadual 63/1990",
     "pontos": (_p("K1", "há manifestação do controle interno (CGE/AUDIN) quando exigida"),
                _p("K2", "achados/recomendações do controle foram atendidos ou a recusa foi motivada"),
                _p("K3", "há atuação do TCE (determinação, representação, auditoria) e seu desfecho está nos autos"),
                _p("K4", "irregularidade apontada gerou apuração (sindicância/PAD) com desfecho registrado")),
     "fontes": ("p360_acatamento", "p360_achados")},
)
NOMES_EIXOS: tuple[str, ...] = tuple(e["nome"] for e in EIXOS)
VALORES_PONTO = ("conforme", "desconforme", "nao_se_aplica", "indeterminado")
REGIMES = ("8666", "14133", "13303", "outro", "indeterminado")
_NIVEL_PONTO = {"conforme": 0, "desconforme": 1}
# eixos gravados pelo agente Claude Code (18/11/2026): ponto = {"status": "atende"|"nao_atende"|…, "citacao": …}
_PONTO_AGENTE = {"atende": "conforme", "nao_atende": "desconforme"}


def _status_ponto(v) -> str:
    if isinstance(v, dict):
        v = v.get("status")
    v = str(v or "indeterminado")
    return _PONTO_AGENTE.get(v, v)

_FALHAS_DB = (sqlite3.Error, OSError)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


from compliance_agent.cpf_cnpj import digitos as _dig  # noqa: E402


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _json_curto(obj, teto: int = TETO_EVIDENCIA) -> str:
    t = json.dumps(obj, ensure_ascii=False, default=str)
    return t if len(t) <= teto else t[:teto] + " …[cortado no teto]"


# ── entrada determinística ────────────────────────────────────────────────────────────────────────────
def _resumo_360(p: dict) -> dict:
    achados = [{k: (str(a.get(k))[:300] if a.get(k) is not None else None)
                for k in ("origem", "codigo", "grau", "gravidade", "diz", "evidencia", "apoio") if a.get(k)}
               for a in (p.get("achados") or [])[:40] if isinstance(a, dict)]
    return {"achados": achados, "lacunas": {"processo": p.get("lacunas_processo"), "captura": p.get("lacunas_captura")},
            "acatamento": p.get("acatamento"), "cadeia": p.get("cadeia")}


def _ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)


def coletar_evidencias(*, numero: str, cnpj: str | None, texto: str, integra: bool) -> dict:
    """Evidências que a casa JÁ calcula, por fonte. Fonte que falhar vira {"indisponivel": motivo} — nunca 0."""
    ev: dict = {}

    def _tenta(nome, fn):
        try:
            ev[nome] = fn()
        except (ImportError, AttributeError, KeyError, TypeError, ValueError, sqlite3.Error, OSError) as e:
            ev[nome] = {"indisponivel": f"{type(e).__name__}: {str(e)[:80]}"}

    def _rapp():
        from compliance_agent import lex_redflags
        return lex_redflags.avaliar_rapp(texto, cnpj_contratada=cnpj, texto_integral=integra)
    _tenta("rapp", _rapp)

    def _fraude():
        from compliance_agent import lex_indicadores_fraude as F
        rfs = ev.get("rapp") if isinstance(ev.get("rapp"), list) else []
        t = F.triagem(F.sinais_do_contexto({}, {"achados": rfs}))
        return {k: t.get(k) for k in ("n_indicadores", "faixa", "tipologias", "nota")} | {
            "indicadores": [i.get("id") or i.get("nome") for i in t.get("indicadores") or []]}
    _tenta("indicadores_fraude", _fraude)

    def _linha(sql, args, cols):
        con = _ro()
        try:
            r = con.execute(sql, args).fetchone()
        finally:
            con.close()
        return dict(zip(cols, r)) if r else {"consta": False}

    _tenta("lex_execucao", lambda: _linha(
        "SELECT execucao_comprovada, coerencia, nota_risco, indicios, resumo, modelo FROM lex_execucao "
        "WHERE numero_sei=?", (numero,), ("execucao_comprovada", "coerencia", "nota_risco", "indicios", "resumo",
                                          "modelo")))
    _tenta("sei_ficha", lambda: {"aviso": "extraído por modelo, não conferido — use só como pista"} | _linha(
        "SELECT objeto, modalidade, fundamento_legal FROM sei_ficha WHERE numero_sei=?", (numero,),
        ("objeto", "modalidade", "fundamento_legal")))
    if cnpj and len(_dig(cnpj)) == 14:
        c = _dig(cnpj)
        _tenta("pericia_fornecedor", lambda: _linha(
            "SELECT grau, score, resumo, n_confirmados, n_indicios, atualizado_em FROM pericia_fornecedor "
            "WHERE cnpj=? ORDER BY atualizado_em DESC", (c,),
            ("grau", "score", "resumo", "n_confirmados", "n_indicios", "atualizado_em")))

        def _conflito():
            from compliance_agent import lex_conflito as L
            a = L.achado_socio_agente(L.socios_agentes_publicos(c))
            return a or {"consta": False}
        _tenta("conflito_socio_agente", _conflito)

        def _sancoes():
            from compliance_agent import lex_conflito as L
            return L.sancoes_siga(c) or {"consta": False}
        _tenta("sancoes_siga", _sancoes)

        def _suja():
            from compliance_agent import lex_conflito as L
            return L.lista_suja(c) or {"consta": False}
        _tenta("lista_suja", _suja)
    else:
        for k in ("pericia_fornecedor", "conflito_socio_agente", "sancoes_siga", "lista_suja"):
            ev[k] = {"indisponivel": "CNPJ do vencedor não identificado no processo"}
    return ev


def _texto_por_valor(pasta: Path, teto: int) -> tuple[str, dict]:
    from compliance_agent.sei import acervo_texto
    from compliance_agent.sei.classificador_doc import ordenar_para_leitura
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict) and d.get("texto")]
    partes, total, lidos, fora = [], 0, 0, []
    for d in ordenar_para_leitura(docs):
        t = acervo_texto.ler(pasta, d).strip()
        if len(t) < 40:
            continue
        titulo = str(d.get("titulo") or "").strip() or "(sem título)"
        if total >= teto:
            fora.append(titulo)
            continue
        t = t[: min(TETO_DOC, teto - total)]
        partes.append(f"--- DOCUMENTO: {titulo} ---\n{t}")
        total += len(t)
        lidos += 1
    return "\n\n".join(partes), {"docs_com_texto": len(docs), "docs_lidos": lidos, "docs_fora_do_teto": len(fora),
                                 "titulos_fora_do_teto": fora[:30], "chars": total}


def _pago(numero: str, obs: dict | None) -> dict | None:
    from tools.lex_execucao import _chave_processo, mapa_obs_siafe
    if obs is None:
        con = _ro()
        try:
            obs = mapa_obs_siafe(con, [numero])
        finally:
            con.close()
    return obs.get(_chave_processo(numero) or "")


def _bloco_ob(ob: dict | None) -> str:
    from tools.lex_execucao import _ressalva_ob
    if not ob or not ob.get("n"):
        return ("PAGAMENTO (SIAFE): nenhuma OB contabilizada localizada pelo nº deste processo — INDISPONÍVEL "
                "(pode estar sob outra numeração); não é prova de ausência de pagamento.")
    ds = sorted((x for x in ob.get("datas") or [] if x), key=lambda s: s[6:10] + s[3:5] + s[0:2])
    per = f", emitidas de {ds[0]} a {ds[-1]}" if ds else ""
    return (f"PAGAMENTO (SIAFE, fonte oficial da OB): {ob['n']} OB(s) contabilizada(s), total {_brl(ob['total'])}"
            f"{per}. {_ressalva_ob(ob)}Só a OB é pagamento; empenho e liquidação não são.")


def numero_da_pasta(nome: str) -> str:
    p = nome.split("_")
    return f"SEI-{p[0]}/{p[1]}/{p[2]}" if len(p) >= 3 else nome


def montar_entrada(pasta: Path | str, *, avaliar: Callable | None = None, obs: dict | None = None,
                   coletar: Callable | None = None, teto_chars: int | None = None) -> dict:
    pasta = Path(pasta)
    numero = numero_da_pasta(pasta.name)
    documentos, cobertura = _texto_por_valor(pasta, teto_chars or TETO_TEXTO)
    if not documentos.strip():
        return {"processo": numero, "status": "SEM_TEXTO", "cobertura": cobertura}
    if avaliar is None:
        from compliance_agent.processo_360 import avaliar_pasta as avaliar
    try:
        p360 = avaliar(pasta, com_llm=False)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as e:
        p360 = {"status": "INDISPONIVEL", "motivo": f"{type(e).__name__}: {str(e)[:120]}"}
    try:
        ob = _pago(numero, obs)
    except _FALHAS_DB as e:
        logger.warning("pericia_integral: SIAFE ilegível (%s)", type(e).__name__)
        ob = None
    cnpj = p360.get("cnpj_vencedor")
    integra = bool((p360.get("cobertura") or {}).get("captura_integra"))
    ev = (coletar or coletar_evidencias)(numero=numero, cnpj=cnpj, texto=documentos, integra=integra)
    r360 = _resumo_360(p360) if p360.get("status") == "OK" else {}
    fontes = {"p360_achados": r360.get("achados"), "p360_lacunas": r360.get("lacunas"),
              "p360_acatamento": r360.get("acatamento"), "p360_cadeia": r360.get("cadeia"),
              "siafe_ob": _bloco_ob(ob), **ev}
    linhas = [f"PROCESSO: {numero}",
              f"MODALIDADE (manifesto): {p360.get('modalidade') or 'não informada'} · natureza: "
              f"{p360.get('natureza') or '?'} · ato principal: {p360.get('ato_principal') or '?'}",
              f"CNPJ VENCEDOR (extraído do texto): {cnpj or 'não identificado'}",
              f"CAPTURA ÍNTEGRA: {'sim' if integra else 'NÃO — ausência no texto não prova ausência no processo'}"
              f" · documentos lidos {cobertura['docs_lidos']} de {cobertura['docs_com_texto']}"
              f" ({cobertura['docs_fora_do_teto']} fora do teto de leitura)",
              _bloco_ob(ob)]
    if p360.get("status") != "OK":
        linhas.append(f"AVALIAÇÃO DETERMINÍSTICA (360): INDISPONÍVEL — {p360.get('motivo', '')}")
    linhas.append("EVIDÊNCIAS DETERMINÍSTICAS (calculadas por código; julgue sobre elas, não as recalcule):")
    for nome, v in fontes.items():
        if nome == "siafe_ob":
            continue
        linhas.append(f"[{nome}] " + (_json_curto(v) if v not in (None, [], {}) else "nada consta"))
    return {"processo": numero, "status": "OK", "pasta": str(pasta), "bloco": "\n".join(linhas),
            "documentos": documentos, "cobertura": cobertura, "valor_pago": round((ob or {}).get("total", 0.0), 2),
            "cnpj": cnpj, "captura_integra": integra}


# ── prompt ────────────────────────────────────────────────────────────────────────────────────────────
_SISTEMA_EXTRA = (
    " Você faz PERÍCIA INTEGRAL de um processo de contratação pública do Estado do RJ, em vários eixos, numa "
    "única leitura. Pense com profundidade, eixo a eixo, antes de concluir. Regras: (1) só a entrada é fonte de "
    "fatos; (2) cada achado traz a CITAÇÃO LITERAL copiada da entrada — o código confere letra a letra e descarta "
    "achado com citação que não existe; (3) documento que não está na entrada ⇒ grau null (INDETERMINADO) e o "
    "documento faltante vai em `lacunas`, nunca grau de irregularidade; (4) sobrepreço só com base de preço "
    "presente na entrada; (5) Empenho ≠ Liquidação ≠ OB — pagamento é só a OB; (6) indício, não acusação."
)


# Regras de calibração (pi-3), tiradas das divergências MEDIDAS entre o Claude e a cascata em 16/11/2026 (eixo jurídico:
# cascata mais grave em 27 de 36 pares; planejamento 12/24; orçamentário-contábil: cascata MENOS grave em 29/60, por não
# comparar datas). Valem para todo modelo — descrevem o critério que o Claude já aplica.
REGRAS_CALIBRACAO = (
    "REGRAS DE JULGAMENTO (obrigatórias):\n"
    "R1. Documento que NÃO aparece nos autos lidos é LACUNA (vai em `lacunas`/`diligencias`, ponto `indeterminado`), "
    "nunca achado: ausência não prova irregularidade.\n"
    "R2. Ordem entre atos só se afirma com as DATAS de assinatura/emissão citadas dos dois atos; número/ID do documento "
    "no SEI e posição na árvore NÃO provam cronologia.\n"
    "R3. Erro formal (numeração de aditivo, soma, referência normativa trocada, digitação) é no máximo grau 1, salvo "
    "efeito financeiro ou restrição de competição demonstrados com citação.\n"
    "R4. Grau 2 exige os três: o ATO praticado (citado), a NORMA violada e o EFEITO (dano, sobrepreço, restrição de "
    "competição, pagamento indevido). Faltando um, é grau 1.\n"
    "R5. Eixo orçamentário-contábil: para cada empenho, liquidação e OB citados, COMPARE as datas — empenho emitido "
    "depois da competência da despesa (art. 60 da Lei 4.320), OB antes da liquidação (arts. 62–63), liquidação sem "
    "atesto. Só marque `conforme` citando as datas que comparou; sem as datas, `indeterminado`.\n"
    "R6. Eixos de fornecedor e compliance: todo sinal presente no bloco de evidências determinísticas (sanção, sócio "
    "servidor/doador, situação cadastral, empresa nova, endereço compartilhado) tem de ser avaliado expressamente — "
    "confirmado com citação ou afastado com a hipótese inocente; nunca ignorado.\n"
    "R7. Planejamento: ETP/TR ou pesquisa de preços ausentes nos autos lidos são lacuna (R1); só é achado o que está "
    "nos documentos e contraria a norma (ex.: pesquisa com uma única cotação, quantitativo sem memória de cálculo citado).\n"
)


def montar_prompt(entrada: dict) -> tuple[str, str]:
    eixos = "\n".join(
        f"{i + 1}. `{e['nome']}` — {e['pergunta']} Base: {e['base']}. Evidências determinísticas a consultar: "
        f"{', '.join(e.get('fontes') or ()) or '—'}.\n" + "\n".join(f"   {p['id']}: {p['texto']}" for p in e["pontos"])
        for i, e in enumerate(EIXOS))
    exemplo_eixo = ('{"grau": 0|1|2|null, "pontos": {"<id>": "conforme|desconforme|nao_se_aplica|indeterminado", ...}, '
                    '"achados": [{"documento": "título do documento ou [fonte] da evidência", '
                    '"citacao": "trecho LITERAL copiado da entrada, 20 a 200 caracteres", "descricao": "o que o trecho '
                    'indica (até 160 caracteres)", "grau": 1|2, "fundamento": "dispositivo legal", "ponto": "<id>"}], '
                    '"fundamento": "base normativa do juízo do eixo", "lacunas": ["documento que faltou para julgar"], '
                    '"diligencias": ["pedido CONCRETO de informação/documento que fecharia a dúvida"], '
                    '"hipotese_inocente": "a explicação regular mais plausível que você considerou e por que (não) basta"}')
    schema = ('{"regime": "8666|14133|13303|outro|indeterminado", "regime_citacao": "trecho literal que mostra o '
              'regime", "eixos": {' + ", ".join(f'"{n}": EIXO' for n in NOMES_EIXOS) + '}, "resumo": "até 3 frases"}')
    prompt = (
        f"PERÍCIA INTEGRAL DO PROCESSO DE CONTRATAÇÃO {entrada['processo']}\n\n"
        f"Julgue o processo em CADA um dos {len(EIXOS)} eixos abaixo:\n{eixos}\n\n"
        "Escala do grau: 0 = sem sinal; 1 = atenção (indício a diligenciar); 2 = grave (indício forte, com prova "
        "citada); null = INDETERMINADO (falta documento para julgar). Grau 1 ou 2 exige ao menos um achado com "
        "citação literal. No máximo 3 achados por eixo, os mais fortes.\n"
        "Primeiro identifique o REGIME legal (Lei 8.666, Lei 14.133 ou Lei 13.303 de estatais) pela data e pelo texto "
        "dos atos, e aplique os artigos do regime certo. Depois responda TODOS os pontos de controle de cada eixo: "
        "`desconforme` exige achado com citação (indique o ponto no achado); `indeterminado` quando faltar o documento; "
        "`nao_se_aplica` quando o ponto não cabe ao tipo de contratação. O grau do eixo resume os pontos.\n\n"
        f"{REGRAS_CALIBRACAO}\n"
        f"{_MARCA_INI}\n{entrada['bloco']}\n\nDOCUMENTOS DO PROCESSO (ordenados por valor fiscalizatório):\n"
        f"{entrada['documentos']}\n{_MARCA_FIM}\n\n"
        f"Responda SOMENTE com este JSON, com TODOS os eixos: {schema}\nonde cada EIXO é {exemplo_eixo}"
    )
    return claude_motor.SISTEMA_PADRAO + _SISTEMA_EXTRA, prompt


def _fonte_do_prompt(prompt: str) -> str:
    """O trecho do prompt que é ENTRADA (dados + documentos) — a única fonte contra a qual se confere citação."""
    i = (prompt or "").find(_MARCA_INI)
    j = (prompt or "").rfind(_MARCA_FIM)
    if i < 0 or j < 0 or j <= i:
        return ""
    return prompt[i + len(_MARCA_INI):j]


# ── interpretação + verificação literal ───────────────────────────────────────────────────────────────
def _grau(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and int(v) == v and 0 <= v <= 2:
        return int(v)
    if isinstance(v, str) and v.strip() in ("0", "1", "2"):
        return int(v.strip())
    return None


def _pontos(bruto: dict, ids: tuple[str, ...]) -> dict:
    """{id: valor} para TODOS os pontos do eixo; valor fora da escala ou ausente = indeterminado; id estranho cai."""
    dado = bruto.get("pontos") if isinstance(bruto.get("pontos"), dict) else {}
    out = {}
    for i in ids:
        v = str(dado.get(i) or "").strip().lower().replace(" ", "_").replace("ã", "a")
        out[i] = v if v in VALORES_PONTO else "indeterminado"
    return out


def conferir_eixo(bruto, fonte: str, ids_pontos: tuple[str, ...] = ()) -> dict:
    """Confere as citações do eixo contra a fonte. Achado sem citação literal cai; 🟡/🔴 sem achado = null."""
    if not isinstance(bruto, dict):
        return {"grau": None, "achados": [], "fundamento": "", "descartados": [],
                "pontos": {i: "indeterminado" for i in ids_pontos}, "diligencias": [], "hipotese_inocente": "",
                "lacunas": ["eixo não respondido pelo modelo"]}
    g = _grau(bruto.get("grau"))
    ok, fora = [], []
    for a in bruto.get("achados") or []:
        if not isinstance(a, dict):
            continue
        cit = str(a.get("citacao") or "")
        if citacao_existe(cit, fonte):
            ok.append({"documento": str(a.get("documento") or "")[:200], "citacao": cit[:400],
                       "descricao": str(a.get("descricao") or "")[:300], "grau": _grau(a.get("grau")),
                       "fundamento": str(a.get("fundamento") or "")[:200], "ponto": str(a.get("ponto") or "")[:8]})
        else:
            fora.append({"citacao": cit[:300], "descricao": str(a.get("descricao") or "")[:200],
                         "motivo": "citação não encontrada literalmente na entrada"})
    lacunas = [str(x)[:200] for x in (bruto.get("lacunas") or []) if x][:10]
    nota = None
    if g in (1, 2):
        graus = [a["grau"] if a["grau"] in (1, 2) else g for a in ok]
        if not graus:
            nota = f"grau {g} declarado sem achado com citação conferida — INDETERMINADO"
            g = None
        else:
            g = min(g, max(graus))
    out = {"grau": g, "achados": ok, "fundamento": str(bruto.get("fundamento") or "")[:400], "lacunas": lacunas,
           "descartados": fora, "pontos": _pontos(bruto, ids_pontos),
           "diligencias": [str(x)[:300] for x in (bruto.get("diligencias") or []) if x][:5],
           "hipotese_inocente": str(bruto.get("hipotese_inocente") or "")[:500]}
    if nota:
        out["nota_verificacao"] = nota
    return out


def interpretar(texto: str, fonte: str) -> dict | None:
    """{eixo: conferido} para TODOS os eixos de `EIXOS`; None se a resposta não tem o JSON pedido."""
    from compliance_agent.llm.json_resposta import parse_json_llm
    d = parse_json_llm(texto or "")
    if not isinstance(d, dict) or not isinstance(d.get("eixos"), dict):
        return None
    eixos = {e["nome"]: conferir_eixo(d["eixos"].get(e["nome"]), fonte, tuple(p["id"] for p in e["pontos"]))
             for e in EIXOS}
    regime = str(d.get("regime") or "").replace(".", "").replace("/", "").strip()
    regime = next((r for r in REGIMES if regime == r or regime.startswith(r)), "indeterminado")
    eixos["_global"] = {"resumo": str(d.get("resumo") or "")[:800], "regime": regime,
                        "regime_citacao": str(d.get("regime_citacao") or "")[:300]}
    return eixos


def grau_global(eixos: dict) -> int | None:
    gs = [eixos[n]["grau"] for n in NOMES_EIXOS if eixos.get(n, {}).get("grau") is not None]
    return max(gs) if gs else None


# ── cruzamento por eixo ───────────────────────────────────────────────────────────────────────────────
def _veredito_eixo(e: dict) -> str:
    g = e.get("grau")
    v = f"grau {g if g is not None else 'indeterminado'}"
    if e.get("achados"):
        a = e["achados"][0]          # dict da perícia; texto nos eixos gravados pelo agente Claude Code (18/11/2026)
        v += ": " + str(a.get("descricao") or "" if isinstance(a, dict) else a)[:60]
    return v


def cruzar_eixos(processo: str, eixos_ref: dict, modelo_ref: str, eixos_outro: dict, modelo_outro: str,
                 resumo: str = "", *, com_exemplos: bool = False) -> int:
    """Um par por eixo (`pericia_integral:<eixo>`): referência (Claude/Opus) × outro modelo. Devolve quantos gravou."""
    n = 0
    for nome in NOMES_EIXOS:
        a, b = eixos_ref.get(nome) or {}, eixos_outro.get(nome) or {}
        try:
            cruzamento.cruzar(f"{TAREFA}:{nome}", f"sei:{processo}",
                              cruzamento.Lado("claude", modelo_ref, _veredito_eixo(a), a.get("grau")),
                              cruzamento.Lado("cascata", modelo_outro, _veredito_eixo(b), b.get("grau"),
                                              com_exemplos=com_exemplos),
                              entrada_resumo=f"{resumo}\nEIXO {nome}: {dict((e['nome'], e['pergunta']) for e in EIXOS)[nome]}")
            n += 1
        except _FALHAS_DB + (ValueError,) as e:
            logger.warning("pericia_integral: cruzamento do eixo %s não gravado (%s)", nome, type(e).__name__)
        n += _cruzar_pontos(processo, nome, a, modelo_ref, b, modelo_outro, com_exemplos)
    return n


def _cruzar_pontos(processo: str, eixo: str, a: dict, modelo_ref: str, b: dict, modelo_outro: str,
                   com_exemplos: bool = False) -> int:
    """Um par por ponto de controle em que ao menos um lado decidiu (conforme/desconforme): a padronização no detalhe."""
    pa, pb = a.get("pontos") or {}, b.get("pontos") or {}
    textos = {p["id"]: p["texto"] for e in EIXOS if e["nome"] == eixo for p in e["pontos"]}
    n = 0
    for pid in textos:
        va, vb = _status_ponto(pa.get(pid)), _status_ponto(pb.get(pid))
        if va not in _NIVEL_PONTO and vb not in _NIVEL_PONTO:
            continue
        try:
            cruzamento.cruzar(f"{TAREFA}:{eixo}:{pid}", f"sei:{processo}",
                              cruzamento.Lado("claude", modelo_ref, va, _NIVEL_PONTO.get(va)),
                              cruzamento.Lado("cascata", modelo_outro, vb, _NIVEL_PONTO.get(vb), com_exemplos=com_exemplos),
                              entrada_resumo=f"PONTO {pid}: {textos[pid]}")
            n += 1
        except _FALHAS_DB + (ValueError,) as e:
            logger.warning("pericia_integral: cruzamento do ponto %s não gravado (%s)", pid, type(e).__name__)
    return n


# ── persistência ──────────────────────────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS pericia_integral(
  id INTEGER PRIMARY KEY, rodada TEXT NOT NULL, processo TEXT NOT NULL, eixo TEXT NOT NULL, grau INTEGER,
  achados TEXT, modelo TEXT, provedor TEXT, versao_prompt TEXT, conferido_opus INTEGER DEFAULT 0,
  valor_pago REAL, criado_em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pericia_integral_proc ON pericia_integral(processo, versao_prompt);
CREATE INDEX IF NOT EXISTS ix_pericia_integral_rodada ON pericia_integral(rodada);
"""


def _garantir_tabela(con: sqlite3.Connection) -> None:
    con.executescript(_DDL)


def _con_escrita() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    return con


def gravar(processo: str, eixos: dict, *, modelo: str, provedor: str, conferido_opus: int, valor_pago: float | None,
           extra_global: dict | None = None, con: sqlite3.Connection | None = None) -> str:
    """Acrescenta UMA rodada (linha por eixo + `_global`) num commit curto. Nunca sobrescreve."""
    rodada = uuid.uuid4().hex[:16]
    em = _agora()
    proprio = con is None
    con = con or _con_escrita()
    try:
        _garantir_tabela(con)
        linhas = [(rodada, processo, n, eixos[n]["grau"], json.dumps(eixos[n], ensure_ascii=False), modelo, provedor,
                   VERSAO_PROMPT, conferido_opus, valor_pago, em) for n in NOMES_EIXOS]
        glob = {**(eixos.get("_global") or {}), **(extra_global or {}),
                "descartados": sum(len(eixos[n]["descartados"]) for n in NOMES_EIXOS)}
        linhas.append((rodada, processo, "_global", grau_global(eixos), json.dumps(glob, ensure_ascii=False, default=str),
                       modelo, provedor, VERSAO_PROMPT, conferido_opus, valor_pago, em))
        con.executemany("INSERT INTO pericia_integral(rodada,processo,eixo,grau,achados,modelo,provedor,versao_prompt,"
                        "conferido_opus,valor_pago,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?)", linhas)
        con.commit()
        return rodada
    finally:
        if proprio:
            con.close()


# ── a cascata desta tarefa: Gemini com teto de saída próprio, depois a cascata padrão ─────────────────────
def _cascata_longa(prompt: str, sistema: str = "", timeout: float = TIMEOUT_CASCATA,
                   json_saida: bool = True) -> tuple[str, str]:
    import asyncio

    from compliance_agent import direcionamento_cerebro as dc
    from compliance_agent.llm.free_llm import _em_cooldown, _limpar_cooldown, _marcar_cooldown
    try:
        if dc._gemini_keys() and not _em_cooldown("gemini"):
            msgs = [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}]
            fut = asyncio.run_coroutine_threadsafe(
                dc.gerar_gemini(msgs, max_tokens=MAX_TOKENS_SAIDA, json_saida=json_saida, tarefa=TAREFA), dc._bg_loop())
            txt = fut.result(timeout=timeout)
            if txt and txt.strip():
                _limpar_cooldown("gemini")
                return txt, f"gemini:{getattr(dc, 'ultimo_modelo', '') or '?'}"
    except (RuntimeError, OSError, ValueError, TypeError, KeyError) as e:   # TimeoutError é OSError
        _marcar_cooldown("gemini", e)
        logger.warning("pericia_integral: Gemini de saída longa falhou (%s: %s) — cascata padrão",
                       type(e).__name__, str(e)[:120])
    # 2º degrau (15/11/2026): Gemini sem cota e a cascata padrão sem modelo que coubesse ~65k tokens deixavam a perícia
    # SEM o segundo lado — o cruzamento que padroniza as IAs não acontecia. Modelo :free do catálogo vivo com contexto
    # longo (o guard `_forcar_free` fica no nível baixo: nunca a variante paga).
    txt, modelo = _openrouter_longo(prompt, sistema)
    if txt:
        return txt, modelo
    txt = dc.gerar_sync(prompt, sistema, timeout, json_saida, tarefa=TAREFA)
    return txt, contingencia.modelo_da_cascata()


CTX_MIN_CASCATA = 128_000


def _chat_longo(free_llm, key: str, modelo: str, msgs: list[dict]) -> str:
    """Uma chamada OpenRouter com prazo de perícia (o cliente comum tem 60 s fixos: curto para 10 eixos de saída)."""
    if not modelo.endswith(":free"):
        raise ValueError(f"modelo não-free recusado: {modelo}")
    with httpx.Client(timeout=TIMEOUT_CASCATA + 60) as cli:
        r = cli.post(f"{free_llm.OPENROUTER_BASE}/chat/completions",
                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                              **free_llm.OPENROUTER_HEADERS},
                     json={"model": modelo, "messages": msgs, "max_tokens": MAX_TOKENS_SAIDA})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


def _openrouter_longo(prompt: str, sistema: str) -> tuple[str, str]:
    from compliance_agent.llm import free_llm, openrouter_catalogo
    key = free_llm._openrouter_key()
    if not key:
        return "", ""
    ctx = {m["id"]: m.get("ctx") or 0 for m in openrouter_catalogo.catalogo()}
    msgs = ([{"role": "system", "content": sistema}] if sistema else []) + [{"role": "user", "content": prompt}]
    from compliance_agent.llm import cascata_ajuste      # 404 sai; rebaixado nesta tarefa vai para o fim
    for mid in cascata_ajuste.ordenar(openrouter_catalogo.escolher_varios("documento", n=4), TAREFA,
                                      chave=lambda m: f"openrouter:{m}"):
        if ctx.get(mid, 0) < CTX_MIN_CASCATA:
            continue
        modelo = free_llm._forcar_free(mid)
        try:
            txt = _chat_longo(free_llm, key, modelo, msgs)
        except (httpx.HTTPError, RuntimeError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
            logger.warning("pericia_integral: %s falhou (%s: %s)", modelo, type(e).__name__, str(e)[:120])
            continue
        if txt and txt.strip():
            return txt, f"openrouter:{modelo}"
    return "", ""


# ── uma perícia ───────────────────────────────────────────────────────────────────────────────────────
# Calibração A/B (15/11/2026): concordância de partida cascata × Claude = 52% por eixo (planejamento 1/8, jurídico
# 2/13). Metade das chamadas da cascata recebe divergências anteriores do PRÓPRIO eixo com o veredito do Claude como
# referência; a outra metade é o controle — o cruzamento mede os dois braços (`com_exemplos`), porque prompt mudado
# sem A/B já derrubou recall nesta casa.
FRACAO_CALIBRACAO = float(os.environ.get("JFN_PERICIA_CALIBRACAO", "0"))   # A/B de 16/11: exemplos não ajudaram (44% × 45%) — trocados pelas REGRAS_CALIBRACAO
_TETO_CALIBRACAO = 4000


def bloco_calibracao(k_por_eixo: int = 2) -> str:
    linhas = []
    for e in EIXOS:
        for ex in cruzamento.exemplos(f"{TAREFA}:{e['nome']}", k=k_por_eixo):
            linhas.append(f"- eixo `{e['nome']}` — caso: {str(ex.get('entrada') or '')[:220]} → perito de referência: "
                          f"{str(ex.get('referencia') or '')[:160]}")
    if not linhas:
        return ""
    corpo = "\n".join(linhas)[:_TETO_CALIBRACAO]
    return ("\n\nCALIBRAÇÃO — casos anteriores em que outro modelo divergiu do perito de referência. Aplique o CRITÉRIO "
            "do perito (não copie os casos; eles não são fonte de fatos deste processo):\n" + corpo)


def periciar(pasta: Path | str, *, pensar: Callable | None = None, cascata: Callable | None = None,
             avaliar: Callable | None = None, coletar: Callable | None = None, obs: dict | None = None,
             teto_chars: int | None = None) -> dict:
    entrada = montar_entrada(pasta, avaliar=avaliar, obs=obs, coletar=coletar, teto_chars=teto_chars)
    proc = entrada["processo"]
    if entrada["status"] != "OK":
        return {"processo": proc, "status": entrada["status"]}
    sistema, prompt = montar_prompt(entrada)
    fonte = _fonte_do_prompt(prompt)
    cap: dict = {}
    _pensar = pensar or claude_motor.pensar

    def _p(t, p, **kw):
        kw["backend"] = "cli"                       # só a ASSINATURA: nunca a API paga da Anthropic
        r = _pensar(t, p, **kw)
        cap["claude"] = r
        return r

    def _c(p, s, timeout, json_saida):
        if random.random() < FRACAO_CALIBRACAO:
            bloco = bloco_calibracao()
            if bloco:
                p, cap["com_exemplos"] = p + bloco, True
        try:
            if cascata is not None:
                txt, rot = cascata(p, s, timeout, json_saida), "cascata"
            else:
                txt, rot = _cascata_longa(p, s, timeout, json_saida)
        except (RuntimeError, OSError, ValueError) as e:     # o co-motor só repassa o TIPO; a mensagem fica aqui
            logger.warning("pericia_integral: cascata falhou em %s (%s: %s)", proc, type(e).__name__, str(e)[:200])
            raise
        cap["cascata"], cap["modelo_cascata"] = txt, rot
        return txt

    # sorteio=1.0 desliga o few-shot GLOBAL do co-motor nesta tarefa (o "resumo" dele seriam só instruções); os
    # exemplos úteis são os POR EIXO, em A/B dentro de `_c` (`bloco_calibracao`).
    gerar = comotor.juizo(TAREFA, modelo=claude_motor.MODELO_JUIZO, pensar=_p, cascata=_c, sorteio=lambda: 1.0,
                          espera=ESPERA_TRAVA, timeout_claude=TIMEOUT_CLAUDE)
    try:
        txt = gerar(prompt, sistema, TIMEOUT_CASCATA, item=f"sei:{proc}")
    except RuntimeError as e:
        return {"processo": proc, "status": "SEM_MOTOR", "motivo": str(e)[:200]}
    u = comotor.ultima_chamada()
    exibido = u.get("exibido") or "desconhecido"
    eixos = interpretar(txt, fonte)
    if eixos is None:
        return {"processo": proc, "status": "RESPOSTA_INVALIDA", "motor": exibido}
    do_claude = exibido.startswith("claude:")
    resumo = f"Processo {proc} · pago {_brl(entrada['valor_pago'])} · captura íntegra: {entrada['captura_integra']}"
    cruzados = 0
    r_c, t_o = cap.get("claude"), cap.get("cascata")
    if r_c is not None and t_o:
        eixos_o = interpretar(t_o, fonte)
        if eixos_o is not None:
            cruzados = cruzar_eixos(proc, eixos, f"{r_c.modelo}", eixos_o, cap.get("modelo_cascata") or "cascata",
                                    resumo, com_exemplos=bool(cap.get("com_exemplos")))
    provedor = "claude" if do_claude else (cap.get("modelo_cascata") or exibido).split(":", 1)[0]
    try:
        rodada = gravar(proc, eixos, modelo=exibido if do_claude else (cap.get("modelo_cascata") or exibido),
                        provedor=provedor, conferido_opus=1 if do_claude else 0, valor_pago=entrada["valor_pago"],
                        extra_global={"cobertura": entrada["cobertura"], "captura_integra": entrada["captura_integra"]})
    except _FALHAS_DB as e:
        return {"processo": proc, "status": "NAO_GRAVADO", "motivo": f"{type(e).__name__}: {str(e)[:120]}"}
    return {"processo": proc, "status": "OK", "rodada": rodada, "motor": exibido, "grau_global": grau_global(eixos),
            "graus": {n: eixos[n]["grau"] for n in NOMES_EIXOS}, "cruzados": cruzados,
            "descartados": sum(len(eixos[n]["descartados"]) for n in NOMES_EIXOS),
            "conferencia_pendente": bool(u.get("conferencia_pendente"))}


# ── fila ──────────────────────────────────────────────────────────────────────────────────────────────
def _bytes_texto(pasta: Path) -> int:
    t = pasta / "texto"
    return sum(f.stat().st_size for f in t.glob("*.txt")) if t.is_dir() else 0


def _ja_periciados(con: sqlite3.Connection) -> set[str]:
    try:
        return {_dig(r[0]) for r in con.execute("SELECT DISTINCT processo FROM pericia_integral WHERE versao_prompt=?",
                                                (VERSAO_PROMPT,))}
    except sqlite3.OperationalError:
        return set()                                   # tabela ainda não existe: ninguém periciado


# Natureza (`tools.sei_triagem_pericia.natureza`, a mesma do 360): processo financeiro (empenho→liquidação→OB),
# repasse e compra cancelada não são PROCESSO DE CONTRATAÇÃO — a contratação mora no processo-pai. Sem este
# corte, o 1º da fila em 15/11/2026 era um processo de pagamento de R$ 8 bi com 99 peças de NE/NL/OB.
# `indefinido` entra: sem sinal no título não se presume que não é contratação.
NATUREZAS_CONTRATACAO = ("contratacao", "aditivo", "indefinido")


def _elegivel(pasta: Path, naturezas: tuple[str, ...] | None) -> tuple[bool, str]:
    """(íntegra capturada E natureza de contratação?, natureza)."""
    from compliance_agent.sei import manifesto_norm
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "?"
    man["_pasta"] = str(pasta)
    if not manifesto_norm.captura_integra(man, pasta)[0]:
        return False, "?"
    if naturezas is None:
        return True, "?"
    from tools.sei_triagem_pericia import natureza
    norm = manifesto_norm.normalizar(man)
    nat = natureza(norm, norm["docs"])
    return nat in naturezas, nat


def fila(limite: int, naturezas: tuple[str, ...] | None = NATUREZAS_CONTRATACAO) -> list[dict]:
    """Processos do acervo com íntegra capturada, de natureza de contratação e sem perícia na versão atual do
    prompt, por VALOR PAGO (OB contabilizada no SIAFE) decrescente. `naturezas=None` não filtra a natureza."""
    from tools.lex_execucao import _chave_processo, mapa_obs_siafe
    con = _ro()
    try:
        feitos = _ja_periciados(con)
        cands = []
        for p in (ACERVO.iterdir() if ACERVO.is_dir() else ()):
            if not p.is_dir():
                continue
            numero = numero_da_pasta(p.name)
            if _dig(numero) in feitos:
                continue
            tam = _bytes_texto(p)
            if tam >= MIN_TEXTO:
                cands.append({"pasta": str(p), "numero": numero, "bytes": tam})
        # só ORDENA a fila: autos=False; o processo periciado recalcula com os autos em `_pago`
        obs = mapa_obs_siafe(con, [c["numero"] for c in cands], autos=False) if cands else {}
    finally:
        con.close()
    for c in cands:
        c["ob"] = obs.get(_chave_processo(c["numero"]))
        c["pago"] = round((c["ob"] or {}).get("total", 0.0), 2)
    cands.sort(key=lambda c: (-c["pago"], -c["bytes"]))

    def _elegiveis():                                  # íntegra é cara de medir: só até encher o limite
        for c in cands:
            ok, nat = _elegivel(Path(c["pasta"]), naturezas)
            if ok:
                yield c | {"natureza": nat}
    # FOCO (22/11/2026): metade do lote do período Couto, cada metade na ordem por valor pago (compliance_agent/foco)
    from compliance_agent.foco import data_processo, intercalar
    return intercalar(_elegiveis(), lambda c: data_processo(c["numero"]), limite=limite)


def rodar(limite: int, *, so_cascata: bool = False, naturezas: tuple[str, ...] | None = NATUREZAS_CONTRATACAO,
          pensar: Callable | None = None, cascata: Callable | None = None,
          avaliar: Callable | None = None, coletar: Callable | None = None) -> list[dict]:
    """Periciar os `limite` primeiros da fila. `so_cascata` força a contingência (JFN_CLAUDE_CONTINGENCIA=1):
    o Claude nem é tentado e tudo vai para a fila de conferência do Opus.

    Contingência real (limite de 5 h, teto do motor): `claude_motor.pensar` devolve None NA HORA pelo
    `motivo_desligado` — sem esperar a trava, sem laço — e o processo sai pela cascata para a fila do Opus."""
    from tools.lex_execucao import _chave_processo, mapa_obs_siafe
    antes = os.environ.get("JFN_CLAUDE_CONTINGENCIA")
    if so_cascata:
        os.environ["JFN_CLAUDE_CONTINGENCIA"] = "1"
    try:
        alvos = fila(limite, naturezas)
        # a fila ordenou SEM os autos; o periciado leva a soma COM eles (NL/PD/OB juntadas, GD) — 1 varredura
        con = _ro()
        try:
            com_autos = mapa_obs_siafe(con, [a["numero"] for a in alvos]) if alvos else {}
        finally:
            con.close()
        feitos = []
        for a in alvos:
            a.pop("ob", None)
            ob = com_autos.get(_chave_processo(a["numero"]))
            obs = {_chave_processo(a["numero"]): ob} if ob else {}
            bloqueio = claude_motor.motivo_desligado(tarefa=TAREFA)
            r = periciar(a["pasta"], pensar=pensar, cascata=cascata, avaliar=avaliar, coletar=coletar, obs=obs)
            r["claude_bloqueado"] = bloqueio
            feitos.append(r)
            print(f"[{_agora()}] {a['numero']} pago {_brl(a['pago'])} → {r.get('status')} "
                  f"grau {r.get('grau_global')} motor {r.get('motor')} cruzados {r.get('cruzados', 0)} "
                  f"descartados {r.get('descartados', 0)}" + (f" (Claude: {bloqueio})" if bloqueio else ""))
        return feitos
    finally:
        if so_cascata:
            if antes is None:
                os.environ.pop("JFN_CLAUDE_CONTINGENCIA", None)
            else:
                os.environ["JFN_CLAUDE_CONTINGENCIA"] = antes


# ── aplicador da conferência do Opus (`llm/conferencia_opus.APLICADORES`) ───────────────────────────────
def _entrada_da_fila(item: str) -> str | None:
    from compliance_agent.llm import conferencia_opus
    if not conferencia_opus.caminho().exists():
        return None
    con = sqlite3.connect(conferencia_opus.caminho(), timeout=30)
    try:
        r = con.execute("SELECT entrada FROM fila WHERE tarefa=? AND item=? AND entrada IS NOT NULL "
                        "ORDER BY id DESC LIMIT 1", (TAREFA, item)).fetchone()
    finally:
        con.close()
    return zlib.decompress(r[0]).decode("utf-8", "replace") if r and r[0] else None


def aplicar_conferencia(item: str, resposta: str, modelo: str, concorda, con: sqlite3.Connection | None = None) -> bool:
    """O Opus releu a MESMA entrada que a cascata periciou. Passa pela mesma verificação literal; cruza eixo a
    eixo contra a rodada da cascata; igual em todos os eixos ⇒ a rodada vira conferida (1); diferente em algum ⇒
    nova rodada do Opus (1) e a anterior fica como substituída (2). Sem entrada legível ou sem JSON: não aplica."""
    if not str(item or "").startswith("sei:"):
        return False
    proc = item[4:]
    try:
        prompt = _entrada_da_fila(item)
    except (sqlite3.Error, OSError, zlib.error) as e:
        logger.warning("pericia_integral: entrada da fila ilegível (%s)", type(e).__name__)
        return False
    fonte = _fonte_do_prompt(prompt or "")
    eixos_op = interpretar(resposta, fonte) if fonte else None
    if eixos_op is None:
        return False
    proprio = con is None
    con = con or _con_escrita()
    try:
        _garantir_tabela(con)
        ult = con.execute("SELECT rodada, modelo, valor_pago FROM pericia_integral WHERE processo=? AND "
                          "conferido_opus=0 ORDER BY id DESC LIMIT 1", (proc,)).fetchone()
        if not ult:
            return False
        rodada, modelo_casc, valor = ult
        antes = {e: (g, json.loads(a or "{}")) for e, g, a in con.execute(
            "SELECT eixo, grau, achados FROM pericia_integral WHERE rodada=?", (rodada,))}
        eixos_casc = {n: {"grau": antes.get(n, (None, {}))[0], **antes.get(n, (None, {}))[1]} for n in NOMES_EIXOS}
        con.commit()
        cruzar_eixos(proc, eixos_op, f"{modelo}", eixos_casc, modelo_casc or "cascata",
                     f"Processo {proc} · conferência do Opus")
        iguais = all(eixos_op[n]["grau"] == eixos_casc[n]["grau"] for n in NOMES_EIXOS)
        # Mesmo com os graus iguais, a rodada que fica é a do Opus (18/11/2026): grau igual com fundamento diferente
        # deixava VERIFICADO o achado que o Opus não escreveu. A concordância fica só na proveniência.
        con.execute("UPDATE pericia_integral SET conferido_opus=2 WHERE rodada=?", (rodada,))
        nota = "concordou com" if iguais else "antes"
        gravar(proc, eixos_op, modelo=f"claude:{modelo} (conferência; {nota} {modelo_casc})"[:200], provedor="claude",
               conferido_opus=1, valor_pago=valor, con=con)            # o commit do gravar fecha as duas mudanças
        return True
    finally:
        if proprio:
            con.close()


# ── status ────────────────────────────────────────────────────────────────────────────────────────────
def status() -> dict:
    try:
        con = _ro()
    except sqlite3.Error as e:
        return {"disponivel": False, "motivo": str(e)}
    try:
        try:
            ult = ("SELECT p.* FROM pericia_integral p JOIN (SELECT processo, MAX(id) mid FROM pericia_integral "
                   "WHERE eixo='_global' AND conferido_opus IN (0,1) GROUP BY processo) u ON u.processo=p.processo "
                   "AND p.rodada=(SELECT rodada FROM pericia_integral WHERE id=u.mid)")
            proc = con.execute(f"SELECT COUNT(DISTINCT processo), SUM(conferido_opus=0 AND eixo='_global') "
                               f"FROM ({ult})").fetchone()
            por_eixo = {}
            for eixo, grau, n in con.execute(f"SELECT eixo, grau, COUNT(*) FROM ({ult}) GROUP BY eixo, grau"):
                por_eixo.setdefault(eixo, {})[{None: "indeterminado", 0: "0", 1: "1", 2: "2"}.get(grau, str(grau))] = n
            versoes = dict(con.execute("SELECT versao_prompt, COUNT(DISTINCT processo) FROM pericia_integral "
                                       "GROUP BY versao_prompt").fetchall())
        except sqlite3.OperationalError:
            return {"disponivel": True, "processos": 0, "motivo": "nenhuma perícia integral ainda"}
    finally:
        con.close()
    return {"disponivel": True, "versao_prompt": VERSAO_PROMPT, "processos": proc[0],
            "pendentes_conferencia_opus": proc[1] or 0, "por_eixo": por_eixo, "por_versao": versoes,
            "claude": claude_motor.motivo_desligado(tarefa=TAREFA) or "disponível"}


def _main(argv=None) -> int:
    # o cron não lê o .env; sem isto a cascata não via a chave do OpenRouter (15/11/2026: 2º lado ausente)
    from compliance_agent.envfile import carregar_env
    carregar_env()
    ap = argparse.ArgumentParser(description="Perícia integral por processo de contratação (Claude co-motor)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rodar", help="periciar os N primeiros da fila (por valor pago)")
    r.add_argument("--limite", type=int, default=1)
    r.add_argument("--so-cascata", action="store_true", help="força contingência: cascata + fila do Opus")
    r.add_argument("--todas-naturezas", action="store_true", help="inclui processos de pagamento/repasse")
    sub.add_parser("status")
    sub.add_parser("fila").add_argument("--limite", type=int, default=20)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if a.cmd == "rodar":
        feitos = rodar(a.limite, so_cascata=a.so_cascata,
                       naturezas=None if a.todas_naturezas else NATUREZAS_CONTRATACAO)
        print(json.dumps(feitos, ensure_ascii=False, indent=1, default=str))
    elif a.cmd == "fila":
        print(json.dumps([{k: v for k, v in c.items() if k != "ob"} for c in fila(a.limite)], ensure_ascii=False,
                         indent=1))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
