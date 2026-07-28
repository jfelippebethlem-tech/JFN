#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analisa processos SEI um a um, aponta indícios e registra no segundo cérebro.

    .venv/bin/python tools/sei_analise_em_serie.py --n 10 [--vault] [--so-fila]
    .venv/bin/python tools/sei_analise_em_serie.py --fila           # só mostra a ordem

O QUE ESTE PIPELINE FAZ, e por que cada etapa está onde está:

    1. FILA por relevância — processo com mais pagamento primeiro. Fiscalizar em ordem
       alfabética é desperdiçar a primeira hora do dia.
    2. DOSSIÊ (`sei_dossie_md`) — a IA lê os documentos e extrai fatos COM citação; o código
       agrupa. Cabe inteiro na janela na maioria dos casos; fraciona só na cauda.
    3. INDÍCIOS (`indicios_dossie`) — réguas de código sobre o texto já citado.
    4. CONFRONTO entre caminhos independentes — o que a extração por REGEX
       (`agentes_publicos`) encontrou de responsáveis contra o que a IA leu. Divergência entre
       dois métodos independentes é informação sobre AMBOS: onde a regex cala e a IA acha, há
       grafia nova a aprender; onde a regex acha e a IA cala, houve falha de leitura.
    5. NOTA no vault (`~/vault/processos/`), com links, para o conhecimento sobreviver à sessão.

HONESTIDADE: indício é hipótese a verificar. O grau é prioridade INTERNA de diligência, nunca
nota pública. Processo sem indício pode ser processo limpo OU processo sem dado — e a nota diz
qual dos dois, informando a cobertura de leitura.

RETOMADA: o índice em `data/analise_serie.json` guarda o que já foi analisado; relançar continua
de onde parou em vez de refazer (e o dossiê tem checkpoint próprio por lote).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))
VAULT = pathlib.Path(os.path.expanduser("~/vault/processos"))
INDICE = pathlib.Path("data/analise_serie.json")
DB = os.environ.get("JFN_DB", "data/compliance.db")


def _norm_sei(pasta: str) -> str:
    """`030001_004946_2026` → `030001/004946/2026`, para exibição."""
    return pasta.replace("_", "/")


def _chave(numero: str) -> str:
    """Só os dígitos — a única forma de casar as duas bases.

    O campo `processo` do SIAFE tem grafias muito diferentes para o mesmo tipo de número:
    `SEI-100003/000108/2026` (67.645 linhas), `sei-10003/00054/2025`, `330003/001581/2024`,
    `2026-06041596`, `4572/26`, e até `-` puro (12.082 linhas, que é ausência). Comparar texto
    com texto casava 4 processos de 2.055; comparar dígito com dígito é o que funciona.

    Devolve "" quando não há dígitos suficientes para identificar — e "" nunca casa com nada,
    que é o comportamento correto para "não sei qual processo é este".
    """
    d = "".join(ch for ch in str(numero or "") if ch.isdigit())
    return d if len(d) >= 12 else ""


def _pagos_por_chave(*, so_contratacao: bool = True) -> dict[str, float]:
    """Total de OB por processo, indexado pela chave de dígitos. OB = pagamento = verdade.

    `so_contratacao` exclui repasse intragoverno e transferência a fundo — e isso MUDA a
    prioridade de forma decisiva. Medido em 2026-07-28: o maior processo sem texto capturado
    tinha R$ 1,42 bilhão, mas o credor era o "Fundo de Equalização Federativa". Transferência
    federativa é obrigação constitucional, não contratação: não há licitação a fiscalizar ali,
    e colocá-la no topo da fila desviaria a primeira hora do dia do analista.
    """
    from compliance_agent.entidades_gov import eh_nao_fornecedor

    pagos: dict[str, float] = {}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        for numero, nome, total in con.execute(
            "SELECT processo, MIN(nome_credor), SUM(COALESCE(valor,0)) "
            "FROM ob_orcamentaria_siafe WHERE COALESCE(processo,'') <> '' GROUP BY processo"
        ):
            if so_contratacao and eh_nao_fornecedor(nome or ""):
                continue
            if (k := _chave(numero)):
                pagos[k] = pagos.get(k, 0.0) + float(total or 0)
        con.close()
    except sqlite3.Error as e:
        print(f"aviso: não consegui ler pagamentos ({e}) — fila sai sem ordenação por valor")
    return pagos


