# -*- coding: utf-8 -*-
"""Rotas da Prefeitura do Rio (`/api/pcrj/*`): comissionados, fantasmas, gastos, aditivos, DOE e o acervo de
íntegras dos contratos do Município.

Saiu de `rotas/investigacao.py` na O7.6 (2026-11-25), sem mudar comportamento: mesmas rotas, mesmos corpos.
O cache do painel e os ajudantes (`_ro`, `_cache_calc`…) continuam em `rotas/investigacao.py` e são importados de lá
(o materializador e os testes redirecionam aqueles nomes naquele módulo)."""
from __future__ import annotations

import json
import re
import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rotas.investigacao import _cache_get, _cache_put, _ro, logger

router = APIRouter()


@router.get("/api/pcrj/comissionados_candidatos")
def api_pcrj_comissionados_candidatos(limite: int = 300):
    """Comissionados da PREFEITURA do Rio que foram CANDIDATOS (TSE) — tabela
    pcrj_comissionado_candidato (data/pcrj.db, coletor pcrj/comissionados_candidatos).
    Agregado por PESSOA (nome_norm): 1 entrada por pessoa com a lista de postos
    (nomeações) e candidaturas no histórico — a tabela tem 1 linha por (pessoa, órgão,
    cargo, admissão), e a variação textual de orgao_pcrj entre coletas mensais duplicava
    o mesmo vínculo em várias linhas (achado 2026-07-21); `limite` agora é por PESSOA,
    não por linha bruta. Padrão de agrupamento espelha pericia.py::_tabela_comissionados_cand."""
    try:
        lim = max(1, min(int(limite or 300), 1000))
        ck = f"pcrj:comis_cand:v3:{lim}"  # v3: identidade (homônimo visível no TSE/folha)
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _ro("pcrj.db", linhas=True)
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT nome_norm, nome_pcrj, cargo_pcrj, orgao_pcrj, admissao, exoneracao, "
                "matricula, cand_ano, cand_cargo, cand_cidade FROM pcrj_comissionado_candidato")]
            n_linhas = len(rows)
        finally:
            con.close()

        from compliance_agent.pcrj.comissionados_candidatos import agrupar_por_pessoa, pessoas_tse_por_nome
        out_pessoas = agrupar_por_pessoa(rows, pessoas_tse_por_nome())
        n_pessoas = len(out_pessoas)
        truncado = len(out_pessoas) > lim
        out_pessoas = out_pessoas[:lim]

        out = {"ok": True, "n": n_linhas, "n_pessoas": n_pessoas, "truncado": truncado,
               "comissionados": out_pessoas,
               "explicacao": ("Cruzamento por nome entre a folha de comissionados da Prefeitura do "
                              "Rio e as candidaturas do TSE. Comissionado que concorreu (ou concorre) "
                              "a cargo eletivo é sinal de aparelhamento político do cargo de confiança. "
                              "Cada pessoa aparece uma vez, com o histórico de nomeações abaixo."),
               "identidade": ("INDETERMINADO — a folha da Prefeitura não publica CPF; só o nome liga as bases. "
                              "Quando o TSE mostra candidatos DIFERENTES (CPF/título) com o mesmo nome, o item "
                              "sai marcado como homônimo."),
               "n_homonimo_visivel": sum(1 for p in out_pessoas if p.get("homonimo_provavel")),
               "ressalva": "Match por NOME (homônimo possível) — confirmar por CPF antes de citar. Não é achado."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/fantasmas")
def api_pcrj_fantasmas(faixa: str = "", limite: int = 200):
    """Servidor-fantasma na folha da Câmara/PCRJ — 8 sinais determinísticos (pcrj/fantasma_servidor),
    cache materializado em pcrj_fantasma_servidor. ?faixa=forte|verificar|fraco filtra."""
    try:
        lim = max(1, min(int(limite or 200), 800))
        fx = faixa if faixa in ("forte", "verificar", "fraco") else ""
        ck = f"pcrj:fantasma:{fx}:{lim}"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _ro("pcrj.db", linhas=True)
        try:
            cond = "WHERE faixa=?" if fx else ""
            args = ([fx] if fx else []) + [lim]
            rows = [dict(r) for r in con.execute(
                f"""SELECT nome, gabinetes, cargos_camara, sinais, score, faixa, homonimo, gerado_em
                    FROM pcrj_fantasma_servidor {cond}
                    ORDER BY CASE faixa WHEN 'forte' THEN 0 WHEN 'verificar' THEN 1 ELSE 2 END,
                             score DESC LIMIT ?""", args)]
            faixas = dict(con.execute(
                "SELECT faixa, COUNT(*) FROM pcrj_fantasma_servidor GROUP BY faixa").fetchall())
            gerado = con.execute("SELECT MAX(gerado_em) FROM pcrj_fantasma_servidor").fetchone()[0]
        finally:
            con.close()
        if not rows and not faixas:
            return JSONResponse({"ok": False, "erro": "detector ainda não rodou — "
                                 "rodar: python -m compliance_agent.pcrj.fantasma_servidor"})
        out = {"ok": True, "n": sum(faixas.values()), "faixas": faixas, "itens": rows,
               "gerado_em": gerado,
               "explicacao": ("Sinais objetivos de servidor-fantasma (múltiplos gabinetes, cargo "
                              "incompatível, vínculo concomitante, geografia impossível…) somados em "
                              "escore. Faixa FORTE exige identidade conferida por documento; as folhas "
                              "da Prefeitura e da Câmara não publicam CPF e os sinais ligam as bases só "
                              "pelo NOME, então o teto é VERIFICAR (fila de diligência, não achado)."),
               "identidade": "INDETERMINADO — só o nome liga as bases (sem CPF na folha municipal)",
               "ressalva": ("Indício ≠ acusação. `homonimo`=1 marca nome presente em ≥3 municípios "
                            "(ambiguidade — confirmar por CPF/matrícula antes de qualquer citação).")}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/gastos_achados")
def api_pcrj_gastos_achados(limite_por_detector: int = 40):
    """Achados da perícia de gastos da PREFEITURA (D7 fracionamento · D8 recém-aberta · D9 sócio na
    folha · D10 rede de sócios entre concorrentes · aditivo estourado) — lê os alertas gravados pela
    última corrida de tools/pcrj_pericia_gastos.py (dedup por título, mais recente vence)."""
    try:
        lim = max(5, min(int(limite_por_detector or 40), 200))
        ck = f"pcrj:gastos:{lim}"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        con = _ro(linhas=True)
        try:
            rows = con.execute(
                """SELECT tipo, severidade, titulo, descricao, evidencias, MAX(id) id
                   FROM alertas WHERE tipo LIKE 'pcrj_d%' GROUP BY titulo
                   ORDER BY CASE severidade WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, id DESC
                """).fetchall()
        finally:
            con.close()
        # Agrupamento, filtro de esfera e contagem moram em `pericia_gastos.agrupar_alertas` (testável):
        # só alerta de órgão PROVADO municipal do Rio; `detectores` é o total real, não o tamanho da lista cortada.
        from compliance_agent.pcrj.pericia_gastos import agrupar_alertas
        g = agrupar_alertas([dict(r) for r in rows], lim)
        por_det = g["achados"]
        out = {"ok": True, "detectores": g["detectores"], "exibidos": g["exibidos"], "achados": por_det,
               "esfera": "municipal-rio", "fora_da_esfera": g["fora_da_esfera"],
               "nota_esfera": g["nota_esfera"],
               "explicacao": ("Perícia determinística sobre despesa por credor (CGM 2019-2023) + "
                              "contratos/licitações municipais (PNCP 2024+): fracionamento colado no "
                              "teto de dispensa, credor recém-aberto, sócio de credor na folha, rede "
                              "societária entre concorrentes e aditivo acima do art. 125."),
               "ressalva": "Indício ≠ acusação; match por NOME vem sinalizado; só a apuração fecha."}
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/aditivos")
def api_pcrj_aditivos():
    """D11 da Prefeitura contrato a contrato — acréscimos computáveis por termo × teto do art. 125,
    estado (VERIFICADO = provado no termo; PENDENTE = sinal sem prova, com o motivo) e a COBERTURA
    de termos coletados, que é o "de quantos?" do zero. Mesma régua do alerta (só leitura)."""
    try:
        ck = "pcrj:aditivos"
        if d := _cache_get(ck, 600):
            return JSONResponse(d)
        from compliance_agent.pcrj.pericia_gastos import d11_avaliacao
        con = _ro(linhas=True, timeout=30)
        try:
            av = d11_avaliacao(con)
        finally:
            con.close()
        cob = av["cobertura"]
        out = {"ok": True, **av,
               "estado_cobertura": ("VERIFICADO" if cob["com_aditivo_declarado"] and
                                    cob["termos_consultados"] >= cob["com_aditivo_declarado"]
                                    else "PENDENTE"),
               "explicacao": ("Soma dos acréscimos quantitativos NOS TERMOS ADITIVOS publicados no "
                              "PNCP sobre o valor inicial, contra o teto do art. 125 da Lei "
                              "14.133/2021 (25%; 50% só para reforma de edifício ou equipamento; "
                              "até o teto é lícito). Reajuste, repactuação, reequilíbrio (arts. 124 "
                              "II-d, 134 e 135), prorrogação e supressão ficam fora. Só VERIFICADO "
                              "vira alerta."),
               "ressalva": ("Base = valor inicial publicado, não o atualizado que a lei manda usar. "
                            "Valor global maior que o inicial NÃO é acréscimo (o global do PNCP "
                            "cobre o período). Pagamento por contrato: INDISPONÍVEL — a despesa "
                            "CGM é por credor e cobre 2019–2023. Indício ≠ acusação.")}
        return JSONResponse(_cache_put(ck, out))
    except (sqlite3.Error, OSError, KeyError, ValueError) as exc:  # base travada/ausente ou dado torto
        logger.warning("api_pcrj_aditivos: %s", exc)
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/beneficios_vinculo")
def api_pcrj_beneficios_vinculo():
    """Comissionados/servidores municipais × benefício social (Bolsa Família etc.) DURANTE o vínculo
    (fairness: só o mês dentro da janela de vínculo conta). Lê o cache materializado — a perícia
    cruza 7,3 mi de registros e NUNCA roda no request."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("beneficios_vinculo")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/doe_concentracao")
def api_pcrj_doe_concentracao(min_atas: int = 2, min_valor: float = 100_000.0):
    """Concentração de vencedor nas Atas de Registro de Preços mineradas do D.O. RIO
    (pcrj_doe_materia → eventos). CNPJ que vence ≥min_atas atas com valor material —
    sinal de concentração/captura na fonte municipal. Determinístico, roda em ms."""
    try:
        ck = f"pcrj:doe_conc:{int(min_atas)}:{int(min_valor)}"
        if d := _cache_get(ck, 900):
            return JSONResponse(d)
        from compliance_agent.pcrj.doe_minerador import concentracao_vencedor
        out = concentracao_vencedor(min_atas=int(min_atas), min_valor=float(min_valor))
        out["explicacao"] = ("Vencedor recorrente de atas de registro de preços no D.O. do "
                             "Município (fonte OCR). Cobertura = matérias já colhidas pelo doweb; "
                             "INDISPONÍVEL ≠ 0 — a cobertura cresce com o harvest do Diário.")
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pcrj/doe_canal_informal")
def api_pcrj_doe_canal_informal():
    """Canais @gmail.com usados como via de compra por órgão municipal (pesquisa de mercado /
    retirada de empenho por e-mail pessoal) — minerado do D.O. RIO. Baixa transparência,
    vetor de direcionamento (contorna o processo formal SIGA/SEI)."""
    try:
        ck = "pcrj:doe_gmail"
        if d := _cache_get(ck, 900):
            return JSONResponse(d)
        from compliance_agent.pcrj.doe_minerador import canal_informal
        out = canal_informal()
        out["explicacao"] = ("Compra pública conduzida por e-mail pessoal @gmail.com (gratuito, "
                             "sem rastro institucional). Indício de fragilidade de controle interno "
                             "e de canal informal fora do processo administrativo formal.")
        return JSONResponse(_cache_put(ck, out))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


# ── Acervo de íntegras dos contratos do Município do Rio ────────────────────────────────────
# Capturado do PNCP (o SEI público municipal indexa só cadastro de representação — medido em
# 2026-09-02, 0/9 processos de contratação com controle positivo 1/1). O texto vem do PDF
# assinado; `fonte_texto` distingue nativo de OCR, porque OCR erra e o achado precisa saber.
_CNPJ_MUNICIPIO_RIO = "42498733000148"


def _con_integras():
    """sqlite3 nativo: pcrj_contratos tem linhas de outros entes com colunas deslocadas que
    derrubam o scanner do DuckDB na LEITURA, antes de qualquer cast."""
    return _ro()


@router.get("/api/pcrj/integras")
def api_pcrj_integras(q: str = "", modalidade: str = "", fonte: str = "",
                      ordem: str = "valor", limite: int = 200):
    """Lista as íntegras capturadas. `q` casa fornecedor, objeto do contrato ou nº de processo."""
    con = _con_integras()
    try:
        con.execute("SELECT 1 FROM contrato_integra LIMIT 1")
    except sqlite3.OperationalError:
        return JSONResponse({"itens": [], "total": 0, "aviso": "acervo ainda não capturado"})
    where, args = ["1=1"], []
    if q:
        where.append("(upper(fornecedor_nome) LIKE ? OR upper(titulo) LIKE ? "
                     "OR processos_sei LIKE ? OR numero_controle_pncp LIKE ?)")
        args += [f"%{q.upper()}%", f"%{q.upper()}%", f"%{q}%", f"%{q}%"]
    if fonte in ("nativo", "ocr"):
        where.append("coalesce(fonte_texto,'nativo') = ?")
        args.append(fonte)
    ordens = {"valor": "CAST(valor_global AS REAL) DESC",
              "recente": "coletado_em DESC", "texto": "n_chars DESC"}
    sql = (f"SELECT numero_controle_pncp, fornecedor_nome, valor_global, titulo, url, n_chars, "
           f"processos_sei, estado, coalesce(fonte_texto,'nativo'), ano "
           f"FROM contrato_integra WHERE {' AND '.join(where)} "
           f"ORDER BY {ordens.get(ordem, ordens['valor'])} LIMIT ?")
    linhas = con.execute(sql, args + [max(1, min(limite, 2000))]).fetchall()
    total = con.execute("SELECT count(*) FROM contrato_integra").fetchone()[0]
    legiveis = con.execute("SELECT count(*) FROM contrato_integra WHERE estado='TEXTO_OK'").fetchone()[0]
    # ERRO_REDE é fila, NÃO é processado: contá-lo na cobertura infla o placar — foi o que
    # transformou 46,7% em "69,4%" antes. Cobertura mede o que foi de fato lido ou decidido.
    processados = con.execute(
        "SELECT count(*) FROM contrato_integra WHERE estado <> 'ERRO_REDE'").fetchone()[0]
    na_fila = con.execute(
        "SELECT count(*) FROM contrato_integra WHERE estado = 'ERRO_REDE'").fetchone()[0]
    universo = con.execute("SELECT count(*) FROM pcrj_contratos WHERE orgao_cnpj=?",
                           [_CNPJ_MUNICIPIO_RIO]).fetchone()[0]
    # SINAIS do cruzamento íntegra × D.O. (tools/pcrj_integra_x_doe, noturno no cruzador.sh). Só sinal
    # positivo; contrato sem sinal é contrato sem sinal, não contrato limpo — a cobertura do D.O. é parcial.
    sinais_por: dict[str, list] = {}
    sinais_total = 0
    try:
        for num, grau, sinal, det in con.execute(
                "SELECT numero_controle_pncp, grau, sinal, detalhe FROM contrato_doe_sinal"):
            sinais_por.setdefault(num, []).append({"grau": grau, "sinal": sinal, "detalhe": det})
            sinais_total += 1
    except sqlite3.OperationalError:       # tabela ainda não materializada: sem sinais, sem erro
        logger.debug("investigacao.py:2724: exceção ignorada (era except-pass mudo)", exc_info=True)
    con.close()
    itens = [{
        "numero": r[0], "fornecedor": r[1], "valor": float(r[2] or 0), "titulo": r[3],
        "url_pncp": r[4], "n_chars": r[5] or 0,
        "processos_sei": json.loads(r[6] or "[]"), "estado": r[7], "fonte_texto": r[8],
        "ano": r[9],
    } for r in linhas]
    for it in itens:
        it["sinais"] = sorted(sinais_por.get(it["numero"], []), key=lambda s: s["grau"] != "🔴")
    return JSONResponse({
        "itens": itens, "mostrando": len(itens), "sinais_total": sinais_total,
        # cobertura DECLARADA: o painel nunca deve sugerir que o acervo é o universo
        "acervo": total, "legiveis": legiveis, "universo_municipio": universo,
        "processados": processados, "na_fila_rede": na_fila,
        "cobertura_pct": round(100 * processados / universo, 1) if universo else None,
    })


@router.get("/api/pcrj/integra/{numero:path}")
def api_pcrj_integra(numero: str):
    """Íntegra de um contrato: texto completo, processos SEI citados e link do original."""
    con = _con_integras()
    r = con.execute(
        "SELECT numero_controle_pncp, orgao_cnpj, ano, seq, fornecedor_nome, valor_global, "
        "titulo, url, n_chars, texto, processos_sei, estado, coalesce(fonte_texto,'nativo'), "
        "coletado_em FROM contrato_integra WHERE numero_controle_pncp = ?", [numero]).fetchone()
    reg = con.execute("SELECT objeto, orgao_nome, unidade, data_assinatura, tipo, vigencia_ini, "
                      "vigencia_fim FROM pcrj_contratos WHERE numero_controle_pncp = ?",
                      [numero]).fetchone()
    con.close()
    if not r:
        return JSONResponse({"erro": "não capturado", "numero": numero}, status_code=404)
    cnpj, ano, seq = r[1], r[2], r[3]
    return JSONResponse({
        "numero": r[0], "fornecedor": r[4], "valor": float(r[5] or 0),
        "titulo": r[6], "url_pncp": r[7], "n_chars": r[8] or 0, "texto": r[9] or "",
        "processos_sei": json.loads(r[10] or "[]"), "estado": r[11], "fonte_texto": r[12],
        "coletado_em": r[13],
        # o registro do PNCP, ao lado da íntegra: objeto e vigência não estão no PDF
        "objeto": reg[0] if reg else None, "orgao": reg[1] if reg else None,
        "unidade": reg[2] if reg else None, "assinatura": reg[3] if reg else None,
        "tipo": reg[4] if reg else None,
        "vigencia": [reg[5], reg[6]] if reg else None,
        # links para a FONTE original — o painel tem de levar ao documento, não só ao resumo
        "url_pncp_contrato": f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/contratos/{ano}/{seq}/arquivos",
        "url_pncp_web": f"https://pncp.gov.br/app/contratos/{cnpj}/{ano}/{seq}",
    })


# numero em QUERY, não em path: o número de controle do PNCP contém barra
# ("…-2-000708/2026") e um {numero:path} é guloso — engolia o "/download" do fim e a rota
# devolvia 404. Medido no painel, não presumido.
@router.get("/api/pcrj/download")
def api_pcrj_integra_download(numero: str, formato: str = "txt"):
    """Baixa a íntegra. `txt` = texto extraído; `md` = texto com cabeçalho de procedência.

    A procedência vai NO ARQUIVO, não só na tela: quem abrir o .md depois precisa saber se o
    texto veio nativo do PDF ou de OCR (que erra), e de qual URL do PNCP.
    """
    from fastapi.responses import PlainTextResponse
    con = _con_integras()
    r = con.execute("SELECT fornecedor_nome, valor_global, titulo, url, texto, processos_sei, "
                    "coalesce(fonte_texto,'nativo'), coletado_em, n_chars "
                    "FROM contrato_integra WHERE numero_controle_pncp = ?", [numero]).fetchone()
    con.close()
    if not r:
        return JSONResponse({"erro": "não capturado", "numero": numero}, status_code=404)
    nome = re.sub(r"[^A-Za-z0-9._-]", "_", numero)
    if formato != "md":
        return PlainTextResponse(r[4] or "", headers={
            "Content-Disposition": f'attachment; filename="{nome}.txt"'})
    seis = json.loads(r[5] or "[]")
    val = f"R$ {float(r[1] or 0):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    corpo = (
        f"# Contrato {numero}\n\n"
        f"| campo | valor |\n|---|---|\n"
        f"| Fornecedor | {r[0] or '—'} |\n| Valor global | {val} |\n"
        f"| Arquivo | {r[2] or '—'} |\n| Caracteres | {r[8] or 0} |\n"
        f"| Processos SEI citados | {', '.join(seis) if seis else '—'} |\n"
        f"| Origem do texto | {'OCR (pode conter erro de leitura)' if r[6] == 'ocr' else 'nativo do PDF'} |\n"
        f"| Capturado em | {r[7] or '—'} |\n| Fonte | {r[3] or '—'} |\n\n"
        f"---\n\n{r[4] or ''}\n")
    return PlainTextResponse(corpo, headers={
        "Content-Disposition": f'attachment; filename="{nome}.md"'})
