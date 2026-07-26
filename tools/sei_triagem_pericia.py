# -*- coding: utf-8 -*-
"""Triagem DETERMINÍSTICA da perícia sobre o acervo SEI já capturado.

É o estágio 2 do pipeline pedido pelo dono (arquivo compacto → triagem
determinística → LLM só no que sobra). Não chama IA nenhuma: lê o manifesto de
cada processo em ``data/sei_arquivo/`` e aplica regras que ou batem ou não batem.

**A separação que decide tudo: LACUNA ≠ ACHADO.**
59% das red flags de uma safra anterior eram queixa de CAPTURA — documento que
não foi lido — apresentada como se fosse vício do processo. 874 processos só
tinham lacuna e viraram fila do fiscal à toa. Aqui os dois saem em campos
separados e um nunca vira o outro: falta de peça é ``lacunas``; contradição no
que EXISTE é ``achados``.

**Honestidade das regras.** Cada achado diz em que documento se apoia. Nenhuma
regra conclui por ausência: "não achei o parecer" é lacuna, não irregularidade.
E indício ≠ acusação — o campo ``grau`` é fila de apuração, não veredito.

Uso:
    .venv/bin/python -m tools.sei_triagem_pericia            # acervo inteiro
    .venv/bin/python -m tools.sei_triagem_pericia --limite 50
    .venv/bin/python -m tools.sei_triagem_pericia --json /tmp/triagem.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "data" / "sei_arquivo"

# Tipos que o arquivador já classifica. Fonte: contagem no acervo em 2026-07-25.
_PARECER = {"parecer_juridico", "parecer", "nota_juridica"}
_CONTRATO = {"contrato", "termo_contrato", "ata_registro_precos"}
_RESPOSTA = {"despacho", "oficio", "nota_tecnica", "informacao", "manifestacao"}
_EXECUCAO = {"medicao", "relatorio_fotografico", "atesto", "recebimento"}
_PESQUISA = {"pesquisa_preco", "mapa_precos", "cotacao", "orcamento"}

# CALIBRAGEM 2026-07-25 — o `tipo` do arquivador nao basta. Medido em 300
# processos: a regra A5 acusava 222 e em 89 deles (40%) o TITULO trazia
# "Atestado"/"Medicao"/"Recebimento" — o documento existia e o tipo nao o
# reconhecia. Auditor que exagera e ignorado; e a licao que o auditar_layout.py
# ja pagou na primeira geracao. Por isso as regras olham TIPO **ou** TITULO.
_RX_EXEC_TIT = re.compile(
    r"medi[çc][ãa]o|atesto|atestad|recebimento (provis|defin)|termo de recebimento"
    r"|relat[óo]rio fotogr", re.I)
_RX_PESQ_TIT = re.compile(
    r"pesquisa de pre[çc]|mapa de pre[çc]|cota[çc][ãa]o|or[çc]amento"
    r"|proposta comercial|painel de pre|tabela sinapi", re.I)

_RX_ACATA = re.compile(
    r"\bacat(a|o|ando|ada)\b|\bem aten[çc][ãa]o ao parecer\b|\bcumprida[s]? as\b"
    r"|\bsanad[ao]s?\b|\bretific(a|ado|ação)\b", re.I)
_RX_RESSALVA = re.compile(
    r"\bcom ressalva|\bcondicionad[oa]\b|\bdesde que\b|\brecomend(a|o|ando)\b"
    r"|\bnecess[áa]rio (que|se)\b|\bdeve[rm]? ser (sanad|corrigid|providenci)", re.I)


def _docs(man: dict) -> list[dict]:
    return [d for d in (man.get("docs") or []) if isinstance(d, dict)]


def _ordem(d: dict) -> int:
    """Ordem do documento na árvore. É o único eixo temporal confiável aqui:
    o manifesto nem sempre traz data, mas a árvore do SEI é cronológica."""
    try:
        return int(str(d.get("i") or 0))
    except (TypeError, ValueError):
        return 0


def _texto_do_doc(pasta: Path, doc: dict) -> str:
    """Texto capturado do documento, se houver. Vazio nunca vira conclusão."""
    alvo = str(doc.get("titulo") or "")
    m = re.search(r"\((\d{6,})\)|\b(\d{8,})\b", alvo)
    if not m:
        return ""
    ident = m.group(1) or m.group(2)
    for p in (pasta / "texto").glob(f"*{ident}*"):
        try:
            return p.read_text(encoding="utf-8", errors="ignore")[:20000]
        except OSError:
            return ""
    return ""


def periciar(pasta: Path) -> dict | None:
    """Triagem de UM processo. Devolve achados e lacunas SEPARADOS."""
    mf = pasta / "manifest.json"
    if not mf.exists():
        return None
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    docs = _docs(man)
    tipos = Counter(str(d.get("tipo") or "").lower() for d in docs)
    achados: list[dict] = []
    observacoes: list[dict] = []   # estrutural, NAO e contradicao — ver nota abaixo

    pareceres = [d for d in docs if str(d.get("tipo") or "").lower() in _PARECER]
    contratos = [d for d in docs if str(d.get("tipo") or "").lower() in _CONTRATO]
    respostas = [d for d in docs if str(d.get("tipo") or "").lower() in _RESPOSTA]

    # ── A1 · CONTRATO ASSINADO ANTES DO PARECER ────────────────────────────────
    # O jurídico opinou depois de o contrato já existir. É o achado mais forte que
    # a árvore sozinha sustenta: não depende de ler o texto, só da ORDEM.
    if pareceres and contratos:
        p0, c0 = min(map(_ordem, pareceres)), min(map(_ordem, contratos))
        if c0 < p0:
            achados.append({
                "codigo": "A1_CONTRATO_ANTES_DO_PARECER",
                "grau": "alto",
                "diz": "contrato formalizado ANTES do parecer jurídico",
                "apoio": f"contrato na posição {c0} · parecer na posição {p0}",
            })

    # ── A2 · PARECER COM RESSALVA E SEM RESPOSTA ───────────────────────────────
    # Parecer que condiciona ou recomenda, e nenhum documento POSTERIOR que responda.
    # Sem texto do parecer não há achado: vira lacuna, nunca conclusão por ausência.
    for pa in pareceres:
        txt = _texto_do_doc(pasta, pa)
        if not txt:
            continue
        if not _RX_RESSALVA.search(txt):
            continue
        pos = _ordem(pa)
        posteriores = [d for d in respostas if _ordem(d) > pos]
        acatou = any(_RX_ACATA.search(_texto_do_doc(pasta, d) or "") for d in posteriores)
        if not posteriores:
            achados.append({
                "codigo": "A2_PARECER_COM_RESSALVA_SEM_RESPOSTA",
                "grau": "alto",
                "diz": "parecer jurídico condiciona/recomenda e não há documento posterior que responda",
                "apoio": f"parecer na posição {pos}, {len(docs)} documentos no total",
            })
        elif not acatou:
            achados.append({
                "codigo": "A3_PARECER_COM_RESSALVA_SEM_ACATAMENTO_EXPRESSO",
                "grau": "medio",
                "diz": "há documentos posteriores, mas nenhum registra acatamento do parecer",
                "apoio": f"parecer na posição {pos} · {len(posteriores)} documento(s) posterior(es)",
            })
        break  # um achado por processo basta para a fila; o resto é da perícia

    # ── A4 · DESPESA SEM PESQUISA DE PREÇO NO PROCESSO ─────────────────────────
    # Só vale quando HÁ autorização de despesa ou empenho: aí a pesquisa deveria
    # estar. Sem nenhum dos dois, é lacuna de captura e não entra como achado.
    titulos = " | ".join(str(d.get("titulo") or "") for d in docs)
    tem_despesa = tipos.get("autorizacao_despesa", 0) or tipos.get("empenho", 0)
    tem_pesquisa = any(t in _PESQUISA for t in tipos) or bool(_RX_PESQ_TIT.search(titulos))
    if tem_despesa and not tem_pesquisa and len(docs) >= 8:
        observacoes.append({
            "codigo": "A4_DESPESA_SEM_PESQUISA_DE_PRECO",
            "grau": "medio",
            "diz": "processo autoriza despesa e não traz pesquisa de preços",
            "apoio": f"{tem_despesa} doc(s) de despesa, nenhum de pesquisa, {len(docs)} no total",
        })

    # ── A5 · EXECUÇÃO SEM EVIDÊNCIA ────────────────────────────────────────────
    tem_liq = tipos.get("liquidacao", 0) + tipos.get("nota_liquidacao", 0)
    tem_exec = any(t in _EXECUCAO for t in tipos) or bool(_RX_EXEC_TIT.search(titulos))
    fotos = int(man.get("fotos_total") or 0)
    if tem_liq and not tem_exec and not fotos:
        observacoes.append({
            "codigo": "A5_LIQUIDACAO_SEM_EVIDENCIA_DE_ENTREGA",
            "grau": "medio",
            "diz": "há liquidação e nenhuma evidência de execução (medição, atesto ou foto)",
            "apoio": f"{tem_liq} doc(s) de liquidação, 0 de execução, 0 fotos",
        })

    return {
        "processo": man.get("processo") or pasta.name,
        "pasta": pasta.name,
        "n_docs": len(docs),
        "fotos": fotos,
        "qualidade": man.get("qualidade_cache") or "sem-marca",
        # LACUNA e ACHADO em campos SEPARADOS, de propósito. Um nunca vira o outro.
        "lacunas": man.get("lacunas") or [],
        "achados": achados,
        # OBSERVAÇÃO ≠ ACHADO. A4 e A5 batiam em mais da METADE do acervo (149 e 132
        # de 299) mesmo depois de calibradas — e regra que acusa metade do universo
        # nao e fila, e ruido. A causa e estrutural e conhecida: a pesquisa de preco
        # costuma viver no processo de PLANEJAMENTO, nao no de pagamento, e a
        # evidencia de entrega as vezes fica fora do SEI. Ficam registradas, porque
        # somadas a um achado forte elas agravam — mas nao entram na fila sozinhas.
        # Auditor que exagera e ignorado: e a licao que o auditar_layout.py ja pagou.
        "observacoes": observacoes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--json", dest="saida", default="")
    a = ap.parse_args(argv)

    pastas = sorted(p for p in ARQUIVO.iterdir() if p.is_dir())
    if a.limite:
        pastas = pastas[: a.limite]

    linhas, cod, grau = [], Counter(), Counter()
    so_lacuna = com_achado = limpo = 0
    for pasta in pastas:
        r = periciar(pasta)
        if r is None:
            continue
        linhas.append(r)
        for x in r.get("observacoes", []):
            cod["(obs) " + x["codigo"]] += 1
        if r["achados"]:
            com_achado += 1
            for x in r["achados"]:
                cod[x["codigo"]] += 1
                grau[x["grau"]] += 1
        elif r["lacunas"]:
            so_lacuna += 1
        else:
            limpo += 1

    print(f"\n=== TRIAGEM DETERMINÍSTICA · {len(linhas)} processos do acervo ===\n")
    print(f"  com ACHADO (contradição no que existe) .. {com_achado}")
    print(f"  só LACUNA (falta peça — é captura) ...... {so_lacuna}")
    print(f"  sem achado e sem lacuna ................. {limpo}")
    print("\n  achados por código:")
    for k, v in cod.most_common():
        print(f"    {v:>5}  {k}")
    print("\n  por grau:", dict(grau))
    print("\n  LACUNA NÃO É ACHADO: os dois saem em campos separados e o fiscal")
    print("  vê a diferença antes de abrir o processo.")

    if a.saida:
        Path(a.saida).write_text(
            json.dumps(linhas, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  laudo completo → {a.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
