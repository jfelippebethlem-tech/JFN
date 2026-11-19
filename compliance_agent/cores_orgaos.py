# -*- coding: utf-8 -*-
"""cores_orgaos — UMA cor por órgão/UG, a mesma em toda visualização (config/cores_orgaos.yaml).

Pedido do dono (18/11/2026): "pinte cada órgão/unidade gestora de uma cor diferente no segundo cérebro" e "a galáxia
deve reproduzir isso". Aqui ficam: `cor(chave)` (a paleta), `slug_orgao` (a tag `orgao/<sigla>`), `marcar_nota`
(propriedades `ug`/`orgao` + tags `ug/<código>` e `orgao/<sigla>` no frontmatter de uma nota do vault) e
`aplicar_vault` (marca as notas e grava os `colorGroups` do grafo do Obsidian).

Nada é inventado: a UG de uma nota vem do que a nota já declara (autor ou bloco gerado) ou de quem chama com a UG
lida do SIAFE; sem UG conhecida a nota fica `orgao/indeterminado` (cinza). O corpo da nota não é tocado.

CLI:  python -m compliance_agent.cores_orgaos aplicar | cor <UG>
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
VAULT = Path(os.environ.get("JFN_VAULT") or Path.home() / "vault")
INDETERMINADO = "indeterminado"
_SEM = ("", "sem:orgao", "vault:dossies", INDETERMINADO)
_RE_FM = re.compile(r"\A---\n(.*?\n)---\n", re.S)
_NOSSA = re.compile(r"^(?:ug|orgao)/")
_MARCA_GERADA = "# jfn:propriedades"


@lru_cache(maxsize=1)
def carregar() -> dict:
    cfg = yaml.safe_load((RAIZ / "config" / "cores_orgaos.yaml").read_text(encoding="utf-8"))
    cfg["principais"] = [str(u) for u in cfg["principais"]]
    cfg["siglas"] = {str(k): str(v) for k, v in (cfg.get("siglas") or {}).items()}
    return cfg


def cor(chave) -> str:
    """#RRGGBB do órgão. Aceita a UG ("180100"), o aglomerado da galáxia ("ug:180100", "cnpj:…", "nome:…")."""
    cfg = carregar()
    k = str(chave or "").strip()
    if k in _SEM or k.startswith(("sem:", "vault:")):     # baldes sem órgão da galáxia (um por motivo): cinza
        return cfg["indeterminado"]
    k = k.removeprefix("ug:")
    if k in cfg["principais"]:
        return cfg["paleta"][cfg["principais"].index(k)]
    h = hashlib.sha1(k.encode()).digest()
    r, g, b = colorsys.hls_to_rgb((int.from_bytes(h[:2], "big") % 360) / 360, (40, 47, 54)[h[2] % 3] / 100, (60, 72)[h[3] % 2] / 100)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def nomes_ug() -> dict[str, str]:
    from compliance_agent import ugs
    return ugs.carregar()


def slug_orgao(ug, nomes: dict[str, str]) -> str:
    """Sigla curada → sigla do nome canônico ("ITERJ — …") → slug do nome canônico → indeterminado."""
    ug = str(ug or "").strip()
    if ug in carregar()["siglas"]:
        return carregar()["siglas"][ug]
    nome = nomes.get(ug)
    if not nome:
        return INDETERMINADO
    base = nome.split(" — ")[0] if " — " in nome else nome
    s = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or INDETERMINADO


def _valor(linha: str) -> str:
    return linha.split(":", 1)[1].strip().strip("\"'")


def _y(nome: str) -> str:
    """Nome de órgão como escalar YAML: entre aspas só quando tem caractere que o YAML leria como sintaxe."""
    return json.dumps(nome, ensure_ascii=False) if re.search(r"[:#\[\]{}\"']|^\s|\s$", nome) else nome


def _ug_valida(declarada: str, nomes: dict[str, str]) -> str:
    return next((u for u in re.findall(r"(?<!\d)\d{6}(?!\d)", declarada or "") if u in nomes), "")


def _declara_ug_valida(texto: str, nomes: dict[str, str]) -> bool:
    m = re.search(r'^ug: *(.*)$', texto[:1500], re.M)
    return bool(m and _ug_valida(m.group(1), nomes))