def fila(limite: int | None = None) -> list[tuple[str, float]]:
    """Processos do acervo ordenados por pagamento (OB do SIAFE — a fonte de verdade).

    Processo sem pagamento localizado vai para o fim com 0.0, e o 0.0 aqui significa "não
    encontrei OB para este número", não "não houve pagamento".
    """
    # Pasta com diretório `texto` mas SEM .txt dentro é processo conhecido e não capturado —
    # não é processo analisável. Medido em 2026-07-28: os dois maiores do acervo por pagamento
    # (R$ 1,4 bi e R$ 571 mi) estavam assim, e iam para o topo da fila de ANÁLISE, onde não há
    # nada a analisar. Eles pertencem a outra fila, a de CAPTURA — ver `sem_texto()`.
    pastas = [p.name for p in ACERVO.iterdir()
              if (p / "texto").is_dir() and any((p / "texto").glob("*.txt"))]
    pagos = _pagos_por_chave()

    ordenada = sorted(((p, pagos.get(_chave(p), 0.0)) for p in pastas), key=lambda x: -x[1])
    return ordenada[:limite] if limite else ordenada


def sem_texto(limite: int | None = None) -> list[tuple[str, float]]:
    """Processos conhecidos, com pagamento, e SEM texto capturado — a fila de CAPTURA.

    É o inverso da fila de análise, e vale mais por processo: cada um destes é dinheiro pago
    sobre o qual não se leu uma linha. Ordenar por valor diz o que pedir primeiro.
    """
    pagos = _pagos_por_chave()
    vazios = []
    for p in ACERVO.iterdir():
        if not p.is_dir():
            continue
        td = p / "texto"
        if td.is_dir() and any(td.glob("*.txt")):
            continue
        vazios.append((p.name, pagos.get(_chave(p.name), 0.0)))
    vazios.sort(key=lambda x: -x[1])
    return vazios[:limite] if limite else vazios


def recaptura(limite: int | None = None, *, minimo_vazios: float = 0.30) -> list[dict]:
    """Processos capturados PELA METADE — a fila de RECAPTURA.

    A Fase C2 do plano previa "re-extrair os 4.695 documentos com chars=0". Medido em
    2026-07-28: **é impossível como planejado**. Os .txt existem e estão vazios (4.692 de
    4.695), mas o arquivo de ORIGEM não foi guardado — o acervo tem `texto/` e `fotos/`, e um
    único PDF em 2.055 processos. Não há de onde re-extrair.

    Logo, esses documentos precisam de RECAPTURA no SEI, não de reprocessamento local. Esta
    função monta essa fila, priorizada por valor pago e por proporção de documentos cegos: um
    processo lido pela metade é pior que um não lido, porque parece analisado.
    """
    import json

    pagos = _pagos_por_chave()
    fila = []
    for pasta in sorted(ACERVO.iterdir()):
        manifesto = pasta / "manifest.json"
        if not manifesto.is_file():
            continue
        try:
            docs = (json.loads(manifesto.read_text()).get("docs") or [])
        except (OSError, json.JSONDecodeError):
            continue
        if not docs:
            continue
        vazios = sum(1 for d in docs if not int(d.get("chars") or 0))
        if not vazios:
            continue
        prop = vazios / len(docs)
        if prop < minimo_vazios:
            continue
        fila.append({"processo": pasta.name, "n_docs": len(docs), "vazios": vazios,
                     "proporcao": prop, "pago": pagos.get(_chave(pasta.name), 0.0)})
    fila.sort(key=lambda x: (-x["pago"], -x["proporcao"]))
    return fila[:limite] if limite else fila


