# -*- coding: utf-8 -*-
"""sancao_abrangencia — classifica CADA sanção por TIPO e ABRANGÊNCIA (pedido do dono).

Nem toda sanção proíbe contratar, e as que proíbem têm ALCANCE diferente. A abrangência decide se
uma sanção efetivamente VEDA um contrato com um dado ente (ex.: empresa impedida por órgão FEDERAL
não está proibida de contratar com o Estado do RJ; só a inidoneidade alcança toda a Administração).

Tiers de abrangência (base: Lei 8.666 art. 87; Lei 10.520 art. 7; Lei 14.133 art. 156; Lei 12.846):
  • 'nenhuma' — advertência, multa, publicação, demissão, perdimento: NÃO impedem contratar.
  • 'orgao'   — SUSPENSÃO (Lei 8.666 art. 87 III): efeitos restritos ao ÓRGÃO/entidade sancionador
                (posição conservadora; há decisão do STJ ampliando ao ente — anotado na ressalva).
  • 'ente'    — IMPEDIMENTO de licitar (Lei 10.520 art. 7 / Lei 14.133 art. 156 III): âmbito do
                ENTE FEDERATIVO (União OU o Estado OU o Município) que aplicou.
  • 'total'   — INIDONEIDADE (Lei 8.666 art. 87 IV / Lei 14.133 art. 156 IV / improbidade Lei 8.429):
                toda a Administração Pública (federal, estadual e municipal).

Determinístico. Indício ≠ acusação; confirmar a vigência e o alcance no cadastro-fonte (Portal da
Transparência/CGU) antes de qualquer uso externo."""
from __future__ import annotations

import re
import unicodedata

_ABRANGENCIA_ORDEM = {"nenhuma": 0, "orgao": 1, "ente": 2, "total": 3}


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def classificar_sancao(categoria: str | None, fundamentacao: str | None = None,
                       cadastro: str | None = None) -> dict:
    """{tipo, veda_contratacao, abrangencia, rotulo}. `fundamentacao` (base legal) refina o tier
    quando a categoria é ambígua (art. 87 IV → inidoneidade = total; III → suspensão = órgão)."""
    cat = _norm(categoria)
    fund = _norm(fundamentacao)

    def _out(tipo, veda, abrang, rotulo):
        return {"tipo": tipo, "veda_contratacao": veda, "abrangencia": abrang, "rotulo": rotulo}

    # 1) NÃO impedem contratar
    if "advertenc" in cat:
        return _out("advertencia", False, "nenhuma", "Advertência (não impede contratar)")
    if cat == "multa" or cat.startswith("multa"):
        return _out("multa", False, "nenhuma", "Multa (não impede contratar)")
    if "publicacao extraordinaria" in cat:
        return _out("publicacao", False, "nenhuma", "Publicação extraordinária (não impede contratar)")
    if "demissao" in cat:
        return _out("demissao", False, "nenhuma", "Demissão de servidor (não é sanção à empresa)")
    if "perdimento" in cat:
        return _out("perdimento", False, "nenhuma", "Perdimento de bens (não impede contratar)")
    if "proibicao de receber incentivos" in cat:
        return _out("proibicao_incentivos", False, "nenhuma",
                    "Proibição de receber incentivos/subvenções (não impede contratar)")
    if "dissolucao compulsoria" in cat:
        return _out("dissolucao", True, "total", "Dissolução compulsória da PJ")
    if "interdicao das atividades" in cat or "suspensao/interdicao" in cat:
        return _out("interdicao", True, "total", "Interdição das atividades")

    # 2) INIDONEIDADE — toda a Administração (art. 87 IV / 156 IV / improbidade)
    if ("inidoneidade" in cat or re.search(r"art\.?\s*87[,\s]+iv", fund)
            or re.search(r"art\.?\s*156[,\s]+iv", fund) or "8429" in fund):
        return _out("inidoneidade", True, "total",
                    "Declaração de inidoneidade — veda contratar com TODA a Administração Pública")

    # 3) IMPEDIMENTO de licitar — ente federativo (Lei 10.520 art. 7 / Lei 14.133 art. 156 III)
    if "impedimento" in cat or "proibicao de contratar" in cat or "10.520" in fund or "10520" in fund:
        return _out("impedimento", True, "ente",
                    "Impedimento de licitar — veda contratar com o ENTE FEDERATIVO que aplicou")

    # 4) SUSPENSÃO — só o órgão sancionador (art. 87 III)
    if "suspensao" in cat or re.search(r"art\.?\s*87[,\s]+iii", fund):
        return _out("suspensao", True, "orgao",
                    "Suspensão temporária — veda contratar com o ÓRGÃO sancionador")

    # fallback conservador: categoria desconhecida com verbo de proibição → trata como ente
    if "contratar" in cat or "licitar" in cat:
        return _out("outra_impeditiva", True, "ente", f"Sanção impeditiva: {categoria}")
    return _out("outra", False, "nenhuma", f"Sanção sem efeito de vedação conhecido: {categoria}")


# ── ente do ÓRGÃO sancionador ────────────────────────────────────────────────
_RX_FEDERAL = re.compile(
    r"\btrf\d?\b|tribunal regional federal|justica federal|\btcu\b|controladoria-geral da uniao|"
    r"\bcgu\b|advocacia-geral da uniao|\bagu\b|ministerio p(u|ú)blico federal|\bmpf\b|"
    r"superior tribunal|\bstj\b|\bstf\b|\btse\b|\btst\b|comando (do|da) (exercito|marinha|aeronautica)|"
    r"universidade federal|instituto federal|\bifrj\b|receita federal|policia federal|"
    r"secretaria (do|da) receita")
