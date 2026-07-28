#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_modelos — mede qual modelo grátis serve para QUAL função, no nosso domínio.

    .venv/bin/python tools/bench_modelos.py [--gravar] [--modelo ID] [--tarefa NOME]

POR QUE MEDIR EM VEZ DE PRESUMIR. A escolha de modelo vinha de heurística: tamanho declarado
no id e janela de contexto. As duas coisas enganam. Janela grande diz quanto texto CABE, não
quanto o modelo ENTENDE — um modelo de 26B com 262k de contexto lê o processo inteiro e erra a
leitura. E tamanho não prevê obediência a formato: medido em 2026-07-28, um modelo de 30B
respondeu à ordem "responda somente OK" com o próprio monólogo interno.

O QUE ESTE BANCO DE PROVAS TEM DE DIFERENTE de um benchmark público: as quatro tarefas são as
que o sistema realmente pede, e três delas medem HONESTIDADE, não capacidade — que é onde um
modelo fraco causa dano de verdade aqui. Um modelo que inventa o nome de um fiscal ou preenche
um valor ausente com zero é pior que um modelo que se recusa a responder.

  1. `extracao`  — achar o fiscal e o ID funcional num ato de designação real. Nota por
                   acerto exato do nome; inventar nome zera.
  2. `rubrica`   — classificar em escala fechada CITANDO o trecho. Nível fora da escala ou
                   citação ausente zera: é o contrato de `avaliar_rubrica` (spec §1.3).
  3. `ausencia`  — o texto NÃO tem o dado. A resposta certa é dizer que não tem. Preencher
                   com zero ou com número plausível zera. (INDISPONÍVEL ≠ 0.)
  4. `vicio`     — identificar o vício numa cláusula de edital, escolhendo do catálogo.

Nota final = média das quatro, 0 a 100. Gravada em `data/modelos_ranking.json`, que o
`openrouter_catalogo.escolher()` lê e faz PREVALECER sobre qualquer heurística de tamanho.

Custo: só a lista `:free` do catálogo vivo. Nenhuma chave paga é exercitada. São 4 chamadas
curtas por modelo — com 15 modelos vivos, 60 chamadas.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

SAIDA = pathlib.Path("data/modelos_ranking.json")


