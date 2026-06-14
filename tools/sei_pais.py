#!/usr/bin/env python3
"""SEI — DETECTOR + LEITOR de PROCESSOS-PAI (contratação) a partir dos dockets já lidos.

PROBLEMA REAL (verificado, NÃO é captcha): muitos dockets SEI vêm "vazios" (a página abre, mas sem
peça própria) porque são de **execução/pagamento**. A substância (contrato, parecer PGE/CGE, termo de
colaboração/fomento) vive no **PROCESSO-PAI / de contratação**, referenciado no texto dos documentos.

  Ex. comprovado: o docket `SEI-080002/010538/2024` (TAC R$3,3M do IDESI) traz no conteúdo do despacho:
  "...existe processo de contratação em andamento de nº SEI-080002/000821/2024 que virá a suprir a
  demanda..." → o pai `080002/000821/2024` é onde está o **Contrato 215/2024**.

Este módulo:
  1. Varre o cache `data/sei_cache/cdp_SEI_*.json` e DETECTA os números de processo-pai referenciados,
     priorizando os de CONTRATAÇÃO (regex SEI + janela de contexto com palavras-chave), com um
     DENYLIST de boilerplate (refs que aparecem no MENU lateral de centenas de páginas = ruído).
  2. Filtra os pais que JÁ estão no cache (anti-duplicata) e devolve uma fila priorizada.
  3. (no `sei_sweep --seguir-pais`) lê esses pais na MESMA sessão única itkava e grava no cache+ficha.

Honesto: detecção é heurística (indício de parentesco, não prova); refs do menu lateral são DESCARTADAS;
nada é inventado. A maioria dos 392 "vazios" são de execução SEM peça e SEM conteúdo a minerar — o ganho
real vem dos dockets que LERAM documentos e citam o pai de contratação no corpo deles.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "sei_cache"

# Número de processo SEI-RJ: UUUUUU/NNNNNN/AAAA (unidade/sequencial/ano). Tolera prefixo 'SEI-'/'SEI '
# e separadores '/' ou '.'. Captura os 3 grupos para normalizar.
_PAT_SEI = re.compile(r"(?:SEI[-\s]*)?(\d{6})[/.](\d{6})[/.](20\d{2})")

# Palavras-chave de CONTRATAÇÃO: quando uma ref aparece perto delas, é forte candidata a processo-pai.
# (minúsculas, sem acento e com acento — comparamos contra o texto em minúsculas)
_KW_CONTRATACAO = (
    "processo de contrata", "processo principal", "processo originario", "processo originário",
    "processo de origem", "processo matriz", "processo pai", "contrato de gestao",
    "contrato de gestão", "termo de colabora", "termo de fomento", "termo de execucao",
    "termo de execução", "credenciamento", "chamamento", "instrumento contratual",
    "contratacao em andamento", "contratação em andamento", "processo administrativo de contrata",
    "processo de gestao", "processo de gestão", "processo licitatorio", "processo licitatório",
)

# Janela (chars) ao redor de uma palavra-chave para considerar uma ref como pai de contratação.
_JANELA = 240


def _norm(numero: str) -> str:
    """Só os dígitos de um número SEI (p/ comparação/dedup)."""
    return re.sub(r"[^0-9]", "", numero or "")


def _fmt(grupos: tuple) -> str:
    """(uni, seq, ano) -> 'SEI-uni/seq/ano' canônico."""
    return "SEI-%s/%s/%s" % grupos


def _cache_path(proc: str) -> Path:
    return CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"


def carregar_cache() -> dict[str, dict]:
    """Carrega todos os cdp_SEI_*.json (path -> dict). Tolera arquivos corrompidos (pula)."""
    out: dict[str, dict] = {}
    for cf in CACHE.glob("cdp_SEI_*.json"):
        try:
            out[str(cf)] = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return out


def construir_denylist(cache: dict[str, dict], min_freq: int = 40) -> set[str]:
    """DENYLIST de boilerplate: o `texto` do cache é o MENU lateral do SEI (painel 'Acompanhamento
    Especial', listas de tipos de processo) — os MESMOS números SEI aparecem em centenas de páginas.
    Uma ref que figura no `texto` de >= min_freq arquivos NÃO é parentesco do docket: é ruído de menu.
    Retorna o conjunto de refs (formato canônico) a ignorar."""
    from collections import Counter
    c: Counter = Counter()
    for d in cache.values():
        txt = d.get("texto") or ""
        for m in set(_PAT_SEI.findall(txt)):
            c[_fmt(m)] += 1
    return {ref for ref, n in c.items() if n >= min_freq}


def _refs_de_conteudo_com_kw(d: dict, self_digits: str, deny: set[str]) -> list[tuple[str, str]]:
    """Refs encontradas no CONTEÚDO REAL dos documentos (não no menu) numa janela de palavra-chave de
    contratação. Esta é a fonte de MAIOR confiança (o despacho cita o pai). Retorna [(ref, trecho)]."""
    achados: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for c in (d.get("conteudo_documentos") or []):
        cont = c.get("conteudo") if isinstance(c, dict) else None
        if not cont:
            continue
        low = cont.lower()
        # posições de cada palavra-chave de contratação
        kw_pos = [i for kw in _KW_CONTRATACAO for i in _achar_todos(low, kw)]
        for m in _PAT_SEI.finditer(cont):
            ref = _fmt(m.groups())
            digs = "".join(m.groups())
            if digs == self_digits or ref in deny or ref in vistos:
                continue
            ini, fim = m.start(), m.end()
            # a ref está dentro da janela de alguma palavra-chave?
            if any(abs(p - ini) <= _JANELA or abs(p - fim) <= _JANELA for p in kw_pos):
                vistos.add(ref)
                achados.append((ref, cont[max(0, ini - 80):fim + 40].replace("\n", " ").strip()))
    return achados


def _achar_todos(hay: str, needle: str) -> list[int]:
    out, i = [], hay.find(needle)
    while i >= 0:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def _refs_relacionados_raros(d: dict, self_digits: str, freq_rel: dict[str, int],
                             deny: set[str], teto: int = 5) -> list[tuple[str, str]]:
    """Para dockets VAZIOS (0 docs, sem conteúdo a minerar): o único lead é a árvore de `relacionados`.
    Mas a maioria dos relacionados também é boilerplate (painel comum a centenas de páginas). Mantemos só
    os RAROS (aparecem em <= `teto` arquivos) = process-específicos. Confiança MENOR (não há keyword)."""
    out: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for r in (d.get("relacionados") or []):
        blob = (r.get("texto") or "") + " " + (r.get("titulo") or "")
        for m in _PAT_SEI.finditer(blob):
            ref = _fmt(m.groups())
            digs = "".join(m.groups())
            if digs == self_digits or ref in deny or ref in vistos:
                continue
            if freq_rel.get(ref, 0) <= teto:
                vistos.add(ref)
                out.append((ref, (r.get("titulo") or "relacionado")[:80]))
    return out


def _freq_relacionados(cache: dict[str, dict]) -> dict[str, int]:
    """Em quantos arquivos cada ref aparece como RELACIONADO (p/ separar lead raro de boilerplate)."""
    from collections import Counter
    c: Counter = Counter()
    for d in cache.values():
        refs: set[str] = set()
        for r in (d.get("relacionados") or []):
            blob = (r.get("texto") or "") + " " + (r.get("titulo") or "")
            for m in _PAT_SEI.findall(blob):
                refs.add(_fmt(m))
        for ref in refs:
            c[ref] += 1
    return dict(c)


def detectar_pais(cache: dict[str, dict] | None = None, incluir_relacionados: bool = True) -> list[dict]:
    """Detecta os PROCESSOS-PAI de contratação referenciados pelos dockets em cache que AINDA NÃO estão
    no cache. Retorna uma lista priorizada de dicts:
        {pai, fonte: 'conteudo'|'relacionado', confianca: 'alta'|'media',
         origem: <docket que citou>, trecho: <evidência>, n_citacoes: <quantos dockets citam>}
    Ordem: confiança alta (conteúdo+keyword) primeiro, depois nº de citações desc (um pai citado por
    vários dockets = mais central). Anti-duplicata: um pai aparece UMA vez (agrega as origens)."""
    if cache is None:
        cache = carregar_cache()
    deny = construir_denylist(cache)
    freq_rel = _freq_relacionados(cache) if incluir_relacionados else {}
    # conjunto de números JÁ em cache (qualquer grafia) p/ não re-enfileirar o que já temos
    em_cache: set[str] = set()
    for d in cache.values():
        em_cache.add(_norm(d.get("numero") or ""))

    # agrega por pai
    pais: dict[str, dict] = {}

    def _registrar(ref: str, fonte: str, conf: str, origem: str, trecho: str):
        if _norm(ref) in em_cache:
            return  # já lido — anti-duplicata
        p = pais.get(ref)
        if not p:
            pais[ref] = {"pai": ref, "fonte": fonte, "confianca": conf, "origem": origem,
                         "trecho": trecho, "n_citacoes": 1}
        else:
            p["n_citacoes"] += 1
            # promove a confiança/fonte se um novo achado for mais forte
            if conf == "alta" and p["confianca"] != "alta":
                p.update(confianca="alta", fonte=fonte, origem=origem, trecho=trecho)

    for d in cache.values():
        self_digits = _norm(d.get("numero") or "")
        for ref, trecho in _refs_de_conteudo_com_kw(d, self_digits, deny):
            _registrar(ref, "conteudo", "alta", d.get("numero") or "", trecho)
        if incluir_relacionados:
            for ref, trecho in _refs_relacionados_raros(d, self_digits, freq_rel, deny):
                _registrar(ref, "relacionado", "media", d.get("numero") or "", trecho)

    ordem = {"alta": 0, "media": 1}
    return sorted(pais.values(), key=lambda x: (ordem[x["confianca"]], -x["n_citacoes"]))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Detecta processos-pai de contratação no cache SEI (não lê).")
    ap.add_argument("--sem-relacionados", action="store_true",
                    help="só a fonte de alta confiança (conteúdo+keyword), ignora leads de relacionados")
    ap.add_argument("--limite", type=int, default=0, help="mostra só os N primeiros (0=todos)")
    a = ap.parse_args()
    pais = detectar_pais(incluir_relacionados=not a.sem_relacionados)
    if a.limite:
        pais = pais[:a.limite]
    print(f"PROCESSOS-PAI detectados (não em cache): {len(pais)}")
    for p in pais:
        print(f"  [{p['confianca']:5s}/{p['fonte']:11s}] {p['pai']}  (citado por {p['n_citacoes']}; "
              f"ex. {p['origem']})")
        if p["confianca"] == "alta":
            print(f"          ↳ {p['trecho'][:140]}")


if __name__ == "__main__":
    main()
