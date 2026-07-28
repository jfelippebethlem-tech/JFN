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


# Deliberação em primeira pessoa sobre a PRÓPRIA tarefa — o modelo pensando em voz alta em vez
# de responder. Não é qualquer verbo modal: "o gestor deve atestar" é texto legítimo. O gatilho
# é o modelo falando de si e do enunciado.
_MONOLOGO = re.compile(
    r"\b(?:we|i)\s+(?:need\s+to|must|should|will|have\s+to|can|could|'ll)\b"
    r"|\blet(?:'s|\s+me)\b"
    r"|\bthe\s+(?:user|instruction|prompt|question)\s+(?:says|wants|asks|is)\b"
    r"|\bpreciso\s+(?:encontrar|listar|verificar|analisar)\b"
    r"|\bvamos\s+(?:analisar|come[cç]ar|verificar|extrair)\b"
    r"|\bdevo\s+(?:listar|extrair|responder|verificar)\b",
    re.IGNORECASE)

# Cada marcador desconta isto da nota da prova, com teto de 100 (nota nunca fica negativa).
PESO_MONOLOGO = 12


def penalidade_formato(resposta: str) -> int:
    """Desconto por monólogo interno na resposta.

    PONTO CEGO CORRIGIDO EM 2026-07-28. A pontuação das provas casa SUBSTRING, então um modelo
    que despeja o próprio raciocínio e ao final menciona o nome certo pontuava igual a um que
    responde limpo. `nemotron-3-super-120b` tirou 100,0 assim — e, ao consolidar um dossiê real
    de 16 lotes, devolveu 13 marcadores de monólogo em inglês, truncado no meio de uma frase,
    sem nenhuma das sete seções pedidas. Conteúdo bom, formato inutilizável.

    Isso importa porque `escolher("documento")` passou a confiar na nota medida: o ponto cego do
    medidor virava escolha de modelo errada para a tarefa mais caras que temos.
    """
    return min(100, PESO_MONOLOGO * len(_MONOLOGO.findall(resposta or "")))


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


def _com_formato(pontuar):
    """Aplica a penalidade de formato a qualquer pontuador — ponto único, para não corrigir uma
    prova e esquecer as outras."""
    def _p(resposta: str) -> int:
        return max(0, pontuar(resposta) - penalidade_formato(resposta))
    return _p


# ── Prova 5: COMPREENSÃO DE DOCUMENTO LONGO ───────────────────────────────────────────────
# A lacuna que eu mesmo declarei: as quatro provas acima usam textos curtos e NÃO medem o que o
# dono desconfiava desde o início — que modelo pequeno "não vai analisar os documentos direito".
# Uma janela de contexto grande diz quanto texto CABE; esta prova mede o que o modelo ENTENDE
# depois de atravessá-lo.
#
# O documento é REAL, do acervo (~25 mil tokens), e as duas perguntas foram escolhidas por
# propriedades que um teste sintético não teria:
#   · o valor de tributos está a 78% de profundidade — quem lê só as primeiras páginas erra;
#   · há DOIS números de empenho no documento, o segundo bem depois do primeiro. Perguntar
#     "quais" mede COMPLETUDE, não só recuperação: achar um é o resultado típico de quem
#     desiste no meio.
#
# Pontuação assimétrica, e é deliberado: dizer "não localizei" vale mais que inventar um valor.
# Um modelo que erra com confiança é pior, para esta casa, que um que se declara incapaz.
DOC_LONGO = pathlib.Path(
    "data/sei_arquivo/080001_031401_2024/texto/006_85918993.txt")
_VALOR_TRIBUTOS = "74.650,31"
_EMPENHOS = ("2024NE07134", "2024NE08035")


def _carregar_doc_longo() -> str | None:
    """O documento real, ou `None` quando o acervo não está disponível.

    `None` faz a prova ser PULADA (não medida), nunca zerada — a mesma regra que vale para o
    resto do medidor: ausência de medição não é nota ruim.
    """
    try:
        return DOC_LONGO.read_text(errors="replace")
    except OSError:
        return None


