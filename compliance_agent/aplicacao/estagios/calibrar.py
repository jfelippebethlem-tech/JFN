# -*- coding: utf-8 -*-
"""E13 `calibrar:<detector>` — calibração contínua do registro de detectores (plano mestre v2 §3.2/§5, O5.4).

Entrada: os itens CONFERIDOS (Opus da assinatura ou gente) de cada detector. Saída: `fp_medida` (n, falsos, IC95 de
Wilson) e o tier pela régua ÚNICA (`qualidade.detectores.avaliar_tier`: Tier 1 = n ≥ 30 estratificado, ponto ≤ 15%,
limite superior do IC95 ≤ 25%, elegibilidade, cobertura ≥ 50%), gravados no registro com histórico.

Regras desta camada (as da régua ficam na régua):
  · A CADA N NOVO. Só recalcula quando há ≥ `PASSO_NOVOS` conferidos novos desde a última calibração (ou um erro
    grave novo); senão o job é `sem_novidade` e não grava nada (idempotente pela chave `calibrar:<detector>`).
  · SEM VAZAMENTO. Item de bloco reservado ao ouro (`qualidade/ouro.py`) nunca entra na conta da calibração.
  · ESTRATIFICADA. Só conta como amostra estratificada o conferido que entrou por sorteio (`amostra` 1/8 do E12) ou
    pela `cota` dos detectores de manchete. Com ≥ 30 desses, a medida é sobre eles; senão a medida é sobre todos os
    conferidos e fica `estratificada: false` (nunca Tier 1). A fila histórica da triagem foi lida por PRIORIDADE
    (🔴 primeiro, valor), não por sorteio: é `legado`.
  · ERRO GRAVE. Falso positivo conferido em item que o detector emitiu como 🔴 (severidade alta/crítica, ou `grave`
    explícito no veredito) abre `calibracao.erro_grave_aberto`: a régua tira o Tier 1 (`erro_grave_conferido`) até
    decisão do dono. É o "rebaixa no 1º erro grave conferido". O grave FECHADO por decisão (O4.10: "corrigido na
    origem", conferido por replay da versão atual) vai para `calibracao.erro_grave_fechado` e o mesmo conferido
    antigo não o reabre; só um grave NOVO reabre.
  · MEDIDA MANUAL. Medida curada à mão (sem `origem: e13`) com n MAIOR que a do fluxo não é sobrescrita — fica, e
    o histórico registra a conta do fluxo ao lado.
  · CATRACA. Tier nunca é promovido sem n mínimo: além da régua, `calibrar_entrada` recusa Tier 1 com n < 30.

Fontes de conferidos (só-leitura, `mode=ro`): `alertas_triagem.leitura_opus` (Opus) × `alertas` (tipo → id do
registro por `adaptadores.achados.regra_do_alerta`; alerta que se declara "NÃO é acusação" fica fora — não vai ao
juiz) e `fachada_veredito` (dono, `fachada_doubt`). Os laudos de perícia da fila do Opus não são saída de detector
do registro: são contados, não calibrados.

SOMBRA (padrão na PARADA DE OBRAS): grava o resultado num JSON (`--saida`), não no registro. `--gravar` grava no
`config/qualidade_detectores.yaml` SÓ os campos de calibração (`fp_medida`, `calibracao`) e os calculados do tier;
o arquivo é relido e conferido antes de gravar.

CLI:
    python -m compliance_agent.aplicacao.estagios.calibrar rodar --fonte <extrato.db> [--detector X] [--saida S.json]
    python -m compliance_agent.aplicacao.estagios.calibrar cota  --fonte <extrato.db> --saida cota.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import yaml

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.qualidade import detectores as D
from compliance_agent.qualidade import ouro

PASSO_NOVOS = 5
HIST_MAX = 20
ORIGENS_ESTRATIFICADAS = ("amostra", "cota")
# D5 (24/11/2026): o E12 grava a origem; `risco` (fila por prioridade), `amostra_zero` (sorteio só entre ⚪) e
# `prioridade` NUNCA contam como estratificados — só `amostra`/`cota` levam ao Tier 1
ORIGENS_CONHECIDAS = ("amostra", "cota", "risco", "amostra_zero", "prioridade")
SEVERIDADE_GRAVE = ("alta", "critica", "crítica")
DECIDIDO = {"provavel_falso_positivo": True, "monitorar": False, "aprofundar": False}
FACHADA = {"real": True, "fachada": False, "indicio": False}
CAMPOS_CALIBRACAO = ("fp_medida", "calibracao")
ENV_FONTE = "JFN_CALIBRAR_FONTE"
SAIDA_PADRAO = Path(__file__).resolve().parents[3] / "data" / "calibracao_sombra.json"


# ── conferidos ──────────────────────────────────────────────────────────────────────────────────────────────
def _json(txt):
    try:
        return json.loads(txt) if txt else {}
    except (ValueError, TypeError):
        return {}


def origem_de(valor) -> str:
    """A origem que o E12 gravou (`triagem_alertas.origem_conferencia`, D5). Desconhecida/ausente ⇒ `legado`."""
    v = str(valor or "").strip().lower()
    return v if v in ORIGENS_CONHECIDAS else "legado"


def conferidos_triagem(con: sqlite3.Connection) -> list[dict]:
    from compliance_agent.adaptadores.achados import regra_do_alerta
    out = []
    tem_origem = "origem_conferencia" in {r[1] for r in con.execute("PRAGMA table_info(alertas_triagem)")}
    col_origem = "t.origem_conferencia" if tem_origem else "NULL"
    for aid, leitura, rev, conf_em, tipo, sev, titulo, ev, dref, criado, org in con.execute(
            "SELECT t.alerta_id, t.leitura_opus, t.verificado_por, t.em, a.tipo, a.severidade, a.titulo, a.evidencias, "
            f"a.data_referencia, a.created_at, {col_origem} FROM alertas_triagem t JOIN alertas a ON a.id = t.alerta_id "
            "WHERE t.verificado_por IS NOT NULL AND t.leitura_opus IS NOT NULL "
            "AND COALESCE(a.descricao, '') NOT LIKE 'NÃO é acusação%'"):
        did, _ = regra_do_alerta(tipo, titulo)
        falso = DECIDIDO.get(leitura)
        sep = ouro.campos_de_separacao(_json(ev))
        sep["periodo"] = sep["periodo"] or ouro.periodo_de(dref) or ouro.periodo_de(criado)
        out.append({"detector": did, "item": f"alerta:{aid}", "falso": falso,
                    "grave": bool(falso) and str(sev or "").lower() in SEVERIDADE_GRAVE, "origem": origem_de(org),
                    "revisor": rev, "conferido_em": conf_em, "fonte": "alertas_triagem", **sep})
    return out


def conferidos_fachada(con: sqlite3.Connection) -> list[dict]:
    return [{"detector": "fachada_doubt", "item": f"fachada:{cod or ouro._h(cnpj)}", "falso": FACHADA.get(st),
             "grave": False, "origem": "legado", "revisor": "dono", "conferido_em": em, "fonte": "fachada_veredito",
             "processo": None, "entidade": cnpj, "orgao": None, "periodo": ouro.periodo_de(em)}
            for cnpj, cod, st, em in con.execute(
                "SELECT cnpj, codigo, status, veredito_em FROM fachada_veredito WHERE status <> 'pendente'")]


def ler_conferidos(fonte: str) -> tuple[list[dict], dict]:
    """Conferidos de todas as fontes + contagens do que ficou fora (sem tabela = fonte INDISPONÍVEL, dito)."""
    con = sqlite3.connect(f"file:{fonte}?mode=ro", uri=True, timeout=30)
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        itens, fora = [], {}
        if {"alertas_triagem", "alertas"} <= tabelas:
            itens += conferidos_triagem(con)
        else:
            fora["alertas_triagem"] = "INDISPONIVEL"
        if "fachada_veredito" in tabelas:
            itens += conferidos_fachada(con)
        else:
            fora["fachada_veredito"] = "INDISPONIVEL"
        if "fila_conferida" in tabelas:
            fora["pericia_fila_opus_nao_e_detector"] = con.execute("SELECT COUNT(*) FROM fila_conferida").fetchone()[0]
    finally:
        con.close()
    return itens, fora


# ── medida e tier ───────────────────────────────────────────────────────────────────────────────────────────
def medir(conferidos: list[dict]) -> dict:
    decididos = [c for c in conferidos if c.get("falso") is not None]
    estrat = [c for c in decididos if c.get("origem") in ORIGENS_ESTRATIFICADAS]
    base, estratificada = (estrat, True) if len(estrat) >= D.TIER1_N_MIN else (decididos, False)
    n, k = len(base), sum(bool(c["falso"]) for c in base)
    return {"n": n, "falsos": k, "estratificada": estratificada, "n_estratificado": len(estrat),
            "indeterminados": len(conferidos) - len(decididos), "ic95": D.wilson_ic95(k, n),
            "graves": sorted(c["item"] for c in decididos if c.get("falso") and c.get("grave")),
            "revisores": sorted({str(c.get("revisor")) for c in base})}


def marcar_ouro(conferidos: list[dict]) -> list[dict]:
    """Separação GLOBAL (todos os detectores juntos): um processo/entidade/órgão × período no ouro sai da calibração
    de TODOS os detectores. Devolve cópias com `_ouro` (bool) e `bloco`."""
    itens = [dict(c) for c in conferidos]
    _, res = ouro.separar(itens)
    ids = {id(x) for x in res}
    for x in itens:
        x["_ouro"] = id(x) in ids
    return itens


def _lados(conferidos: list[dict]) -> tuple[list[dict], list[dict]]:
    if conferidos and all("_ouro" in c for c in conferidos):
        return [c for c in conferidos if not c["_ouro"]], [c for c in conferidos if c["_ouro"]]
    return ouro.separar([dict(c) for c in conferidos])


def _por_detector(conferidos: list[dict]) -> dict[str, list[dict]]:
    por = defaultdict(list)
    for c in marcar_ouro(conferidos):
        por[c["detector"]].append(c)
    return por


def _n_anterior(entrada: dict) -> int:
    cal = entrada.get("calibracao") or {}
    return int((cal.get("ultima") or {}).get("n_conferidos") or 0)


def calibrar_entrada(did: str, entrada: dict, conferidos: list[dict], *, hoje: date, quem: str,
                     forcar: bool = False) -> dict:
    """Recalcula um detector. Função pura: devolve o resultado e os campos novos (não grava)."""
    cal, reservados = _lados(conferidos)
    m = medir(cal)
    antes = {"tier": D.avaliar_tier(entrada, hoje)["tier"], "fp_ic95": entrada.get("fp_ic95"),
             "n": (entrada.get("fp_medida") or {}).get("n") if isinstance(entrada.get("fp_medida"), dict) else None,
             "falsos": (entrada.get("fp_medida") or {}).get("falsos")
             if isinstance(entrada.get("fp_medida"), dict) else None}
    graves_antes = set((entrada.get("calibracao") or {}).get("erro_grave_aberto") or [])
    fechados = {str(g.get("id")) for g in (entrada.get("calibracao") or {}).get("erro_grave_fechado") or []
                if isinstance(g, dict)}
    graves_novos = sorted(set(m["graves"]) - graves_antes - fechados)
    novos = len(cal) - _n_anterior(entrada)
    res = {"detector": did, "antes": antes, "conferidos": len(conferidos), "reservados_ouro": len(reservados),
           "calibracao": len(cal), "novos": novos, "medida": m, "graves_novos": graves_novos}
    if not cal or m["n"] == 0:
        return {**res, "acao": "sem_conferido_decidido", "depois": antes, "campos": None}
    if not forcar and novos < PASSO_NOVOS and not graves_novos:
        return {**res, "acao": "sem_novidade", "depois": antes, "campos": None}
    fp_atual = entrada.get("fp_medida") if isinstance(entrada.get("fp_medida"), dict) else None
    manual = fp_atual is not None and fp_atual.get("origem") != "e13" and int(fp_atual.get("n") or 0) > m["n"]
    if manual:
        fp_nova = fp_atual
    else:
        p = m["falsos"] / m["n"]
        fp_nova = {"data": hoje.isoformat(),
                   "amostra": (f"{m['n']} conferido(s) decidido(s) "
                               + ("por sorteio estratificado (E12 amostra/cota)" if m["estratificada"]
                                  else "da fila por prioridade (não estratificada)")
                               + f"; {len(reservados)} reservado(s) ao ouro fora da conta"),
                   "taxa": f"{m['falsos']}/{m['n']} falsos ({p:.1%}); {m['indeterminados']} indeterminado(s)",
                   "fonte_primaria": "veredito conferido (Opus da assinatura / dono) sobre o item do detector",
                   "onde": "compliance_agent/aplicacao/estagios/calibrar.py",
                   "n": m["n"], "falsos": m["falsos"], "estratificada": m["estratificada"],
                   "cobertura": (fp_atual or {}).get("cobertura"),     # o E13 não mede cobertura: preserva
                   "origem": "e13"}
    graves = sorted((graves_antes | set(m["graves"])) - fechados)
    ultima = {"em": datetime.now().isoformat(timespec="seconds"), "quem": quem, "n_conferidos": len(cal),
              "n": m["n"], "falsos": m["falsos"], "ic95": list(m["ic95"]) if m["ic95"] else None,
              "estratificada": m["estratificada"], "revisores": m["revisores"],
              "medida_mantida": "manual" if manual else "e13"}
    hist = list((entrada.get("calibracao") or {}).get("historico") or [])
    calib = {"ultima": ultima, "erro_grave_aberto": graves or None}
    if fechados:
        calib["erro_grave_fechado"] = (entrada.get("calibracao") or {})["erro_grave_fechado"]
    nova = {**entrada, "fp_medida": fp_nova, "calibracao": calib}
    t = D.avaliar_tier(nova, hoje)
    if t["tier"] == 1 and (m["n"] < D.TIER1_N_MIN or not m["estratificada"]):   # catraca própria, além da régua
        t = {**t, "tier": 2, "tier_motivo": f"sem_n_minimo_estratificado (n={m['n']})"}
    ultima.update(tier_antes=antes["tier"], tier_depois=t["tier"], motivo=t["tier_motivo"])
    calib["historico"] = (hist + [ultima])[-HIST_MAX:]
    acao = "promove" if t["tier"] < antes["tier"] else "rebaixa" if t["tier"] > antes["tier"] else "mantem"
    return {**res, "acao": acao, "depois": {"tier": t["tier"], "fp_ic95": t["fp_ic95"], "n": fp_nova.get("n"),
                                            "falsos": fp_nova.get("falsos"), "motivo": t["tier_motivo"]},
            "campos": {"fp_medida": fp_nova, "calibracao": calib}}


def calibrar_tudo(reg: dict, conferidos: list[dict], *, hoje: date, quem: str, detector: str | None = None,
                  forcar: bool = False) -> list[dict]:
    por = _por_detector(conferidos)
    alvos = [detector] if detector else sorted(por)
    out = []
    for did in alvos:
        if did not in reg:
            out.append({"detector": did, "acao": "fora_do_registro", "conferidos": len(por.get(did, []))})
            continue
        out.append(calibrar_entrada(did, reg[did], por.get(did, []), hoje=hoje, quem=quem, forcar=forcar))
    return out


# ── cota dos detectores de manchete (entrada do E12 / conferencia_risco) ──────────────────────────────────
def cota_reservada(reg: dict, conferidos: list[dict]) -> dict[str, int]:
    """{detector de manchete: quantos conferidos estratificados faltam para n ≥ 30}. Fundido fica fora (a cota vai
    para a canônica). A medida manual estratificada conta."""
    por = _por_detector(conferidos)
    out = {}
    for did, e in sorted(reg.items()):
        if not e.get("manchete") or e.get("estado") == "fundido":
            continue
        cal, _ = _lados(por.get(did, []))
        n = medir(cal)["n_estratificado"]
        fp = e.get("fp_medida") if isinstance(e.get("fp_medida"), dict) else {}
        if fp.get("estratificada"):
            n = max(n, int(fp.get("n") or 0))
        if n < D.TIER1_N_MIN:
            out[did] = D.TIER1_N_MIN - n
    return out


def candidatos_cota(fonte: str, cota: dict[str, int], conferidos: list[dict] | None = None) -> dict[str, list[str]]:
    """Itens AINDA não conferidos pelo Opus (opus_pendente=1) de cada detector com cota, sorteados pelo hash e fora
    dos componentes do ouro (separados JUNTO com os conferidos) — a proposta de quem ocupa as vagas. Só leitura."""
    from compliance_agent.adaptadores.achados import regra_do_alerta
    con = sqlite3.connect(f"file:{fonte}?mode=ro", uri=True, timeout=30)
    cand = []
    try:
        for aid, tipo, titulo, ev in con.execute(
                "SELECT t.alerta_id, a.tipo, a.titulo, a.evidencias FROM alertas_triagem t JOIN alertas a "
                "ON a.id = t.alerta_id WHERE t.opus_pendente = 1 "
                "AND COALESCE(a.descricao, '') NOT LIKE 'NÃO é acusação%'"):
            did, _ = regra_do_alerta(tipo, titulo)
            if did in cota:
                cand.append({"detector": did, "item": f"alerta:{aid}", "_candidato": True,
                             **ouro.campos_de_separacao(_json(ev))})
    finally:
        con.close()
    por = defaultdict(list)
    for it in marcar_ouro(list(conferidos or []) + cand):
        if it.get("_candidato") and not it["_ouro"]:
            por[it["detector"]].append(it["item"])
    h = lambda s: hashlib.sha1(s.encode()).hexdigest()  # noqa: E731
    return {d: sorted(v, key=h)[:cota[d]] for d, v in por.items()}


# ── gravação no registro (só campos de calibração + calculados) ───────────────────────────────────────────
_RX_ENTRADA = re.compile(r"^  ([^\s#][^:]*?):\s*(#.*)?$")


def _linha(campo: str, valor) -> str:
    v = yaml.safe_dump(valor, allow_unicode=True, default_flow_style=True, width=10**6, sort_keys=False).strip()
    return f"    {campo}: {v.removesuffix('...').strip()}"


def trocar_campos(texto: str, campos: dict[str, dict]) -> str:
    """Em cada entrada de `campos`, tira as linhas dos campos dados (com o corpo aninhado) e grava um por linha ao
    fim da entrada. Comentários e o resto da entrada ficam como estão."""
    linhas = texto.split("\n")
    ini = next(i for i, ln in enumerate(linhas) if ln.rstrip() == "detectores:") + 1
    marcas = [(i, _RX_ENTRADA.match(ln).group(1).strip("'\"")) for i, ln in enumerate(linhas[ini:], ini)
              if _RX_ENTRADA.match(ln)]
    for j in range(len(marcas) - 1, -1, -1):
        i, did = marcas[j]
        if did not in campos:
            continue
        fim = marcas[j + 1][0] if j + 1 < len(marcas) else len(linhas)
        while fim - 1 > i and (not linhas[fim - 1].strip() or linhas[fim - 1].lstrip().startswith("#")):
            fim -= 1
        rx = re.compile(r"^    (" + "|".join(map(re.escape, campos[did])) + r"):")
        corpo, pulando = [], False
        for ln in linhas[i + 1:fim]:
            if rx.match(ln):
                pulando = True
                continue
            if pulando and (ln.startswith("      ") or ln.startswith("    - ")):
                continue
            pulando = False
            corpo.append(ln)
        linhas[i + 1:fim] = corpo + [_linha(c, v) for c, v in campos[did].items()]
    return "\n".join(linhas)


def gravar_registro(resultados: list[dict], arq: Path, hoje: date) -> list[str]:
    """Grava os campos de calibração dos detectores que mudaram e os calculados do tier. Relê e confere: qualquer
    campo fora desses que mude aborta sem gravar. Devolve os ids gravados."""
    reg = D.carregar(arq)
    mud = {r["detector"]: r["campos"] for r in resultados if r.get("campos")}
    if not mud:
        return []
    campos = {}
    for did, c in mud.items():
        nova = {**reg[did], **c}
        campos[did] = {**c, **D.campos_calculados(nova, hoje)}
    novo = trocar_campos(arq.read_text(encoding="utf-8"), campos)
    relido = yaml.safe_load(novo)["detectores"]
    gerenciados = set(CAMPOS_CALIBRACAO) | set(D.CAMPOS_CALCULADOS)
    erro = [did for did in reg if set(relido) != set(reg)
            or {k: v for k, v in relido[did].items() if k not in gerenciados}
            != {k: v for k, v in reg[did].items() if k not in gerenciados}
            or (did in campos and any(relido[did].get(k) != v for k, v in campos[did].items()))]
    if erro:
        raise RuntimeError(f"calibrar: regravação mudaria o que não devia ({erro[:5]}) — nada gravado")
    tmp = arq.with_suffix(".yaml.tmp")
    tmp.write_text(novo, encoding="utf-8")
    os.replace(tmp, arq)
    return sorted(mud)


# ── contrato do estágio ─────────────────────────────────────────────────────────────────────────────────────
def _fonte(payload: dict) -> str:
    # 27/11/2026 (religação, E13 BLOQUEADO): sem fonte no payload nem no env, a cópia do compliance.db deste nó
    # (fluxo.fonte_coleta — a mesma regra do E9); o recurso `fonte_coleta` só deixa reservar onde ela existe
    from compliance_agent.fluxo import fonte_coleta
    f = payload.get("fonte") or os.environ.get(ENV_FONTE) or str(fonte_coleta.caminho())
    if not f or not Path(f).is_file():
        raise ErroPermanente(f"calibrar: fonte de conferidos inexistente ({f!r}; use --fonte ou {ENV_FONTE})")
    return f


def _hoje(payload: dict) -> date:
    return date.fromisoformat(payload["hoje"]) if payload.get("hoje") else date.today()


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    did = payload.get("detector") or (ctx.tipo.split(":", 1)[1] if ":" in ctx.tipo else None)
    did = None if did in (None, "", "todos") else did
    fonte, hoje = _fonte(payload), _hoje(payload)
    arq = Path(payload.get("registro") or D.ARQ)
    reg = D.carregar(arq)
    if did and did not in reg:
        raise ErroPermanente(f"calibrar: detector fora do registro: {did!r}")
    conferidos, fora = ler_conferidos(fonte)
    quem = f"{ctx.no}:{ctx.chave}#{ctx.ficha}"
    res = calibrar_tudo(reg, conferidos, hoje=hoje, quem=quem, detector=did, forcar=bool(payload.get("forcar")))
    sombra = payload.get("sombra", True)
    efeito = {"sombra": sombra, "detectores": len(res), "mudaram": sorted(r["detector"] for r in res if r.get("campos")),
              "hoje": hoje.isoformat(), "fora": fora}
    if sombra:
        saida = Path(payload.get("saida") or SAIDA_PADRAO)
        corpo = {"em": datetime.now().isoformat(timespec="seconds"), "quem": quem, "hoje": hoje.isoformat(),
                 "fonte": str(fonte), "fora": fora, "cota": cota_reservada(reg, conferidos), "resultados": res}
        saida.parent.mkdir(parents=True, exist_ok=True)
        tmp = saida.with_suffix(".tmp")
        tmp.write_text(json.dumps(corpo, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        os.replace(tmp, saida)
        efeito.update(saida=str(saida), sha256=_sha(res))
    else:
        # S3: fonte INDISPONÍVEL não recalibra o registro com n menor sem rótulo (no JSON da sombra ela é dita em `fora`)
        faltam = sorted(k for k, v in fora.items() if v == "INDISPONIVEL")
        if faltam:
            raise ErroPermanente(f"calibrar: fonte(s) INDISPONÍVEL(is) em {fonte}: {', '.join(faltam)} — o registro "
                                 "não é recalibrado com o denominador parcial")
        efeito["gravados"] = gravar_registro(res, arq, hoje)
        efeito["registro"] = str(arq)
    return Resultado(efeito=efeito, eventos=[{"fonte": "calibrar", "tipo": "tier", "chave": d}
                                             for d in efeito["mudaram"]])


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    """Relê o mundo: recalcula a medida da fonte (outro processo, do zero) e exige a MESMA contagem no que foi
    gravado — no JSON da sombra ou no registro relido —, com o IC95 de Wilson batendo com (falsos, n)."""
    ef = resultado.efeito
    conferidos, _ = ler_conferidos(_fonte(payload))
    por = _por_detector(conferidos)
    if ef.get("sombra"):
        corpo = json.loads(Path(ef["saida"]).read_text(encoding="utf-8"))
        if _sha(corpo["resultados"]) != ef.get("sha256"):
            return False
        for r in corpo["resultados"]:
            if r.get("acao") == "fora_do_registro":
                continue
            m = medir(_lados(por.get(r["detector"], []))[0])
            if (m["n"], m["falsos"]) != (r["medida"]["n"], r["medida"]["falsos"]):
                return False
            ic = D.wilson_ic95(m["falsos"], m["n"])
            if (list(ic) if ic else None) != (list(r["medida"]["ic95"]) if r["medida"]["ic95"] else None):
                return False
        return True
    reg = D.carregar(Path(ef["registro"]))
    for did in ef.get("gravados") or []:
        e = reg.get(did) or {}
        ult = (e.get("calibracao") or {}).get("ultima") or {}
        m = medir(_lados(por.get(did, []))[0])
        if (ult.get("n"), ult.get("falsos")) != (m["n"], m["falsos"]):
            return False
        if any(e.get(c) != v for c, v in D.campos_calculados(e, date.fromisoformat(ef["hoje"])).items()):
            return False
    return True


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve", "fonte_coleta"], prioridade=70)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E13 calibrar (O5.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rodar")
    r.add_argument("--fonte", required=True, help="banco SÓ-LEITURA com alertas_triagem/alertas/fachada_veredito")
    r.add_argument("--detector")
    r.add_argument("--saida", default=str(SAIDA_PADRAO))
    r.add_argument("--gravar", action="store_true", help="grava no registro (fora da PARADA DE OBRAS)")
    r.add_argument("--forcar", action="store_true", help="recalcula mesmo sem n novo")
    r.add_argument("--hoje")
    c = sub.add_parser("cota", help="proposta da cota dos detectores de manchete (não altera fila nenhuma)")
    c.add_argument("--fonte", required=True)
    c.add_argument("--saida", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "cota":
        conferidos, _ = ler_conferidos(a.fonte)
        cota = cota_reservada(D.carregar(), conferidos)
        cand = candidatos_cota(a.fonte, cota, conferidos)
        Path(a.saida).write_text(json.dumps({"em": datetime.now().isoformat(timespec="seconds"), "cota": cota,
                                             "candidatos": cand,
                                             "sem_candidato": sorted(set(cota) - {d for d, v in cand.items() if v})},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"cota: {len(cota)} detector(es) de manchete abaixo de n={D.TIER1_N_MIN}; "
              f"{sum(len(v) for v in cand.values())} candidato(s) em {sum(bool(v) for v in cand.values())} detector(es)")
        print(f"aplicar na sombra da fila: python -m compliance_agent.llm.conferencia_risco sombra --cota {a.saida}")
        return 0
    payload = {"detector": a.detector, "fonte": a.fonte, "saida": a.saida, "sombra": not a.gravar,
               "forcar": a.forcar, "hoje": a.hoje}
    ctx = Contexto(no=os.environ.get("JFN_NO", "cli"), tipo=f"calibrar:{a.detector or 'todos'}",
                   chave=f"calibrar:{a.detector or 'todos'}", ficha=0, tentativa=1)
    res = _handler(payload, ctx)
    ok = _efeito(payload, ctx, res)
    print(json.dumps(res.efeito, ensure_ascii=False, default=str))
    if not ok:
        print("calibrar: EFEITO NÃO CONFERIDO", file=sys.stderr)
        return 1
    print(f"calibrar: {res.efeito['detectores']} detector(es) conferido(s); {len(res.efeito['mudaram'])} com medida nova")
    return 0


if __name__ == "__main__":
    sys.exit(main())
