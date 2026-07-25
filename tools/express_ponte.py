"""Ponte entre o Adobe Express e o painel do JFN — sem credencial, sem custo.

Por que existe: a Express API oficial exige entitlement de ORGANIZAÇÃO no Adobe Admin
Console (product profiles com "Adobe Firefly Services" e "Firefly Creative Production
for Enterprise"), o que é plano empresarial pago — vetado aqui. O que sobra, e funciona
hoje, é um fluxo assistido em dois sentidos:

  1. `--spec`     o painel EXPORTA sua identidade (paleta em HEX, fontes, medidas exatas
                  das artes que ele consome) para um documento que se usa no Express.
                  Sem isso o dono desenha "no escuro" e a arte volta fora da marca.
  2. `--importar` o que sair do Express (SVG/PNG/JPG) entra pela pasta de entrada, é
                  validado, otimizado, versionado em `static/assets/express/` e ganha um
                  manifesto + o trecho pronto para colar no painel.

O elo que faltava é a conversão OKLCH → HEX: a paleta da casa é toda OKLCH e o Express
só aceita HEX. É feita aqui, na fonte, para não haver duas verdades de cor.

Uso:
    python -m tools.express_ponte --spec
    python -m tools.express_ponte --importar
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PAINEL = RAIZ / "static" / "jfn-painel.html"
BASE = RAIZ / "docs" / "referencias" / "express"
ENTRADA = BASE / "entrada"
DESTINO = RAIZ / "static" / "assets" / "express"
MANIFESTO = DESTINO / "manifest.json"
EXTS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}
TETO_BYTES = 900_000          # arte de fundo acima disso atrasa o painel na VM

# ── cor ──────────────────────────────────────────────────────────────────────────
_OKLCH = re.compile(
    r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:/\s*([\d.]+)\s*)?\)", re.I
)


def oklch_para_hex(L: float, C: float, H: float) -> str:
    """OKLCH → #RRGGBB (sRGB). O Express não entende OKLCH; a paleta da casa é toda OKLCH."""
    h = math.radians(H)
    a, b = C * math.cos(h), C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )
    out = []
    for c in lin:
        c = 12.92 * c if c <= 0.0031308 else 1.055 * (max(c, 0.0) ** (1 / 2.4)) - 0.055
        out.append(round(max(0.0, min(1.0, c)) * 255))
    return "#%02X%02X%02X" % tuple(out)


def tokens_do_painel() -> dict[str, str]:
    """Lê os tokens OKLCH do painel. O ÚLTIMO valor de cada token vence — é a cascata
    (v7 → v9 → v12), a mesma regra que o navegador aplica."""
    texto = PAINEL.read_text(encoding="utf-8")
    achados: dict[str, str] = {}
    for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*(oklch\([^)]*\))", texto, re.I):
        achados[m.group(1)] = m.group(2)
    saida = {}
    for nome, valor in achados.items():
        g = _OKLCH.search(valor)
        if not g:
            continue
        saida[nome] = oklch_para_hex(float(g.group(1)), float(g.group(2)), float(g.group(3)))
    return saida


# ── medidas ──────────────────────────────────────────────────────────────────────
def artes_existentes() -> list[tuple[str, str]]:
    """Dimensão real das artes que o painel já consome — é a medida a usar no Express."""
    try:
        from PIL import Image
    except ImportError:
        return []
    achados = []
    for p in sorted((RAIZ / "static" / "assets").glob("*.jpg")) + \
             sorted((RAIZ / "static" / "assets").glob("*.png")):
        try:
            with Image.open(p) as im:
                achados.append((p.name, f"{im.width}×{im.height}"))
        except Exception:
            continue
    return achados


PAPEIS = [
    ("ion", "azul — o console: estrutura, interação, frio"),
    ("ion-hi", "azul claro — realce de console"),
    ("flame", "laranja — ENERGIA: ação, dinheiro, carga"),
    ("flame-hi", "laranja claro — número de dinheiro"),
    ("rose", "rosa — severidade crítica (nunca decorativo)"),
    ("green", "verde — conforme/ok"),
    ("bg", "fundo da página"),
    ("card", "superfície de card"),
    ("tx", "texto principal"),
    ("mut", "texto secundário"),
]


