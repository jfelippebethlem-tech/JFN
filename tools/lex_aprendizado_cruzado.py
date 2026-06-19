#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lex_aprendizado_cruzado — INTELIGÊNCIA PROGRESSIVA CROSS-FORNECEDOR (custo LLM = 0).

O padrão de fraude de UM fornecedor informa a análise de OUTRO ligado a ele (mesmos sócios/veículos).
Este módulo destila — por SQL puro sobre tabelas que o sweep já popula — um bloco markdown BOUNDED com o
que já foi APRENDIDO (vereditos persistidos) sobre os fornecedores IRMÃOS do alvo, para corroborar/contrastar
o raciocínio do LLM SEM uma 2ª chamada de modelo.

Duas funções PURAS, ambas degradam honesto para '' (erro/sem-irmão/INDISPONÍVEL):

  aprendizado_cruzado(cnpj, con, *, max_irmaos=5, max_chars=900)
      (a) rede_fachada.sinal_rede(cnpj) → CNPJs irmãos (compartilhados + outros_veiculos);
      (b) p/ cada irmão lê o veredito JÁ persistido (sei_direcionamento_llm.parecer_fornecedor +
          lex_pesquisa_internet.parecer_pesquisa);
      (c) bloco markdown bounded: razão + grau + resumo curto + 1 fonte por irmão.

  padroes_por_tipologia(tags, min_confianca=0.6, max_itens=4)
      lê memoria.lembrar('padrao_fraude'), filtra por tags, devolve bloco bounded — cobre o fornecedor
      SEM irmão direto (a tipologia aprendida em outros casos ainda informa este).