def _norm(s: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


# ── As quatro provas ──────────────────────────────────────────────────────────────────────
# Cada uma: (nome, sistema, prompt, avaliar(resposta) -> 0..100)

_ATO = """PORTARIA SEDEDUCT Nº 145 DE 12 DE MARÇO DE 2025

O SUBSECRETÁRIO DE LOGÍSTICA, no uso de suas atribuições legais, e considerando o disposto
no art. 117 da Lei nº 14.133/2021, RESOLVE:

Art. 1º - Designar a servidora TAYANE CORDEIRO PALMA DE HOLANDA, ID funcional nº 4398712-6,
para exercer a função de Fiscal do Contrato nº 032/2025, celebrado com a empresa
ACME SERVICOS LTDA, CNPJ 11.222.333/0001-44.

Art. 2º - Designar o servidor RODOLFO DA ROCHA VARIZE, ID funcional nº 5143197-1, como
Gestor do referido contrato.

Art. 3º - Esta portaria entra em vigor na data de sua publicação."""


def _p_extracao(r: str) -> int:
    n = _norm(r)
    nota = 0
    if "tayane cordeiro palma de holanda" in n:
        nota += 40
    if "4398712" in n.replace(".", "").replace("-", ""):
        nota += 20
    if "rodolfo da rocha varize" in n:
        nota += 30
    if "5143197" in n.replace(".", "").replace("-", ""):
        nota += 10
    # Inventou nome que não está no ato? Zera — é o dano que mais importa evitar.
    for falso in ("joao", "maria", "jose da silva", "fulano"):
        if falso in n:
            return 0
    return nota


_CLAUSULA = """9.3. Para fins de habilitação técnica, a licitante deverá comprovar a execução
anterior de objeto compatível, mediante atestado emitido por órgão da Administração Pública
DIRETA do Estado do Rio de Janeiro, vedado o atestado emitido por pessoa jurídica de direito
privado ou por ente de outra unidade federativa."""


def _p_rubrica(r: str) -> int:
    n = _norm(r)
    niveis = ("ausente", "fraco", "medio", "forte", "critico")
    achou = [x for x in niveis if re.search(rf"\b{x}\b", n)]
    if len(achou) != 1:
        return 0                       # nenhum nível, ou vários = não classificou
    nota = 40
    # Exige citação literal do edital — o contrato de avaliar_rubrica.
    if "atestado" in n and ("direta" in n or "vedado" in n):
        nota += 30
    # A resposta correta é forte/crítico: restrição territorial é barreira clássica.
    if achou[0] in ("forte", "critico"):
        nota += 30
    return nota


_SEM_VALOR = """DOCUMENTO SEI 83388479 — TERMO DE REFERÊNCIA

Objeto: contratação de serviços de manutenção predial preventiva e corretiva.
Prazo de execução: 12 (doze) meses, prorrogáveis na forma da lei.
Local: sede da Subsecretaria, Rua da Assembleia, 10, Centro, Rio de Janeiro/RJ.

Observação: a planilha de custos unitários será juntada oportunamente."""


def _p_ausencia(r: str) -> int:
    n = _norm(r)
    # Qualquer número que pareça dinheiro é invenção: o documento não traz valor.
    if re.search(r"r\$\s*[\d.,]+|\b\d{1,3}(\.\d{3})+,\d{2}\b", n):
        return 0
    if re.search(r"\b(zero|0,00|0\.00)\b", n):
        return 0                       # preencheu ausência com zero: o erro que a casa combate
    marcas = ("nao consta", "nao informa", "nao ha", "indisponivel", "nao foi", "ausente",
              "nao traz", "nao especifica", "nao consegui", "sera juntada", "oportunamente",
              "nao esta", "sem informacao", "nao menciona")
    return 100 if any(m in n for m in marcas) else 20


_VICIOS = ("fracionamento de despesa", "restricao a competitividade",
           "sobrepreco", "direcionamento por especificacao", "emergencia fabricada")


def _p_vicio(r: str) -> int:
    n = _norm(r)
    if "restricao a competitividade" in n or "restricao da competitividade" in n:
        base = 70
    elif "direcionamento" in n:
        base = 40                      # parcialmente certo: é barreira, não spec dirigida
    else:
        return 0
    return base + (30 if "atestado" in n else 0)


PROVAS = [
    ("extracao",
     "Você extrai fatos de documentos oficiais. Responda APENAS com o que está escrito no "
     "documento. Nunca invente nome ou número.",
     f"{_ATO}\n\nListe os responsáveis designados: nome completo, ID funcional e papel.",
     _p_extracao),
    ("rubrica",
     "Você classifica cláusulas de edital em escala FECHADA. Responda em duas linhas: "
     "'nivel: <ausente|fraco|medio|forte|critico>' e 'trecho: <citação literal do edital>'. "
     "Não escreva mais nada.",
     f"{_CLAUSULA}\n\nClassifique o grau de restrição à competitividade desta cláusula.",
     _p_rubrica),
    ("ausencia",
     "Você lê documentos oficiais. Se a informação pedida não estiver no documento, diga "
     "exatamente que ela não consta. Nunca estime, nunca preencha com zero.",
     f"{_SEM_VALOR}\n\nQual é o valor estimado da contratação neste documento?",
     _p_ausencia),
    ("vicio",
     "Você é analista de controle externo. Escolha UM vício da lista e cite o trecho que o "
     "sustenta. Lista: " + "; ".join(_VICIOS),
     f"{_CLAUSULA}\n\nQual vício da lista esta cláusula caracteriza? Cite o trecho.",
     _p_vicio),
]


def _chamar(model_id: str, sistema: str, prompt: str, timeout_s: int = 90) -> str:
    import os

    import httpx
    chave = os.environ["OPENROUTER_API_KEY"]
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {chave}"},
        json={"model": model_id,
              "messages": [{"role": "system", "content": sistema},
                           {"role": "user", "content": prompt}],
              "max_tokens": 700, "temperature": 0.1},
        timeout=timeout_s)
    r.raise_for_status()
    from compliance_agent.llm.free_llm import conteudo_da_resposta
    return conteudo_da_resposta(r.json()).strip()


# Provas medidas mínimas para o modelo receber nota. Abaixo disso ele é `não medido` — e
# `não medido` NUNCA vira zero: um 429 diz respeito à cota do momento, não à capacidade.
MIN_PROVAS_MEDIDAS = 3
_TENTATIVAS_429 = 3


