"""Replica no ACERVO INTEIRO o que a leitura processo a processo ensinou, e monta a FAMÍLIA de cada processo.

1. REGRAS (camada determinística) — as lições da leitura integral viraram regra com teste e prevalência medida:
     cronologia_do_ato ............ liquidação antes da ordem, conferência antes do pedido, data retroativa
     execucao_fatos (aditivos) .... prorrogação que renova valor sem enquadramento de serviço contínuo
     E7 (coletor_edital) .......... quantitativo mínimo exigido do PROFISSIONAL (art. 30 §1º I)
   Grava só o que ACENDE, com o porquê, em `data/regras_acervo.json`.

2. FAMÍLIA — um processo lido sozinho não faz sentido: o de pagamento só se explica com o de contratação e os de
   aditivo. Cada processo registra os números SEI que CITA; o índice inverso dá quem o CITA. Página coletiva do
   D.O. (título de publicação/extrato, ou documento que cita > 15 processos) fica FORA — foi ela que misturou
   aditivos de contratos alheios no INEA 34/2023 e 60+ processos sem relação na busca do PE 24/2023.
   Grava `data/sei_familia.json`.

Offline, determinístico. Uso: nice -n 19 ionice -c3 .venv/bin/python -m tools.acervo_regras_e_familia
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from compliance_agent import cronologia_do_ato as CR  # noqa: E402
from compliance_agent import execucao_fatos as EF  # noqa: E402
from compliance_agent.detectores import coletor_edital as CE  # noqa: E402
from compliance_agent.detectores import e7_clausula_restritiva as E7  # noqa: E402

ARQUIVO = RAIZ / "data" / "sei_arquivo"
SAIDA_REGRAS = RAIZ / "data" / "regras_acervo.json"
SAIDA_FAMILIA = RAIZ / "data" / "sei_familia.json"
_SLUG = re.compile(r"^\d+_\d+_\d{4}$")
_RX_NUM = re.compile(r"SEI[-\s]?(\d{6})[/\s]?(\d{6})[/\s]?(\d{4})")
_RX_COLETIVO = re.compile(r"publica[çc][ãa]o|doerj|di[áa]rio\s+oficial|extrato|anexo\s+d\.?o\.?\b|recorte", re.I)
MAX_CITACOES_DOC = 15


def _numero(slug: str) -> str:
    return "SEI-%s/%s/%s" % tuple(slug.split("_"))


def citacoes(docs: list[dict], proprio: str) -> dict[str, int]:
    """{numero_citado: nº de documentos que o citam}, sem página coletiva e sem o próprio processo."""
    out: dict[str, int] = defaultdict(int)
    for d in docs:
        if _RX_COLETIVO.search(str(d.get("titulo") or "")):
            continue
        nums = {f"SEI-{a}/{b}/{c}" for a, b, c in _RX_NUM.findall(str(d.get("texto") or ""))}
        nums.discard(proprio)
        if len(nums) > MAX_CITACOES_DOC:          # página coletiva sem título que a denuncie
            continue
        for n in nums:
            out[n] += 1
    return dict(out)


def regras(docs: list[dict], numero: str) -> list[dict]:
    acesos: list[dict] = []
    c = CR.analisar(docs, numero_processo=numero)
    for a in c.get("achados", []):
        if a["grau"] in ("vermelho", "amarelo") and a["tipo"] != "entrega_no_dia_da_ordem":
            acesos.append({"regra": f"cronologia:{a['tipo']}", "grau": a["grau"], "diz": a["diz"]})
    ads = EF.aditivos_por_documento(docs)
    if ads:
        r = EF.prorrogacao_renova_valor(ads, continuo_nos_autos=EF.declara_continuo(docs))
        if r["grau"] == "amarelo":
            acesos.append({"regra": "aditivos:prorrogacao_renova_valor", "grau": "amarelo", "diz": r["diz"]})
    ed = [x for x in docs if re.search(r"edital|termo de refer|anexo|estudo t", str(x.get("titulo") or ""), re.I)]
    if ed:
        fontes = CE._fontes_de_edital({"conteudo_documentos": [{"doc": x["titulo"], "conteudo": x["texto"]} for x in ed]})
        if fontes:
            for cl in CE._extrair_clausulas_restritivas(CE._paragrafos(CE._linhas_com_contexto(fontes)), None):
                if cl["tipo"] == "atestado_quantitativo" and cl.get("exige_do_profissional"):
                    grau, motivo = E7._teste_atestado(cl, None)
                    if grau == "forte":
                        acesos.append({"regra": "e7:quantitativo_do_profissional", "grau": "vermelho", "diz": motivo})
                        break
    return acesos


def rodar() -> dict:
    t0 = time.time()
    res_regras: dict[str, list] = {}
    cita: dict[str, dict] = {}
    n = 0
    for d in sorted(ARQUIVO.iterdir()):
        if not (d.is_dir() and _SLUG.match(d.name)):
            continue
        docs = CR.docs_do_arquivo(d)
        if not docs:
            continue
        n += 1
        num = _numero(d.name)
        if (a := regras(docs, num)):
            res_regras[num] = a
        if (c := citacoes(docs, num)):
            cita[num] = c
    citado_por: dict[str, dict] = defaultdict(dict)
    for origem, alvos in cita.items():
        for alvo, k in alvos.items():
            citado_por[alvo][origem] = k
    no_acervo = {_numero(d.name) for d in ARQUIVO.iterdir() if d.is_dir() and _SLUG.match(d.name)}
    familia = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "cita": cita, "citado_por": dict(citado_por),
               "no_acervo": sorted(no_acervo)}
    rg = {"gerado_em": familia["gerado_em"], "processos_lidos": n, "acesos": res_regras,
          "por_regra": {}}
    for lst in res_regras.values():
        for a in lst:
            rg["por_regra"][a["regra"]] = rg["por_regra"].get(a["regra"], 0) + 1
    for p, obj in ((SAIDA_REGRAS, rg), (SAIDA_FAMILIA, familia)):
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    rg["segundos"] = round(time.time() - t0, 1)
    return rg


if __name__ == "__main__":
    r = rodar()
    print(f"{r['processos_lidos']} processos · {len(r['acesos'])} com regra acesa · {r['por_regra']} · {r['segundos']} s")
