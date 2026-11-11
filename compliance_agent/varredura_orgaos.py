# -*- coding: utf-8 -*-
"""varredura_orgaos — roda os detectores ÓRGÃO A ÓRGÃO e persiste os achados.

Responde ao pedido *"vai indo de órgão a órgão e buscando suas irregularidades"* e é a base da
fiscalização contínua: **a camada determinística**. Os 31 detectores são regra e limiar em
código — não precisam de LLM e não têm cota. É aqui que o volume tem de ser resolvido; o LLM
fica para a minoria que a camada 1 marcou.

O QUE ESTE MÓDULO **NÃO** FAZ, deliberadamente:

* **não escreve na `compliance.db`.** Lê dela em modo SÓ-LEITURA e grava num banco PRÓPRIO
  (`data/achados.db`). A primeira versão gravava na produção e levou `database is locked` no
  primeiro teste — o servidor e os crons escrevem ali o tempo todo. Além de evitar a disputa,
  isso é o que permite rodar a varredura na VM-2 e trazer só o arquivo de achados de volta;
* **não chama LLM.** A parte subjetiva de cada detector degrada para `nao_avaliavel` quando
  `gerar` é None — é o comportamento honesto do framework, e mantém a varredura barata e
  ilimitada. Quem quiser a camada 2 passa `gerar=`;
* **não inventa contexto.** Cada detector declara os campos de que precisa; o que a base não
  tem fica ausente, e o detector devolve `nao_avaliavel` em vez de score 0. Por isso a
  varredura registra a COBERTURA — quantos detectores puderam de fato ser avaliados por UG —
  junto com os achados. Uma UG "limpa" pode ser só uma UG sem dado.

Idempotente: `INSERT OR REPLACE` por (ug, detector, processo). Nunca `DELETE`.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from datetime import datetime
from typing import Any, Callable, Iterable

from compliance_agent.detectores import rodar_fornecedor, rodar_orgao
from compliance_agent.detectores.base import ResultadoDetector

DB_LEITURA = os.environ.get("JFN_DB", "data/compliance.db")
DB_ACHADOS = os.environ.get("JFN_DB_ACHADOS", "data/achados.db")


def abrir_leitura(caminho: str | None = None) -> sqlite3.Connection:
    """Conexão SÓ-LEITURA com a base de produção — não disputa lock com o servidor nem com o cron."""
    return sqlite3.connect(f"file:{caminho or DB_LEITURA}?mode=ro", uri=True, timeout=30)


def abrir_achados(caminho: str | None = None) -> sqlite3.Connection:
    """Banco PRÓPRIO da varredura. Separado de propósito (ver docstring do módulo)."""
    alvo = pathlib.Path(caminho or DB_ACHADOS)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(alvo, timeout=60)
    init_schema(con)
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS achado_detector (
            ug TEXT, detector TEXT, processo TEXT, escopo TEXT,
            score REAL, status TEXT, motivo TEXT, explicacao_inocente TEXT,
            valores TEXT, evidencia TEXT, gerado_em TEXT,
            PRIMARY KEY (ug, detector, processo)
        );
        CREATE INDEX IF NOT EXISTS ix_achado_score ON achado_detector(score DESC);
        CREATE INDEX IF NOT EXISTS ix_achado_ug ON achado_detector(ug, status);
        CREATE TABLE IF NOT EXISTS varredura_cobertura (
            ug TEXT PRIMARY KEY, n_detectores INTEGER, n_avaliaveis INTEGER,
            n_confirmados INTEGER, n_descartados INTEGER, n_nao_avaliaveis INTEGER,
            n_fornecedores INTEGER, score_max REAL, gerado_em TEXT
        );
    """)
    con.commit()


def ugs_com_pagamento(con: sqlite3.Connection, *, exercicio: int | None = None,
                      min_obs: int = 1) -> list[str]:
    """UGs que efetivamente pagaram no período — a ordem da fila sai do dinheiro, não do alfabeto."""
    sql = ("SELECT ug_emitente, COUNT(*) n, SUM(valor) total FROM ob_orcamentaria_siafe "
           "WHERE COALESCE(ug_emitente,'') <> ''")
    params: list = []
    if exercicio:
        sql += " AND exercicio = ?"
        params.append(exercicio)
    sql += " GROUP BY ug_emitente HAVING n >= ? ORDER BY total DESC"
    params.append(min_obs)
    return [r[0] for r in con.execute(sql, params).fetchall()]