def pais_nao_capturados(limite: int | None = None) -> list[dict]:
    """Processos-PAI citados pelos capturados e ausentes do acervo — a fila que destrava
    os responsáveis.

    Medido em 2026-07-28 sobre os 300 primeiros processos: 77 citam um relacionado, somando 114
    processos-pai apontados, e **apenas 8 têm texto no acervo (7%)**. Por isso ler o pai não
    elevou a cobertura de responsáveis em nada: o mecanismo funciona, mas não há o que ler do
    outro lado.

    O ato de designação de fiscal e gestor vive no processo de CONTRATAÇÃO, e o que se captura
    em volume é o de PAGAMENTO. Cada linha desta fila é um pai que, capturado, tende a
    identificar os responsáveis de um ou mais processos já lidos — e prioriza-se pelo valor
    pago dos FILHOS, que é o que está em jogo.
    """
    from compliance_agent.sei.relacionados import (
        numero_para_pasta, pasta_para_numero, relacionados_de,
    )

    cache = pathlib.Path(os.environ.get("JFN_SEI_CACHE", "data/sei_cache"))
    pagos = _pagos_por_chave()
    por_pai: dict[str, dict] = {}
    for p in sorted(ACERVO.iterdir()):
        if not (p / "texto").is_dir():
            continue
        for rel in relacionados_de(pasta_para_numero(p.name), cache)[:3]:
            alvo = ACERVO / numero_para_pasta(rel)
            if (alvo / "texto").is_dir() and any((alvo / "texto").glob("*.txt")):
                continue                       # o pai já está capturado
            d = por_pai.setdefault(rel, {"pai": rel, "filhos": [], "valor_filhos": 0.0})
            d["filhos"].append(p.name)
            d["valor_filhos"] += pagos.get(_chave(p.name), 0.0)
    fila = sorted(por_pai.values(),
                  key=lambda x: (-x["valor_filhos"], -len(x["filhos"])))
    return fila[:limite] if limite else fila


def _ler_indice() -> dict:
    try:
        return json.loads(INDICE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def gravar_indice_mesclado(caminho, feitos_nesta_rodada: dict) -> None:
    """Grava relendo o disco: esta rodada só afirma o que ELA analisou.

    O read-modify-write sem merge já custou caro: 22 processos foram removidos do índice para
    releitura (leitura antiga feita com tacada acima do teto de contexto) e o lote que já
    rodava, com o índice lido ANTES da remoção, gravou a sua cópia por cima. Os 22 voltaram a
    constar como "analisados" sem que um único dossiê fosse refeito. Dois lotes concorrentes
    se apagariam do mesmo jeito, em silêncio.

    Adição de terceiro fica; remoção de terceiro é respeitada — a menos que ESTA rodada tenha
    analisado o mesmo item agora, caso em que o fato novo prevalece.
    """
    caminho = pathlib.Path(caminho)
    try:
        no_disco = json.loads(caminho.read_text())
        if not isinstance(no_disco, dict):
            no_disco = {}
    except (OSError, json.JSONDecodeError):
        no_disco = {}
    no_disco.update(feitos_nesta_rodada)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(no_disco, ensure_ascii=False, indent=1), encoding="utf-8")


def _gravar_indice(d: dict) -> None:
    gravar_indice_mesclado(INDICE, d)


