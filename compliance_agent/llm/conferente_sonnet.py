# -*- coding: utf-8 -*-
"""conferente_sonnet — conferente INTERMEDIÁRIO antes do Opus no E12 (plano mestre v2 §17 item 1 (b), O6.6).

Por que existe (24/11/2026): a regra de risco (O6.5) retém ~49,1% de ~779 itens/dia (≈ 383/dia) e a assinatura
comporta ~47–71 conferências do Opus por dia. A fila não fecha só com o Opus. Proposta para o LOTE DO DONO:

  ENTRADA (com `JFN_CONFERENCIA_RISCO=1` E `JFN_CONFERENTE_SONNET=1`): o item retido (`pendente`) vai DIRETO ao Opus
  se tem `divergencia` ou `grave`, ou OB paga ≥ `JFN_CONFERENTE_LIMIAR_ALTO` (valor ALTO, padrão R$ 10 mi; OB não
  consultável conta como alto — INDISPONÍVEL ≠ 0). O resto (valor médio, baixa confiança, amostra, cota) entra com
  status `sonnet` — só nas tarefas de `JFN_CONFERENTE_TAREFAS` (padrão `TAREFAS_PADRAO`, SEM a perícia integral:
  medido, o Sonnet leva 225 s por processo contra 210 s do Opus, e o peso do Sonnet na cota não está medido).
  SONNET (`conferir`): o Sonnet da assinatura (`claude_motor.pensar(..., backend="cli")`, NUNCA a API) relê a MESMA
  entrada com o MESMO sistema. Sobe ao Opus (volta a `pendente`, motivo em `risco`) quando:
    · o Sonnet diverge do motor — `JFN_CONFERENTE_DIVERGENCIA=qualquer` (padrão: qualquer nível diferente, a leitura
      literal do §17) ou `grave` (só |Δ| ≥ 2; |Δ| = 1 fecha com o Sonnet, que prevalece pelo aplicador);
    · o Sonnet dá 🔴 (nível 2), não dá nível, ou responde fora do formato;
    · sorteio 1/8 do que o Sonnet fecharia (a amostra contínua que mede o Sonnet contra o Opus, §3.10 item 2).
  Senão fecha como `conferido_sonnet`. O par Sonnet × motor vai ao cruzamento (`cruzamento_motores.db`): os pares
  Sonnet × Opus no mesmo item alimentam a régua do Sonnet (`tools/automelhoria_modelos._SQL_SONNET`).

  RÓTULO: o par (conferencia_sonnet × claude-sonnet-5-5 × PROMPT_VERSION) NÃO tem régua cumprida (bancada 0 grave em
  54/50/32, abaixo de n = 125 e sem ouro congelado) ⇒ `conferido_sonnet` continua PENDENTE para o consumidor (nunca
  VERIFICADO) e o rótulo é "NÃO JULGADO — proposta de claude-sonnet-5-5" até o dono aprovar o par em
  `config/regras_novas.yaml` (`qualidade/regua.checar`).

DESLIGADO por padrão. Sem a variável, `conferencia_opus` se comporta exatamente como antes. Não roda com o ritmo
contido nem em economia (`conferencia_sonnet` não é reserva do Opus).

    python -m compliance_agent.llm.conferente_sonnet simular --proposta data/conferencia_risco_proposta.json
    python -m compliance_agent.llm.conferente_sonnet --conferir N        # só com a flag; rodada pela assinatura
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import zlib
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TAREFA = "conferencia_sonnet"
PROMPT_VERSION = "cs-1"             # mesma entrada e mesmo sistema do produtor; muda se o envelope mudar
MODELO = "claude-sonnet-5-5"        # = claude_api.MODELO_VOLUME (conferido no teste)
STATUS_SONNET = "sonnet"            # aguardando o Sonnet
STATUS_FECHADO = "conferido_sonnet"
LIMIAR_ALTO_PADRAO = 10_000_000.00
MOTIVOS_OPUS = ("divergencia", "grave")
TAREFAS_PADRAO = ("pericia_execucao", "camada_subjetiva", "investigacao_risco")
AMOSTRA_A_CADA = 8
MAX_TENTATIVAS = 3
TIMEOUT_S = 600.0
ESPERA_TRAVA_S = 420.0
_COLUNAS = (("modelo_sonnet", "TEXT"), ("veredito_sonnet", "TEXT"), ("nivel_sonnet", "INTEGER"),
            ("resposta_sonnet", "TEXT"), ("sonnet_em", "TEXT"), ("sonnet_decisao", "TEXT"))


def ativo() -> bool:
    return os.environ.get("JFN_CONFERENTE_SONNET", "").strip().lower() in ("1", "true", "on", "sim")


def limiar_alto() -> float:
    try:
        return float(os.environ.get("JFN_CONFERENTE_LIMIAR_ALTO") or LIMIAR_ALTO_PADRAO)
    except ValueError:
        return LIMIAR_ALTO_PADRAO


def tarefas() -> tuple[str, ...]:
    v = os.environ.get("JFN_CONFERENTE_TAREFAS", "").strip()
    return tuple(t.strip() for t in v.split(",") if t.strip()) if v else TAREFAS_PADRAO


def modo_divergencia() -> str:
    m = os.environ.get("JFN_CONFERENTE_DIVERGENCIA", "").strip().lower()
    return "grave" if m == "grave" else "qualquer"


def _sorteado(chave: str) -> bool:
    return int(hashlib.sha1(f"sonnet\x00{chave}".encode("utf-8", "replace")).hexdigest()[:12], 16) % AMOSTRA_A_CADA == 0


# ── regras puras ──────────────────────────────────────────────────────────────────────────────────────────────
def rota(motivos, valor: float | None, *, tarefa: str, valor_aplica: bool = True, alto: float | None = None,
         com_sonnet: tuple[str, ...] | None = None) -> str:
    """'opus' | 'sonnet' para um item RETIDO. Valor não consultável de item de processo ⇒ Opus (na dúvida, sobe)."""
    alto = limiar_alto() if alto is None else alto
    if tarefa not in (tarefas() if com_sonnet is None else com_sonnet):
        return "opus"
    if set(motivos or ()) & set(MOTIVOS_OPUS):
        return "opus"
    if valor is None and valor_aplica:
        return "opus"
    if valor is not None and valor >= alto:
        return "opus"
    return "sonnet"


def depois_do_sonnet(nivel_motor, nivel_sonnet, chave: str, modo: str | None = None) -> tuple[str, str]:
    """('opus' | 'fecha', motivo) depois que o Sonnet respondeu."""
    modo = modo or modo_divergencia()
    if nivel_sonnet is None:
        return "opus", "sonnet_sem_nivel"
    if nivel_sonnet == 2:
        return "opus", "sonnet_grave"
    if nivel_motor is not None and nivel_motor != nivel_sonnet:
        if modo == "qualquer" or abs(int(nivel_motor) - int(nivel_sonnet)) >= 2:
            return "opus", "sonnet_divergiu"
    if _sorteado(chave):
        return "opus", "sonnet_amostra"
    return "fecha", "sonnet_concorda" if nivel_motor == nivel_sonnet else "sonnet_divergencia_leve"


def regua_cumprida() -> bool:
    """O par do conferente cumpre a régua (§3.10) com aprovação do dono? Só então `conferido_sonnet` sai da pendência."""
    from compliance_agent.qualidade import regua
    return regua.checar(TAREFA, MODELO, PROMPT_VERSION, f"{PROMPT_VERSION}+{MODELO}")["julgado"]


# ── entrada (chamado por conferencia_opus.enfileirar) ───────────────────────────────────────────────────────────
def status_de_entrada(status: str, motivos, *, tarefa: str, item: str | None, valor: float | None,
                      valor_ob=None) -> str:
    """Com a flag: item `pendente` sem motivo de Opus direto vira `sonnet`. Sem a flag ou não pendente: inalterado."""
    if not ativo() or status != "pendente" or tarefa not in tarefas():
        return status
    from compliance_agent.llm import conferencia_risco as risco
    proc = risco.processo_do_item(item)
    if valor is None and proc and not set(motivos or ()) & set(MOTIVOS_OPUS):
        try:
            valor = (valor_ob or risco._valor_ob_de)(proc)
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("conferente Sonnet: OB de %s ilegível (%s) — vai ao Opus", proc, type(e).__name__)
            valor = None
    return "pendente" if rota(motivos, valor, tarefa=tarefa, valor_aplica=proc is not None) == "opus" else STATUS_SONNET


def garantir_colunas(con: sqlite3.Connection) -> None:
    tem = {r[1] for r in con.execute("PRAGMA table_info(fila)")}
    for nome, tipo in _COLUNAS:
        if nome not in tem:
            con.execute(f"ALTER TABLE fila ADD COLUMN {nome} {tipo}")
    if "risco" not in tem:
        con.execute("ALTER TABLE fila ADD COLUMN risco TEXT")
    con.commit()


# ── rodada do Sonnet ──────────────────────────────────────────────────────────────────────────────────────────
def conferir(n: int = 8, *, pensar=None, con: sqlite3.Connection | None = None, escolher=None, ritmo=None,
             executar_em=None) -> list[dict]:
    """O Sonnet da assinatura confere até `n` itens `sonnet`. Sem a flag não faz nada. Mesma trava de ritmo e mesmo
    executor da conferência do Opus; teste injeta `pensar`/`escolher`/`ritmo`/`executar_em`."""
    if not ativo():
        return []
    from compliance_agent.llm import claude_motor, cruzamento
    from compliance_agent.llm import conferencia_executor as exe
    from compliance_agent.llm import conferencia_opus as CO
    producao = pensar is None
    pensar = pensar or claude_motor.pensar
    executar, executor = None, None
    if producao or escolher is not None or ritmo is not None:
        barrado = (ritmo or exe.motivo_ritmo)(TAREFA)
        if barrado:
            logger.info("conferente Sonnet: rodada não confere — %s", barrado)
            return []
        executor, porque = (escolher or exe.escolher)()
        if executor is None:
            logger.warning("conferente Sonnet: nenhum executor da assinatura disponível — %s", porque)
            return []
        executar = (executar_em or exe.executar_em)(executor)
    extra = {"executar": executar} if executar is not None else {}
    proprio = con is None
    con = con or CO.conectar()
    feitos: list[dict] = []
    try:
        garantir_colunas(con)
        rows = con.execute(f"SELECT id, chave, tarefa, item, entrada, sistema, motor, veredito, nivel, risco FROM fila "
                           f"WHERE status=? {CO._ORDEM} LIMIT ?", (STATUS_SONNET, max(1, n))).fetchall()
        for fid, chave, tarefa, item, blob, sistema, motor, ver, niv, rsc in rows:
            entrada = zlib.decompress(blob).decode("utf-8", "replace") if blob else ""
            p = pensar(TAREFA, entrada, modelo=MODELO, sistema=sistema or "", backend="cli", timeout=TIMEOUT_S,
                       espera=ESPERA_TRAVA_S, **extra)
            if p is None:
                if not CO._RE_RECUSA_ITEM.search(claude_motor.ultimo_motivo or ""):
                    break                                    # sem assinatura agora: para sem gastar tentativa
                con.execute("UPDATE fila SET tentativas=tentativas+1, status=CASE WHEN tentativas+1>=? THEN 'pendente' "
                            "ELSE status END, risco=CASE WHEN tentativas+1>=? THEN TRIM(COALESCE(risco,'')||"
                            "',sonnet_recusou', ',') ELSE risco END WHERE id=?", (MAX_TENTATIVAS, MAX_TENTATIVAS, fid))
                con.commit()
                feitos.append({"id": fid, "tarefa": tarefa, "item": item, "estado": "Sonnet recusou ou estourou o prazo"})
                continue
            v_s, n_s = CO._normalizar(tarefa, p.texto)
            decisao, motivo = depois_do_sonnet(niv, n_s, chave)
            novo = "pendente" if decisao == "opus" else STATUS_FECHADO
            risco_novo = ",".join(x for x in (rsc, motivo) if x)
            con.execute("UPDATE fila SET status=?, risco=?, modelo_sonnet=?, veredito_sonnet=?, nivel_sonnet=?, "
                        "resposta_sonnet=?, sonnet_em=?, sonnet_decisao=?, tentativas=0 WHERE id=? AND status=?",
                        (novo, risco_novo, p.modelo, (v_s or None) and str(v_s)[:80], n_s, p.texto[:60000],
                         datetime.now().isoformat(timespec="seconds"), motivo, fid, STATUS_SONNET))
            con.commit()
            try:
                cruzamento.cruzar(tarefa, item, cruzamento.Lado("claude", p.modelo, v_s, n_s),
                                  cruzamento.Lado("cascata", motor, ver, niv), entrada_resumo=entrada[:600])
            except (sqlite3.Error, OSError, ValueError) as e:
                logger.warning("conferente Sonnet: cruzamento não gravado (%s)", type(e).__name__)
            aplicado = None
            if decisao == "fecha" and n_s is not None and niv is not None and n_s != niv:
                aplicado = CO._aplicar(tarefa, item, p.texto, p.modelo, 0)   # divergência leve: vale o Sonnet
            feitos.append({"id": fid, "tarefa": tarefa, "item": item, "motor": motor, "antes": niv, "sonnet": n_s,
                           "decisao": decisao, "motivo": motivo, "aplicado": aplicado, "executor": executor})
        return feitos
    finally:
        if proprio:
            con.close()


# ── simulação da vazão (números da O6.5) ──────────────────────────────────────────────────────────────────────
# Tempos MEDIDOS (s por item, mediana): Sonnet e Opus da execução na bancada de 23/11 (50 cada); Sonnet da integral
# na mesma bancada (35); Opus da integral = 200–220 s medidos na conferência de 21/11 (`conferencia_opus.TIMEOUT_S`).
TEMPOS_S = {"pericia_execucao": {"opus": 26.6, "sonnet": 18.4},
            "pericia_integral": {"opus": 210.0, "sonnet": 225.4},
            "outros": {"opus": 26.6, "sonnet": 18.4}}
# Fração que SOBE ao Opus depois do Sonnet (antes da amostra 1/8), por modo. Medido: "qualquer" = nível do Opus ≠ do
# motor nos conferidos da fila (execução 214/302, integral 117/150); "grave" = |Δ| ≥ 2 ou 🔴 (execução 39/302,
# integral 33/150). Na bancada da execução, o próprio Sonnet: 20/49 (qualquer) e 2/49 (grave) — o lado otimista.
ESCALA = {"qualquer": {"pericia_execucao": 214 / 302, "pericia_integral": 117 / 150, "outros": 214 / 302},
          "grave": {"pericia_execucao": 39 / 302, "pericia_integral": 33 / 150, "outros": 39 / 302}}
ESCALA_OTIMISTA = {"qualquer": {"pericia_execucao": 20 / 49}, "grave": {"pericia_execucao": 2 / 49}}


def mix_da_proposta(itens: list[dict], alto: float = LIMIAR_ALTO_PADRAO,
                    com_sonnet: tuple[str, ...] = TAREFAS_PADRAO) -> dict:
    """{tarefa: {retidos, opus_direto}} dos itens que a regra de risco reteve (proposta da sombra da O6.5)."""
    out: dict = {}
    for i in itens:
        if i.get("decisao") != "fila":
            continue
        t = i["tarefa"] if i["tarefa"] in TEMPOS_S else "outros"
        d = out.setdefault(t, {"retidos": 0, "opus_direto": 0})
        d["retidos"] += 1
        proc = str(i.get("item") or "").startswith("sei:")
        d["opus_direto"] += rota(i.get("motivos"), i.get("valor"), tarefa=i["tarefa"], valor_aplica=proc, alto=alto,
                                 com_sonnet=com_sonnet) == "opus"
    return out


def capacidade_semanal_dias() -> float:
    """Dias-equivalentes de cota por semana pelo ritmo (`ritmo_assinatura`): a linha libera (ALVO − PISO)/7 por dia
    e o dia da virada sobe a TETO_FIM — o excedente vale como fração de um dia a mais."""
    from compliance_agent.llm import ritmo_assinatura as R
    por_dia = (R.ALVO_SEMANA - R.PISO) / 7
    return 7 + (R.TETO_FIM - R.ALVO_SEMANA) / por_dia


def capacidade_s(mix: dict, cap_opus_dia: float, tempos: dict | None = None) -> float:
    """Capacidade diária em segundos-Opus: `cap_opus_dia` conferências (O6.5: 47–71) no tempo médio do mix retido."""
    tempos = tempos or TEMPOS_S
    total = sum(d["retidos"] for d in mix.values()) or 1
    return cap_opus_dia * sum(d["retidos"] / total * tempos[t]["opus"] for t, d in mix.items())


def simular(mix: dict, *, retidos_dia: float, cap_s: float, peso_sonnet: float, modo: str | None = None,
            sem: tuple[str, ...] = (), escala: dict | None = None, tempos: dict | None = None) -> dict:
    """Vazão diária em segundos-Opus de assinatura (o Sonnet custa `peso_sonnet` segundo-Opus por segundo — peso NÃO
    medido). `modo=None` ⇒ só Opus. `sem` = tarefas cortadas NA ORIGEM (alavanca (a) do §17: não entram na fila).
    Os `retidos_dia` se dividem pelo mix; as tarefas cortadas somem da demanda."""
    tempos = tempos or TEMPOS_S
    total = sum(d["retidos"] for d in mix.values()) or 1
    opus_it = sonnet_it = opus_s = sonnet_s = ret = 0.0
    for t, d in mix.items():
        if t in sem:
            continue
        r = retidos_dia * d["retidos"] / total
        ret += r
        direto = r if modo is None else r * d["opus_direto"] / d["retidos"]
        son = r - direto
        esc = (escala or ESCALA.get(modo) or {}).get(t, ESCALA["qualquer" if modo is None else modo]["outros"])
        sobe = son * esc
        sobe += (son - sobe) / AMOSTRA_A_CADA
        opus_it += direto + sobe
        sonnet_it += son
        opus_s += (direto + sobe) * tempos[t]["opus"]
        sonnet_s += son * tempos[t]["sonnet"]
    demanda = opus_s + peso_sonnet * sonnet_s
    fecha = min(1.0, cap_s / demanda) if demanda else 1.0
    semana = min(1.0, cap_s * capacidade_semanal_dias() / (7 * demanda)) if demanda else 1.0
    return {"modo": modo or "so_opus", "peso_sonnet": peso_sonnet, "sem": list(sem), "retidos_dia": round(ret, 1),
            "opus_itens_dia": round(opus_it, 1), "sonnet_itens_dia": round(sonnet_it, 1),
            "demanda_s": round(demanda), "capacidade_s": round(cap_s), "fracao_que_fecha": round(fecha, 3),
            "fracao_que_fecha_semana": round(semana, 3)}


def cenarios(itens: list[dict], *, entrada_dia: float = 779.0, frac_retidos: float = 0.491, caps=(47.0, 71.0),
             pesos=(1.0, 0.5, 0.2), alto: float = LIMIAR_ALTO_PADRAO) -> list[dict]:
    """S0 só Opus · S1 Sonnet em todas as tarefas · S2 Sonnet sem a integral (padrão) · S3 = S2 com a perícia integral
    cortada na origem (E11 só pela assinatura não entra na fila). Capacidade fixa em segundos-Opus do mix atual."""
    base = mix_da_proposta(itens, alto, com_sonnet=tuple({i["tarefa"] for i in itens}))
    padrao = mix_da_proposta(itens, alto)
    ret = entrada_dia * frac_retidos
    out = []
    for cap in caps:
        cs = capacidade_s(base, cap)
        out.append({"cenario": "S0", "cap_opus_dia": cap, **simular(base, retidos_dia=ret, cap_s=cs, peso_sonnet=0)})
        for nome, mix, sem in (("S1", base, ()), ("S2", padrao, ()), ("S3", padrao, ("pericia_integral",))):
            for modo in ("qualquer", "grave"):
                for w in pesos:
                    out.append({"cenario": nome, "cap_opus_dia": cap, **simular(
                        mix, retidos_dia=ret, cap_s=cs, peso_sonnet=w, modo=modo, sem=sem)})
        out.append({"cenario": "S3-so-opus", "cap_opus_dia": cap, **simular(
            base, retidos_dia=ret, cap_s=cs, peso_sonnet=0, sem=("pericia_integral",))})
    return out


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Conferente intermediário Sonnet (E12) — flag JFN_CONFERENTE_SONNET")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("simular", help="vazão Sonnet + Opus × só Opus com a proposta da O6.5 (sem LLM)")
    s.add_argument("--proposta", required=True)
    s.add_argument("--entrada-dia", type=float, default=779.0)
    s.add_argument("--retidos", type=float, default=0.491)
    s.add_argument("--alto", type=float, default=LIMIAR_ALTO_PADRAO)
    ap.add_argument("--conferir", type=int, metavar="N")
    a = ap.parse_args(argv)
    if a.cmd == "simular":
        itens = json.loads(Path(a.proposta).read_text(encoding="utf-8"))["itens"]
        print(json.dumps({"mix": mix_da_proposta(itens, a.alto),
                          "cenarios": cenarios(itens, entrada_dia=a.entrada_dia, frac_retidos=a.retidos, alto=a.alto)},
                         ensure_ascii=False, indent=1))
        return 0
    if a.conferir:
        print(json.dumps(conferir(a.conferir), ensure_ascii=False))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