def fornecedores_da_ug(con: sqlite3.Connection, ug: str, *, exercicio: int | None = None,
                       limite: int = 25) -> list[str]:
    """Maiores credores pessoa jurídica da UG. Só CNPJ de 14 dígitos — código de fundo não é fornecedor."""
    sql = ("SELECT credor, SUM(valor) t FROM ob_orcamentaria_siafe "
           "WHERE ug_emitente = ? AND LENGTH(TRIM(credor)) = 14 AND TRIM(credor) GLOB '[0-9]*'")
    params: list = [ug]
    if exercicio:
        sql += " AND exercicio = ?"
        params.append(exercicio)
    sql += " GROUP BY credor ORDER BY t DESC LIMIT ?"
    params.append(limite)
    return [r[0] for r in con.execute(sql, params).fetchall()]


_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"

# Índice folha×QSA por arquivo de banco. `registros_folha` tem 1.359.447 linhas e NENHUM índice
# por nome (medido em 11/11/2026): `montar_ctx_servidores` lê a tabela inteira a cada chamada,
# o que em 118 UGs × 25 fornecedores seriam ~3.000 varreduras completas. Aqui é UMA por
# execução, guardando só as linhas cujo nome está em algum QSA (31.449 sócios).
_INDICE_FOLHA: dict[str, dict[str, list[dict]] | None] = {}
_BASE_TSE: dict[str, str] = {}


def _caminho_do_banco(con: sqlite3.Connection) -> str:
    try:
        for _, nome, arquivo in con.execute("PRAGMA database_list"):
            if nome == "main":
                return arquivo or f"mem:{id(con)}"
    except sqlite3.Error:
        pass
    return f"mem:{id(con)}"


def _indice_folha(con: sqlite3.Connection) -> dict[str, list[dict]] | None:
    """`nome normalizado → servidores` restrito a nomes de sócio. None = folha ilegível."""
    chave = _caminho_do_banco(con)
    if chave in _INDICE_FOLHA:
        return _INDICE_FOLHA[chave]
    from compliance_agent.detectores.c8_servidor_socio import _norm
    try:
        alvo = {_norm(r[0]) for r in con.execute(
            "SELECT DISTINCT socio_nome FROM socios_fornecedor WHERE COALESCE(socio_nome,'') <> ''")}
    except sqlite3.OperationalError:
        alvo = set()
    alvo.discard("")
    indice: dict[str, list[dict]] | None = {}
    norm_cache: dict[str, str] = {}
    vistos: set[tuple] = set()
    try:
        for nome, cpf, orgao, cargo, vinculo, fonte in con.execute(
                "SELECT nome, cpf, orgao_nome, cargo, vinculo, fonte FROM registros_folha "
                "WHERE COALESCE(nome,'') <> ''"):
            n = norm_cache.get(nome)
            if n is None:
                n = norm_cache[nome] = _norm(nome)
            if n not in alvo:
                continue
            chave_linha = (n, cpf, orgao, cargo, vinculo)   # a folha repete por competência
            if chave_linha in vistos:
                continue
            vistos.add(chave_linha)
            indice.setdefault(n, []).append({"nome": nome, "cpf": cpf, "orgao": orgao,
                                             "cargo": cargo, "vinculo": vinculo, "fonte": fonte})
    except sqlite3.OperationalError:
        indice = None
    _INDICE_FOLHA[chave] = indice
    return indice


def _descricao_base_tse(con: sqlite3.Connection) -> str:
    """Nome da base de doações e as eleições que ela cobre — vai literal para o motivo do C6."""
    chave = _caminho_do_banco(con)
    if chave not in _BASE_TSE:
        try:
            anos = [str(r[0]) for r in con.execute(
                "SELECT DISTINCT ano_eleicao FROM doacoes_eleitorais "
                "WHERE ano_eleicao IS NOT NULL ORDER BY 1")]
        except sqlite3.OperationalError:
            anos = []
        _BASE_TSE[chave] = ("doacoes_eleitorais (TSE"
                            + (f", eleições {', '.join(anos)})" if anos else ")"))
    return _BASE_TSE[chave]


def _iso_br(d: str | None) -> str | None:
    s = str(d or "").strip()
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    return s[:10] or None


