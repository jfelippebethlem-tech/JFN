# -*- coding: utf-8 -*-
"""SBOM CycloneDX das dependências Python + resumo de licenças (O9.3; plano §18: lib nova entra no SBOM com licença).

Entrada (gerada num venv NOVO montado só dos locks, nunca no venv vivo):

    python3.12 -m venv /tmp/v && /tmp/v/bin/pip install --require-hashes --no-deps \
        -r requirements-dev.lock -r requirements-sei.lock
    cyclonedx-py environment --of JSON --sv 1.6 --output-reproducible --mc-type application -o sbom.json /tmp/v/bin/python
    pip-licenses --python /tmp/v/bin/python --format=json --with-urls --from=mixed > lic.json

    python tools/sbom_python.py sbom.json lic.json   # grava docs/sbom/sbom-python.cdx.json e docs/sbom/LICENCAS.md

O que este passo acrescenta ao SBOM cru: licença onde o metadado do pacote não declara (via classificador do
pip-licenses ou conferência manual citada em `MANUAL`), a classe da licença e em quais locks o pacote está. Não remove
nada: copyleft forte, proprietária e desconhecida só são MARCADAS para decisão do dono.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
LOCKS = ("requirements.lock", "requirements-dev.lock", "requirements-sei.lock")
SAIDA = RAIZ / "docs" / "sbom"

# Conferência manual (25/11/2026) onde o metadado do wheel não declara licença.
MANUAL = {
    "pymupdf-layout": ("NOASSERTION (meta-pacote vazio)",
                       "wheel 2.1 sem arquivo fora do .dist-info e sem campo de licença (PyPI: license=None); puxado "
                       "por pymupdf==2.1, cujo código é AGPL-3.0 ou comercial Artifex"),
    "pymupdf4llm": ("AGPL-3.0 (repositório)",
                    "wheel 2.1 sem arquivo fora do .dist-info e sem campo de licença; o LICENSE de "
                    "github.com/pymupdf/pymupdf4llm é a GNU AGPL v3"),
}

CLASSES = ("copyleft forte", "proprietária", "desconhecida", "copyleft fraco", "permissiva")


def norm(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def _no_lock() -> dict[str, list[str]]:
    onde: dict[str, list[str]] = {}
    for lock in LOCKS:
        for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", (RAIZ / lock).read_text(encoding="utf-8"), re.M):
            onde.setdefault(norm(m.group(1)), []).append(lock)
    return onde


def _textos(comp: dict) -> list[str]:
    out = []
    for lic in comp.get("licenses", []):
        if "expression" in lic:
            out.append(lic["expression"])
        else:
            out.append(lic["license"].get("id") or lic["license"].get("name", ""))
    return out


def classe(textos: list[str]) -> str:
    t = " | ".join(textos).upper()
    if not t.strip() or "UNKNOWN" in t or "NOASSERTION" in t:
        return "desconhecida"
    fraco = re.search(r"\bLGPL|LESSER|LIBRARY", t)
    if re.search(r"AGPL|AFFERO", t) or (re.search(r"\bGPL|GENERAL PUBLIC LICENSE", t) and not fraco):
        return "copyleft forte"
    if "PROPRIETARY" in t:
        return "proprietária"
    if fraco or re.search(r"\bMPL|MOZILLA", t):
        return "copyleft fraco"
    # `any-OSI` (SPDX) = o usuário escolhe qualquer licença OSI — permissiva. "OSI Approved" sem nome não diz qual.
    if re.fullmatch(r"(LICENSE :: )?OSI APPROVED|LICENSE :: DFSG APPROVED", t.strip()):
        return "desconhecida"
    return "permissiva"


def gerar(sbom_cru: pathlib.Path, lic_json: pathlib.Path) -> None:
    sbom = json.loads(sbom_cru.read_text(encoding="utf-8"))
    pl = {norm(x["Name"]): x for x in json.loads(lic_json.read_text(encoding="utf-8"))}
    onde = _no_lock()
    sbom["metadata"]["component"] = {"type": "application", "bom-ref": "jfn", "name": "JFN",
                                     "description": "motor de auditoria/compliance (repositório público)"}
    linhas = []
    for comp in sorted(sbom["components"], key=lambda c: norm(c["name"])):
        n = norm(comp["name"])
        nota = ""
        if not comp.get("licenses"):
            if n in MANUAL:
                txt, nota = MANUAL[n]
            else:
                txt = pl.get(n, {}).get("License", "UNKNOWN")
                nota = "SBOM cru sem licença; texto do campo License/classificador lido pelo pip-licenses"
            comp["licenses"] = [{"license": {"name": txt, "acknowledgement": "concluded"}}]
        cl = classe(_textos(comp))
        if n == "pymupdf":  # dual: AGPL-3.0 OU comercial — vale o lado copyleft enquanto não houver licença comercial
            cl = "copyleft forte"
        props = comp.setdefault("properties", [])
        props += [{"name": "jfn:classe_licenca", "value": cl},
                  {"name": "jfn:locks", "value": ",".join(onde.get(n, [])) or "(fora dos locks)"}]
        if nota:
            props.append({"name": "jfn:nota_licenca", "value": nota})
        linhas.append((cl, " OR ".join(_textos(comp)), comp["name"], comp.get("version", ""), onde.get(n, []), nota))
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "sbom-python.cdx.json").write_text(json.dumps(sbom, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    nomes_sbom = {norm(c["name"]) for c in sbom["components"]}
    _resumo(linhas, sorted(set(onde) - nomes_sbom), sorted(nomes_sbom - set(onde)))


def _resumo(linhas, so_no_lock, so_no_sbom) -> None:
    from collections import Counter
    cont = Counter(cl for cl, *_ in linhas)
    curto = {"requirements.lock": "prod", "requirements-dev.lock": "dev", "requirements-sei.lock": "sei"}
    md = ["# Licenças das dependências Python (SBOM)", "",
          "> Gerado por `tools/sbom_python.py` a partir de `docs/sbom/sbom-python.cdx.json` (CycloneDX 1.6). "
          "Não editar à mão.", "",
          "## 1. Escopo", "",
          f"- **{len(linhas)} componentes** instalados num venv novo, montado só de `requirements-dev.lock` + "
          "`requirements-sei.lock` (`pip install --require-hashes --no-deps`), Linux aarch64, Python 3.12 (VM-2).",
          "- Coluna *camadas*: `prod` = requirements.lock · `dev` = requirements-dev.lock · `sei` = "
          "requirements-sei.lock.",
          f"- Pinados no lock e fora do SBOM (marcador de outra plataforma, não instalados no aarch64): "
          f"{', '.join(so_no_lock) or 'nenhum'}.",
          f"- No SBOM e fora dos locks (ferramenta do venv): {', '.join(so_no_sbom) or 'nenhum'}.", "",
          "## 2. Quadro por classe", "", "| Classe | Pacotes |", "|---|---:|"]
    md += [f"| {cl} | {cont.get(cl, 0)} |" for cl in CLASSES]
    md += ["", "## 3. Para decisão do dono", "",
           "> **Atenção:** o painel é servido publicamente e o repositório é público. Os pacotes abaixo têm licença "
           "copyleft forte (GPL/AGPL), proprietária ou desconhecida. Nada foi removido — só marcado. AGPL alcança "
           "uso por rede (§13); GPL alcança distribuição.", "",
           "| Classe | Pacote | Versão | Licença declarada/concluída | Camadas | Nota |", "|---|---|---|---|---|---|"]
    for cl, lic, nome, ver, locks, nota in sorted(linhas):
        if cl in ("copyleft forte", "proprietária", "desconhecida"):
            md.append(f"| **{cl}** | `{nome}` | {ver} | {lic} | {', '.join(curto[x] for x in locks)} | {nota} |")
    md += ["", "## 4. Licença → pacotes", ""]
    por_lic: dict[tuple[str, str], list[str]] = {}
    for cl, lic, nome, ver, *_ in linhas:
        por_lic.setdefault((cl, lic), []).append(f"`{nome}` {ver}")
    md += ["| Classe | Licença | Nº | Pacotes |", "|---|---|---:|---|"]
    for (cl, lic), pk in sorted(por_lic.items(), key=lambda kv: (CLASSES.index(kv[0][0]), -len(kv[1]), kv[0][1])):
        md.append(f"| {cl} | {lic.replace('|', '/')} | {len(pk)} | {', '.join(pk)} |")
    (SAIDA / "LICENCAS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[sbom] {len(linhas)} componentes; {dict(cont)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("uso: python tools/sbom_python.py <sbom-cru.json> <pip-licenses.json>")
    gerar(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
