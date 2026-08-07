# -*- coding: utf-8 -*-
"""Rotas de VÍNCULOS — beneficiário final, parentesco inferido e histórico societário.

Domínio novo, em módulo próprio de propósito: `rotas/investigacao.py` já tem 2.291 linhas e 98
rotas, e somar aqui o que é um eixo inteiro só pioraria o problema. O split por domínio é o mesmo
critério de 2026-07-06 (hermes / produtos / sistema / investigacao).

Todas as rotas deste módulo têm uma obrigação comum: **nenhuma resposta afirma vínculo sem dizer o
que não observou.** Beneficiário final declara a cobertura de QSA da cadeia; parentesco declara a
prevalência do eixo que acendeu; histórico societário responde INDISPONÍVEL — com a diligência
anexa — quando a data pedida está fora da série de snapshots.
"""
from __future__ import annotations

import logging
import re
import sqlite3

# Erros que uma rota de LEITURA do acervo pode ver de verdade: base ocupada/corrompida, esquema
# ausente, argumento fora de forma, módulo opcional ausente. Captura genérica aqui esconderia
# defeito de programação — a catraca de tests/test_catraca_excepts.py cobra isso, e com razão.
_FALHAS_DE_LEITURA = (sqlite3.Error, ValueError, KeyError, TypeError, OSError, ImportError)


from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _db_ro() -> sqlite3.Connection:
    from compliance_agent.reporting.intel_base import _DB
    return sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)


@router.get("/api/osint/contato_compartilhado")
def api_contato_compartilhado(cnpj: str, extras: str = ""):
    """Telefone e e-mail compartilhados — as arestas mais fortes da régua depois de `mesma_sala`.

    ESTAVA TUDO PRONTO E PARADO. `data/receita_estab.db` guarda **6.171.766 estabelecimentos** com
    telefone (83,9%) e e-mail (69,0%), indexados; `osint/contato_compartilhado` implementa
    `mesmo_telefone` (0,70) e `mesmo_email` (0,80) com os guardas todos medidos — telefone-lixo (o
    `00` liga 129.152 empresas), fan-out (43 telefones ligam mais de mil) e e-mail de contabilidade
    (`abertura@maismei.com.br`, 17.665 clientes, que vira `mesmo_contador` a 0,30). Faltava
    consumidor: o docstring do módulo dizia, literalmente, *"dado ingerido, indexado, e sem um
    único consumidor"*.

    O que a primeira amostra real mostrou (120 CNPJs vencedores do acervo, 2026-08-06): **APPA
    SERVIÇOS TEMPORÁRIOS** e **OBJETIVA SERVIÇOS TERCEIRIZADOS** — raízes de CNPJ diferentes, duas
    empresas de terceirização que atendem o poder público — dividem o telefone 1147593220.

    `extras`: outros CNPJs separados por vírgula, para pedir o conjunto de uma vez.
    """
    try:
        from compliance_agent.osint.contato_compartilhado import vinculos_por_contato

        alvos = [c.strip() for c in (cnpj + "," + extras).split(",") if c.strip()]
        return JSONResponse(vinculos_por_contato(alvos))
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("contato_compartilhado falhou")
        return JSONResponse({"erro": str(exc)[:200], "arestas": []}, status_code=200)


