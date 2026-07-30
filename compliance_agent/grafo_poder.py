# -*- coding: utf-8 -*-
"""Grafo de Poder — JFN 2.0, Onda 4. Une sócios+OB+doações+folha+co-endereço num grafo único.

Constrói a vizinhança de um alvo por EXPANSÃO LOCAL (BFS limitado em saltos e fanout) —
não carrega o grafo inteiro (1,1M OBs) em memória. Arestas vêm das tabelas reais:
  cnpj —[socio]→ pessoa (QSA, socios_fornecedor)
  cnpj —[pago_por]→ ug (ordens_bancarias)
  pessoa —[doou]→ candidato (doacoes_eleitorais)
  cnpj —[co_endereco]→ cnpj (endereco_fornecedor)
  pessoa —[servidor]→ ug (registros_folha)

CADA ARESTA DE VÍNCULO CARREGA FORÇA (2026-07-29). Antes não carregava, e o efeito era medido:
sócio ligado por NOME puro valia o mesmo que sócio ligado por documento, e co-endereço não separava
sala de prédio — **76% das arestas de co-endereço do acervo são de prédio** (435 de 570), e valiam
0,75 quando valem 0,05. Sobrepeso de 15× em três quartos das arestas.

A régua é a de `osint/vinculos.TIPOS_ARESTA`, calibrada nas lições que a casa pagou (por prédio, o
topo do acervo é um endereço com 318 CNPJs; por sala, o mesmo dado dá grupos que significam algo).
Ela existia e não estava aqui — que é justamente onde o usuário olha o grafo.

`pago_por` NÃO recebe força: pagamento é FATO (a Ordem Bancária existe), não inferência de
proximidade. Dar-lhe força de vínculo misturaria duas coisas e inflaria o grau de qualquer
fornecedor grande.

Honestidade: vínculo é INDÍCIO de relação (presunção de legitimidade); CPF mascarado (LGPD).
"""
from __future__ import annotations

import re
import sqlite3
from compliance_agent.database.models import _resolver_db
from compliance_agent.osint.vinculos import TIPOS_ARESTA, classificar_endereco

_FANOUT = 12  # teto de vizinhos por nó (evita explosão em UG/sócio de alto grau)

# Relações que são FATO registrado, não inferência de proximidade — não recebem força de aresta.
_RELACOES_FACTUAIS = ("pago_por",)

# Como cada relação do grafo se traduz na régua fechada de `osint/vinculos`.
_REL_PARA_TIPO = {"doou": "doou_para", "servidor": "servidor_de"}


def forca_da_relacao(rel: str) -> tuple[float | None, str | None]:
    """`(forca, tipo_calibrado)` de uma relação simples. `(None, None)` para relação factual."""
    if rel in _RELACOES_FACTUAIS:
        return None, None
    tipo = _REL_PARA_TIPO.get(rel, rel)
    t = TIPOS_ARESTA.get(tipo)
    return (t.forca, t.id) if t else (None, None)


def calibrar_socio(doc_resolvido: str = "", doc_mascarado: str = "") -> tuple[str, float, str]:
    """Gradua a aresta de sócio pelo QUANTO a pessoa está identificada — três graus.

    O grau do meio é o que mais aparece: a Receita mascara o CPF de todo sócio, e 94,9% dos vínculos
    do acervo (29.837 de 31.449) só têm nome + seis dígitos centrais. Tratar isso como documento
    pleno inflaria; tratar como nome puro jogaria fora informação real.
    """
    if (doc_resolvido or "").strip():
        t = TIPOS_ARESTA["mesmo_socio"]
        return t.id, t.forca, ""
    if (doc_mascarado or "").strip():
        t = TIPOS_ARESTA["mesmo_socio_doc_parcial"]
        return t.id, t.forca, t.exculpatoria
    t = TIPOS_ARESTA["nome_igual_sem_documento"]
    return t.id, t.forca, t.exculpatoria


