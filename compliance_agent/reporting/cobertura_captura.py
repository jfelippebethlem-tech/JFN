# -*- coding: utf-8 -*-
"""Quanto do que foi PAGO o motor consegue ler — o número que limita todos os outros.

Por que existe. O painel mostra achados, fila do fiscal e cobertura da perícia, e nenhum deles
diz o mais básico: sobre que fração do dinheiro a casa consegue afirmar alguma coisa. Medido em
2026-08-04, o quadro era este e só existia para quem rodasse ferramenta de linha de comando:

    38.955 processos com OB paga NUNCA foram tocados     R$ 13,86 bi
       234 arquivados sem captura utilizável              (94 sem teor · 86 parciais · 54 sem docs)
     1.941 arquivados e íntegros                          ← a base de tudo que o motor afirma

Um painel que mostra 51 processos EXTREMO sem dizer que eles saem de 1.941 lidos, num universo de
40 mil pagos, deixa a impressão contrária à verdade. INDISPONÍVEL ≠ 0, e ponto cego medido é
melhor que ponto cego calado.

HONESTIDADE: a contagem de "nunca tocados" vem do SIAFE (`ob_orcamentaria_siafe`, status
Contabilizado — OB é pagamento, empenho não), que é a fonte canônica da casa. Folha, previdência
e encargo entram SEPARADOS: não são alvo da fiscalização de contratação, e somá-los ao ponto cego
inflaria o problema com dinheiro que ninguém pretende auditar por este caminho.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_ACERVO = _REPO / "data" / "sei_arquivo"


def _estado_do_acervo(base: Path) -> dict[str, int]:
    """Quantos processos arquivados estão íntegros, parciais, sem teor ou sem índice.

    Lê o manifesto UMA vez por processo. A versão anterior chamava `docs_com_conteudo` e depois
    `captura_integra`, que reabre e reparseia o mesmo JSON — três leituras por processo, 30
    segundos no acervo inteiro. O `J()` do painel aborta em 30s: a promessa rejeitava e a aba
    INTEIRA deixava de renderizar, sem erro no console. Cartão que mata a aba é pior que cartão
    nenhum. (2026-08-04)
    """
    from compliance_agent.sei import acervo_texto

    fora = {"integro": 0, "parcial": 0, "sem_teor": 0, "sem_docs": 0, "teto_de_coleta": 0}
    if not base.is_dir():
        return fora
    for p in base.iterdir():
        if not p.is_dir() or p.name.startswith("_"):
            continue
        mf = p / "manifest.json"
        if not mf.exists():
            continue
        try:
            man = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
        if not docs:
            fora["sem_docs"] += 1
            continue
        # mesmo critério do `manifesto_norm.captura_integra` — 60% dos declarados com teor —
        # mas sem reabrir o manifesto: os caminhos já estão em mãos.
        # TETO DE COLETA: o painel dizia 1.941 íntegros enquanto o motor recusava 176 deles.
        # Arquivo montado do CACHE do sweep parado em EXATAMENTE 40 documentos é corte, não
        # processo completo — medido em 2026-08-05: dos 1.902 arquivos vindos do cache, 176 param
        # em 40 e ZERO passa disso; o cache do SEI-170002/000732/2022 registra árvore de 783
        # documentos contra 40 lidos. É a mesma régua de `manifesto_norm.captura_integra`, e a
        # razão de estar duplicada aqui é a de sempre neste arquivo: uma leitura por processo, ou
        # a aba inteira do painel deixa de renderizar.
        if len(docs) == 40 and "CACHE do sweep" in str(man.get("aviso") or ""):
            fora["teto_de_coleta"] += 1
            continue
        com = sum(1 for d in docs
                  if d.get("texto") and acervo_texto.tem_conteudo(p / str(d["texto"])))
        if com == 0:
            fora["sem_teor"] += 1
        elif com >= max(1, int(len(docs) * 0.6)):
            fora["integro"] += 1
        else:
            fora["parcial"] += 1
        # A bandeira `captura_vazia`/`captura_completa` do manifesto NÃO entra aqui de propósito:
        # o disco é que diz o estado da captura, e bandeira desmentida pelo disco é dado velho —
        # a mesma doutrina que `manifesto_norm.captura_integra` aplica desde 2026-08-04.
    return fora


def _restricao_por_unidade(caminho: Path, base: Path) -> dict[str, Any]:
    """Quanto do que a casa TENTOU ler está fora do alcance por nível de acesso — e onde.

    "Nunca tocado" e "tentado e barrado" são cegueiras diferentes, e só a segunda é um limite
    INSTITUCIONAL: o processo existe, o itkava tem login, e mesmo assim a árvore não abre. O
    registro de controle (`sei_restritos.json`, alimentado a cada leitura do sweep) confirma
    RESTRITO só com duas leituras 0-doc de processo que EXISTE no cadastro.

    Medido em 2026-08-04, e a restrição é da UNIDADE, não do processo:

        040014 Fundo Único de Previdência ....  93% restrito  (52 de 56 tentados)
        260006/080001/260007 Fundo Est. Saúde .  31%–58%
        080002 Fundação Saúde ................  50%  (130 de 261)
        270131 / 270003 / 270006 .............  1%–3%

    Metade da Saúde está assim classificada, e a Fundação Saúde é justamente a entidade que paga
    27% de tudo por TAC/indenização. Isso não é achado contra ninguém — é o tamanho do que a casa
    NÃO pode afirmar hoje.

    ATRIBUIÇÃO HONESTA, e a casa tem regra sobre isto: **nunca culpar acesso**. O número acima é a
    classificação do REGISTRO DE CONTROLE (`sei_restritos`), que marca RESTRITO quando a árvore não
    abre em duas leituras de um processo que existe no cadastro — inclusive depois de o sweep
    tentar o caminho *cracked*. É evidência consistente de nível de acesso restrito do PROCESSO
    (sigilo), não de falta de permissão da nossa conta: processos ostensivos das MESMAS unidades
    abrem normalmente, e é isso que faz o percentual variar de 1% a 93% entre unidades. Confirmar
    por amostra com o leitor canônico (`tools/sei_consultar`) antes de qualquer afirmação externa.
    """
    fora: dict[str, Any] = {"disponivel": False}
    reg_path = base.parent / "sei_restritos.json"
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fora
    if not isinstance(reg, dict) or not reg:
        return fora

    nomes: dict[str, str] = {}
    valores: dict[str, float] = {}
    try:
        con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        try:
            melhor: dict[str, tuple[int, str]] = {}
            for pre, nome, n, v in con.execute(
                    "SELECT substr(numero_sei, 5, 6), ug_nome, COUNT(*), "
                    "       COALESCE(SUM(valor), 0) FROM ordens_bancarias "
                    "WHERE numero_sei LIKE 'SEI-%' GROUP BY 1, 2"):
                if not pre:
                    continue
                # o VALOR é por prefixo, somando todos os rótulos de UG que apareçam nele
                valores[str(pre)] = valores.get(str(pre), 0.0) + float(v or 0)
                if nome and int(n or 0) > melhor.get(str(pre), (0, ""))[0]:
                    melhor[str(pre)] = (int(n), str(nome))
            nomes = {k: v[1] for k, v in melhor.items()}
        finally:
            con.close()
    except sqlite3.Error:
        # a mesma consulta traz nome e valor: perdendo-a, perdem-se os dois. Zerar `valores`
        # explicitamente evita ordenar por um rateio pela metade.
        nomes, valores = {}, {}

    por: dict[str, dict[str, int]] = {}
    total = restritos = 0
    for e in reg.values():
        if not isinstance(e, dict):
            continue
        st = str(e.get("status") or "")
        pre = str(e.get("prefixo") or "?")
        d = por.setdefault(pre, {"lidos": 0, "restritos": 0})
        d["lidos"] += 1
        total += 1
        if st in ("RESTRITO", "RESTRITO?"):
            d["restritos"] += 1
            restritos += 1
    # PERCENTUAL SEM DINHEIRO ENGANA. Medido em 2026-08-04: a unidade que lidera a restrição
    # (040014, 93%) tem 40 processos somando R$ 0,9 mi, enquanto a Fundação Saúde, com 50%,
    # responde por R$ 10,41 bi. Ordenar por percentual poria a primeira no topo do cartão como se
    # fosse o maior ponto cego — e ela é o menor. Ordena-se pelo VALOR barrado.
    unidades = [
        {"ug": ug, "nome": nomes.get(ug, ""), "lidos": d["lidos"], "restritos": d["restritos"],
         "pct": round(100 * d["restritos"] / d["lidos"], 0),
         "valor_pago": round(valores.get(ug, 0.0), 2),
         "valor_sob_restricao": round(valores.get(ug, 0.0) * d["restritos"] / d["lidos"], 2)}
        for ug, d in por.items() if d["lidos"] >= 20 and d["restritos"]
    ]
    unidades.sort(key=lambda u: u["valor_sob_restricao"], reverse=True)
    # A JANELA IMPORTA. O registro de controle começou em 2026-07-14; o progresso do sweep conhece
    # 9.112 processos tentados no total. Dizer "dos processos que o sweep tentou ler" sobre 1.268
    # sugeriria que essa é a experiência inteira da casa — não é, é a parte com veredito
    # registrado. O campo declara o começo da janela para que o cartão possa dizê-lo.
    desde = min((str(e.get("primeira") or "") for e in reg.values()
                 if isinstance(e, dict) and e.get("primeira")), default="")
    return {"disponivel": True, "processos_tentados": total, "restritos": restritos,
            "desde": desde[:10],
            "pct": round(100 * restritos / total, 1) if total else None,
            "por_unidade": unidades[:8],
            "nota_valor": ("`valor_sob_restricao` é RATEIO PROPORCIONAL: o valor pago da unidade "
                           "multiplicado pela fração de processos classificados como restritos. "
                           "Supõe que o processo barrado vale a média da unidade, o que não se "
                           "sabe — serve para ordenar o ponto cego por relevância, nunca para "
                           "ser citado como quantia."),
            }


def medir(*, db: str | Path | None = None, acervo: Path | None = None) -> dict[str, Any]:
    """Cobertura de captura: o que o motor lê, o que não lê, e quanto dinheiro há de cada lado."""
    caminho = Path(db or os.environ.get("JFN_DB") or _DB)
    base = Path(acervo or _ACERVO)
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}

    estado = _estado_do_acervo(base)
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        tem = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='ob_orcamentaria_siafe'").fetchone()
        if not tem:
            # A porta fechada é fato independente da fonte de pagamento: sem o SIAFE não se diz
            # QUANTO dinheiro está fora do alcance, mas continua-se dizendo QUANTOS processos a
            # casa tentou ler e não conseguiu. Esconder o limite de acesso por falta de outra
            # tabela seria calar duas coisas por causa de uma.
            return {"ok": True, "indisponivel": True, "acervo": estado,
                    "restricao": _restricao_por_unidade(caminho, base),
                    "motivo": ("`ob_orcamentaria_siafe` ausente — sem a fonte canônica de "
                               "pagamento não se afirma quanto do dinheiro está fora do alcance")}
        # universo: processos SEI com OB paga (Contabilizado); o resto é empenho/cancelado
        universo, pago = con.execute(
            "SELECT COUNT(DISTINCT processo), ROUND(COALESCE(SUM(valor), 0), 2) "
            "FROM ob_orcamentaria_siafe "
            "WHERE processo LIKE 'SEI-%/%/20%' AND status='Contabilizado'").fetchone()
    finally:
        con.close()

    arquivados = sum(estado.values())
    return {
        "ok": True, "indisponivel": False,
        "acervo": estado,
        "restricao": _restricao_por_unidade(caminho, base),
        "arquivados": arquivados,
        "processos_com_ob_paga": universo,
        "nunca_tocados": max(0, (universo or 0) - arquivados),
        "valor_pago_universo": pago,
        "pct_arquivado": round(100 * arquivados / universo, 1) if universo else None,
        "pct_utilizavel": round(100 * estado["integro"] / universo, 1) if universo else None,
        "nota": ("Sobre 'nunca tocados' a casa não afirma NADA — não é ausência de irregularidade, "
                 "é ausência de leitura. Os parciais e sem teor voltam à fila do sweep pelo "
                 "critério do `captura_integra` (ver tools/sei_sweep._arquivo_incompleto)."),
    }
