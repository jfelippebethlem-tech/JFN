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
    # 1-A) FUNDAMENTAÇÃO antes da categoria (revisão 13/11/2026): no CEIS a categoria contradiz a base legal
    #    em casos reais — "Suspensão/Interdição das atividades" e até "Inidoneidade" com base na Lei 13.019
    #    art. 73, II (suspensão de parceria, alcance do ente sancionador), e "Impedimento" com base na
    #    Lei 8.666 art. 87, III (suspensão, alcance do órgão sancionador).
    if "13019" in fund or "13.019" in fund or "organizacoes da sociedade civil" in fund:
        if re.search(r"art\.?\s*73[,\s]+iii", fund):
            return _out("inidoneidade", True, "total",
                        "Declaração de inidoneidade (Lei 13.019, art. 73, III) — toda a Administração")
        if re.search(r"art\.?\s*73[,\s]+ii\b", fund):
            return _out("suspensao", True, "ente",
                        "Suspensão de parceria (Lei 13.019, art. 73, II) — só a esfera do ente sancionador")
    tem_87_iv = bool(re.search(r"art\.?\s*87[,\s]+iv", fund) or re.search(r"art\.?\s*156[,\s]+iv", fund))
    if re.search(r"art\.?\s*87[,\s]+iii", fund) and not tem_87_iv and "8429" not in fund:
        return _out("suspensao", True, "orgao",
                    "Suspensão temporária (Lei 8.666, art. 87, III) — veda contratar com o ÓRGÃO sancionador")

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
    r"\btrf\d?\b|tribunal regional federal|justica federal|\btcu\b|tribunal de contas da uniao|"
    r"controladoria-geral da uniao|"
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


_ABRANGENCIA_CEIS = {
    # coluna "ABRANGÊNCIA DA SANÇÃO" do CEIS/CNEP (grafada "ABRAGÊNCIA" no CSV da CGU) → tier
    "todas as esferas em todos os poderes": "total",
    "em todos os poderes da esfera do orgao sancionador": "ente",
    "na esfera e no poder do orgao sancionador": "ente_poder",
    "no orgao sancionador": "orgao",
}
_RX_JUDICIARIO = re.compile(r"tribunal de justica|justica (federal|do trabalho|eleitoral|militar)|"
                            r"tribunal regional|\btrf\d?\b|\btrt\b|\btre\b|\bstf\b|\bstj\b|\btst\b|"
                            r"supremo tribunal|superior tribunal|vara\b|comarca|juizo")
_RX_LEGISLATIVO = re.compile(r"assembleia legislativa|camara (municipal|dos deputados)|senado federal|"
                             r"tribunal de contas|\btce\b|\btcu\b|\btcm\b")


CAMPOS_CEIS = ("abrangencia", "esfera_sancionador", "data_publicacao")