def calibrar_endereco(endereco: str, complemento: str = "") -> tuple[str, float, str]:
    """`mesma_sala` (0,75) × `mesmo_predio` (0,05) — a diferença de 15× que faltava aqui.

    Delega a `osint/vinculos.classificar_endereco`, que também trata endereço de natureza
    compartilhada (coworking, escritório virtual, caixa postal) como prédio mesmo havendo sala.
    """
    tipo, obs = classificar_endereco(endereco or "", complemento or "")
    t = TIPOS_ARESTA[tipo]
    return t.id, t.forca, "; ".join(obs) or t.exculpatoria


def _con() -> sqlite3.Connection:
    return sqlite3.connect(str(_resolver_db()))


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm_nome(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").upper()).strip()


def _resolver_alvo(con, alvo: str) -> str | None:
    """Resolve o alvo num node-id: 'cnpj:<14>' | 'socio:<nome>' | 'cand:<nome>' | 'ug:<cod>'."""
    d = _digits(alvo)
    if len(d) == 14:
        # só é nó se o CNPJ aparece em alguma fonte (senão = fora do universo de dados)
        existe = con.execute(
            "SELECT 1 FROM socios_fornecedor WHERE cnpj=? LIMIT 1", (d,)).fetchone() or \
            con.execute(
                "SELECT 1 FROM ordens_bancarias WHERE "
                "REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')=? LIMIT 1",
                (d,)).fetchone()
        return f"cnpj:{d}" if existe else None
    if d and len(d) in (6, 7) and con.execute(
            "SELECT 1 FROM ordens_bancarias WHERE ug_codigo=? LIMIT 1", (d,)).fetchone():
        return f"ug:{d}"
    nome = _norm_nome(alvo)
    # empresa por nome?
    row = con.execute(
        "SELECT favorecido_cpf FROM ordens_bancarias WHERE UPPER(favorecido_nome) LIKE ? "
        "AND LENGTH(REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-',''))=14 LIMIT 1",
        (f"%{nome}%",)).fetchone()
    if row:
        return f"cnpj:{_digits(row[0])}"
    # candidato?
    if con.execute("SELECT 1 FROM doacoes_eleitorais WHERE UPPER(nome_candidato) LIKE ? LIMIT 1",
                   (f"%{nome}%",)).fetchone():
        return f"cand:{nome}"
    # sócio/doador por nome
    if con.execute("SELECT 1 FROM socios_fornecedor WHERE socio_nome_norm LIKE ? LIMIT 1",
                   (f"%{nome}%",)).fetchone():
        return f"socio:{nome}"
    return None


def _expandir(con, node: str, so_contrato: bool) -> list[tuple]:
    """Vizinhos de um nó: [(vizinho_id, tipo_aresta, attrs_no)]. Limitado a _FANOUT por classe."""
    tipo, _, val = node.partition(":")
    out: list[tuple] = []

    if tipo == "cnpj":
        cnpj = val
        # UGs que pagaram (pago_por)
        for ug, ugn, tot in con.execute(
                "SELECT ug_codigo, MAX(ug_nome), SUM(valor) FROM ordens_bancarias "
                "WHERE REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')=? "
                "GROUP BY ug_codigo ORDER BY SUM(valor) DESC LIMIT ?", (cnpj, _FANOUT)):
            # nome CANÔNICO da UG (ITERJ p/ 133100), consistente com /relatorio e /orgao — não o
            # ug_nome cru da OB (que às vezes traz o órgão superior). Fallback ao nome cru.
            from compliance_agent import ugs as _ugs
            _lbl = _ugs.nome_canonico(str(ug), fallback="") or ugn or str(ug)
            out.append((f"ug:{ug}", "pago_por", {"label": _lbl, "total_ob": round(tot or 0, 2)}))
        if so_contrato:
            return out
        # sócios (QSA) — força graduada pelo quanto a pessoa está identificada
        for nome, doc, doc_res in con.execute(
                "SELECT socio_nome_norm, socio_doc, cpf_resolvido FROM socios_fornecedor "
                "WHERE cnpj=? LIMIT ?", (cnpj, _FANOUT)):
            if nome:
                tipo, forca, obs = calibrar_socio(doc_res or "", doc or "")
                out.append((f"socio:{nome}", "socio",
                            {"label": nome, "doc": doc, "forca": forca,
                             "tipo_calibrado": tipo, "ressalva": obs}))
        # co-endereço — sala (0,75) × prédio (0,05); 76% do acervo é prédio
        for c2, end2 in con.execute(
                "SELECT b.cnpj, b.endereco FROM endereco_fornecedor a JOIN endereco_fornecedor b "
                "ON a.endereco_norm=b.endereco_norm AND a.cnpj<>b.cnpj WHERE a.cnpj=? LIMIT ?",
                (cnpj, _FANOUT)):
            tipo, forca, obs = calibrar_endereco(end2 or "")
            out.append((f"cnpj:{_digits(c2)}", "co_endereco",
                        {"label": c2, "endereco": end2, "forca": forca,
                         "tipo_calibrado": tipo, "ressalva": obs}))

    elif tipo == "socio":
        nome = val
        # outras empresas do mesmo sócio — MESMA graduação: por nome puro isto vale 0,10
        for c2, doc, doc_res in con.execute(
                "SELECT cnpj, MAX(socio_doc), MAX(cpf_resolvido) FROM socios_fornecedor "
                "WHERE socio_nome_norm=? GROUP BY cnpj LIMIT ?", (nome, _FANOUT)):
            tipo, forca, obs = calibrar_socio(doc_res or "", doc or "")
            out.append((f"cnpj:{_digits(c2)}", "socio",
                        {"label": c2, "forca": forca, "tipo_calibrado": tipo, "ressalva": obs}))
        if so_contrato:
            return out
        # doações que esse nome fez
        for cand, partido, val_d in con.execute(
                "SELECT nome_candidato, MAX(partido), SUM(valor) FROM doacoes_eleitorais "
                "WHERE UPPER(nome_doador)=? GROUP BY nome_candidato ORDER BY SUM(valor) DESC LIMIT ?",
                (nome, _FANOUT)):
            _f, _t = forca_da_relacao("doou")
            out.append((f"cand:{_norm_nome(cand)}", "doou",
                        {"label": cand, "partido": partido, "valor": round(val_d or 0, 2),
                         "forca": _f, "tipo_calibrado": _t}))

    elif tipo == "ug":
        ug = val
        # top empresas pagas
        for cpf, nm, tot in con.execute(
                "SELECT favorecido_cpf, MAX(favorecido_nome), SUM(valor) FROM ordens_bancarias "
                "WHERE ug_codigo=? GROUP BY favorecido_cpf ORDER BY SUM(valor) DESC LIMIT ?",
                (ug, _FANOUT)):
            if len(_digits(cpf)) == 14:
                out.append((f"cnpj:{_digits(cpf)}", "pago_por",
                            {"label": nm, "total_ob": round(tot or 0, 2)}))

    elif tipo == "cand":
        nome = val
        # doadores do candidato
        for doador, doc, val_d in con.execute(
                "SELECT nome_doador, MAX(cpf_cnpj_doador), SUM(valor) FROM doacoes_eleitorais "
                "WHERE UPPER(nome_candidato) LIKE ? GROUP BY nome_doador ORDER BY SUM(valor) DESC LIMIT ?",
                (f"%{nome}%", _FANOUT)):
            d = _digits(doc)
            vid = f"cnpj:{d}" if len(d) == 14 else f"socio:{_norm_nome(doador)}"
            _f, _t = forca_da_relacao("doou")
            out.append((vid, "doou", {"label": doador, "valor": round(val_d or 0, 2),
                                      "forca": _f, "tipo_calibrado": _t}))

    return out


def vizinhanca(alvo: str, saltos: int = 2, so_contrato: bool = False) -> dict:
    """Subgrafo ao redor do alvo até `saltos` (BFS limitado). Retorna {ok, alvo, nos, arestas, n_nos}."""
    if not _resolver_db().exists():
        return {"ok": False, "erro": "compliance.db ausente"}
    saltos = max(1, min(int(saltos), 3))
    con = _con()
    try:
        raiz = _resolver_alvo(con, alvo)
        if not raiz:
            return {"ok": True, "alvo": alvo, "nos": [], "arestas": [],
                    "_nota": f"INDISPONÍVEL: alvo '{alvo}' não encontrado (CNPJ/UG/nome)."}
        nos: dict[str, dict] = {raiz: {"id": raiz, "tipo": raiz.split(":")[0], "salto": 0}}
        arestas: list[dict] = []
        vistas: set[tuple] = set()
        fronteira = [raiz]
        for nivel in range(1, saltos + 1):
            nova = []
            for node in fronteira:
                for viz, rel, attrs in _expandir(con, node, so_contrato):
                    if viz not in nos:
                        nos[viz] = {"id": viz, "tipo": viz.split(":")[0], "salto": nivel,
                                    "label": attrs.get("label")}
                        nova.append(viz)
                    chave = tuple(sorted([node, viz])) + (rel,)
                    if chave not in vistas:
                        vistas.add(chave)
                        arestas.append({"de": node, "para": viz, "rel": rel, **{
                            k: v for k, v in attrs.items() if k != "label"}})
            fronteira = nova
            if not fronteira:
                break
        return {"ok": True, "alvo": alvo, "raiz": raiz, "n_nos": len(nos),
                "nos": list(nos.values()), "arestas": arestas,
                "_fonte": "QSA + OB + TSE + folha + co-endereço (compliance.db)",
                "_regua": {
                    "o_que_e": ("Cada aresta de VÍNCULO traz `forca` (0-1) e `tipo_calibrado`. Força "
                                "é o quanto aquela aresta, SOZINHA, aproxima duas entidades."),
                    "graus": {tid: {"forca": tt.forca, "descricao": tt.descricao,
                                    "explicacao_inocente": tt.exculpatoria}
                              for tid, tt in TIPOS_ARESTA.items()
                              if tid in ("mesmo_socio", "mesmo_socio_doc_parcial",
                                         "nome_igual_sem_documento", "mesma_sala",
                                         "mesmo_predio", "doou_para")},
                    "pago_por": ("Sem força: pagamento é FATO registrado (a Ordem Bancária existe), "
                                 "não inferência de proximidade."),
                    "por_que_importa": ("76% das arestas de co-endereço do acervo são de PRÉDIO "
                                        "(435 de 570) e valem 0,05, não 0,75 — o topo do acervo por "
                                        "prédio é um endereço com 318 CNPJs. E só 3,8% dos vínculos "
                                        "de sócio têm CPF resolvido; 94,9% têm nome + máscara da "
                                        "Receita, cuja colisão medida é ~4%."),
                },
                "_nota": ("Vínculo = indício de relação (presunção de legitimidade); CPF mascarado "
                          "(LGPD). Caminho FORTE vale mais que caminho curto: para afirmar vínculo "
                          "numa peça, use `/api/osint/beneficiario_final`, que sobe a cadeia por "
                          "documento e devolve a confiança do trajeto.")}
    finally:
        con.close()


def comunidades(ug: str | None = None, limite: int = 20) -> dict:
    """Detecta comunidades (sócios/co-endereço comuns) entre fornecedores — reusa grafo_cartel/rede."""
    try:
        from compliance_agent import grafo_cartel
        base = grafo_cartel.captura_orgaos(limite=limite) if not ug else \
            grafo_cartel.vizinhanca_cartel(ug, limite=limite)
        return {"ok": True, "comunidades": base,
                "_nota": "Indício de cluster (sócio/endereço/órgão comum), não prova de cartel."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e)}
