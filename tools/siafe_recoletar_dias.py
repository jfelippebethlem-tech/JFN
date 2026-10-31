# -*- coding: utf-8 -*-
"""
siafe_recoletar_dias — automelhoria de DADO: recoleta os dias do SIAFE parados no platô do teto de consulta.

POR QUE EXISTE. Em 24/10/2026 o verificador do diário nunca tinha disparado (contava linhas do DOM) e 8 dias
de 2026 estavam parados em 981–997 OBs — a assinatura do teto. Recoletados à mão: 21/10 foi de 992 para 1.719.
Isto vira laço automático: `suspeitos()` acha os dias no platô, `--auto` os recoleta com `coletar_por_data`
(que agora decide o estouro pelo colhido e subdivide), e o dia recoletado entra em
`data/siafe_dias_verificados.json` — para o sensor de dados do loop de automelhoria não insistir nele.

Uso:
  python tools/siafe_recoletar_dias.py --listar            # dias suspeitos (só SQL)
  python tools/siafe_recoletar_dias.py --auto [--max 3]    # recoleta os suspeitos ainda não verificados
  python tools/siafe_recoletar_dias.py --tfe [--auto]      # dias em que o espelho TFE tem OB que o SIAFE não tem
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DB = _REPO / "data" / "compliance.db"
VERIFICADOS = _REPO / "data" / "siafe_dias_verificados.json"
PLATO = (975, 1000)          # [min, max): faixa em que a colheita bate no teto (platô medido 980–997)


def verificados() -> dict:
    try:
        return json.loads(VERIFICADOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


INCONCLUSIVOS = _REPO / "data" / "siafe_dias_inconclusivos.json"
try:
    _ULT_INCONCLUSIVO: dict = json.loads(INCONCLUSIVOS.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _ULT_INCONCLUSIVO = {}


def _salvar_inconclusivos() -> None:
    INCONCLUSIVOS.write_text(json.dumps(_ULT_INCONCLUSIVO, ensure_ascii=False, indent=1), encoding="utf-8")


def _contar(dia: str, exercicio: int, db: Path = DB) -> int:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE exercicio=? AND data_emissao=?",
                           (exercicio, dia)).fetchone()[0]
    finally:
        con.close()


def suspeitos(exercicio: int | None = None, db: Path = DB) -> list[tuple[str, int]]:
    """Dias do exercício com contagem no platô e ainda não verificados. `data_emissao` é TEXTO DD/MM/AAAA."""
    ano = exercicio or datetime.now().year
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT data_emissao, COUNT(*) FROM ob_orcamentaria_siafe WHERE exercicio=? "
                           "GROUP BY data_emissao", (ano,)).fetchall()
    finally:
        con.close()
    ok = verificados()
    return sorted(((d, n) for d, n in rows if PLATO[0] <= n < PLATO[1] and d not in ok),
                  key=lambda x: datetime.strptime(x[0], "%d/%m/%Y"), reverse=True)


async def recoletar(dias: list[str], exercicio: int) -> dict:
    from compliance_agent import siafe_ob_orcamentaria as M
    ok, out = verificados(), {}
    for d in dias:
        antes = _contar(d, exercicio)
        r = await M.coletar_por_data(exercicio, d)
        out[d] = {k: r.get(k) for k in ("ok", "estouro", "ingeridas", "erro")} | {"antes": antes}
        # VERIFICADO SÓ COM PROVA: subdividiu (estouro) OU a colheita viu ao menos o que a base já tem.
        # Medido em 24/10/2026 no 17/03: colheu 879 com 998 na base — a rolagem parou antes do fim; marcar
        # como verificado seria declarar cura sem efeito. Fica inconclusivo, o sensor insiste e escala.
        # …OU ESTÁVEL: duas colheitas independentes, abaixo do teto, com o MESMO número provam que a visão por
        # data está completa. Medido em 24/10/2026: 17/03 deu 879 duas vezes (passo e espera diferentes) com
        # 998 na base — as 119 a mais vêm de outras coletas (dreno por UG), não de truncamento.
        n = r.get("ingeridas") or 0
        estavel = bool(r.get("ok")) and n < 980 and _ULT_INCONCLUSIVO.get(d) == n
        if r.get("ok") and (r.get("estouro") or n >= antes or estavel):
            ok[d] = {"quando": datetime.now().isoformat(timespec="seconds"), "estouro": r.get("estouro"),
                     "ingeridas": n, "base": antes,
                     "nota": "colheita estável em 2 rodadas; a base tem OBs de outras coletas" if estavel and n < antes
                     else ""}
            VERIFICADOS.write_text(json.dumps(ok, ensure_ascii=False, indent=1), encoding="utf-8")
            _ULT_INCONCLUSIVO.pop(d, None)
        elif r.get("ok"):
            _ULT_INCONCLUSIVO[d] = n
        _salvar_inconclusivos()
        print(f"[{datetime.now():%F %T}] dia {d}: {out[d]}", flush=True)
    return out


# ─────────── lacunas apontadas pelo TFE (gabarito) ───────────
# Pedido do dono em 30/10/2026. O platô só vê dia que BATEU no teto; dia que a coleta mal visitou passa calado.
# Medido no mesmo dia: 01/09/2026 com 318 OBs no SIAFE e 1.271 no espelho TFE; agosto–setembro somavam 10,7 mil
# OBs (R$ 2,4 bi) que o espelho publica e a fonte canônica não tem. O espelho NÃO é fonte de valor — só diz QUAL
# DIA recolher; o número continua vindo do SIAFE.
TFE_VERIFICADOS = _REPO / "data" / "siafe_dias_tfe_verificados.json"
MIN_LACUNA_DIA = 30


def _tfe_verificados() -> dict:
    try:
        return json.loads(TFE_VERIFICADOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _faltas_tfe(exercicio: int, db: Path = DB, dia: str | None = None) -> dict[str, int]:
    """{DD/MM/AAAA: OBs do espelho TFE daquele dia ausentes do SIAFE (mesmo número E mesma UG)}."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    filtro, args = "", [str(exercicio)]
    if dia:
        filtro, args = " AND o.data_emissao = ?", args + ["-".join(reversed(dia.split("/")))]
    try:
        rows = con.execute(
            "SELECT o.data_emissao, COUNT(*) FROM ordens_bancarias o WHERE o.categoria = 'tfe_ob' "
            "AND o.exercicio = ?" + filtro + " AND NOT EXISTS (SELECT 1 FROM ob_orcamentaria_siafe s "
            "WHERE s.numero_ob = o.numero_ob AND s.ug_emitente = o.ug_codigo) GROUP BY 1", args).fetchall()
    finally:
        con.close()
    return {"/".join(reversed(d.split("-"))): n for d, n in rows if d}


