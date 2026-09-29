#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confronta a leitura de um processo SEI feita por LLM GRÁTIS contra um GABARITO conferido à mão.

POR QUE ISTO EXISTE (2026-08-12). O pedido é pôr as IAs gratuitas para ler os 2.351 processos do
acervo. Antes de apontar qualquer modelo para esse volume, é preciso saber se dá para confiar nele
— e a única forma honesta de saber é comparar contra uma leitura que se sabe correta.

O gabarito não é opinião: são fatos VERIFICÁVEIS que já foram extraídos do processo e conferidos no
texto (número do contrato, dispositivo legal, data, valor, CNPJ). Cada um ou bate ou não bate.

O QUE ESTE CONFRONTO MEDE, e o que não mede. Mede se o modelo ACHA o fato que está no texto e se o
transcreve sem inventar. NÃO mede juízo jurídico — para isso não há gabarito, e pedir juízo a um
modelo de triagem seria trocar volume por opinião.

TRÊS RESULTADOS POR CAMPO, e a distinção importa:
  · ACERTOU     — o valor bate com o gabarito (normalizado: só dígitos, ou trecho contido)
  · ERROU       — respondeu outra coisa: é INVENÇÃO, o pior caso, porque parece resposta
  · OMITIU      — declarou não achar. Honesto, e muito menos grave que errar.

    PYTHONPATH=. .venv/bin/python -m tools.sei_confronto_llm --processo 350010/025576/2026
    PYTHONPATH=. .venv/bin/python -m tools.sei_confronto_llm --listar-gabaritos
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ARQ = _REPO / "data" / "sei_arquivo"
_GAB = _REPO / "data" / "gabaritos_sei.json"

# Perguntas FECHADAS, uma por fato. Pergunta aberta não é confrontável — e o que se quer medir é a
# fidelidade ao texto, não a prosa.
PERGUNTAS = {
    "instrumento": "Qual o NÚMERO do contrato que ampara os pagamentos deste processo?",
    "processo_origem": "Qual o número do processo SEI de ORIGEM da contratação (a dispensa)?",
    "dispositivo": "Qual o dispositivo legal do enquadramento (lei, artigo e inciso)?",
    "data_contratacao": "Qual a data da licitação/contratação direta?",
    "objeto": "Qual o OBJETO contratado, em até 8 palavras?",
    "valor_empenho": "Qual o valor do empenho registrado neste processo?",
    "cnpj_favorecido_nf": "Em favor de qual CNPJ as notas fiscais devem ser emitidas?",
    "processo_licitacao": "Qual o número do processo SEI da LICITAÇÃO do mesmo objeto, citado como "
                          "o que encerraria esta contratação?",
    "pregao_anterior": "Qual o número do pregão eletrônico do contrato ANTERIOR que deixou de "
                       "cobrir o serviço?",
    "vigencia_inicio": "Qual a data de INÍCIO da vigência do contrato?",
    "vigencia_fim": "Qual a data de FIM da vigência do contrato?",
    "escolas_sem_cobertura": "Quantas unidades escolares estão sem cobertura contratual, segundo o "
                             "documento de oficialização da demanda?",
}

_SISTEMA = (
    "Você lê processos administrativos brasileiros. Responda SOMENTE com JSON válido no formato "
    '{"campo": "valor"}. Use EXATAMENTE o texto do documento. Se o documento não trouxer o dado, '
    'responda "NAO_CONSTA" naquele campo — nunca invente, nunca deduza.'
)


def texto_do_processo(proc: str, max_chars: int = 120_000) -> str:
    """Concatena o texto arquivado do processo, do mais informativo ao menos.

    O teto existe porque modelo gratuito com 1M de contexto ainda cobra latência, e porque a
    resposta a estas perguntas mora nos documentos de contratação e despesa — não no rodapé de
    tramitação. Quando corta, o corte é DECLARADO no laudo.
    """
    tag = re.sub(r"\D", "_", proc).strip("_")
    pasta = _ARQ / tag
    if not pasta.is_dir():
        # A leitura integral grava PDF em `data/proc_integra/`, não texto no acervo. Ler só o
        # acervo faria a ferramenta dizer "não está em casa" sobre processo que ESTÁ — a família
        # de erro que a casa mais paga. Cai para o PDF e declara a origem no laudo.
        pdf = next((_REPO / "data" / "proc_integra").glob(f"*{tag}.pdf"), None)
        if pdf is None:
            return ""
        try:
            import fitz
            with fitz.open(pdf) as d:
                return "\n".join(pg.get_text() for pg in d)[:max_chars]
        except (ImportError, OSError, ValueError):
            return ""
    partes: list[str] = []
    total = 0
    for f in sorted((pasta / "texto").glob("*.txt")) if (pasta / "texto").is_dir() else []:
        try:
            t = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        if total + len(t) > max_chars:
            t = t[: max(0, max_chars - total)]
        partes.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return "\n\n".join(partes)