def _p_documento_longo(r: str) -> int:
    n = _norm(r)
    nota = 0

    # (a) recuperação a 78% de profundidade
    if _VALOR_TRIBUTOS in r or "74650,31" in r.replace(".", ""):
        nota += 50
    elif re.search(r"n[aã]o\s+(?:localiz|encontr|consta|consegu)", n):
        nota += 20          # falha honesta vale mais que valor inventado
    elif re.search(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", r):
        return 0            # deu OUTRO valor: alucinação com aparência de resposta

    # (b) completude: os DOIS empenhos, espalhados pelo documento
    achados = sum(1 for e in _EMPENHOS if e.lower() in n)
    nota += {0: 0, 1: 20, 2: 50}[achados]
    return min(100, nota)


PROVAS = [
    ("extracao",
     "Você extrai fatos de documentos oficiais. Responda APENAS com o que está escrito no "
     "documento. Nunca invente nome ou número.",
     f"{_ATO}\n\nListe os responsáveis designados: nome completo, ID funcional e papel.",
     _com_formato(_p_extracao)),
    ("rubrica",
     "Você classifica cláusulas de edital em escala FECHADA. Responda em duas linhas: "
     "'nivel: <ausente|fraco|medio|forte|critico>' e 'trecho: <citação literal do edital>'. "
     "Não escreva mais nada.",
     f"{_CLAUSULA}\n\nClassifique o grau de restrição à competitividade desta cláusula.",
     _com_formato(_p_rubrica)),
    ("ausencia",
     "Você lê documentos oficiais. Se a informação pedida não estiver no documento, diga "
     "exatamente que ela não consta. Nunca estime, nunca preencha com zero.",
     f"{_SEM_VALOR}\n\nQual é o valor estimado da contratação neste documento?",
     _com_formato(_p_ausencia)),
    ("vicio",
     "Você é analista de controle externo. Escolha UM vício da lista e cite o trecho que o "
     "sustenta. Lista: " + "; ".join(_VICIOS),
     f"{_CLAUSULA}\n\nQual vício da lista esta cláusula caracteriza? Cite o trecho.",
     _com_formato(_p_vicio)),
]

_DOC = _carregar_doc_longo()
if _DOC:
    PROVAS.append((
        "documento_longo",
        "Você lê documentos fiscais longos e responde APENAS com o que está escrito. Se um dado "
        "não estiver no documento, diga que não localizou — nunca estime, nunca invente número.",
        f"{_DOC}\n\n---\n\nCom base no documento acima, responda:\n"
        "1) Qual é o valor aproximado dos tributos (Val Aprox Tributos) informado?\n"
        "2) Quais são TODOS os números de empenho (formato AAAANEnnnnn) citados no documento?",
        _com_formato(_p_documento_longo),
    ))


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
_TENTATIVAS_429 = 4
_ESPERA_BASE = 15        # 15s, 30s, 45s — generoso de propósito (ver _chamar_com_paciencia)


def _chamar_com_paciencia(model_id: str, sistema: str, prompt: str) -> str:
    """Insiste enquanto o erro for TRANSITÓRIO. Condição do momento não é defeito do modelo.

    Duas famílias de erro passageiro, e a segunda estava escapando: além do 429 (cota), o
    agregador devolve HTTP 200 com `{"error": {code: 502, ResourceExhausted}}` quando o provedor
    de trás está sem capacidade — o que `RespostaProvedorErro.retentavel` já classifica. O bench
    só retentava o 429, então um soluço de capacidade virava "não medido" e o modelo ficava fora
    do ranking sem ter sido avaliado. Foi o que aconteceu com `gemma-4-26b` em 2026-07-28.

    Espera crescente e generosa: medir 15 modelos é raro e barato; medir errado sai caro, porque
    a nota decide qual modelo lê 2.045 processos.
    """
    import httpx

    from compliance_agent.llm.free_llm import RespostaProvedorErro

    ultimo: Exception | None = None
    for tentativa in range(_TENTATIVAS_429):
        try:
            return _chamar(model_id, sistema, prompt)
        except httpx.HTTPStatusError as e:
            ultimo = e
            if e.response.status_code != 429:
                raise
        except RespostaProvedorErro as e:
            ultimo = e
            if not e.retentavel:
                raise            # 400/401/403/404 não melhoram esperando
        if tentativa < _TENTATIVAS_429 - 1:
            espera = _ESPERA_BASE * (tentativa + 1)
            print(f"      {model_id}: {type(ultimo).__name__} — aguardando {espera}s "
                  f"(tentativa {tentativa + 2}/{_TENTATIVAS_429})")
            time.sleep(espera)
    if ultimo:
        raise ultimo
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
            # 404 "No endpoints found" NÃO é cota: o catálogo lista o modelo, mas ele não tem
            # servidor. Tratar isso como "não medido" (transitório) faria o medidor voltar a
            # tentá-lo para sempre e sugeriria que a nota chegaria um dia. Registra o óbito no
            # catálogo e diz o que é — "não consegui medir agora" e "não existe" são fatos
            # diferentes, e confundi-los é o erro que esta casa persegue.
            permanente = "404" in str(e) or "No endpoints found" in str(e)
            if permanente:
                try:
                    from compliance_agent.llm.openrouter_catalogo import marcar_morto
                    marcar_morto(model_id, motivo="sem endpoint (404) no banco de provas")
                except Exception:  # noqa: BLE001
                    pass
            detalhe[nome] = {"nota": None, "ms": int((time.monotonic() - t0) * 1000),
                             "indisponivel": bool(permanente),
                             "erro": f"{type(e).__name__}: {str(e)[:90]}"}
            continue
        nota = pontuar(resp)
        detalhe[nome] = {"nota": nota, "ms": int((time.monotonic() - t0) * 1000),
                         "amostra": resp[:160]}
        notas.append(nota)

    # O piso existe para não dar nota a quem mal foi medido — mas ele não pode bloquear uma
    # execução deliberadamente restrita (`--tarefa documento_longo`). O mínimo é o menor entre
    # o piso e o número de provas PEDIDAS.
    minimo = min(MIN_PROVAS_MEDIDAS, len(provas))
    medido = len(notas) >= minimo
    return {"modelo": model_id,
            "nota": round(sum(notas) / len(notas), 1) if medido else None,
            "n_provas": len(notas),
            "indisponivel": any(v.get("indisponivel") for v in detalhe.values()),
            "detalhe": detalhe}


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    from compliance_agent.llm.openrouter_catalogo import catalogo

    ap = argparse.ArgumentParser()
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--modelo", action="append", help="limita a um id (repetível)")
    ap.add_argument("--tarefa", action="append", choices=[p[0] for p in PROVAS])
    ap.add_argument("--pausa", type=float, default=6.0,
                    help="segundos entre modelos (evita 429 contra si mesmo)")
    a = ap.parse_args()

    ids = a.modelo or [m["id"] for m in catalogo()]
    if not ids:
        print("catálogo indisponível — nada a medir")
        return 1
    print(f"medindo {len(ids)} modelo(s) × {len(a.tarefa or PROVAS)} prova(s)\n")

    linhas = []
    for n, mid in enumerate(ids):
        if n:
            # Ritmo: medir 15 modelos em rajada gera 429 contra si mesmo — foi o que aconteceu
            # em 2026-07-28 (8 de 15 ficaram sem medição por cota).
            time.sleep(a.pausa)
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
        indisp = [r for r in nao_medidos if r.get("indisponivel")]
        transit = [r for r in nao_medidos if not r.get("indisponivel")]
        if indisp:
            print(f"\nINDISPONÍVEIS ({len(indisp)}) — o catálogo lista, mas NÃO há endpoint "
                  "(404). Não é cota e não vai melhorar esperando; marcados como mortos:")
            for r in indisp:
                print(f"        {r['modelo']}")
        if transit:
            print(f"\nNÃO MEDIDOS ({len(transit)}) — cota ou erro passageiro, NÃO incapacidade; "
                  "ficam de fora do ranking e a heurística de tamanho decide por eles:")
            for r in transit:
                motivos = {v.get("erro", "").split(":")[0] for v in r["detalhe"].values()
                           if v.get("erro")}
                print(f"        {r['modelo']}  ({', '.join(sorted(motivos)) or '?'})")

    if a.gravar:
        # MEDIÇÃO ACUMULA, não substitui. A 1ª versão sobrescrevia `notas` com só o que esta
        # execução mediu — e como bater na API três vezes seguidas gera 429, uma rodada com cota
        # cheia APAGAVA medição boa de rodadas anteriores. Mesmo erro de família do
        # `INDISPONÍVEL ≠ 0`: ausência de medição virava ausência de nota.
        anterior = {}
        try:
            anterior = json.loads(SAIDA.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        notas = dict(anterior.get("notas") or {})
        detalhe = dict(anterior.get("detalhe") or {})
        notas.update({r["modelo"]: r["nota"] for r in medidos})
        # FUNDIR PROVA A PROVA, não modelo a modelo. `detalhe.update({modelo: novo})` substitui
        # o dicionário inteiro — então rodar `--tarefa documento_longo` APAGAVA as notas de
        # rubrica/ausência/extração medidas antes, e o perfil `fast` ficava sem medição. Mesma
        # família do "medição acumula, não substitui" que já corrigi no nível do modelo.
        for r in linhas:
            if r["nota"] is None:
                continue
            alvo = detalhe.setdefault(r["modelo"], {})
            alvo.update(r["detalhe"])
        SAIDA.parent.mkdir(parents=True, exist_ok=True)
        SAIDA.write_text(json.dumps(
            {"medido_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "notas": notas,
             "nao_medidos_nesta_rodada": [r["modelo"] for r in nao_medidos],
             "detalhe": detalhe},
            ensure_ascii=False, indent=1))
        print(f"  ranking acumulado: {len(notas)} modelo(s) com nota "
              f"({len(medidos)} medidos agora)")
        print(f"\ngravado em {SAIDA} — escolher() passa a usar a nota medida no lugar da "
              "heurística de tamanho")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
