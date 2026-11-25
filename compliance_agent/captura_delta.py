# -*- coding: utf-8 -*-
"""Captura por DELTA — Fase 4 do plano (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, seções 3 e 4).

Medido em 23/11/2026: 25% do tempo de captura do it-campo é recaptura com a MESMA árvore, e o nó que recaptura não
sabe o que já está guardado na VM-1 — baixa o processo inteiro. Aqui, funções PURAS que comparam a árvore viva com o
que o arquivo canônico (`data/sei_arquivo/<tag>/manifest.json`) já tem e dizem o que baixar.

Identidade do documento = a do núcleo (`compliance_agent.evidencias`): `sei:<nº SEI do título>` ou `pos:<i>`; número
repetido no mesmo processo vira `#2`, `#3`… pela ordem de aparição. Hash da árvore = `evidencias.hash_arvore` sobre os
ids SEM o sufixo `#k` (mesma regra de `importar_pasta`).

Formato da árvore viva = o de `tools/sei_integra_completa.py` (linhas 636-637): lista de `{"t": título, "u": url do nó
arvore_visualizar (traz `id_documento=`), "pai": contexto}`; a posição na lista é o `i` (`NNN.pdf`). O
`id_documento` sai da url (`sei_integra_completa.id_documento`, linhas 123-129).

Regras (nunca negociáveis):
  - documento novo, sem texto guardado, ou que mudou (título ou id_documento diferente para o mesmo doc_id) → BAIXAR;
    o mudado sai com `preservar_anterior=True`: a versão antiga fica no arquivo, nada é sobrescrito;
  - `pos:<i>` só é mantido se o `id_documento` casar (a posição muda entre enumerações — `arvore_anterior`);
  - documento que sumiu da árvore viva vai para `removidos` e NUNCA é apagado (este módulo não apaga nada).

Ligar no worker: `JFN_CAPTURA_DELTA=1` (filtra o que baixar) ou `JFN_CAPTURA_DELTA=sombra` (só calcula e registra no
manifesto da captura, baixa tudo como hoje). Sem a variável: nada muda.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from compliance_agent.evidencias import hash_arvore, id_sei

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "data" / "sei_arquivo"
GUARDADOS_DIR = RAIZ / "data" / "sei_guardados"      # <tag>.json exportados (vão ao nó junto com a fila)
_RX_ID_DOC = re.compile(r"id_documento=(\d+)")


def _norm(t: str) -> str:
    return " ".join(str(t or "").split())


def _ids_estaveis(titulos_pos: list[tuple[str, object]]) -> list[str]:
    """doc_id de cada entrada (título, posição), com `#k` para número repetido — igual a `evidencias.importar_pasta`."""
    vistos: dict[str, int] = {}
    out = []
    for titulo, pos in titulos_pos:
        n = id_sei(titulo)
        base = f"sei:{n}" if n else f"pos:{pos}"
        vistos[base] = vistos.get(base, 0) + 1
        out.append(base if vistos[base] == 1 else f"{base}#{vistos[base]}")
    return out


def _id_documento(x: dict) -> str:
    if x.get("id_documento"):
        return str(x["id_documento"])
    m = _RX_ID_DOC.search(str(x.get("u") or x.get("url") or ""))
    return m.group(1) if m else ""


def guardados(manifest: dict) -> dict[str, dict]:
    """{doc_id: {i, titulo, chars, texto, id_documento}} do manifesto do ARQUIVO (`data/sei_arquivo/<tag>`).
    `chars` 0 (ou `nao_capturado`) = não há texto guardado — o plano baixa de novo."""
    docs = [d for d in (manifest.get("docs") or []) if isinstance(d, dict)]
    ids = _ids_estaveis([(d.get("titulo", ""), d.get("i")) for d in docs])
    out: dict[str, dict] = {}
    for doc_id, d in zip(ids, docs):
        tem = bool(d.get("texto")) and not d.get("nao_capturado")
        out[doc_id] = {"i": d.get("i"), "titulo": d.get("titulo") or "", "chars": int(d.get("chars") or 0) if tem else 0,
                       "texto": d.get("texto") or "", "id_documento": str(d.get("id_documento") or "")}
    return out


def _hash(ids: list[str]) -> str:
    return hash_arvore([k.split("#")[0] for k in ids])


def plano_de_captura(arvore_viva: list[dict], guardados: dict[str, dict]) -> dict:
    """Compara a árvore viva (formato de `sei_integra_completa`: `{"t", "u", "pai"}`) com os guardados.

    Devolve `{"baixar": [{i, doc_id, motivo, preservar_anterior?}], "manter": [{i, doc_id}],
    "removidos": [{doc_id, titulo, i}], "arvore_igual": bool, "hash": hash da árvore viva}`.
    `motivo` ∈ novo | sem_texto | retificado | pos_sem_id. Nada em `guardados` é alterado."""
    ids = _ids_estaveis([(x.get("t", ""), i) for i, x in enumerate(arvore_viva)])
    baixar, manter, sem_id = [], [], 0
    for i, (doc_id, x) in enumerate(zip(ids, arvore_viva)):
        g = guardados.get(doc_id)
        ident = _id_documento(x)
        if g is None:
            baixar.append({"i": i, "doc_id": doc_id, "motivo": "novo"})
        elif doc_id.startswith("pos:") and not (ident and ident == g.get("id_documento")):
            # sem nº SEI a identidade é a posição, que muda entre enumerações: só o id_documento prova que é o mesmo
            baixar.append({"i": i, "doc_id": doc_id, "motivo": "pos_sem_id"})
        elif (_norm(x.get("t", "")) != _norm(g.get("titulo", ""))
              or (ident and g.get("id_documento") and ident != g["id_documento"])):
            baixar.append({"i": i, "doc_id": doc_id, "motivo": "retificado", "preservar_anterior": True})
        elif int(g.get("chars") or 0) <= 0:
            baixar.append({"i": i, "doc_id": doc_id, "motivo": "sem_texto"})
        else:
            manter.append({"i": i, "doc_id": doc_id})
            sem_id += not g.get("id_documento")     # guardado sem id (legado): retificação de id não é verificável
    vivos = set(ids)
    removidos = [{"doc_id": k, "titulo": g.get("titulo", ""), "i": g.get("i")}
                 for k, g in guardados.items() if k not in vivos]
    h = _hash(ids)
    return {"baixar": baixar, "manter": manter, "removidos": removidos, "mantidos_sem_id_documento": sem_id,
            "arvore_igual": bool(guardados) and h == _hash(list(guardados)), "hash": h}


def exportar_guardados(tag: str, arquivo: Path | str = ARQUIVO) -> dict:
    """Lista compacta e serializável do que o arquivo tem do processo (vai ao nó junto com a fila).
    `docs` = [[doc_id, título, chars, id_documento], …]. Sem manifesto → `docs` vazio (o nó baixa tudo)."""
    try:
        man = json.loads((Path(arquivo) / tag / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    g = guardados(man if isinstance(man, dict) else {})
    return {"tag": tag, "processo": (man or {}).get("processo", "") if isinstance(man, dict) else "",
            "hash": _hash(list(g)) if g else "",
            "docs": [[k, v["titulo"], v["chars"], v["id_documento"]] for k, v in g.items()]}


def carregar_guardados(dados: str | dict) -> dict[str, dict]:
    """Inverso de `exportar_guardados` (aceita o JSON em texto ou já carregado)."""
    d = json.loads(dados) if isinstance(dados, str) else dados
    out = {}
    for linha in d.get("docs") or []:
        doc_id, titulo, chars = linha[0], linha[1], linha[2]
        out[doc_id] = {"titulo": titulo, "chars": int(chars or 0), "id_documento": linha[3] if len(linha) > 3 else ""}
    return out


# ── ponto de encaixe (tools/sei_integra_completa.py) ─────────────────────────────────────────────────────────────────
def modo(env=None) -> str:
    """"filtrar" (`JFN_CAPTURA_DELTA=1`), desligado (`=0`/`off`) ou "sombra" — o PADRÃO desde 23/11/2026 (plano de
    reescrita, Fase 4: 7 dias de sombra em todos os nós). A sombra só registra o plano no manifesto da captura; baixa
    tudo como antes e o `sei_arquivar` só usa o registro no modo "filtrar"."""
    v = str((os.environ if env is None else env).get("JFN_CAPTURA_DELTA", "sombra")).strip().lower()
    return "filtrar" if v in ("1", "filtrar") else "" if v in ("0", "off", "desligado", "") else "sombra"


ENV_E3 = "JFN_E3_DELTA"


def modo_e3(env=None) -> str:
    """Valor de `JFN_CAPTURA_DELTA` que o E3 (`arvore.NavegadorSEI.capturar`) passa à captura. DESLIGADO por padrão
    (O3.5, 25/11/2026): "sombra" = baixa tudo e só registra o plano no manifesto. `JFN_E3_DELTA=1` liga o incremental
    por id_documento ("1": só o novo/mudado; o "Gerar PDF" em lotes só com eles) — quem liga é a religação (O9.0)."""
    v = str((os.environ if env is None else env).get(ENV_E3, "")).strip().lower()
    return "1" if v in ("1", "filtrar", "ligado") else "sombra"


def guardados_do_processo(tag: str, pasta_exportados: Path | str = GUARDADOS_DIR,
                          arquivo: Path | str = ARQUIVO) -> dict[str, dict] | None:
    """Guardados do processo: o exportado (`<pasta>/<tag>.json`, no nó) ou, SÓ SE ELE NÃO EXISTE, o manifesto do
    arquivo. None se não há nenhum dos dois (a captura segue como hoje). Exportado que existe e não se lê é ERRO
    (ValueError) — cair calado no manifesto do arquivo trocaria a fonte do delta (revisão de falhas caladas S6); o
    encaixe do `sei_integra_completa` registra o erro e baixa tudo."""
    exp = Path(pasta_exportados) / f"{tag}.json"
    if exp.exists():
        try:
            return carregar_guardados(exp.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, IndexError, AttributeError) as e:
            raise ValueError(f"guardados exportados ilegíveis em {exp}: {type(e).__name__}: {e}") from e
    try:
        man = json.loads((Path(arquivo) / tag / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return guardados(man) if isinstance(man, dict) else None


def encaixe(tag: str, arvore_viva: list[dict], env=None, **onde) -> tuple[set[int], dict | None]:
    """(posições a NÃO baixar, registro para o manifesto da captura). Desligado ou sem guardados → (set(), None):
    a captura fica idêntica à de hoje. No modo sombra o registro é feito, mas nada é pulado."""
    m = modo(env)
    if not m:
        return set(), None
    g = guardados_do_processo(tag, **onde)
    if g is None:
        return set(), None
    p = plano_de_captura(arvore_viva, g)
    reg = {"modo": m, "baixados": len(p["baixar"]), "mantidos": len(p["manter"]),
           "removidos": len(p["removidos"]), "arvore_igual": p["arvore_igual"], "hash": p["hash"],
           "mantidos_sem_id_documento": p["mantidos_sem_id_documento"],
           "retificados": [b["doc_id"] for b in p["baixar"] if b.get("preservar_anterior")],
           "manter": [{"i": e["i"], "doc_id": e["doc_id"]} for e in p["manter"]]}   # o sei_arquivar junta estes
    return ({e["i"] for e in p["manter"]} if m == "filtrar" else set()), reg