def esfera_poder(ug: str, nomes: dict[str, str], fm: str) -> tuple[str, str]:
    """(esfera, poder) da nota — regra CNF-12 (19/11/2026: 132 casos abertos sem esfera). UG estadual válida →
    estadual + Poder pelo nome do órgão (sem casar, Executivo); sem UG e frontmatter de Prefeitura → municipal.
    Sem dado → ("", ""): a nota fica sem esfera e o sensor segue apontando (nunca chute)."""
    # Poder pelo nome e sinal municipal: FONTE ÚNICA `esfera_orgao` (19/11/2026). UG do SIAFE = Estado do RJ.
    from compliance_agent.esfera_orgao import RX_MUNICIPAL, poder_por_nome
    if ug and ug in nomes:
        return "estadual", poder_por_nome(nomes[ug], "Executivo")
    campos = " ".join(ln for ln in fm.splitlines() if re.match(r"^(orgao|entidade|tags|esfera_texto):", ln))
    if RX_MUNICIPAL.search(campos):
        return "municipal", ("Legislativo" if re.search(r"c[aâ]mara", campos, re.I) else "Executivo")
    return "", ""


def marcar_nota(texto: str, ug, nomes: dict[str, str]) -> str | None:
    """A nota com `ug`/`orgao` (se o autor não escreveu) e as tags `ug/<código>` + `orgao/<sigla>`. A UG que a nota declara
    vence; `ug` (lida de fora, do SIAFE) só vale para nota que não declara nenhuma. None se a nota não tem frontmatter. Só o frontmatter muda."""
    m = _RE_FM.match(texto)
    if not m:
        return None
    linhas = m.group(1).splitlines()
    tem = {ln.split(":", 1)[0]: i for i, ln in enumerate(linhas) if re.match(r"^[A-Za-z_][\w-]*:", ln)}
    declarada = _valor(linhas[tem["ug"]]) if "ug" in tem else ""
    # a UG que a nota declara vence a lida de fora — se for UG de verdade (19/11/2026: "030002" é prefixo SEI do DEGASE,
    # não UG; "180100, 404400, 570100" lista três): vale a 1ª declarada que existe; nenhuma → a lida de fora
    ug = _ug_valida(declarada, nomes) or str(ug or "").strip()
    ug = ug if ug in nomes else ""
    nossas = ([f"ug/{ug}"] if ug else []) + [f"orgao/{slug_orgao(ug, nomes)}"]
    if ug and "ug" in tem and not declarada:                 # chave vazia do bloco gerado: preenche no lugar
        linhas[tem["ug"]] = f'ug: "{ug}"'
    if ug and "orgao" in tem and not _valor(linhas[tem["orgao"]]):
        linhas[tem["orgao"]] = f"orgao: {_y(nomes[ug])}"
    novas = ([f'ug: "{ug}"'] if ug and "ug" not in tem else []) + ([f"orgao: {_y(nomes[ug])}"] if ug and "orgao" not in tem else [])
    if not any(k in tem and _valor(linhas[tem[k]]) for k in ("esfera", "ente")):
        esf, poder = esfera_poder(ug, nomes, m.group(1))
        if esf:
            if "esfera" in tem:
                linhas[tem["esfera"]] = f"esfera: {esf}"
            else:
                novas.append(f"esfera: {esf}")
            if "poder" not in tem:
                novas.append(f"poder: {poder}")
    if "tags" in tem:
        i = tem["tags"]
        inline = re.match(r"^tags:\s*\[(.*)\]\s*$", linhas[i])
        if inline:
            outras = [t.strip() for t in inline.group(1).split(",") if t.strip() and not _NOSSA.match(t.strip().strip("\"'"))]
            linhas[i] = f"tags: [{', '.join(outras + nossas)}]"
        else:
            j = i + 1
            itens = []
            while j < len(linhas) and re.match(r"^\s+-\s", linhas[j]):
                if not _NOSSA.match(linhas[j].split("-", 1)[1].strip().strip("\"'")):
                    itens.append(linhas[j])
                j += 1
            recuo = re.match(r"^(\s+)-", itens[0]).group(1) if itens else "  "
            proprio = [t.strip() for t in _valor(linhas[i]).split() if t.strip()] if _valor(linhas[i]) else []
            linhas[i:j] = ["tags:"] + [f"{recuo}- {t}" for t in proprio] + itens + [f"{recuo}- {t}" for t in nossas]
    else:
        novas.append(f"tags: [{', '.join(nossas)}]")
    if novas:
        fim = next((i for i, ln in enumerate(linhas) if ln.startswith(_MARCA_GERADA)), len(linhas))
        linhas[fim:fim] = novas
    return "---\n" + "\n".join(linhas) + "\n---\n" + texto[m.end():]


def grupos_obsidian(ugs_presentes: set[str]) -> list[dict]:
    """`colorGroups` do grafo do Obsidian: principais primeiro (ordem da paleta), depois as demais, cinza por último."""
    pri = carregar()["principais"]
    ordem = [u for u in pri if u in ugs_presentes] + sorted(u for u in ugs_presentes if u not in pri)
    return [{"query": f"tag:#ug/{u}", "color": {"a": 1, "rgb": int(cor(u)[1:], 16)}} for u in ordem] + [
        {"query": f"tag:#orgao/{INDETERMINADO}", "color": {"a": 1, "rgb": int(cor("")[1:], 16)}}]