@router.get("/api/osint/beneficiario_final")
def api_beneficiario_final(cnpj: str, profundidade: int = 4):
    """G.3 — sobe a cadeia societária de uma PJ até as pessoas físicas.

    Cadeia que não chega a pessoa física NÃO significa que não haja beneficiário: significa lacuna
    de captura, e é o que o campo `motivo` diz. `cobertura` informa quantas empresas da cadeia
    tinham QSA na base — sem isso o leitor não sabe o quanto da subida foi observada.
    """
    try:
        from compliance_agent.osint.fonte_grafo import beneficiario_final_do_cnpj

        return JSONResponse(beneficiario_final_do_cnpj(
            cnpj, profundidade=max(1, min(int(profundidade), 8))))
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("beneficiario_final falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/parentesco")
def api_parentesco(cnpj: str):
    """Hipóteses de vínculo familiar no QSA, com a prevalência de cada eixo acionado.

    Não existe base aberta brasileira de parentesco — o que sai daqui é inferência calibrada por
    prevalência, e o eixo de sobrenome (16,9% da base) nunca acende sozinho.
    """
    try:
        from compliance_agent.osint.parentesco import avaliar

        raiz = "".join(ch for ch in str(cnpj) if ch.isdigit())[:8]
        if len(raiz) < 8:
            return JSONResponse({"ok": False, "erro": "CNPJ inválido"}, status_code=400)
        con = _db_ro()
        try:
            return JSONResponse({"ok": True, **avaliar(con, raiz)})
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("parentesco falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/parentesco/prevalencia")
def api_parentesco_prevalencia():
    """Prevalência de cada eixo NA BASE DE HOJE, contra a calibração declarada.

    Publicar isto é o que impede a calibração de envelhecer em silêncio: um eixo cuja prevalência
    subiu deixou de discriminar, e quem lê o produto tem de poder ver isso.
    """
    try:
        from compliance_agent.osint.parentesco import EIXOS, prevalencia

        p = prevalencia()
        p["declarado"] = {k: {"prevalencia_medida": v.prevalencia_medida,
                              "pode_acender_sozinho": v.pode_acender_sozinho,
                              "descricao": v.descricao} for k, v in EIXOS.items()}
        return JSONResponse({"ok": True, **p})
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("prevalencia falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/vinculo_na_data")
def api_vinculo_na_data(cnpj: str, data: str, nome: str = "", doc: str = ""):
    """*Fulano era sócio desta empresa NESTA data?* — a pergunta que fecha direcionamento.

    Três respostas: SIM, NAO (com a ressalva da defasagem mensal da publicação da Receita) e
    INDISPONIVEL, que é a que importa — perguntar por data fora da série não pode devolver "não
    era sócio". Nesse caso vem o pedido de diligência à JUCERJA.
    """
    try:
        from compliance_agent.osint.historico_societario import vinculo_na_data

        raiz = "".join(ch for ch in str(cnpj) if ch.isdigit())[:8]
        con = _db_ro()
        try:
            return JSONResponse({"ok": True, **vinculo_na_data(
                con, raiz, data, doc_socio=doc, nome=nome)})
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("vinculo_na_data falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/historico_socio")
def api_historico_socio(nome: str = "", doc: str = ""):
    """Todas as sociedades de uma pessoa ao longo da série, com entrada e saída observadas."""
    try:
        from compliance_agent.osint.historico_societario import historico_do_socio

        if not (nome or doc):
            return JSONResponse({"ok": False, "erro": "informe nome ou doc"}, status_code=400)
        con = _db_ro()
        try:
            linhas = historico_do_socio(con, doc_socio=doc, nome=nome)
        finally:
            con.close()
        return JSONResponse({"ok": True, "n": len(linhas), "vinculos": linhas})
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("historico_socio falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/trocas_societarias")
def api_trocas_societarias(cnpj: str, data: str, janela: int = 6):
    """Troca de quadro societário perto de uma data — sócio que entra depois da homologação, ou
    que sai depois do pagamento. O padrão que a linha do tempo sempre quis ler e não tinha fonte."""
    try:
        from compliance_agent.osint.historico_societario import trocas_perto_de

        raiz = "".join(ch for ch in str(cnpj) if ch.isdigit())[:8]
        con = _db_ro()
        try:
            return JSONResponse({"ok": True, **trocas_perto_de(
                con, raiz, data, meses_janela=max(1, min(int(janela), 36)))})
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("trocas_societarias falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/serie_societaria")
def api_serie_societaria():
    """Estado da série de snapshots: o denominador que impede ler silêncio como limpeza.

    Enquanto houver um único snapshot, saída de sócio é inobservável — e o painel tem de mostrar
    isso, não esconder.
    """
    try:
        from compliance_agent.osint.fonte_grafo import cobertura_qsa
        from compliance_agent.osint.historico_societario import snapshots_ingeridos

        con = _db_ro()
        try:
            meses = snapshots_ingeridos(con)
            try:
                por_status = dict(con.execute(
                    "SELECT status, COUNT(*) FROM socio_historico GROUP BY status").fetchall())
            except sqlite3.Error:
                por_status = {}
        finally:
            con.close()
        return JSONResponse({
            "ok": True,
            "snapshots": meses,
            "n_snapshots": len(meses),
            "cobertura": f"{meses[0]} a {meses[-1]}" if meses else None,
            "vinculos_por_status": por_status,
            "qsa": cobertura_qsa(),
            "fonte": ("espelho público dados-abertos-rf-cnpj.casadosdados.com.br — 41 snapshots "
                      "mensais de 2023-03 a 2026-07, sem chave e sem custo. Os caminhos oficiais da "
                      "Receita respondem 404 desde janeiro/2026."),
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("serie_societaria falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/conluio_municipal")
def api_conluio_municipal(limite: int = 200):
    """E.3.2 municipal — vencedor × perdedora com sócio em comum nos certames do TCE-RJ.

    O eixo devolvia zero por falta de DADO, não de motor: eram 114 certames com classificado além do
    1º lugar em todo o acervo. A cadeia que o destravou está medida na resposta (`cobertura`), degrau
    a degrau — e o denominador importa tanto quanto o achado: certame fora de `cruzaveis` não é
    certame limpo, é certame não observado.
    """
    try:
        from compliance_agent.osint.qsa_certame_municipal import cruzar_certames

        con = _db_ro()
        try:
            return JSONResponse(cruzar_certames(con, limite=max(0, min(int(limite), 2000))))
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("conluio_municipal falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/resolucao_nome_cnpj")
def api_resolucao_nome_cnpj():
    """Estado da resolução razão social → CNPJ pelo catálogo nacional da Receita.

    É o denominador de tudo que depende de partir de um nome. Nome ambíguo fica com CNPJ NULO —
    declarado, nunca chutado.
    """
    try:
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from tools.resolver_nome_cnpj import relatorio

        con = _db_ro()
        try:
            return JSONResponse({"ok": True, **relatorio(con)})
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("resolucao_nome_cnpj falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/interposicao")
def api_interposicao(cnpj: str, data_referencia: str = ""):
    """G.4 — perfil de laranja no QSA, calibrado por PREVALÊNCIA de cada eixo.

    Foi o módulo que ensinou a lição: marcava 55% da base até alguém medir que "empresa com um só
    sócio" é 54,9% do normal e sócio com mais de 80 anos é 1,87%. Depois da calibragem, 1,4%.
    Existia só em CLI desde então.
    """
    try:
        from compliance_agent.osint.interposicao import avaliar

        raiz = "".join(ch for ch in str(cnpj) if ch.isdigit())[:8]
        if len(raiz) < 8:
            return JSONResponse({"ok": False, "erro": "CNPJ inválido"}, status_code=400)
        con = _db_ro()
        try:
            return JSONResponse({"ok": True, **avaliar(
                con, raiz, data_referencia=data_referencia or None)})
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("interposicao falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/patrimonio")
def api_patrimonio(cnpj: str = "", nome: str = ""):
    """G.2 — capacidade declarada × recebimento público.

    Sem renda conhecida o veredito é `nao_aferivel`, **nunca** "renda incompatível": a distinção
    entre fachada e enriquecimento depende de saber o que a pessoa declara, e quase sempre não se
    sabe.
    """
    try:
        import sqlite3 as _sq

        from compliance_agent.osint.patrimonio import avaliar_empresa, avaliar_pessoa

        con = _db_ro()
        con.row_factory = _sq.Row
        try:
            if cnpj:
                raiz = "".join(ch for ch in str(cnpj) if ch.isdigit())[:8]
                r = con.execute(
                    "SELECT razao_social, capital_social FROM empresas_cadastro WHERE cnpj_basico=?",
                    (raiz,)).fetchone()
                pago = con.execute(
                    "SELECT COALESCE(SUM(valor),0) FROM ordens_bancarias "
                    "WHERE substr(REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-',''),1,8)=?",
                    (raiz,)).fetchone()[0]
                return JSONResponse({"ok": True, **avaliar_empresa(
                    razao_social=(r["razao_social"] if r else "") or raiz,
                    capital_social=(r["capital_social"] if r else None),
                    valor_pago_ob=pago)})
            if nome:
                return JSONResponse({"ok": True, **avaliar_pessoa(nome=nome)})
            return JSONResponse({"ok": False, "erro": "informe cnpj ou nome"}, status_code=400)
        finally:
            con.close()
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("patrimonio falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/agente_publico")
def api_agente_publico(so_comissionados: int = 0, limite: int = 60, filtro: str = ""):
    """Fila de agente público × entidade que recebeu dinheiro público.

    A fila nasceu em linha de comando e ficou lá — o mesmo "construído, testado, nunca rodado" que
    esta casa já corrigiu seis vezes. Aqui ela ganha superfície, com as ressalvas coladas ao dado:
    o casamento é por NOME (a folha não traz CPF utilizável e o dump traz o CPF mascarado), a
    explicação institucional vai declarada ao lado do par, e o valor vem SEPARADO POR FONTE porque
    OB estadual, despesa municipal e emenda federal não são a mesma coisa.
    """
    try:
        import json

        from tools.agente_publico_reverso import _FILA_JSON

        # SÓ LÊ O ARQUIVO. Calcular aqui custava 22,3 s por request — a fila remonta o dicionário de
        # 5,86 milhões de razões sociais. Quem escreve é o sweep, como já faz `/api/tac/ranking`.
        if not _FILA_JSON.exists():
            return JSONResponse({"ok": False, "erro": (
                "fila ainda não materializada — rode `python -m tools.agente_publico_reverso` "
                "(o sweep diário a regenera)")}, status_code=503)
        corpo = json.loads(_FILA_JSON.read_text(encoding="utf-8"))
        itens = corpo.get("itens") or []
        if so_comissionados:
            itens = [x for x in itens if x.get("comissionado")]
        # O FILTRO É APLICADO NA FILA INTEIRA, NUNCA NA PÁGINA. Filtrar depois do corte fazia o
        # clique contradizer o próprio KPI: o cartão dizia 68 comissionados e a fatia mostrava 55,
        # porque só os 60 primeiros tinham chegado ao navegador. Métrica que não bate com o que o
        # clique mostra é pior do que métrica sem clique.
        _FATIAS = {
            "apComissionados": lambda x: x.get("comissionado"),
            "apTerceiroSetor": lambda x: x.get("terceiro_setor"),
            "apExplicados": lambda x: bool(x.get("explicacao_institucional")),
            "apNovos": lambda x: bool(x.get("novo")),
            "apConflito": lambda x: bool(x.get("orgao_pagador_e_o_proprio")),
        }
        fn = _FATIAS.get(filtro)
        if fn:
            itens = [x for x in itens if fn(x)]
        return JSONResponse({
            "ok": True,
            "gerado_em": corpo.get("gerado_em"),
            "total": corpo.get("total"),
            "comissionados": corpo.get("comissionados"),
            "terceiro_setor": corpo.get("terceiro_setor"),
            "com_explicacao_institucional": corpo.get("com_explicacao_institucional"),
            "novos": corpo.get("novos", 0),
            "fila_md": corpo.get("fila_md"),
            "filtro": filtro or "apTodos",
            "total_fatia": len(itens),
            "itens": itens[:max(1, min(int(limite), 500))],
            "ressalva": (
                "INDÍCIO, nunca prova. O casamento é por NOME NORMALIZADO: a folha não traz CPF "
                "utilizável e a Receita entrega o CPF do sócio mascarado. Nomes com mais de um CPF "
                "no índice já foram excluídos, mas os que ficam podem ser homônimos sem que a base "
                "o mostre. Servidor PODE ser sócio — o que se afirma aqui é que há o que conferir."),
            "fontes": (
                "socios_full.csv.zst (QSA nacional, 27,6 mi de linhas) × folhas do Estado e da "
                "ALERJ; dinheiro por OB do SIAFE, despesa paga do município (2019-2023), emenda "
                "federal na fase de pagamento e contrato municipal (procedência, não valor)"),
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("agente_publico falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/processos")
def api_osint_processos(limite: int = 80, so_conflito: int = 0):
    """Processos já lidos cuja empresa tem sinal OSINT — a correlação que faltava.

    Inteligência sobre empresa não fiscaliza nada sozinha: quem fiscaliza abre AUTOS. Aqui a fila
    de agente público (já sem homônimo comprovado e sem o que é desenho de programa) encontra as
    fichas de processo que citam aquele CNPJ.
    """
    try:
        import json

        from tools.osint_x_processos import _SAIDA_JSON

        if not _SAIDA_JSON.exists():
            return JSONResponse({"ok": False, "erro": (
                "correlação ainda não materializada — rode `python -m tools.osint_x_processos` "
                "(o sweep diário a regenera)")}, status_code=503)
        corpo = json.loads(_SAIDA_JSON.read_text(encoding="utf-8"))
        itens = corpo.get("achados") or []
        if so_conflito:
            itens = [x for x in itens
                     if any(a.get("conflito_pelo_processo") or a.get("conflito_de_orgao")
                            for a in x.get("agentes") or [])]
        return JSONResponse({
            "ok": True,
            "gerado_em": corpo.get("gerado_em"),
            "processos_com_cnpj": corpo.get("processos_com_cnpj"),
            "total": corpo.get("com_achado"),
            "total_fatia": len(itens),
            "itens": itens[:max(1, min(int(limite), 500))],
            "ressalva": (
                "INDÍCIO, nunca prova. A ponte processo→empresa vem do CNPJ citado na FICHA; a "
                "ponte empresa→pessoa vem do casamento por NOME com as folhas. Ausência de QSA "
                "capturado é LACUNA de captura, não limpeza."),
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("osint_processos falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/elos_ocultos")
def api_elos_ocultos(limite: int = 60, so_sem_explicacao: int = 0):
    """Empresas que dividem contato E ambas recebem do Estado — o elo que ninguém declarou."""
    try:
        import json

        from tools.elos_ocultos import _SAIDA

        if not _SAIDA.exists():
            return JSONResponse({"ok": False, "erro": (
                "levantamento ainda não materializado — rode `python -m tools.elos_ocultos` "
                "(o sweep diário o regenera)")}, status_code=503)
        corpo = json.loads(_SAIDA.read_text(encoding="utf-8"))
        itens = corpo.get("itens") or []
        if so_sem_explicacao:
            itens = [x for x in itens if not x.get("mesmo_grupo_aparente")]
        return JSONResponse({
            "ok": True, "gerado_em": corpo.get("gerado_em"),
            "arestas_de_contato": corpo.get("arestas_de_contato"),
            "estruturais": corpo.get("estruturais"),
            "total": corpo.get("os_dois_lados_pagos"),
            "mesmo_grupo_aparente": corpo.get("mesmo_grupo_aparente"),
            "sem_explicacao": corpo.get("sem_explicacao"),
            "total_fatia": len(itens),
            "itens": itens[:max(1, min(int(limite), 300))],
            "ressalva": (
                "INDÍCIO, nunca prova. Telefone e e-mail vêm do cadastro da Receita e podem ser de "
                "escritório de contabilidade, central de atendimento ou grupo econômico legítimo. "
                "Grupo econômico é LÍCITO — o que ele não pode é disputar o mesmo certame fingindo "
                "concorrência (art. 337-F do Código Penal; Lei 12.529/2011)."),
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("elos_ocultos falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/osint/cocontato_certame")
def api_cocontato_certame(limite: int = 60, so_sem_explicacao: int = 0):
    """Dois participantes do MESMO certame atendendo pelo mesmo telefone ou e-mail."""
    try:
        import json

        from tools.cocontato_certame import SAIDA

        if not SAIDA.exists():
            return JSONResponse({"ok": False, "erro": (
                "levantamento ainda não materializado — rode "
                "`python -m tools.cocontato_certame` (o sweep diário o regenera)")},
                status_code=503)
        corpo = json.loads(SAIDA.read_text(encoding="utf-8"))
        pares = corpo.get("pares") or []
        if so_sem_explicacao:
            pares = [p for p in pares
                     if not p.get("contato_de_servico") and not p.get("mesmo_grupo_aparente")]
        return JSONResponse({
            "ok": True, "gerado_em": corpo.get("gerado_em"),
            "certames_com_disputa": corpo.get("certames_com_disputa"),
            "cnpjs_participantes": corpo.get("cnpjs_participantes"),
            "total": len(corpo.get("pares") or []),
            "sem_explicacao": corpo.get("sem_explicacao"),
            "contato_de_servico": corpo.get("contato_de_servico"),
            "mesmo_grupo_aparente": corpo.get("mesmo_grupo_aparente"),
            "total_fatia": len(pares),
            "itens": pares[:max(1, min(int(limite), 300))],
            "ressalva": (
                "INDÍCIO, nunca prova. Telefone e e-mail vêm do cadastro da Receita e podem estar "
                "desatualizados ou ser de escritório contábil. O que se afirma é que dois "
                "participantes do MESMO certame atendem pelo mesmo contato — cabe verificar as "
                "propostas, os sócios e se houve disputa real (art. 337-F do Código Penal)."),
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("cocontato_certame falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/assinaturas")
def api_pcrj_assinaturas(limite: int = 80, so_identificadas: int = 0):
    """Quem assinou cada despacho da Prefeitura — matrícula publicada pelo SEI × folha municipal.

    Identificação por CADASTRO, não por nome: a matrícula vem do próprio órgão. É a ponte que faz
    a pergunta da fila de agente público valer também para o município.
    """
    try:
        import json

        from tools.pcrj_assinaturas_x_folha import SAIDA
        from tools.pcrj_signatario_x_qsa import SAIDA as SAIDA_QSA

        if not SAIDA.exists():
            return JSONResponse({"ok": False, "erro": (
                "identificação ainda não materializada — rode "
                "`python -m tools.pcrj_assinaturas_x_folha` (o sweep diário a regenera)")},
                status_code=503)
        corpo = json.loads(SAIDA.read_text(encoding="utf-8"))
        itens = corpo.get("itens") or []
        if so_identificadas:
            itens = [x for x in itens if x.get("identificada")]
        qsa = {}
        if SAIDA_QSA.exists():
            q = json.loads(SAIDA_QSA.read_text(encoding="utf-8"))
            qsa = {"no_qsa_nacional": q.get("no_qsa_nacional"),
                   "vinculos_societarios": q.get("vinculos_societarios"),
                   "com_empresa_paga_pela_prefeitura": q.get("com_empresa_paga_pela_prefeitura"),
                   "ressalva_qsa": q.get("ressalva")}
        return JSONResponse({
            "ok": True, "gerado_em": corpo.get("gerado_em"),
            "total": corpo.get("assinaturas"),
            "matriculas": corpo.get("matriculas"),
            "identificadas": corpo.get("identificadas"),
            "ambiguas": corpo.get("ambiguas"),
            "nao_identificadas": corpo.get("nao_identificadas"),
            "top_signatarios": corpo.get("top_signatarios") or [],
            "total_fatia": len(itens),
            "itens": itens[:max(1, min(int(limite), 500))],
            "ressalva": corpo.get("ressalva"), **qsa,
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("pcrj_assinaturas falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/fiscal/fila")
def api_fiscal_fila(limite: int = 60, so_osint: int = 0):
    """A FILA DO FISCAL — a ordem em que os autos devem ser abertos.

    Ela existia só como markdown em disco: quem quisesse a prioridade da casa tinha de abrir um
    arquivo. Aqui ela chega ao painel com a régua declarada — pontos por QUALIDADE do achado, não
    por score cru, porque o score satura no topo em processo grande.
    """
    try:
        import subprocess
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        r = subprocess.run(
            [str(raiz / ".venv" / "bin" / "python"),
             str(raiz / "tools" / "processo_360_ranking.py"), "--top", str(max(1, min(limite, 300)))],
            capture_output=True, text=True, timeout=300, cwd=str(raiz), check=False)
        if r.returncode != 0:
            return JSONResponse({"ok": False, "erro": "ranking não pôde ser calculado"},
                                status_code=503)
        itens, resumo = [], ""
        for linha in r.stdout.splitlines():
            m = re.match(r"\s*(\d+)\.\s*\[\s*(\d+) pts\]\s+(\S+)\s+\(([^)]+)\)\s+—\s*(.*)",
                         linha)
            if m:
                itens.append({"posicao": int(m.group(1)), "pontos": int(m.group(2)),
                              "processo": m.group(3), "grau": m.group(4),
                              "motivos": m.group(5).strip(),
                              "osint": "OSINT:" in m.group(5)})
            elif "processos avaliados" in linha:
                resumo = linha.strip()
        if so_osint:
            itens = [x for x in itens if x["osint"]]
        return JSONResponse({
            "ok": True, "total": len(itens),
            "com_osint": sum(1 for x in itens if x["osint"]),
            "resumo": resumo, "itens": itens,
            "regua": ("Pontos por QUALIDADE do achado, não por score cru — o score de convergência "
                      "satura no topo em processo grande. Vício LIDO NOS AUTOS pesa mais que "
                      "indício sobre a empresa: pagamento sem execução vale 5; o sinal OSINT mais "
                      "forte (autos no próprio órgão do agente) vale 3."),
        })
    except _FALHAS_DE_LEITURA as exc:
        logger.exception("fiscal_fila falhou")
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