def confronto_responsaveis(pasta: str, dossie: str) -> dict:
    """Compara o que a REGEX extraiu com o que a IA leu — dois caminhos independentes.

    Divergência entre métodos independentes é informação sobre os dois. Onde a regex cala e a
    IA acha um nome com ID, há grafia nova para a régua aprender; onde a regex acha e a IA não
    menciona, a leitura falhou naquele documento. É assim que um método ensina o outro.
    """
    import re

    regex_nomes: set[str] = set()
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        regex_nomes = {r[0] for r in con.execute(
            "SELECT nome FROM agente_processo WHERE processo = ?", (pasta,))}
        con.close()
    except sqlite3.Error:
        pass

    ids_no_dossie = set(re.findall(r"\b\d{6,8}-\d\b", dossie or ""))
    ids_da_regex: set[str] = set()
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        ids_da_regex = {r[0] for r in con.execute(
            "SELECT id_funcional FROM agente_processo "
            "WHERE processo = ? AND id_funcional IS NOT NULL", (pasta,))}
        con.close()
    except sqlite3.Error:
        pass

    return {
        "regex_nomes": sorted(regex_nomes),
        "ids_regex": sorted(ids_da_regex),
        "ids_dossie": sorted(ids_no_dossie),
        "so_no_dossie": sorted(ids_no_dossie - ids_da_regex),
        "so_na_regex": sorted(ids_da_regex - ids_no_dossie),
    }


def leitura_incompleta(dossie: str) -> int:
    """Quantos lotes de documentos ficaram FORA do dossiê por falha de leitura.

    O dossiê fracionado registra "lote N não pôde ser lido — nenhum provedor respondeu" e
    segue. A contagem do cabeçalho ("Documentos com texto: 35", "leitura integral") vem da
    CAPTURA, não da leitura — então um dossiê sem um único fato extraído continua parecendo
    completo. Medido em 2026-07-28: 4 dos 157 processos analisados estavam assim, somando
    R$ 70.201.773,31, e os 4 geraram nota com `indicios: 0`.
    """
    return len(re.findall(r"lote \d+ não pôde ser lido", dossie or ""))


def _nota_vault(pasta: str, pago: float, dossie: str, indicios, conf: dict) -> str:
    from compliance_agent.sei.indicios_dossie import resumo_md

    graus = {i.grau for i in indicios}
    perdidos = leitura_incompleta(dossie)
    # Leitura incompleta nunca sai como 🔵: "0 indícios" só pode significar "procurei e não
    # achei". Quando o modelo não respondeu, o honesto é "não procurei", e isso precisa vir
    # ANTES do número — é a diferença entre processo limpo e processo não lido.
    tag = ("🔴" if "prioritario" in graus else "🟡" if "atencao" in graus
           else "⚠️" if perdidos else "🔵")
    valor = (f"R$ {pago:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
             if pago else "não localizado no SIAFE")
    aviso = ([f"> ⚠️ **LEITURA INCOMPLETA — {perdidos} lote(s) de documentos não foram lidos** "
              "(nenhum provedor respondeu na hora da extração). Os documentos desse(s) lote(s) "
              "**não entraram** neste dossiê: o número de indícios abaixo mede o que foi lido, "
              "não o processo. Relançar `tools/sei_dossie_md.py` retoma só os lotes que faltam.",
              ""] if perdidos else [])
    linhas = [
        "---",
        f"processo: {_norm_sei(pasta)}",
        f"pago_ob_siafe: {pago:.2f}" if pago else "pago_ob_siafe: null",
        f"indicios: {len(indicios)}",
        *([f"leitura_incompleta: {perdidos}"] if perdidos else []),
        f"analisado_em: {time.strftime('%Y-%m-%d')}",
        "---",
        "",
        f"# {tag} Processo {_norm_sei(pasta)}",
        "",
        *aviso,
        f"**Pago (OB SIAFE):** {valor}  ",
        f"**Indícios apontados:** {len(indicios)}"
        + (" *(sobre a parte lida — ver aviso acima)*" if perdidos else ""),
        "",
        "> Documento de trabalho. Indício é hipótese a verificar, não afirmação de "
        "irregularidade — vigora a presunção de legitimidade dos atos administrativos.",
        "",
        resumo_md(list(indicios)),
        "",
        "## Confronto entre métodos de extração",
        "",
        "Dois caminhos independentes leram o mesmo processo: a régua por expressão regular e a "
        "leitura por modelo. Onde discordam, há o que aprender nos dois lados.",
        "",
        f"- IDs funcionais pela régua: {', '.join(conf['ids_regex']) or '—'}",
        f"- IDs funcionais no dossiê: {', '.join(conf['ids_dossie']) or '—'}",
    ]
    if conf["so_no_dossie"]:
        linhas.append(f"- ⚠️ **Só a leitura achou** (grafia nova para a régua aprender): "
                      f"{', '.join(conf['so_no_dossie'])}")
    if conf["so_na_regex"]:
        linhas.append(f"- ⚠️ **Só a régua achou** (a leitura passou batido): "
                      f"{', '.join(conf['so_na_regex'])}")
    linhas += ["", "## Dossiê completo", "",
               f"Ver `output/dossies/{pasta}.md` — extração integral com as citações por "
               "documento.", "",
               "## Ligações", "",
               "[[MOC-Casos]] · [[aprendizados/honestidade-investigacao]]"]
    return "\n".join(linhas)