def ug_dos_processos(stems: list[str], db: Path | None = None) -> dict[str, str]:
    """{`030001_047970_2026`: UG} pela OB do SIAFE do processo — só quando UMA UG emitiu a maioria estrita das OB;
    empate ou processo sem OB fica de fora (a nota sai `orgao/indeterminado`)."""
    import sqlite3
    db = db or Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data") / "compliance.db"
    if not stems or not db.exists():
        return {}
    de = {"SEI-" + s.replace("_", "/"): s for s in stems}
    cont: dict[str, dict[str, int]] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    try:
        from compliance_agent.cruzamentos_intel import _ob_paga
        paga = _ob_paga(con)                                 # OB paga: o filtro único da casa (catraca CNF-02)
        chaves = sorted(de)
        for i in range(0, len(chaves), 400):
            lote = chaves[i:i + 400]
            for proc, ug, n in con.execute("SELECT processo, ug_emitente, COUNT(*) FROM ob_orcamentaria_siafe WHERE processo IN "
                                           f"({','.join('?' * len(lote))}) AND {paga} GROUP BY 1, 2", lote):
                cont.setdefault(de[proc], {})[str(ug)] = n
    finally:
        con.close()
    return {s: max(c, key=c.get) for s, c in cont.items() if 2 * max(c.values()) > sum(c.values())}


def aplicar_vault(vault: Path | None = None, nomes: dict[str, str] | None = None, pastas: tuple = ("casos", "processos", "jfn/pericias-agente"),
                  ug_de: dict[str, str] | None = None, idade_min_s: float = 120) -> dict:
    """Marca as notas das `pastas` e grava os grupos de cor no grafo. `ug_de` = {nome do arquivo sem .md: UG} lida de
    fora; sem ele, a UG das notas de `processos/` que não a declaram vem da OB do SIAFE (`ug_dos_processos`) e a das
    demais notas sem UG, do SEI/CNPJ citado (`orgao_fonte.resolver_notas`). Nota mexida há menos de `idade_min_s` é pulada (alguém está editando)."""
    vault, nomes = vault or VAULT, nomes if nomes is not None else nomes_ug()
    if ug_de is None:
        ug_de = {}
        if "processos" in pastas:                            # notas de processo que ainda não declaram UG: OB do processo
            falta = [a.stem for a in sorted((vault / "processos").glob("*.md"))
                     if not _declara_ug_valida(a.read_text(encoding="utf-8"), nomes)]
            ug_de = ug_dos_processos(falta)
        # demais notas sem UG (19/11/2026): OB paga do processo citado → prefixo SEI no índice de OB → quem mais pagou
        # o CNPJ citado (`orgao_fonte`); sem nada disso a nota segue `orgao/indeterminado`
        from compliance_agent.orgao_fonte import resolver_notas
        sem_ug = {a.stem: t for p in pastas for a in sorted((vault / p).glob("*.md")) if a.stem not in ug_de
                  for t in [a.read_text(encoding="utf-8")] if not _declara_ug_valida(t, nomes)}
        ug_de.update({s: r["ug"] for s, r in resolver_notas(sem_ug).items() if r.get("ug")})
    ug_de = ug_de or {}
    r = {"notas": 0, "marcadas": 0, "indeterminadas": 0, "grupos": 0}
    presentes: set[str] = set()
    for pasta in pastas:
        for arq in sorted((vault / pasta).glob("*.md")):
            texto = arq.read_text(encoding="utf-8")
            novo = marcar_nota(texto, ug_de.get(arq.stem), nomes)
            if novo is None:
                continue
            r["notas"] += 1
            tag = re.search(r"\bug/(\d{6})\b", _RE_FM.match(novo).group(1))
            if tag:
                presentes.add(tag.group(1))
            else:
                r["indeterminadas"] += 1
            if novo != texto and time.time() - arq.stat().st_mtime >= idade_min_s:
                arq.write_text(novo, encoding="utf-8")
                r["marcadas"] += 1
    grafo = vault / ".obsidian" / "graph.json"
    if grafo.exists():
        d = json.loads(grafo.read_text(encoding="utf-8"))
        grupos = grupos_obsidian(presentes)
        r["grupos"] = len(grupos)
        if d.get("colorGroups") != grupos:
            d["colorGroups"] = grupos
            grafo.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return r


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["cor"] and len(a) == 2:
        print(cor(a[1]))
        return 0
    if a == ["aplicar"]:
        print(json.dumps(aplicar_vault(), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