def gerar_spec() -> Path:
    cores = tokens_do_painel()
    BASE.mkdir(parents=True, exist_ok=True)
    ENTRADA.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    L = [
        "# Especificação de design — JFN (para usar no Adobe Express)",
        "",
        f"> Gerado de `static/jfn-painel.html` em {agora}. **Não editar à mão** — rode",
        "> `python -m tools.express_ponte --spec` de novo quando a paleta mudar.",
        "",
        "## 1 · Paleta (HEX, convertida do OKLCH do painel)",
        "",
        "No Express: **Cores da marca → Adicionar cor → colar o HEX**.",
        "",
        "| Token | HEX | Papel |",
        "|---|---|---|",
    ]
    for token, papel in PAPEIS:
        if token in cores:
            L.append(f"| `--{token}` | `{cores[token]}` | {papel} |")
    L += [
        "",
        "**Regra de cor da casa:** azul = console/estrutura · laranja = energia/dinheiro ·",
        "rosa e verde só carregam severidade. Cor saturada sem significado é proibida.",
        "",
        "## 2 · Tipografia",
        "",
        "- **IBM Plex Sans** — texto (auto-hospedada em `/static/assets/fonts/`)",
        "- **IBM Plex Mono** — número, telemetria, CNPJ",
        "",
        "As duas são gratuitas e estão na biblioteca do Express. Não substituir por outra",
        "sem-serifa geométrica: o par do painel é serifa-menos-mono, não duas sem-serifa.",
        "",
        "## 3 · Medidas das artes que o painel consome",
        "",
    ]
    artes = artes_existentes()
    if artes:
        L += ["| Arquivo | Dimensão |", "|---|---|"]
        L += [f"| `{n}` | {d} |" for n, d in artes]
    else:
        L.append("_(Pillow ausente — medidas não lidas)_")
    L += [
        "",
        f"**Teto de peso por arte: {TETO_BYTES // 1000} KB.** A VM tem 2 vCPU; arte pesada",
        "atrasa a primeira dobra. Exportar JPEG qualidade 80 para fundo, SVG para vetor.",
        "",
        "## 4 · O que exportar do Express",
        "",
        "- **fundo/nebulosa** → JPEG, na dimensão da tabela acima;",
        "- **ícone, selo, marca, diagrama** → **SVG** (escala sem peso e aceita cor por CSS);",
        "- **não** exportar texto como imagem: o painel precisa do texto legível e buscável.",
        "",
        "## 5 · Como devolver ao painel",
        "",
        f"1. salve o arquivo exportado em `{ENTRADA.relative_to(RAIZ)}/`;",
        "2. rode `python -m tools.express_ponte --importar`;",
        "3. cole no painel o trecho que o comando imprimir.",
        "",
    ]
    destino = BASE / "ESPECIFICACAO.md"
    destino.write_text("\n".join(L), encoding="utf-8")
    return destino


# ── importação ───────────────────────────────────────────────────────────────────
def importar() -> list[dict]:
    ENTRADA.mkdir(parents=True, exist_ok=True)
    DESTINO.mkdir(parents=True, exist_ok=True)
    entradas = [p for p in sorted(ENTRADA.iterdir()) if p.suffix.lower() in EXTS]
    registro: list[dict] = []
    if MANIFESTO.exists():
        try:
            registro = json.loads(MANIFESTO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            registro = []
    novos = []
    for p in entradas:
        tam = p.stat().st_size
        aviso = None
        if tam > TETO_BYTES:
            aviso = f"{tam // 1000} KB — acima do teto de {TETO_BYTES // 1000} KB"
        dim = None
        if p.suffix.lower() != ".svg":
            try:
                from PIL import Image
                with Image.open(p) as im:
                    dim = f"{im.width}×{im.height}"
            except Exception as e:                      # arquivo corrompido é erro, não silêncio
                print(f"!! {p.name}: não abriu como imagem ({e}) — pulado")
                continue
        elif b"<svg" not in p.read_bytes()[:2000].lower():
            print(f"!! {p.name}: extensão .svg mas sem tag <svg> — pulado")
            continue
        alvo = DESTINO / p.name
        shutil.copy2(p, alvo)
        item = {
            "arquivo": p.name,
            "url": f"/static/assets/express/{p.name}",
            "bytes": tam,
            "dimensao": dim,
            "importado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if aviso:
            item["aviso"] = aviso
        registro = [r for r in registro if r.get("arquivo") != p.name] + [item]
        novos.append(item)
    MANIFESTO.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return novos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", action="store_true", help="gera a especificação de design para o Express")
    ap.add_argument("--importar", action="store_true", help="traz o que está em docs/referencias/express/entrada/")
    args = ap.parse_args()
    if not (args.spec or args.importar):
        ap.print_help()
        return 1
    if args.spec:
        d = gerar_spec()
        print(f"especificação: {d.relative_to(RAIZ)}")
        print(f"entrada para artes do Express: {ENTRADA.relative_to(RAIZ)}/")
    if args.importar:
        novos = importar()
        if not novos:
            print(f"nada novo em {ENTRADA.relative_to(RAIZ)}/ (extensões aceitas: {', '.join(sorted(EXTS))})")
            return 0
        print(f"{len(novos)} arte(s) importada(s) → {DESTINO.relative_to(RAIZ)}/\n")
        for it in novos:
            print(f"  {it['arquivo']}  {it.get('dimensao') or 'vetor'}  {it['bytes'] // 1000} KB"
                  + (f"  ⚠ {it['aviso']}" if it.get("aviso") else ""))
            if it["arquivo"].lower().endswith(".svg"):
                print(f"      HTML:  <img src=\"{it['url']}\" alt=\"\" width=\"…\" height=\"…\">")
            else:
                print(f"      CSS :  background-image:url({it['url']});")
        print(f"\n  manifesto: {MANIFESTO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