HONESTO (cláusula JFN): indício a verificar, NUNCA acusação (presunção de legitimidade). INDISPONÍVEL ≠ 0.
Filtra fornecedor UBÍQUO (utilities/bancos, footprint largo) reusando o mesmo teto de grafo_cartel/
lex_base_empirica — senão o bloco explode e a co-ocorrência vira ruído. NUNCA concatena achados crus.
"""
from __future__ import annotations

import re
import sqlite3

# teto de footprint p/ descartar fornecedor ubíquo (mesma régua de grafo_cartel.vizinhanca_cartel:
# >max_ubiquidade órgãos = utilities/bancos/telefonia, co-ocorrência espúria). Conservador.
_MAX_UBIQUIDADE = 40


def _norm(c: str) -> str:
    return re.sub(r"\D", "", c or "")


def _ubiquo(con: sqlite3.Connection, raiz8: str) -> bool:
    """True se a raiz é de um fornecedor ubíquo (atua em > _MAX_UBIQUIDADE UGs) — filtro anti-ruído.
    Honesto/barato: 1 query bounded; tabela ausente → False (não filtra, mas o bloco já é limitado)."""
    try:
        n = con.execute(
            "SELECT COUNT(DISTINCT ug_codigo) FROM ordens_bancarias "
            "WHERE substr(favorecido_cpf,1,8)=? AND valor>0", (raiz8,)).fetchone()
    except sqlite3.Error:
        return False
    return bool(n and n[0] and n[0] > _MAX_UBIQUIDADE)


def _cnpj_pleno_da_raiz(con: sqlite3.Connection, raiz8: str) -> str:
    """Resolve uma raiz de 8 dígitos p/ um CNPJ pleno (14) representativo — os pareceres persistidos são
    chaveados por CNPJ completo. Prefere quem já tem parecer; senão o maior recebedor da raiz. '' se nada."""
    raiz8 = _norm(raiz8)[:8]
    if len(raiz8) < 8:
        return ""
    # 1) já existe parecer de direcionamento p/ algum CNPJ desta raiz?
    for tabela, col in (("sei_direcionamento", "fornecedor_cnpj"), ("lex_pesquisa", "fornecedor_cnpj")):
        try:
            if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                               (tabela,)).fetchone():
                continue
            row = con.execute(
                f"SELECT {col} FROM {tabela} WHERE "
                f"substr(replace(replace(replace({col},'.',''),'/',''),'-',''),1,8)=? LIMIT 1",
                (raiz8,)).fetchone()
            if row and row[0]:
                return _norm(row[0])
        except sqlite3.Error:
            continue
    # 2) senão, o CNPJ pleno mais relevante da raiz nas OBs
    try:
        row = con.execute(
            "SELECT favorecido_cpf FROM ordens_bancarias WHERE substr(favorecido_cpf,1,8)=? "
            "AND length(favorecido_cpf)=14 AND valor>0 GROUP BY favorecido_cpf "
            "ORDER BY SUM(valor) DESC LIMIT 1", (raiz8,)).fetchone()
        if row and row[0]:
            return _norm(row[0])
    except sqlite3.Error:
        pass
    return ""


def _coletar_irmaos(rede: dict) -> list[dict]:
    """Extrai os CNPJs IRMÃOS (raiz 8 díg) da saída de sinal_rede, dedup, marcando fornecedor_nosso quando
    o campo existir (outros_veiculos traz; compartilhados não traz → fornecedor_nosso=None, honesto)."""
    irmaos: dict[str, dict] = {}

    def _put(raiz8: str, razao: str, via: str, fornecedor_nosso):
        r = _norm(raiz8)[:8]
        if len(r) < 8 or r in irmaos:
            return
        irmaos[r] = {"raiz": r, "razao": (razao or "").strip(), "via": via,
                     "fornecedor_nosso": fornecedor_nosso}

    # compartilhados[].outros_cnpjs = raízes (sem flag fornecedor_nosso → None)
    for c in (rede.get("compartilhados") or []):
        for raiz in (c.get("outros_cnpjs") or []):
            _put(raiz, "", "sócio compartilhado", None)
    # outros_veiculos[].veiculos[] = {cnpj_basico, razao, fornecedor_nosso}
    for v in (rede.get("outros_veiculos") or []):
        for o in (v.get("veiculos") or []):
            _put(o.get("cnpj_basico"), o.get("razao"), "outro veículo do administrador",
                 o.get("fornecedor_nosso"))
    return list(irmaos.values())


def _veredito_irmao(cnpj_pleno: str) -> dict | None:
    """Lê o veredito JÁ persistido (NENHUM LLM) p/ um irmão: direcionamento (grau+resumo) e/ou
    pesquisa-internet (1 achado 'agrava' + 1 fonte). None se não há nada relevante persistido."""
    grau = resumo = nome = fonte = ""
    agrava = ""
    try:
        from tools.sei_direcionamento_llm import parecer_fornecedor
        p = parecer_fornecedor(cnpj_pleno)
    except Exception:  # noqa: BLE001
        p = None
    if p:
        nome = p.get("nome") or nome
        grau = str(p.get("grau") or "").strip()
        resumo = str(p.get("resumo") or "").strip()
    try:
        from tools.lex_pesquisa_internet import parecer_pesquisa
        q = parecer_pesquisa(cnpj_pleno)
    except Exception:  # noqa: BLE001
        q = None
    if q:
        nome = nome or (q.get("nome") or "")
        for a in (q.get("achados") or []):
            if str(a.get("veredito") or "").lower() == "agrava":
                agrava = str(a.get("duvida") or a.get("nota") or "").strip()
                for f in (a.get("fontes") or []):
                    if f:
                        fonte = str(f).strip()
                        break
                break
        if not resumo and (q.get("resumo") or "").strip():
            resumo = str(q["resumo"]).strip()
    # só vale como "aprendizado" se houver grau de risco OU um achado que agrava
    grau_l = grau.lower()
    tem_risco = any(t in grau_l for t in ("amarelo", "vermelho", "alto", "medio", "média", "media"))
    if not (tem_risco or agrava):
        return None
    return {"nome": nome, "grau": grau, "resumo": resumo, "agrava": agrava, "fonte": fonte}


def aprendizado_cruzado(cnpj: str, con: sqlite3.Connection, *,
                        max_irmaos: int = 5, max_chars: int = 900) -> str:
    """Bloco markdown BOUNDED com o que já foi aprendido sobre os fornecedores IRMÃOS (mesmos sócios/
    veículos) do alvo. PURO, custo LLM 0, honesto ('' em erro/sem-irmão). NUNCA concatena achados crus —
    só razão + grau + resumo curto + 1 fonte por irmão; filtra ubíquo; teto duro de itens e chars."""
    cd = _norm(cnpj)
    if len(cd) < 8:
        return ""
    raiz_alvo = cd[:8]
    try:
        from compliance_agent.rede_fachada import sinal_rede
        rede = sinal_rede(cd)
    except Exception:  # noqa: BLE001 — sem rede = sem aprendizado cruzado, honesto
        return ""
    if not rede or not rede.get("qsa"):
        return ""
    irmaos = [i for i in _coletar_irmaos(rede) if i["raiz"] != raiz_alvo]
    if not irmaos:
        return ""

    linhas: list[str] = []
    usados = 0
    for irmao in irmaos:
        if usados >= max_irmaos:
            break
        if _ubiquo(con, irmao["raiz"]):
            continue  # utilities/bancos: co-ocorrência espúria, não é "irmão" significativo
        pleno = _cnpj_pleno_da_raiz(con, irmao["raiz"])
        if not pleno:
            continue
        if _norm(pleno)[:8] == raiz_alvo:
            continue
        ver = _veredito_irmao(pleno)
        if not ver:
            continue  # sem veredito persistido relevante = nada aprendido sobre este irmão
        nome = (ver.get("nome") or irmao.get("razao") or irmao["raiz"] + "…").strip()
        grau = (ver.get("grau") or "—").upper()
        # resumo curto: prioriza o achado que agrava; senão o resumo do parecer
        nucleo = (ver.get("agrava") or ver.get("resumo") or "").strip()
        nucleo = re.sub(r"\s+", " ", nucleo)[:160]
        item = f"- **{nome}** (irmão via {irmao['via']}; grau {grau}) — {nucleo or 'indício registrado'}"
        if ver.get("fonte"):
            item += f" [fonte: {str(ver['fonte'])[:90]}]"
        # respeita o teto de chars GLOBAL (não estoura mesmo no último item)
        if sum(len(x) + 1 for x in linhas) + len(item) + 1 > max_chars and linhas:
            break
        linhas.append(item)
        usados += 1

    if not linhas:
        return ""
    bloco = "\n".join(linhas)
    return bloco[:max_chars].rstrip()


# ───────────────────────── tipologia (cobre fornecedor SEM irmão direto) ─────────────────────────

# rótulo legível por tag de tipologia (as mesmas tags do typology store de lex_feedback.coletar_auto)
_ROTULO_TAG = {
    "fachada": "empresa de fachada",
    "laranja_socio_compartilhado": "laranja / sócio compartilhado",
    "concorrencia_ficticia": "concorrência fictícia (rodízio/cartel)",
    "exigencia_restritiva": "exigência restritiva (direcionamento)",
    "fracionamento": "fracionamento de despesa",
    "sobrepreco": "sobrepreço",
}


def padroes_por_tipologia(tags, min_confianca: float = 0.6, max_itens: int = 4,
                          *, max_chars: int = 900) -> str:
    """Bloco markdown BOUNDED com os PADRÕES de fraude já aprendidos (memoria 'padrao_fraude') das tipologias
    em `tags` — cobre o fornecedor que NÃO tem irmão direto, mas cuja tipologia já foi vista. PURO, custo
    LLM 0, honesto ('' se nada). Confiança = indício interno acumulado, não prova."""
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t).strip().lower() for t in (tags or []) if str(t).strip()]
    if not tags:
        return ""
    try:
        from compliance_agent.llm import memoria
        itens = memoria.lembrar("padrao_fraude", min_confianca=min_confianca)
    except Exception:  # noqa: BLE001
        return ""
    if not itens:
        return ""
    linhas: list[str] = []
    vistos: set[str] = set()
    for m in itens:
        if len(linhas) >= max_itens:
            break
        chave = str(m.get("chave") or "").lower()
        if not any(t in chave for t in tags):
            continue
        if chave in vistos:
            continue
        vistos.add(chave)
        rotulo = next((_ROTULO_TAG[t] for t in tags if t in chave and t in _ROTULO_TAG), chave or "padrão")
        conf = m.get("confianca")
        valor = re.sub(r"\s+", " ", str(m.get("valor") or "")).strip()[:180]
        cab = f"- **{rotulo}**"
        if conf is not None:
            cab += f" (conf {conf:.1f}, n={m.get('n_observacoes', '?')})"
        item = f"{cab}: {valor or 'padrão registrado'}"
        if sum(len(x) + 1 for x in linhas) + len(item) + 1 > max_chars and linhas:
            break
        linhas.append(item)
    if not linhas:
        return ""
    return "\n".join(linhas)[:max_chars].rstrip()


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Aprendizado cruzado (cross-fornecedor) — bloco bounded p/ um CNPJ")
    ap.add_argument("cnpj")
    ap.add_argument("--tags", nargs="*", default=[], help="tipologias p/ padroes_por_tipologia")
    a = ap.parse_args()
    db = Path(__file__).resolve().parents[1] / "data" / "compliance.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
    try:
        print("=== APRENDIZADO CRUZADO (irmãos) ===")
        print(aprendizado_cruzado(a.cnpj, con) or "(vazio)")
        if a.tags:
            print("\n=== PADRÕES POR TIPOLOGIA ===")
            print(padroes_por_tipologia(a.tags) or "(vazio)")
    finally:
        con.close()
