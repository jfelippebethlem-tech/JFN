"""Gera o relatório HTML (artifact) a partir de output/eleicoes2026/dados_relatorio.json."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import eleicao2026_analise as A  # noqa: E402

OUT = os.path.expanduser("~/JFN/output/eleicoes2026")
ARQ = "relatorio_jorge_felippe_neto_2026.html"


def limpa(o):
    """NaN → null e sigla interna fora do entregável: chaves/colunas "jfn" viram "jorge"."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k.replace("jfn", "jorge"): limpa(v) for k, v in o.items()}
    if isinstance(o, list):
        return [limpa(v) for v in o]
    if isinstance(o, str) and o.startswith(("votos_jfn", "pct_jfn")):
        return o.replace("jfn", "jorge")
    return o


def main():
    d = limpa(json.load(open(f"{OUT}/dados_relatorio.json")))
    html = open(os.path.join(os.path.dirname(__file__), "eleicao2026_relatorio.html")).read()
    html = html.replace("/*__DADOS__*/null", json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    A.checar_neutro(html, "relatório interativo")
    destino = f"{OUT}/{ARQ}"
    open(destino, "w").write(html)
    print(destino, os.path.getsize(destino) // 1024, "KB")


if __name__ == "__main__":
    main()