def analisar(pasta: str, pago: float, *, vault: bool = True) -> dict:
    from tools.sei_dossie_md import gerar
    from compliance_agent.sei.indicios_dossie import varrer

    destino = pathlib.Path("output/dossies") / f"{pasta}.md"
    if not destino.exists():
        gerar(pasta, vault=False)
    if not destino.exists():
        return {"processo": pasta, "erro": "dossiê não foi gerado"}

    dossie = destino.read_text()
    indicios = varrer(dossie)
    conf = confronto_responsaveis(pasta, dossie)

    if vault:
        VAULT.mkdir(parents=True, exist_ok=True)
        (VAULT / f"{pasta}.md").write_text(_nota_vault(pasta, pago, dossie, indicios, conf))

    return {"processo": pasta, "pago": pago, "n_indicios": len(indicios),
            "indicios": [i.to_dict() for i in indicios],
            "citacoes": dossie.count("[doc"),
            "ids_so_no_dossie": conf["so_no_dossie"],
            "ids_so_na_regex": conf["so_na_regex"],
            "analisado_em": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="quantos processos analisar")
    ap.add_argument("--fila", action="store_true", help="só mostra a ordem; não analisa")
    ap.add_argument("--fila-pais", action="store_true",
                    help="processos-pai citados e não capturados (destravam os responsáveis)")
    ap.add_argument("--fila-recaptura", action="store_true",
                    help="processos lidos pela metade (documentos com texto vazio)")
    ap.add_argument("--fila-captura", action="store_true",
                    help="processos com pagamento e SEM texto — o que pedir primeiro")
    ap.add_argument("--sem-vault", action="store_true")
    ap.add_argument("--refazer", action="store_true", help="ignora o índice e reanalisa")
    a = ap.parse_args()

    ordem = fila()
    if a.fila:
        print(f"{len(ordem)} processo(s) no acervo · top 25 por pagamento (OB SIAFE):\n")
        for p, v in ordem[:25]:
            print(f"  {('R$ %0.2f' % v).replace('.', ','):>22}  {p}")
        print("\n0,00 = OB não localizada para este número, NÃO 'não houve pagamento'.")
        return 0

    if a.fila_pais:
        # Nome local distinto de propósito: `fila` é função de módulo e sombreá-la já quebrou
        # este arquivo duas vezes (F823 — referenciada antes da atribuição, lá embaixo).
        pendentes_pai = pais_nao_capturados()
        com_valor = [x for x in pendentes_pai if x["valor_filhos"] > 0]
        # NÃO somar `valor_filhos` entre pais: um filho que cita DOIS pais teria seu valor
        # contado duas vezes, e o total inflaria. O que está em jogo é o conjunto de FILHOS
        # distintos cujos responsáveis seguem desconhecidos.
        filhos_distintos = {f for x in pendentes_pai for f in x["filhos"]}
        pagos_map = _pagos_por_chave()
        total = sum(pagos_map.get(_chave(f), 0.0) for f in filhos_distintos)
        print(f"{len(pendentes_pai)} processo(s)-pai citados e NÃO capturados · "
              f"{len(com_valor)} com filho que tem pagamento · "
              f"{len(filhos_distintos)} filho(s) distinto(s) afetado(s), somando "
              f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "\n")
        for x in pendentes_pai[:30]:
            v = (f"R$ {x['valor_filhos']:,.2f}".replace(",", "X").replace(".", ",")
                 .replace("X", ".") if x["valor_filhos"] else "—")
            print(f"  {v:>20}  {x['pai']:<24} {len(x['filhos'])} filho(s) já capturado(s)")
        print("\nO ato de designação de fiscal e gestor vive no processo de CONTRATAÇÃO; o que "
              "se captura em volume é o de PAGAMENTO. Capturar estes tende a identificar os "
              "responsáveis dos filhos já lidos.")
        return 0

    if a.fila_recaptura:
        pendentes_rec = recaptura()
        tot_vazios = sum(x["vazios"] for x in pendentes_rec)
        com_valor = [x for x in pendentes_rec if x["pago"] > 0]
        print(f"{len(pendentes_rec)} processo(s) com ao menos 30% dos documentos sem texto · "
              f"{tot_vazios} documento(s) cegos · {len(com_valor)} com pagamento localizado\n")
        for x in pendentes_rec[:30]:
            v = (f"R$ {x['pago']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                 if x["pago"] else "—")
            print(f"  {v:>20}  {x['processo']:<22} {x['vazios']:>3}/{x['n_docs']:<3} "
                  f"({x['proporcao']*100:.0f}% cegos)")
        print("\nEstes documentos NÃO podem ser re-extraídos: o arquivo de origem não foi "
              "guardado (o acervo tem só `texto/` e `fotos/`). Precisam de RECAPTURA no SEI.")
        print("Processo lido pela metade é pior que não lido — parece analisado.")
        return 0

    if a.fila_captura:
        vazios = sem_texto()
        com_valor = [(p, v) for p, v in vazios if v > 0]
        total = sum(v for _, v in com_valor)
        print(f"{len(vazios)} processo(s) conhecidos SEM texto capturado; {len(com_valor)} "
              f"com pagamento localizado, somando "
              f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "\n")
        for p, v in com_valor[:30]:
            print(f"  {('R$ %0.2f' % v).replace('.', ','):>22}  {p}")
        print("\nCada linha é dinheiro pago sobre o qual não se leu uma linha do processo.")
        return 0

    indice = {} if a.refazer else _ler_indice()
    pendentes = [(p, v) for p, v in ordem if p not in indice][:a.n]
    if not pendentes:
        print("nada pendente — use --refazer para reanalisar")
        return 0

    print(f"analisando {len(pendentes)} processo(s); {len(indice)} já no índice\n")
    for i, (pasta, pago) in enumerate(pendentes, 1):
        print(f"[{i}/{len(pendentes)}] {pasta}")
        try:
            r = analisar(pasta, pago, vault=not a.sem_vault)
        except Exception as e:  # noqa: BLE001 — um processo ruim não para a série
            print(f"    falhou: {type(e).__name__}: {str(e)[:120]}")
            continue
        indice[pasta] = r
        # grava só o resultado DESTA rodada; o merge preserva o disco (ver
        # `gravar_indice_mesclado`) e não ressuscita o que foi removido para releitura
        gravar_indice_mesclado(INDICE, {pasta: r})
        if r.get("erro"):
            print(f"    {r['erro']}")
            continue
        print(f"    {r['n_indicios']} indício(s) · {r['citacoes']} citações")
        for ind in r["indicios"]:
            print(f"      {ind['grau']:12} {ind['codigo']:5} {ind['titulo']}")
        if r["ids_so_no_dossie"]:
            print(f"      ⚠️ IDs só na leitura: {r['ids_so_no_dossie']}")

    print(f"\níndice: {INDICE} ({len(indice)} processos)")
    print("Lembrete: indício é hipótese a verificar. Processo sem indício pode ser processo "
          "sem dado — leia a cobertura no dossiê.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