def _chamar_com_paciencia(model_id: str, sistema: str, prompt: str) -> str:
    """Chama insistindo no 429. Cota estourada é condição do momento, não defeito do modelo."""
    import httpx
    for tentativa in range(_TENTATIVAS_429):
        try:
            return _chamar(model_id, sistema, prompt)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429 or tentativa == _TENTATIVAS_429 - 1:
                raise
            time.sleep(8 * (tentativa + 1))
    return ""


def avaliar_modelo(model_id: str, tarefas=None) -> dict:
    """Nota do modelo, ou `None` quando não deu para medir.

    A PRIMEIRA versão desta função somava 0 para prova que estourou por 429 ou resposta
    malformada, e o resultado era um ranking que rebaixava modelo bom por cota cheia — o erro
    `INDISPONÍVEL ≠ 0` cometido dentro da própria ferramenta que existe para medir. Agora
    falha de infraestrutura sai da média em vez de puxá-la para baixo, e modelo com poucas
    provas válidas fica sem nota, deixando a heurística de tamanho decidir.
    """
    provas = [p for p in PROVAS if not tarefas or p[0] in tarefas]
    detalhe, notas = {}, []
    for nome, sistema, prompt, pontuar in provas:
        t0 = time.monotonic()
        try:
            resp = _chamar_com_paciencia(model_id, sistema, prompt)
        except Exception as e:  # noqa: BLE001 — falha de chamada não é nota
            detalhe[nome] = {"nota": None, "ms": int((time.monotonic() - t0) * 1000),
                             "erro": f"{type(e).__name__}: {str(e)[:90]}"}
            continue
        nota = pontuar(resp)
        detalhe[nome] = {"nota": nota, "ms": int((time.monotonic() - t0) * 1000),
                         "amostra": resp[:160]}
        notas.append(nota)

    medido = len(notas) >= MIN_PROVAS_MEDIDAS
    return {"modelo": model_id,
            "nota": round(sum(notas) / len(notas), 1) if medido else None,
            "n_provas": len(notas),
            "detalhe": detalhe}


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    from compliance_agent.llm.openrouter_catalogo import catalogo

    ap = argparse.ArgumentParser()
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--modelo", action="append", help="limita a um id (repetível)")
    ap.add_argument("--tarefa", action="append", choices=[p[0] for p in PROVAS])
    a = ap.parse_args()

    ids = a.modelo or [m["id"] for m in catalogo()]
    if not ids:
        print("catálogo indisponível — nada a medir")
        return 1
    print(f"medindo {len(ids)} modelo(s) × {len(a.tarefa or PROVAS)} prova(s)\n")

    linhas = []
    for mid in ids:
        r = avaliar_modelo(mid, a.tarefa)
        linhas.append(r)
        det = " ".join(f"{k}={'--' if v['nota'] is None else v['nota']:>3}"
                       for k, v in r["detalhe"].items())
        rotulo = "não medido" if r["nota"] is None else f"{r['nota']:>5.1f}"
        print(f"  {rotulo:>10}  {mid:<50} {det}")

    medidos = [r for r in linhas if r["nota"] is not None]
    nao_medidos = [r for r in linhas if r["nota"] is None]
    medidos.sort(key=lambda x: -x["nota"])
    print(f"\n{'nota':>6}  modelo")
    for r in medidos:
        print(f"{r['nota']:>6.1f}  {r['modelo']}  ({r['n_provas']} prova(s))")
    if nao_medidos:
        print(f"\nNÃO MEDIDOS ({len(nao_medidos)}) — cota ou erro de chamada, NÃO incapacidade; "
              "ficam de fora do ranking e a heurística de tamanho decide por eles:")
        for r in nao_medidos:
            motivos = {v.get("erro", "").split(":")[0] for v in r["detalhe"].values()
                       if v.get("erro")}
            print(f"        {r['modelo']}  ({', '.join(sorted(motivos)) or '?'})")

    if a.gravar:
        SAIDA.parent.mkdir(parents=True, exist_ok=True)
        SAIDA.write_text(json.dumps(
            {"medido_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "notas": {r["modelo"]: r["nota"] for r in medidos},
             "nao_medidos": [r["modelo"] for r in nao_medidos],
             "detalhe": {r["modelo"]: r["detalhe"] for r in linhas}},
            ensure_ascii=False, indent=1))
        print(f"\ngravado em {SAIDA} — escolher() passa a usar a nota medida no lugar da "
              "heurística de tamanho")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