def _norm(v) -> str:
    """Só alfanumérico, SEM acento e em caixa alta.

    Manter acento fazia "conservação" ≠ "conservacao" e reprovava resposta correta — o comparador
    acusava o modelo de errar o que ele acertara. Primeiro confronto real, primeiro defeito
    encontrado, e no MEU código.
    """
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9A-Za-z]", "", t).upper()


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def comparar(resposta: dict, gabarito: dict) -> dict:
    """Campo a campo: ACERTOU / ERROU / OMITIU.

    A comparação é tolerante à FORMA e rígida ao CONTEÚDO: normaliza pontuação e caixa, e aceita
    quando um contém o outro (o modelo pode devolver "Contrato nº 443/2025-DGS" onde o gabarito diz
    "443/2025"). O que não se tolera é valor diferente — isso é invenção.
    """
    out: dict = {"campos": {}, "acertou": 0, "errou": 0, "omitiu": 0}
    for campo, esperado in gabarito.items():
        dado = resposta.get(campo, "")
        n_esp, n_dad = _norm(esperado), _norm(dado)
        if not n_dad or "NAOCONSTA" in n_dad:
            estado = "OMITIU"
        elif n_esp and (n_esp in n_dad or n_dad in n_esp):
            estado = "ACERTOU"
        elif _digitos(esperado) and _digitos(esperado) == _digitos(dado):
            # "Lei n 14.133/2021, Art. 75, VIII" × "Lei 14.133/2021, Art. 75, VIII": a palavra
            # solta quebra a continência, mas os NÚMEROS — que é o que identifica o dispositivo —
            # são idênticos. Reprovar aqui seria acusar o modelo do erro do comparador.
            estado = "ACERTOU"
        else:
            estado = "ERROU"
        out["campos"][campo] = {"esperado": esperado, "respondeu": dado, "estado": estado}
        out[estado.lower()] += 1
    return out


def confrontar(proc: str, gabarito: dict, *, gerar=None, max_chars: int = 120_000) -> dict:
    texto = texto_do_processo(proc, max_chars=max_chars)
    if not texto:
        return {"ok": False, "erro": f"processo {proc} não está no acervo", "estado": "indisponivel"}
    if gerar is None:
        from compliance_agent.llm.camada_triagem import gerar_triagem
        gerar = gerar_triagem()
    perguntas = "\n".join(f'- "{k}": {v}' for k, v in PERGUNTAS.items() if k in gabarito)
    prompt = (f"DOCUMENTOS DO PROCESSO {proc}:\n\n{texto}\n\n"
              f"Responda em JSON com estes campos:\n{perguntas}")
    # DUAS TENTATIVAS, e a razão é medida: o OpenRouter rotaciona entre modelos `:free`, e duas
    # chamadas seguidas com o MESMO código e a MESMA entrada deram 6 acertos e depois nada. A
    # variabilidade é do provedor, não do prompt — insistir uma vez é barato e honesto; insistir
    # muitas seria mascarar um modelo ruim como se fosse bom.
    resp: dict = {}
    bruto = ""
    for _tentativa in range(2):
        bruto = gerar(prompt, _SISTEMA) or ""
        if not bruto:
            continue
        try:
            from compliance_agent.llm.json_resposta import extrair_json
            resp = extrair_json(bruto) or {}
        except ImportError:
            m = re.search(r"\{.*\}", bruto, re.S)
            resp = json.loads(m.group(0)) if m else {}
        if isinstance(resp, dict) and any(str(v).strip() for v in resp.values()):
            break
    if not bruto:
        return {"ok": False, "erro": "LLM sem cota/pausada — não mediu", "estado": "indisponivel"}
    r = comparar(resp if isinstance(resp, dict) else {}, gabarito)
    r.update({"ok": True, "processo": proc, "chars_lidos": len(texto),
              "truncado": len(texto) >= max_chars, "bruto": str(bruto)[:400]})
    return r