def sql_campos_ceis(con) -> str:
    """Fragmento de SELECT com as colunas que `tools/ingerir_ceis_cnep.py` passou a guardar; base antiga
    (sem a migração) devolve NULL com o mesmo nome — o chamador não precisa saber qual é o caso."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(sancoes_federais)")}
    return ", ".join(c if c in cols else f"NULL AS {c}" for c in CAMPOS_CEIS)


_TIER = {"orgao": 1, "ente_poder": 2, "ente": 3, "total": 4}


def teto_legal(fundamentacao: str | None) -> str | None:
    """Alcance MÁXIMO que a base legal citada permite (None = sem teto: inidoneidade, improbidade, cautelar penal).
    Revisão cética 13/11/2026: o CEIS traz "Todas as Esferas" em suspensão de parceria (Lei 13.019 art. 73, II) e
    em impedimento municipal (Lei 14.133 art. 156, III) — a declaração não pode alargar o que a lei limita."""
    f = _norm(fundamentacao)
    if not f or re.search(r"art\.?\s*(87|156)[,\s]+iv|art\.?\s*73[,\s]+iii", f) or "8429" in f:
        return None
    if ("13019" in f or "organizacoes da sociedade civil" in f) and re.search(r"art\.?\s*73[,\s]+ii\b", f):
        return "ente"
    if re.search(r"art\.?\s*87[,\s]+iii", f):
        return "orgao"
    if re.search(r"art\.?\s*156[,\s]+iii", f) or "10520" in f or "10.520" in f:
        return "ente"
    return None


INICIO_LEI_14230 = "2021-10-26"


def teto_por_lei_especial(fundamentacao: str | None, data_inicio: str | None = None) -> tuple[str | None, str]:
    """(teto, motivo) para bases legais que a categoria do CEIS esconde — verificação independente de 13/11/2026.
    Vale também SEM abrangência declarada (o teto de `teto_legal` só entrava quando o CEIS declarava algo).

    · Lei 8.443/92 art. 46 (TCU): inidoneidade "para participar de licitação na Administração Pública FEDERAL" →
      teto = ente (a União). O CEIS grava a categoria "Declaração de Inidoneidade" e, em 9 registros, "Todas as
      Esferas" — a lei não dá isso.
    · Lei 13.303/16 art. 83, III: suspensão e impedimento "com a ENTIDADE sancionadora" → teto = órgão.
    · Lei 8.429/92 art. 12, §4º (redação da Lei 14.230/2021, em vigor em 26/10/2021): a proibição de contratar
      alcança o ENTE LESADO; só "em caráter excepcional e por motivos relevantes devidamente justificados" extrapola.
      Sanção iniciada desde então e sem abrangência declarada → teto = ente (o do sancionador é a melhor
      aproximação disponível do ente lesado; ler a sentença). Anterior ou sem data: mantém-se a leitura ampla."""
    f = _norm(fundamentacao)
    if re.search(r"\b8\.?443\b", f) and re.search(r"art\.?\s*46", f):
        return "ente", "Lei 8.443/92, art. 46 — só a Administração Pública Federal"
    if re.search(r"\b13\.?303\b", f) and re.search(r"art\.?\s*83", f):
        return "orgao", "Lei 13.303/16, art. 83, III — só a entidade sancionadora"
    if "8429" in f and (data_inicio or "")[:10] >= INICIO_LEI_14230:
        return "ente", "Lei 8.429/92, art. 12, §4º (Lei 14.230/2021) — ente lesado, salvo decisão que o estenda"
    return None, ""


def abrangencia_declarada(texto: str | None) -> str | None:
    """Tier da abrangência que o próprio CEIS declara; 'Sem Informação'/vazio/'Em outro órgão' → None."""
    return _ABRANGENCIA_CEIS.get(_norm(texto).strip())


def poder_do_orgao(orgao: str | None) -> str:
    o = _norm(orgao)
    if _RX_JUDICIARIO.search(o):
        return "judiciario"
    if _RX_LEGISLATIVO.search(o):
        return "legislativo"
    return "executivo"


def vigente_em(sancao: dict, data_iso: str | None) -> bool:
    """A sanção estava VIGENTE na data (ISO AAAA-MM-DD)? Sem início ou sem data do ato → não se afirma.
    "Com prazo determinado" sem data final → não se afirma (revisão 13/11/2026: era lido como vigente)."""
    d = (data_iso or "")[:10]
    ini = (sancao.get("data_inicio") or "")[:10]
    fim = (sancao.get("data_fim") or "")[:10]
    if not d or not ini or d < ini:
        return False
    if fim:
        return d <= fim
    return "com prazo determinado" not in _norm(sancao.get("categoria"))


def veda_ente(sancao: dict, esfera_alvo: str = "estadual", uf_alvo: str = "RJ",
              poder_alvo: str = "executivo") -> dict:
    """Uma sanção efetivamente VEDA um contrato do ente-alvo (default: Executivo do Estado do RJ)?
    {veda, motivo}. 'total' sempre veda; 'ente'/'orgao' só se a esfera+UF do sancionador batem.
    A abrangência DECLARADA no CEIS (quando ingerida) prevalece sobre a inferida pela categoria/base legal;
    a esfera declarada do sancionador prevalece sobre o palpite pelo nome do órgão."""
    cl = classificar_sancao(sancao.get("categoria"), sancao.get("fundamentacao"),
                            sancao.get("cadastro"))
    decl = abrangencia_declarada(sancao.get("abrangencia"))
    if decl and cl["veda_contratacao"]:
        teto = teto_legal(sancao.get("fundamentacao"))
        if teto and _TIER[decl] > _TIER[teto]:
            decl = teto        # a declaração só estreita o alcance que a lei dá; nunca o alarga
        cl = {**cl, "abrangencia": decl}
    if cl["veda_contratacao"]:
        # lei especial: o teto vale com ou sem declaração; improbidade pós-2021 só quando o CEIS NÃO declara
        # (declaração de "todas as esferas" ali pode ser a decisão que o §4º admite)
        teto_e, _mot = teto_por_lei_especial(sancao.get("fundamentacao"), sancao.get("data_inicio"))
        if teto_e and not (decl and "8429" in _norm(sancao.get("fundamentacao"))):
            if _TIER.get(cl["abrangencia"], 0) > _TIER[teto_e]:
                cl = {**cl, "abrangencia": teto_e, "tipo": "impedimento" if teto_e == "ente" else "suspensao"}
                if decl:
                    decl = teto_e
    esf_decl = _norm(sancao.get("esfera_sancionador")).strip()
    if decl == "ente_poder":
        ente = ente_do_orgao(sancao.get("orgao"), sancao.get("uf"))
        esfera = esf_decl if esf_decl in ("federal", "estadual", "municipal") else ente["esfera"]
        uf = (sancao.get("uf") or "").strip().upper() or None
        poder = poder_do_orgao(sancao.get("orgao"))
        veda = (esfera == esfera_alvo and (esfera_alvo == "federal" or uf in (uf_alvo, None))
                and poder == poder_alvo)
        return {"veda": veda, "abrangencia": "ente_poder", "tipo": cl["tipo"], "esfera_sancionador": esfera,
                "uf_sancionador": uf,
                "motivo": (f"{cl['tipo']} na esfera e no poder do sancionador ({esfera}/{poder})"
                           + (" — alcança o alvo" if veda else " — NÃO alcança o alvo"))}
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
    if esf_decl in ("federal", "estadual", "municipal"):
        ente = {"esfera": esf_decl, "uf": None if esf_decl == "federal" else ente["uf"]}
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
            "SELECT cadastro, categoria, orgao, uf, data_inicio, data_fim, fundamentacao, processo, "
            f"{sql_campos_ceis(con)} FROM sancoes_federais WHERE cpf_cnpj=? ORDER BY data_inicio DESC", (cnpj,)):
        s = dict(r)
        v = veda_ente(s, esfera_alvo, uf_alvo)
        cl = classificar_sancao(s["categoria"], s["fundamentacao"], s["cadastro"])
        veda_alvo = veda_alvo or v["veda"]
        linhas.append({
            "cadastro": s["cadastro"], "tipo": cl["tipo"], "rotulo": cl["rotulo"],
            "abrangencia": v.get("abrangencia") or cl["abrangencia"], "orgao": s["orgao"], "uf": s["uf"],
            "abrangencia_declarada": s.get("abrangencia"),
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