def _sancoes_do_cnpj(con: sqlite3.Connection,
                     cnpj: str) -> tuple[list[dict], list[dict]] | None:
    """(sanções com vigência conhecida, sanções de vigência incerta). None = nenhuma base legível.

    `siga_sancoes` (SIGA-RJ, 3.078 linhas) não tem data de término, só a de efetivação e o status
    visto na coleta. 'Vigente' vale da efetivação até hoje — entra sem `data_fim`. 'Decorrido'
    terminou em data que a base não guarda: entra como INCERTA e o C7 declara a lacuna em vez de
    inventar o fim. Multa/advertência não têm vigência e não vedam contratar — ficam fora.
    """
    from compliance_agent.detectores.c7_sancionada_contratada import montar_ctx_sancoes
    leu = False
    sancoes: list[dict] = []
    incertas: list[dict] = []
    try:
        sancoes += montar_ctx_sancoes(con, cnpj)
        leu = True
    except sqlite3.OperationalError:
        pass
    try:
        for categoria, inicio, orgao, status in con.execute(
                "SELECT enquadramento, data_efetivacao, orgao_apenador, status FROM siga_sancoes "
                "WHERE doc = ?", (cnpj,)):
            item = {"cadastro": "SIGA-RJ", "categoria": categoria, "data_inicio": _iso_br(inicio),
                    "data_fim": None, "orgao": orgao, "uf": "RJ"}
            st = (status or "").strip().lower()
            if st == "vigente":
                sancoes.append(item)
            elif st == "decorrido":
                incertas.append(item)
        leu = True
    except sqlite3.OperationalError:
        pass
    return (sancoes, incertas) if leu else None