def _gabaritos() -> dict:
    try:
        return json.loads(_GAB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def amostra(gabaritos: dict, *, max_chars: int = 60_000) -> dict:
    """Roda o confronto em TODOS os gabaritos e agrega — a taxa por CAMPO é o que decide o volume.

    A agregação por campo importa mais que a média: um modelo que acerta 90% mas erra sempre o
    MESMO campo não serve para aquele campo, e a média esconde isso. Foi assim que a casa descobriu
    que a régua do fracionamento saturava — 451 de 451 alertas em "alta".
    """
    laudos, por_campo = [], {}
    for proc, gab in gabaritos.items():
        r = confrontar(proc, gab, max_chars=max_chars)
        laudos.append(r)
        if not r.get("ok"):
            continue
        for campo, d in r["campos"].items():
            e = por_campo.setdefault(campo, {"ACERTOU": 0, "ERROU": 0, "OMITIU": 0})
            e[d["estado"]] += 1
    ok = [x for x in laudos if x.get("ok")]
    tot = sum(x["acertou"] + x["errou"] + x["omitiu"] for x in ok)
    return {
        "processos": len(laudos), "medidos": len(ok),
        "acertou": sum(x["acertou"] for x in ok),
        "errou": sum(x["errou"] for x in ok),
        "omitiu": sum(x["omitiu"] for x in ok),
        "campos": tot, "por_campo": por_campo, "laudos": laudos,
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--amostra", action="store_true", help="roda todos os gabaritos e agrega")
    ap.add_argument("--processo")
    ap.add_argument("--listar-gabaritos", action="store_true")
    ap.add_argument("--max-chars", type=int, default=120_000)
    a = ap.parse_args(argv)
    gabs = _gabaritos()
    if a.amostra:
        r = amostra(gabs, max_chars=a.max_chars)
        print(f"amostra: {r['medidos']}/{r['processos']} processos medidos · {r['campos']} campos")
        print(f"  ✅ {r['acertou']}   ❌ {r['errou']}   ➖ {r['omitiu']}")
        if r["campos"]:
            print(f"  taxa de acerto: {100*r['acertou']/r['campos']:.1f}% · "
                  f"invenção: {100*r['errou']/r['campos']:.1f}%")
        print("\n  por campo (o que a média esconde):")
        for campo, e in sorted(r["por_campo"].items()):
            print(f"    {campo:24} ✅{e['ACERTOU']} ❌{e['ERROU']} ➖{e['OMITIU']}")
        for lau in r["laudos"]:
            if not lau.get("ok"):
                print(f"  INDISPONÍVEL {lau.get('processo','?')}: {lau.get('erro')}")
        return 0
    if a.listar_gabaritos or not a.processo:
        print(f"gabaritos conferidos à mão: {len(gabs)}")
        for k, v in gabs.items():
            print(f"  {k}: {len(v)} campos")
        return 0
    gab = gabs.get(a.processo)
    if not gab:
        print(f"sem gabarito para {a.processo} — confronto exige leitura conferida à mão")
        return 1
    r = confrontar(a.processo, gab, max_chars=a.max_chars)
    if not r.get("ok"):
        print(f"INDISPONÍVEL: {r.get('erro')}")
        return 1
    print(f"{r['processo']} · {r['chars_lidos']:,} chars"
          f"{' (TRUNCADO)' if r['truncado'] else ''}".replace(",", "."))
    for campo, d in r["campos"].items():
        marca = {"ACERTOU": "✅", "ERROU": "❌", "OMITIU": "➖"}[d["estado"]]
        print(f"  {marca} {campo:22} esperado={str(d['esperado'])[:40]!r}")
        if d["estado"] != "ACERTOU":
            print(f"     {'':22} respondeu={str(d['respondeu'])[:60]!r}")
    print(f"\nacertou={r['acertou']} · errou={r['errou']} · omitiu={r['omitiu']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
