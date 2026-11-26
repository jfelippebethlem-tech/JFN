"""Teto ADAPTATIVO de logins simultâneos no SEI-RJ (26/11/2026, pedido do dono: "algo pra saber se dá pra aumentar ou
diminuir"). Quantas sessões o SEI aguenta pelo mesmo IP não é chute: o motor mede.

AIMD sobre a taxa de falha de CONEXÃO dos jobs do SEI (árvore E2 e captura E3) numa janela recente:
  · taxa < 2 %  → +1 sessão (até o teto declarado no yaml, `concorrencia.sei_rj_ip.max`);
  · taxa > 5 %  → metade (mínimo 1);
  · entre os dois, ou amostra < 10 jobs → mantém (o corte não espera amostra: 3+ falhas acima de 5 % já cortam).
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
MIN_AMOSTRA = 10          # para SUBIR
MIN_ERROS_CORTE = 3       # para DESCER basta isto acima de DESCE_ACIMA
MEMORIA_CORTE_S = 6 * 3600  # o nível que sofreu corte não volta por 6 h (sem isso oscilava 2→3→corte a cada ~45 min)
SOBE_ABAIXO, DESCE_ACIMA = 0.02, 0.05
_RX_CONEXAO = re.compile(r"ERR_CONNECTION|ERR_TIMED_OUT|ERR_NAME_NOT_RESOLVED|ERR_NETWORK|login no SEI falhou|"
                         r"Page\.goto: Timeout|navegação ao login falhou|net::ERR_", re.I)


def e_erro_de_conexao(texto: str | None) -> bool:
    return bool(texto) and bool(_RX_CONEXAO.search(texto))


def decidir(atual: int, n: int, erros: int, *, maximo: int, minimo: int = 1) -> tuple[int, str]:
    """(novo teto, motivo). Puro."""
    atual = max(minimo, min(maximo, int(atual)))
    if n and erros >= MIN_ERROS_CORTE and erros / n > DESCE_ACIMA:
        # corte NÃO espera amostra: falha em massa derruba a vazão, e a vazão baixa travava a descida (26/11 17h15)
        novo = max(minimo, atual // 2)
        return novo, f"falha de conexão {erros / n:.1%} ({erros} em {n}) > {DESCE_ACIMA:.0%}: {atual} → {novo}"
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


def nivel_que_falhou(con, etiqueta: str = ETIQUETA) -> int | None:
    """Menor nível que sofreu corte nas últimas MEMORIA_CORTE_S (o controle não volta a ele)."""
    r = con.execute("SELECT min((rotulos->>'corte_de')::int) FROM metricas WHERE nome = 'teto_adaptativo' "
                    "AND rotulos->>'etiqueta' = %s AND rotulos ? 'corte_de' "
                    "AND quando > now() - make_interval(secs => %s)", (etiqueta, MEMORIA_CORTE_S)).fetchone()
    return r[0] if r else None


def rodar(con, *, maximo: int, atual_padrao: int = 2, etiqueta: str = ETIQUETA) -> dict:
    atual = vigente(con, maximo=maximo, etiqueta=etiqueta) or atual_padrao
    m = medir(con)
    falhou = nivel_que_falhou(con, etiqueta)
    limite = min(maximo, falhou - 1) if falhou else maximo
    novo, motivo = decidir(atual, m["n"], m["erros"], maximo=max(1, atual, limite))
    if limite < maximo and novo == atual == limite and "já no teto" in motivo:
        motivo = (f"falha de conexão {m['erros'] / max(1, m['n']):.1%} em {m['n']}; não sobe: o nível {falhou} "
                  f"falhou nas últimas {MEMORIA_CORTE_S // 3600} h")
    rot = {"etiqueta": etiqueta, "anterior": atual, "medida": m, "motivo": motivo}
    if novo < atual:
        rot["corte_de"] = atual
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'teto_adaptativo', %s, %s)",
                (novo, json.dumps(rot, ensure_ascii=False)))
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