_RX_ESTADO = re.compile(
    r"tribunal de justica do estado|controladoria-geral do estado|\btce\b|tribunal de contas do estado|"
    r"governo do estado|secretaria de estado|ministerio publico do estado|procuradoria geral do estado|"
    r"policia militar do estado|defensoria publica do estado|assembleia legislativa")
_RX_MUNICIPIO = re.compile(
    r"municipio|prefeitura|camara municipal|controladoria(-| )geral do municipio|"
    r"secretaria municipal|tribunal de contas do municipio")


def ente_do_orgao(orgao: str | None, uf: str | None) -> dict:
    """{esfera: 'federal'|'estadual'|'municipal'|'?', uf}. Deriva do texto do órgão sancionador."""
    o = _norm(orgao)
    uf = (uf or "").strip().upper()
    if _RX_FEDERAL.search(o):
        return {"esfera": "federal", "uf": None}
    if _RX_MUNICIPIO.search(o):
        return {"esfera": "municipal", "uf": uf or None}
    if _RX_ESTADO.search(o) or "estado" in o:
        return {"esfera": "estadual", "uf": uf or None}
    return {"esfera": "?", "uf": uf or None}


def veda_ente(sancao: dict, esfera_alvo: str = "estadual", uf_alvo: str = "RJ") -> dict:
    """Uma sanção efetivamente VEDA um contrato do ente-alvo (default: Estado do RJ)?
    {veda, motivo}. 'total' sempre veda; 'ente'/'orgao' só se a esfera+UF do sancionador batem."""
    cl = classificar_sancao(sancao.get("categoria"), sancao.get("fundamentacao"),
                            sancao.get("cadastro"))
    if not cl["veda_contratacao"]:
        return {"veda": False, "motivo": cl["rotulo"], "abrangencia": cl["abrangencia"],
                "tipo": cl["tipo"]}
    if cl["abrangencia"] == "total":
        return {"veda": True, "motivo": "inidoneidade alcança toda a Administração",
                "abrangencia": "total", "tipo": cl["tipo"]}
    if cl["abrangencia"] == "orgao":
        # suspensão (art. 87 III) veda SÓ o órgão sancionador; sem identificar o órgão comprador
        # exato, não se pode afirmar vedação para um órgão diferente (conservador — evita FP).
        return {"veda": False, "abrangencia": "orgao", "tipo": cl["tipo"],
                "motivo": "suspensão restrita ao órgão sancionador — não verificável p/ outro órgão"}
    ente = ente_do_orgao(sancao.get("orgao"), sancao.get("uf"))
    # impedimento (ente) ou suspensão (órgão): só veda se a esfera do sancionador == a do alvo
    mesma_esfera = ente["esfera"] == esfera_alvo
    mesma_uf = (esfera_alvo == "federal") or (ente["uf"] == uf_alvo) or (ente["uf"] is None and mesma_esfera)
    veda = mesma_esfera and mesma_uf
    motivo = (f"{cl['tipo']} de órgão {ente['esfera']}"
              + (f"/{ente['uf']}" if ente["uf"] else "")
              + (" — alcança o alvo" if veda else " — NÃO alcança contrato "
                 f"{esfera_alvo}/{uf_alvo} (risco reputacional, não vedação)"))
    return {"veda": veda, "motivo": motivo, "abrangencia": cl["abrangencia"],
            "tipo": cl["tipo"], "esfera_sancionador": ente["esfera"], "uf_sancionador": ente["uf"]}


def detalhar(cnpj: str, con, esfera_alvo: str = "estadual", uf_alvo: str = "RJ") -> dict:
    """Lista legível das sanções de um CNPJ: tipo, abrangência, órgão, vigência e se VEDA o alvo.
    Responde 'quais são e qual a abrangência'."""
    linhas = []
    veda_alvo = False
    for r in con.execute(
            "SELECT cadastro, categoria, orgao, uf, data_inicio, data_fim, fundamentacao, processo "
            "FROM sancoes_federais WHERE cpf_cnpj=? ORDER BY data_inicio DESC", (cnpj,)):
        s = dict(r)
        v = veda_ente(s, esfera_alvo, uf_alvo)
        cl = classificar_sancao(s["categoria"], s["fundamentacao"], s["cadastro"])
        veda_alvo = veda_alvo or v["veda"]
        linhas.append({
            "cadastro": s["cadastro"], "tipo": cl["tipo"], "rotulo": cl["rotulo"],
            "abrangencia": cl["abrangencia"], "orgao": s["orgao"], "uf": s["uf"],
            "vigencia": f"{s['data_inicio'] or '?'} → {s['data_fim'] or 'sem prazo'}",
            "veda_alvo": v["veda"], "motivo_alcance": v["motivo"]}
        )
    linhas.sort(key=lambda x: (-int(x["veda_alvo"]), -_ABRANGENCIA_ORDEM.get(x["abrangencia"], 0)))
    return {"ok": True, "cnpj": cnpj, "n": len(linhas), "veda_contrato_alvo": veda_alvo,
            "alvo": f"{esfera_alvo}/{uf_alvo}", "sancoes": linhas,
            "explicacao": ("Cada sanção com seu TIPO e ABRANGÊNCIA. 'veda_alvo' = a sanção "
                           f"efetivamente proíbe contratar com {esfera_alvo} {uf_alvo} (inidoneidade "
                           "sempre; impedimento/suspensão só se o ente do sancionador coincide)."),
            "ressalva": ("Efeito de suspensão (art. 87 III) tem divergência jurisprudencial (STJ já "
                         "ampliou ao ente); aqui é conservador (órgão). Confirmar vigência e alcance "
                         "no cadastro-fonte (CGU) antes de uso externo. Indício ≠ acusação.")}