def contexto_fornecedor(con: sqlite3.Connection, cnpj: str, ug: str | None = None) -> dict:
    """Monta o contexto que os detectores de fornecedor pedem, a partir do que a base JÁ tem.

    Sem isto a varredura roda e não avalia nada: medido em 2026-07-27 na UG 294200, apenas
    **1 de 41** detectores era avaliável, porque cada card declara os campos de que precisa e a
    varredura não os entregava. O ganho aqui é o C6 (vínculo político-financeiro), cujas duas
    fontes essenciais — QSA e doações do TSE — estão no banco há tempos.

    Só preenche o que EXISTE. Campo que a base não tem continua ausente, e o detector devolve
    `nao_avaliavel` — que é a resposta honesta, e não score 0.
    """
    ctx: dict[str, Any] = {}
    if ug:
        ctx["orgao_contratante"] = ug

    qsa: list[dict] = []
    socios: list[dict] = []   # o formato do C8: doc mascarado da RFB (D4–D9) + qualificação
    try:
        for r in con.execute(
            "SELECT socio_nome, socio_doc, cpf_resolvido, qualificacao FROM socios_fornecedor "
            "WHERE cnpj = ?", (cnpj,),
        ):
            nome = (r[0] or "").strip()
            if nome:
                qsa.append({"nome": nome, "cpf": (r[2] or r[1] or "") or None})
                socios.append({"nome": nome, "doc": r[1], "qualificacao": r[3] or ""})
    except sqlite3.OperationalError:
        qsa, socios = [], []
    if qsa:
        ctx["qsa"] = qsa

    # Doações dos sócios — cruza por CPF quando há, senão por nome normalizado.
    doacoes: list[dict] = []
    consultou_tse = False
    if qsa:
        cpfs = [q["cpf"] for q in qsa if q.get("cpf")]
        nomes = [q["nome"].upper() for q in qsa]
        try:
            if cpfs:
                marcas = ",".join("?" * len(cpfs))
                doacoes += [dict(zip(("doador_cpf", "doador_nome", "beneficiario",
                                      "cargo_beneficiario", "valor"), r))
                            for r in con.execute(
                                f"SELECT cpf_cnpj_doador, nome_doador, nome_candidato, "
                                f"cargo_candidato, valor FROM doacoes_eleitorais "
                                f"WHERE cpf_cnpj_doador IN ({marcas})", cpfs)]
            if nomes and not doacoes:
                marcas = ",".join("?" * len(nomes))
                doacoes += [dict(zip(("doador_cpf", "doador_nome", "beneficiario",
                                      "cargo_beneficiario", "valor"), r))
                            for r in con.execute(
                                f"SELECT cpf_cnpj_doador, nome_doador, nome_candidato, "
                                f"cargo_candidato, valor FROM doacoes_eleitorais "
                                f"WHERE UPPER(nome_doador) IN ({marcas})", nomes)]
            consultou_tse = True
        except sqlite3.OperationalError:
            doacoes = []
    if doacoes:
        ctx["doacoes"] = doacoes
    elif consultou_tse:
        # Busca FEITA e vazia é resultado: o C6 grava `descartado` citando a base consultada.
        # Era "faltam doações" em 317 fornecedores com QSA (achados.db, 11/11/2026).
        ctx["doacoes_consultadas_em"] = _descricao_base_tse(con)

    # SANÇÕES (C7) — CEIS/CNEP federais + SIGA-RJ estadual. A lista entra mesmo vazia: busca
    # feita e vazia é "sem sanção", não "falta". 285 C7 eram `nao_avaliavel` só por isso.
    sancoes = _sancoes_do_cnpj(con, cnpj)
    if sancoes is not None:
        ctx["sancoes"], incertas = sancoes
        if incertas:
            ctx["sancoes_vigencia_incerta"] = incertas

    # SERVIDORES (C8) — folha × QSA. Só entra quando a folha é legível; lista vazia = nenhum
    # sócio consta nas folhas coletadas (juízo), não ausência de dado.
    if socios:
        ctx["socios"] = socios
        folha = _indice_folha(con)
        if folha is not None:
            from compliance_agent.detectores.c8_servidor_socio import _norm as _norm_c8
            vistos: list[dict] = []
            for s in socios:
                vistos.extend(folha.get(_norm_c8(s["nome"]), []))
            ctx["servidores"] = vistos

    # CADASTRO — `empresas.raw_json` já está no formato que `investigacao_dd.investigar` espera
    # (situacao, abertura, capital, porte, cnae, logradouro, numero, bairro, socios[]). Sem isto o
    # detector C (fachada) chamava o caminho de REDE e voltava sem hipótese: 0 de 312 avaliáveis na
    # medição de 2026-07-27. Passar um dict (mesmo incompleto) também evita a ida à rede, que numa
    # varredura de 118 UGs seria inviável.
    try:
        linha = con.execute(
            "SELECT raw_json, situacao, data_abertura, porte, capital_social, atividade_princ "
            "FROM empresas WHERE cnpj = ?", (cnpj,)).fetchone()
    except sqlite3.OperationalError:
        linha = None
    if linha:
        cad: dict[str, Any] = {}
        if linha[0]:
            try:
                cad = json.loads(linha[0]) or {}
            except json.JSONDecodeError:
                cad = {}
        # colunas normalizadas prevalecem sobre o json bruto quando existem
        for chave, valor in (("situacao", linha[1]), ("abertura", linha[2]), ("porte", linha[3]),
                             ("capital", linha[4]), ("cnae", linha[5])):
            if valor not in (None, ""):
                cad[chave] = valor
        if qsa and not cad.get("socios"):
            cad["socios"] = [{"nome": q["nome"], "doc": q.get("cpf")} for q in qsa]
        ctx["cadastral"] = cad

    # PEGADA NAS OBs — total pago, nº de ordens e a primeira data. Alimenta tanto a razão
    # retorno/doação do C6 quanto a hipótese "empresa recém-aberta antes do 1º recebimento".
    # `data_emissao` é TEXTO DD/MM/AAAA: MIN() direto era lexicográfico (01/10/2024 "antes" de
    # 16/12/2022). Converte para ISO dentro do MIN, a mesma expressão de `cruzamentos_intel`.
    try:
        sql = (f"SELECT SUM(valor), COUNT(*), MIN(CASE WHEN data_emissao LIKE '__/__/____' "
               f"THEN {_OB_ISO} END) FROM ob_orcamentaria_siafe WHERE credor = ?")
        params: list = [cnpj]
        if ug:
            sql += " AND ug_emitente = ?"
            params.append(ug)
        total, n_obs, primeira = con.execute(sql, params).fetchone()
        if total:
            ctx["valor_contratado"] = float(total)
            ctx["pagamentos"] = {"total_pago": float(total), "n_obs": int(n_obs or 0),
                                 "primeira_data": primeira}
            if primeira and "sancoes" in ctx:
                # C7 pede a data da contratação; a assinatura não está na base por UG. A 1ª OB
                # é o ato mais antigo que a base prova — o C7 rebaixa e declara o proxy.
                ctx["data_referencia"] = primeira
                ctx["data_referencia_origem"] = (
                    "1ª OB do credor" + (f" na UG {ug}" if ug else "")
                    + " (proxy: a data de assinatura do contrato não está na base)")
    except sqlite3.OperationalError:
        pass

    # Rede e geocode ficam DESLIGADOS na varredura: cruzamento de co-endereço em DuckDB e
    # Nominatim a 1 req/s são inviáveis em 118 UGs. Quem quiser o exame profundo roda o dossiê
    # do fornecedor, que é o produto feito para isso.
    ctx.setdefault("usar_rede", False)
    ctx.setdefault("geocode", False)
    ctx.setdefault("usar_beneficios", False)
    return ctx


