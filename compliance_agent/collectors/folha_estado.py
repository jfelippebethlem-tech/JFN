# -*- coding: utf-8 -*-
"""folha_estado — folha de ATIVOS do Executivo do Estado do RJ (GESPERJ).

A SPA https://www.rj.gov.br/remuneracao/ consome uma API REST aberta (descoberta no bundle
2026-07-17): ``/remuneracao/api/rest/remuneracoes?page=&size=&ano=&mes=``, com órgão, nome,
CPF mascarado (middle-6), cargo, vínculo e valores.
Regras da API: ``size`` ∈ [10, 50]; export CSV dá 504 (inviável); portanto paginação com pausa.

TAMANHO REAL (medido 31/07/26, competência 2026-06): ``totalElements = 909.916`` em 18.199 páginas
de 50 — e não os "~482 mil" que este docstring afirmava. O número importa porque define o quanto
fica de fora.

TETO DE JANELA (medido no mesmo dia): a partir da página **10.000** a API devolve HTTP 200 com a
MESMA fatia de 50 registros, indefinidamente. Numa varredura global isso limita a 10.000 × 50 =
500.000 de 909.916 (**55%**), e `size` não contorna (>50 → HTTP 400).

PARTIÇÃO POR CARGO (medido 01/08/26) — é o que derruba os 55%, mas NÃO leva a 100%. O que estava
escrito como limite de FONTE era limite do PARÂMETRO testado: `orgao`, `orgaoId`, `vinculo`,
`funcaoCargo`, `cargo`, `lotacao` e `folhaRef` são de fato ignorados (total continua 909.916), mas
**`codCargo` filtra** — `codCargo=403` devolve 17.000 registros em 340 páginas, só daquele cargo.
Como toda partição cabe muito abaixo das 10.000 páginas, a janela nunca é atingida. Os códigos vêm
de ``/remuneracoes/cargos`` (1.136 únicos na competência 2026-06) e a coleta varre cargo a cargo.

ALCANCE MEDIDO cargo a cargo (soma dos 1.136 `totalElements`): **681.876 de 909.916 = 74,9%**.
Os 228.040 que faltam **não têm cargo**: são pensionistas (orgao "RIOPREVIDENCIA PENSÕES", vínculo
PENSÃO, folhaRef "Pensionistas", `funcaoCargo: null`) e não existe balde de cargo nulo — `codCargo=0`
devolve `totalElements: 0` e valor inválido é ignorado (volta 909.916). Eles só aparecem na listagem
GLOBAL, e ali vale a janela de 10.000 páginas: amostra de 40 páginas uniformes (2.000 registros) deu
19,4% sem cargo → ≈96.750 dentro da janela, ou seja **~42% dos pensionistas seriam recuperáveis** por
uma passada global complementar (custo: 10.000 páginas). Os outros ~131 mil (14,4% do universo)
estão fora dos dois eixos. Enquanto essa passada não existir, a folha é de QUEM TEM CARGO — dizer
"folha do Estado" sem essa ressalva é dizer 75% chamando de 100%.

Coleta RESUMÍVEL: progresso em data/folha_estado_progresso.json ({competencia, cargo, pagina,
completa}); cada run continua do cargo e da página onde parou (teto ``paginas_por_run`` p/ caber no
cron do orquestrador). Só o ÚLTIMO cargo esgotado marca `completa` — parar por guarda de janela ou
por banco ocupado nunca marca. Grava em ``registros_folha`` (fonte=gesperj_estado), dedup por
(nome, cargo, orgao, matrícula) na competência.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import httpx

_BASE = "https://www.rj.gov.br/remuneracao/api/rest"
_H = {"User-Agent": "Mozilla/5.0 (X11; Linux) JFN-Compliance/2.0"}
_FONTE = "gesperj_estado"
_RAIZ = Path(__file__).resolve().parent.parent.parent
_DB = _RAIZ / "data" / "compliance.db"
_PROGRESSO = _RAIZ / "data" / "folha_estado_progresso.json"
# lock de instância única, como constante para o teste não disputar o flock de um run em curso
_LOCK = _RAIZ / "data" / "folha_estado.lock"
_SIZE = 50  # máximo aceito pela API (validação rejeita >50 e <10)
# TETO DE JANELA DO BACKEND. Medido em 31/07/26: a partir da página 10.000 a API devolve HTTP 200
# com a MESMA fatia de 50 registros (páginas 12825, 12826, 12840, 12864 e 17000 têm overlap 50/50),
# enquanto 2000/4000/6000/8000/9000 trazem conteúdo distinto. Não é erro — é sucesso repetido, que é
# pior: o coletor caminhava, o dedup descartava tudo (medido: 2.000 registros, 0 novos) e ao chegar
# em totalPages=18.199 marcaria a competência como COMPLETA com 575 de 909.916 linhas (0,06%).
# Na faixa válida o mesmo teste rendeu 458 novos em 2.000. `size` não contorna (>50 dá HTTP 400).
# Continua valendo como GUARDA: com a partição por `codCargo` a maior fatia medida tem 340 páginas,
# então chegar aqui significa que a fonte mudou — é aviso (`teto_da_fonte`), nunca "completa".
_PAGINA_MAX = 10_000
# Esperas pelo banco antes de desistir do lote: 15+30+...+90 s ≈ 5,5 min. A varredura completa
# leva horas e cruza com o `sweep_sei` (cron */30) escrevendo no mesmo compliance.db.
_ESPERAS_BANCO = 6
_SQL_INSERT = (
    "INSERT INTO registros_folha (cpf,nome,orgao_codigo,orgao_nome,cargo,vinculo,competencia,"
    "remuneracao_bruta,remuneracao_liquida,abonos,descontos,matricula,fonte,created_at) "
    f"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'{_FONTE}',datetime('now'))")


def _get(client: httpx.Client, params: dict) -> dict | None:
    for tent in range(4):
        try:
            r = client.get(f"{_BASE}/remuneracoes", params=params, headers=_H)
        except httpx.HTTPError:
            time.sleep(2 * (tent + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 502, 503, 504):
            time.sleep(4 * (tent + 1))
            continue
        return None
    return None


def ultima_competencia(client: httpx.Client) -> tuple[int, int] | None:
    """Competência mais recente com dado (a publicação atrasa alguns meses)."""
    a, m = date.today().year, date.today().month
    for _ in range(10):
        j = _get(client, {"page": 0, "size": 10, "ano": a, "mes": m})
        if j and j.get("totalElements"):
            return a, m
        a, m = (a - 1, 12) if m == 1 else (a, m - 1)
    return None


def _cpf_middle6(masc: str) -> str:
    """"***.889.157-**" → "XX889157XXX" (reusa o parser middle-6 canônico do projeto)."""
    from compliance_agent.resolucao_cpf import middle6
    m = middle6(masc)
    return f"XX{m}XXX" if m else ""


def _cargos(client: httpx.Client) -> list[int]:
    """Códigos de cargo (as partições da coleta), em ordem estável p/ a retomada ser previsível.

    `/remuneracoes/cargos` devolve [{tipo, codigo, nome}] — 1.778 na competência 2026-06."""
    for tent in range(4):
        try:
            r = client.get(f"{_BASE}/remuneracoes/cargos", headers=_H, timeout=60)
        except httpx.HTTPError:
            time.sleep(2 * (tent + 1))
            continue
        if r.status_code == 200:
            try:
                return sorted({int(c["codigo"]) for c in r.json() if c.get("codigo") is not None})
            except Exception:
                return []
        if r.status_code in (429, 502, 503, 504):
            time.sleep(4 * (tent + 1))
            continue
        return []
    return []


def _carregar_progresso() -> dict:
    """{"competencia","cargo","pagina","completa"} do último run, ou {} (ausente/corrompido)."""
    try:
        p = json.loads(_PROGRESSO.read_text())
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def _salvar_progresso(comp: str, pagina: int, completa: bool = False,
                      cargo: int | None = None) -> None:
    # write atômico: crash no meio do write_text deixaria JSON truncado → run recomeça da pág. 0
    import os
    tmp = _PROGRESSO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"competencia": comp, "cargo": cargo, "pagina": pagina,
                               "completa": completa}))
    os.replace(tmp, _PROGRESSO)


def coletar(paginas_por_run: int = 1500, pausa: float = 0.35, db_path: str | None = None) -> dict:
    """Coleta incremental da competência mais recente. Idempotente (dedup) e resumível.
    Lock de instância única: sweep manual × cron do orquestrador ao MESMO tempo leriam o mesmo
    dedup inicial e duplicariam linhas — o segundo processo sai limpo."""
    import fcntl
    import sqlite3
    lock = open(_LOCK, "w")  # noqa: SIM115 — vive até o fim do run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {"fonte": _FONTE, "erro": "já em execução (lock)", "paginas": 0, "novos": 0}
    con = sqlite3.connect(db_path or str(_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    # migração leve: matrícula desambigua homônimos (2 "JOSE DA SILVA" PROFESSOR na mesma
    # secretaria são servidores DISTINTOS) e torna o dedup resumível sem subcontar
    cols = {r[1] for r in con.execute("PRAGMA table_info(registros_folha)")}
    if "matricula" not in cols:
        con.execute("ALTER TABLE registros_folha ADD COLUMN matricula VARCHAR(30)")
        con.commit()
    tot = {"fonte": _FONTE, "paginas": 0, "novos": 0, "vistos": 0, "erros": 0}
    try:
        with httpx.Client(timeout=40) as client:
            # competência-alvo: TERMINAR a do progresso antes de pular para uma recém-publicada
            # (senão a anterior ficaria ~parcial p/ sempre, indistinguível de completa)
            prog = _carregar_progresso()
            if prog.get("competencia") and not prog.get("completa"):
                comp = prog["competencia"]
                ano, mes = int(comp[:4]), int(comp[5:7])
                pagina = int(prog.get("pagina", 0))
            else:
                comp_am = ultima_competencia(client)
                if not comp_am:
                    return {**tot, "erro": "nenhuma competência com dado (API fora?)"}
                ano, mes = comp_am
                comp = f"{ano:04d}-{mes:02d}"
                pagina = 0
                if prog.get("competencia") == comp and prog.get("completa"):
                    return {**tot, "competencia": comp, "completa": True}
            tot["competencia"] = comp
            # PARTIÇÃO POR CARGO: sem ela a varredura global morre no teto de janela (55%).
            cargos = _cargos(client)
            if not cargos:
                return {**tot, "competencia": comp,
                        "erro": "lista de cargos indisponível (/remuneracoes/cargos)"}
            cargo_prog = prog.get("cargo") if prog.get("competencia") == comp else None
            if cargo_prog in cargos:
                i0 = cargos.index(cargo_prog)
            else:  # progresso de antes da partição (ou cargo extinto): recomeça a varredura
                i0, pagina = 0, 0
            tot["cargos_total"], tot["cargos_feitos"] = len(cargos), i0
            # dedup: o que já existe desta fonte nesta competência (matrícula desambigua homônimo)
            vistos = {(r[0], r[1], r[2], r[3] or "") for r in con.execute(
                "SELECT nome, cargo, orgao_nome, matricula FROM registros_folha "
                "WHERE fonte=? AND competencia=?", (_FONTE, comp))}
            lote: list[tuple] = []
            cargo = cargos[i0]
            fim = False  # acabou a competência inteira (último cargo esgotado)

            def _gravar(completa: bool) -> bool:
                """Grava o lote e o progresso. False = banco ocupado, o run tem de parar limpo.

                A varredura inteira leva horas e o `sweep_sei` (cron */30) escreve no MESMO
                compliance.db, segurando o lock por mais que o busy_timeout. Estourar ali perderia
                o lote E o progresso; então espera, e se não der, para sem avançar o progresso —
                as páginas não confirmadas voltam a ser pedidas no próximo run."""
                nonlocal lote
                if lote:
                    for tent in range(_ESPERAS_BANCO):
                        try:
                            con.executemany(_SQL_INSERT, lote)
                            con.commit()
                            break
                        except sqlite3.OperationalError as e:
                            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                                raise
                            con.rollback()
                            time.sleep(15 * (tent + 1))
                    else:
                        tot["erro"] = "banco ocupado por outro processo — run encerrado sem perder lugar"
                        return False
                    tot["novos"] += len(lote)
                    lote = []
                _salvar_progresso(comp, pagina, completa=completa, cargo=cargo)
                return True

            for idx in range(i0, len(cargos)):
                cargo = cargos[idx]
                if idx > i0:
                    pagina = 0
                while tot["paginas"] < paginas_por_run:
                    j = _get(client, {"page": pagina, "size": _SIZE, "ano": ano, "mes": mes,
                                      "codCargo": cargo})
                    if j is None:
                        tot["erros"] += 1
                        break
                    regs = j.get("remuneracoes") or []
                    for r in regs:
                        chave = (r.get("nomeServidor"), r.get("funcaoCargo"), r.get("orgao"),
                                 (r.get("matriculaServidor") or "").strip())
                        if not chave[0] or chave in vistos:
                            tot["vistos"] += 1
                            continue
                        vistos.add(chave)
                        lote.append((_cpf_middle6(r.get("cpf") or ""), r["nomeServidor"], "",
                                     r.get("orgao") or "", r.get("funcaoCargo") or "",
                                     (r.get("vinculo") or "")[:50], comp,
                                     float(r.get("totalVantagens") or 0),
                                     float(r.get("valorLiquido") or 0), 0.0,
                                     float(r.get("totalDescontos") or 0), chave[3]))
                    tot["paginas"] += 1
                    pagina += 1
                    # Fim da PARTIÇÃO (esperado) × teto de janela dentro dela (não deveria ocorrer:
                    # a maior partição medida tem 340 páginas — se ocorrer, é aviso, não "completa").
                    fim_cargo = fim_real = pagina >= (j.get("totalPages") or 0)
                    if pagina >= _PAGINA_MAX and not fim_real:
                        tot["teto_da_fonte"] = True  # parou por guarda, NÃO por ter acabado
                        fim_cargo = True
                    if len(lote) >= 1000 or fim_cargo:
                        # só o ÚLTIMO cargo esgotado DE VERDADE fecha a competência
                        fim = fim_real and idx == len(cargos) - 1
                        if not _gravar(completa=fim):
                            tot["completa"] = False
                            return tot
                    if fim_cargo:
                        tot["cargos_feitos"] = idx + 1
                        break
                    time.sleep(pausa)
                if tot["erros"] or tot["paginas"] >= paginas_por_run:
                    break
            _gravar(completa=fim)
            tot["completa"] = fim
    finally:
        con.close()
        lock.close()  # solta o flock
    return tot


if __name__ == "__main__":
    import sys
    teto = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500
    print(json.dumps(coletar(paginas_por_run=teto), ensure_ascii=False), flush=True)