def lacunas_tfe(exercicio: int | None = None, db: Path = DB, minimo: int = MIN_LACUNA_DIA) -> list[tuple[str, int]]:
    """Dias com `minimo`+ OBs do espelho fora do SIAFE, maior lacuna primeiro. Dia já recolhido só volta se a
    lacuna CRESCEU desde então (espelho novo): o resíduo que sobra é OB cuja emissão caiu noutro dia, e insistir
    nele seria trabalho que parece progresso."""
    ano = exercicio or datetime.now().year
    vistos = _tfe_verificados()
    out = [(d, n) for d, n in _faltas_tfe(ano, db).items()
           if n >= minimo and n > vistos.get(d, {}).get("falta_depois", -1)]
    return sorted(out, key=lambda x: -x[1])


async def recoletar_tfe(dias: list[str], exercicio: int) -> dict:
    from compliance_agent import siafe_ob_orcamentaria as M
    vistos, out = _tfe_verificados(), {}
    for d in dias:
        antes = _faltas_tfe(exercicio, dia=d).get(d, 0)
        r = await M.coletar_por_data(exercicio, d)
        depois = _faltas_tfe(exercicio, dia=d).get(d, 0)
        out[d] = {k: r.get(k) for k in ("ok", "estouro", "ingeridas", "erro")} | {"falta_antes": antes,
                                                                                 "falta_depois": depois}
        if r.get("ok"):          # só a colheita que rodou conta como visita; erro de login não fecha o dia
            vistos[d] = {"quando": datetime.now().isoformat(timespec="seconds"), "falta_antes": antes,
                         "falta_depois": depois, "ingeridas": r.get("ingeridas")}
            TFE_VERIFICADOS.write_text(json.dumps(vistos, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{datetime.now():%F %T}] dia {d} (lacuna TFE): {out[d]}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--exercicio", type=int, default=None)
    ap.add_argument("--tfe", action="store_true", help="dias que o espelho TFE aponta como lacuna do SIAFE")
    a = ap.parse_args()
    ano = a.exercicio or datetime.now().year
    if a.tfe:
        lac = lacunas_tfe(ano)
        if a.listar or not a.auto:
            print(json.dumps(lac, ensure_ascii=False))
        elif lac:
            asyncio.run(recoletar_tfe([d for d, _ in lac[:a.max]], ano))
        else:
            print(f"[{datetime.now():%F %T}] nenhuma lacuna do TFE por recolher em {ano}")
        return 0
    sus = suspeitos(ano)
    if a.listar or not a.auto:
        print(json.dumps(sus, ensure_ascii=False))
        return 0
    if sus:
        asyncio.run(recoletar([d for d, _ in sus[:a.max]], ano))
    else:
        print(f"[{datetime.now():%F %T}] nenhum dia no platô por verificar em {ano}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(main())