def _persistir(con: sqlite3.Connection, ug: str, escopo: str,
               resultados: Iterable[ResultadoDetector]) -> int:
    agora = datetime.now().isoformat(timespec="seconds")
    linhas = [
        (ug, r.detector, r.processo, escopo, r.score, r.status,
         (r.motivo_refutacao or "")[:2000], (r.explicacao_inocente or "")[:1200],
         json.dumps(r.valores, ensure_ascii=False, default=str)[:8000],
         json.dumps(r.evidencia, ensure_ascii=False, default=str)[:8000], agora)
        for r in resultados
    ]
    con.executemany("INSERT OR REPLACE INTO achado_detector VALUES (?,?,?,?,?,?,?,?,?,?,?)", linhas)
    return len(linhas)


def varrer_ug(con: sqlite3.Connection, ug: str, *, exercicio: int | None = None,
              max_fornecedores: int = 25, gerar: Callable | None = None,
              con_achados: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Roda os detectores de ÓRGÃO e de FORNECEDOR aplicáveis a uma UG.

    Só as famílias que se alimentam do que a base tem hoje (pagamento, cadastro, QSA). Edital,
    julgamento e execução exigem contexto de certame que a varredura por UG não possui — chamá-los
    aqui só produziria `nao_avaliavel` em massa, o que polui a fila sem informar nada.
    """
    resultados: list[ResultadoDetector] = list(rodar_orgao(ug, gerar=gerar))
    fornecedores = fornecedores_da_ug(con, ug, exercicio=exercicio, limite=max_fornecedores)
    for cnpj in fornecedores:
        resultados.extend(rodar_fornecedor(cnpj, contexto=contexto_fornecedor(con, cnpj, ug),
                                           gerar=gerar))

    confirmados = [r for r in resultados if r.status == "confirmado"]
    descartados = [r for r in resultados if r.status == "descartado"]
    nao_av = [r for r in resultados if r.status == "nao_avaliavel"]
    resumo = {
        "ug": ug,
        "n_detectores": len(resultados),
        "n_avaliaveis": len(resultados) - len(nao_av),
        "n_confirmados": len(confirmados),
        "n_descartados": len(descartados),
        "n_nao_avaliaveis": len(nao_av),
        "n_fornecedores": len(fornecedores),
        "score_max": max((r.score for r in resultados), default=0.0),
        "achados": sorted(confirmados, key=lambda r: -r.score),
    }

    if con_achados is not None:
        _persistir(con_achados, ug, "ug", resultados)
        con_achados.execute(
            "INSERT OR REPLACE INTO varredura_cobertura VALUES (?,?,?,?,?,?,?,?,?)",
            (ug, resumo["n_detectores"], resumo["n_avaliaveis"], resumo["n_confirmados"],
             resumo["n_descartados"], resumo["n_nao_avaliaveis"], resumo["n_fornecedores"],
             resumo["score_max"], datetime.now().isoformat(timespec="seconds")))
        con_achados.commit()
    return resumo


def varrer_todas(con: sqlite3.Connection, *, exercicio: int | None = None,
                 limite_ugs: int | None = None, max_fornecedores: int = 25,
                 gerar: Callable | None = None,
                 con_achados: sqlite3.Connection | None = None,
                 log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Percorre as UGs por volume pago. Uma UG por vez — a VM tem 2 vCPU."""
    ugs = ugs_com_pagamento(con, exercicio=exercicio)
    if limite_ugs:
        ugs = ugs[:limite_ugs]
    total_achados = 0
    por_ug: list[dict] = []
    for i, ug in enumerate(ugs, 1):
        r = varrer_ug(con, ug, exercicio=exercicio, max_fornecedores=max_fornecedores,
                      gerar=gerar, con_achados=con_achados)
        total_achados += r["n_confirmados"]
        por_ug.append({k: v for k, v in r.items() if k != "achados"})
        if log and (i % 10 == 0 or r["n_confirmados"]):
            log(f"  [{i}/{len(ugs)}] UG {ug}: {r['n_confirmados']} achado(s) em "
                f"{r['n_avaliaveis']}/{r['n_detectores']} avaliáveis "
                f"({r['n_fornecedores']} fornecedores)")
    return {"n_ugs": len(ugs), "total_achados": total_achados, "por_ug": por_ug,
            "exercicio": exercicio}
