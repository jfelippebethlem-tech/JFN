"""Teto ADAPTATIVO de logins simultâneos no SEI-RJ (26/11/2026, pedido do dono: "algo pra saber se dá pra aumentar ou
diminuir"). Quantas sessões o SEI aguenta pelo mesmo IP não é chute: o motor mede.

AIMD sobre a taxa de falha de CONEXÃO dos jobs do SEI (árvore E2 e captura E3) numa janela recente:
  · taxa < 2 %  → +1 sessão (até o teto declarado no yaml, `concorrencia.sei_rj_ip.max`);
  · taxa > 5 %  → metade (mínimo 1);
  · entre os dois, ou amostra < 10 jobs → mantém.
Medido na janela 1 da religação: serial, 0 conexão fechada em 74 árvores; 6 em paralelo com login novo por árvore,
10 ERR_CONNECTION_CLOSED em 45 (22 %). A falha é do método (login novo a cada árvore), não bloqueio — por isso a
medida decide e o teto pode voltar a subir quando o método melhorar.

Cada decisão vai a `fluxo.metricas` (nome `teto_adaptativo`, rótulos: etiqueta, medida, motivo); o supervisor usa o
MENOR entre o teto do yaml e o vigente (mais novo que `VALIDADE_S`). Sem decisão vigente vale o yaml.
CLI: `python -m compliance_agent.fluxo.teto_adaptativo` (rotina E18 da agenda, a cada 15 min).
"""
from __future__ import annotations

import json
import re
import sys

ETIQUETA = "sei_rj_ip"
TIPOS = ("arvore", "capturar")
JANELA_S = 1800
VALIDADE_S = 2 * 3600
MIN_AMOSTRA = 10
SOBE_ABAIXO, DESCE_ACIMA = 0.02, 0.05
_RX_CONEXAO = re.compile(r"ERR_CONNECTION|ERR_TIMED_OUT|ERR_NAME_NOT_RESOLVED|ERR_NETWORK|login no SEI falhou|"
                         r"Page\.goto: Timeout|navegação ao login falhou|net::ERR_", re.I)


def e_erro_de_conexao(texto: str | None) -> bool:
    return bool(texto) and bool(_RX_CONEXAO.search(texto))


def decidir(atual: int, n: int, erros: int, *, maximo: int, minimo: int = 1) -> tuple[int, str]:
    """(novo teto, motivo). Puro."""
    atual = max(minimo, min(maximo, int(atual)))
    if n < MIN_AMOSTRA:
        return atual, f"amostra pequena ({n} < {MIN_AMOSTRA} jobs na janela): mantém {atual}"
    taxa = erros / n
    if taxa > DESCE_ACIMA:
        novo = max(minimo, atual // 2)
        return novo, f"falha de conexão {taxa:.1%} > {DESCE_ACIMA:.0%} em {n}: {atual} → {novo}"
    if taxa < SOBE_ABAIXO:
        novo = min(maximo, atual + 1)
        return novo, (f"falha de conexão {taxa:.1%} < {SOBE_ABAIXO:.0%} em {n}: {atual} → {novo}" if novo != atual
                      else f"falha de conexão {taxa:.1%} em {n}, já no teto do yaml ({maximo})")
    return atual, f"falha de conexão {taxa:.1%} na zona morta ({SOBE_ABAIXO:.0%}–{DESCE_ACIMA:.0%}) em {n}: mantém {atual}"


def medir(con, janela_s: int = JANELA_S) -> dict:
    """Jobs do SEI que terminaram (feito) ou falharam por conexão na janela. O erro conta pelo texto do último erro
    do job (erro_resumo) quando a tentativa caiu dentro da janela."""
    feitos = con.execute(
        "SELECT count(*) FROM jobs WHERE tipo = ANY(%s) AND estado = 'feito' "
        "AND concluido_em > now() - make_interval(secs => %s)", (list(TIPOS), janela_s)).fetchone()[0]
    falhas = [r[0] for r in con.execute(
        "SELECT erro_resumo FROM jobs WHERE tipo = ANY(%s) AND estado <> 'feito' AND erro_resumo IS NOT NULL "
        "AND coalesce(concluido_em, iniciado_em) > now() - make_interval(secs => %s)", (list(TIPOS), janela_s))]
    erros = sum(1 for e in falhas if e_erro_de_conexao(e))
    return {"n": feitos + erros, "feitos": feitos, "erros": erros, "janela_s": janela_s}


def vigente(con, *, maximo: int, etiqueta: str = ETIQUETA) -> int | None:
    """O teto decidido mais novo que VALIDADE_S (limitado ao yaml), ou None (vale o yaml)."""
    r = con.execute("SELECT valor FROM metricas WHERE nome = 'teto_adaptativo' AND rotulos->>'etiqueta' = %s "
                    "AND quando > now() - make_interval(secs => %s) ORDER BY quando DESC LIMIT 1",
                    (etiqueta, VALIDADE_S)).fetchone()
    return None if r is None or r[0] is None else max(1, min(maximo, int(r[0])))


def rodar(con, *, maximo: int, atual_padrao: int = 2, etiqueta: str = ETIQUETA) -> dict:
    atual = vigente(con, maximo=maximo, etiqueta=etiqueta) or atual_padrao
    m = medir(con)
    novo, motivo = decidir(atual, m["n"], m["erros"], maximo=maximo)
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'teto_adaptativo', %s, %s)",
                (novo, json.dumps({"etiqueta": etiqueta, "anterior": atual, "medida": m, "motivo": motivo},
                                  ensure_ascii=False)))
    return {"etiqueta": etiqueta, "anterior": atual, "novo": novo, "motivo": motivo, "medida": m}


def main() -> int:
    from compliance_agent.fluxo import fila
    from compliance_agent.fluxo import grafo as G
    maximo = int(G.carregar().tetos().get(ETIQUETA) or 1)
    con = fila.conectar()
    try:
        r = rodar(con, maximo=maximo)
    finally:
        con.close()
    print(f"teto_adaptativo: {json.dumps(r, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
