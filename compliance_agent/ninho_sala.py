# -*- coding: utf-8 -*-
"""Ninho de fachada pela SALA, não pelo prédio — e por CONJUNTO de fatores, não por um só.

Pedido do dono (25/07/2026): *"essa coisa de ninho empresarial não sei se faz tanto sentido.
na realidade queremos saber se existem na mesma SALA por exemplo. é um conjunto de fatores
que faz uma empresa ser de fachada"*. Ele está certo nos dois pontos, e a medição confirma.

**Por que o prédio não serve.** `hub_compartilhado` agrupa por `endereco_norm`, que é
logradouro + número + bairro + CEP — o **complemento fica de fora**. Medido sobre os
endereços onde alguém recebe OB:

    por PRÉDIO : 844 grupos com 2+ recebendo. No topo, "AV. PRES. ANTONIO CARLOS 375"
                 (3 de 13 CNPJs, R$ 7,2 bi) e "RUA DA ASSEMBLEIA 10" com 318 CNPJs.
                 São edifícios comerciais conhecidos do Centro do Rio. Não é ninho.
    por SALA   : 120 grupos. No topo, "RUA MEXICO 11 · SALA 401" — 2 CNPJs, e os DOIS
                 recebendo. **Essa** é a assinatura de interposição.

**Duas armadilhas do complemento**, ambas medidas no dump:
  · genérico não identifica unidade — 226 mil estabelecimentos dizem só `CASA`, 135 mil só
    `LOJA`, mais `FUNDOS`/`PARTE`/`TERREO`. Exigir um DÍGITO descarta todos eles;
  · **escritório virtual**: "VISCONDE DE PIRAJA 414 · SAL 718" tem **3.183 CNPJs** e
    "RUA CONCEICAO 37 · SALA 104" tem 386. Sala física não abriga dezenas de empresas.

**Por que não é uma consulta SQL.** Agrupar por `endereco_norm || complemento` não usa o
índice e vira varredura de 6,17 milhões de linhas — medido, **>15 min**, morto duas vezes.
Aqui o caminho é outro e barato: parte-se dos ~74 mil CNPJs que RECEBEM OB (a única coisa
que interessa), resolve-se o endereço de cada um por **chave primária** (0 ms), e só então
se lê quem mais mora nesses ~12,8 mil endereços — aí sim pelo índice `idx_estab_endereco_norm`.

**Conjunto de fatores.** Um sinal isolado não faz fachada. Cada grupo recebe os fatores que
de fato ocorrem, e o veredito exige ACÚMULO — nunca um só. Fator ausente é `INDISPONÍVEL`,
que não conta a favor nem contra (regra da casa). Indício ≠ acusação.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_DB_RECEITA = _REPO / "data" / "receita_estab.db"

# complemento que NÃO identifica unidade (contagem real no dump ao lado)
_COMPL_GENERICO = {
    "", "CASA", "LOJA", "FUNDOS", "PARTE", "TERREO", "TERREA", "SOBRADO", "GALPAO",
    "SALA", "APT", "APTO", "CONJ", "ANDAR", "SL", "AP", "LJ", "QUADRA", "LOTE",
    "FRENTE", "ANEXO", "PREDIO", "EDIFICIO", "BLOCO", "SN", "S N",
}
# acima disto, "sala" é caixa postal / domiciliação de CNPJ, não sala compartilhada.
# Calibrado contra o dump: os escritórios virtuais aparecem com 386 e 3.183 CNPJs — duas
# ordens de grandeza acima. 10 é folgado para um conjunto com matriz e filiais.
SALA_MASSA = 10
MIN_RECEBEM = 2          # 1 recebedor não é ninho: é fornecedor com vizinhos


def norm_complemento(c: str | None) -> str:
    """Complemento normalizado, ou `''` quando não identifica uma unidade."""
    s = re.sub(r"[^A-Z0-9 ]", " ", (c or "").upper())
    s = re.sub(r"\s+", " ", s).strip()
    if s in _COMPL_GENERICO or not s:
        return ""
    # sem dígito e sem letra isolada de unidade ('LOJA A'), não discrimina nada
    return s if re.search(r"\d", s) or re.search(r"\b[A-Z]\b", s) else ""


def _fatores(cnpjs: list[dict], recebem: dict[str, float]) -> tuple[list[str], list[str]]:
    """Fatores PRESENTES e fatores INDISPONÍVEIS do grupo. Nunca inventa ausência."""
    tem, indisp = [], []
    n = len(cnpjs)
    n_rec = sum(1 for c in cnpjs if c["cnpj"] in recebem)
    if n_rec >= MIN_RECEBEM:
        tem.append(f"{n_rec} dos {n} CNPJs da sala recebem dinheiro público")
    # situação cadastral: maioria não-ativa é casca
    sits = [(c["situacao_cadastral"] or "").upper() for c in cnpjs]
    if any(sits):
        mortas = sum(1 for s in sits if s and s != "ATIVA")
        if mortas and mortas >= n / 2:
            tem.append(f"{mortas} dos {n} estão BAIXADA/INAPTA/SUSPENSA na Receita")
    else:
        indisp.append("situação cadastral")
    # raízes distintas: matriz+filiais de um grupo só não é ninho
    raizes = {c["cnpj"][:8] for c in cnpjs if c["cnpj"]}
    if len(raizes) == 1 and n > 1:
        return [], ["mesma raiz de CNPJ (matriz+filiais) — grupo próprio, não ninho"]
    # nascidas juntas: fachadas costumam ser abertas em lote
    anos = [str(c["data_inicio_atividade"] or "")[:4] for c in cnpjs]
    anos = [a for a in anos if a.isdigit()]
    if len(anos) >= 2:
        if len(set(anos)) == 1:
            tem.append(f"todas abertas no mesmo ano ({anos[0]}) — abertura em lote")
    else:
        indisp.append("data de abertura")
    # mesmo telefone além do mesmo endereço = âncora dupla
    tels = {(c["telefone1"] or "").strip() for c in cnpjs if (c["telefone1"] or "").strip()}
    if len(tels) == 1 and n > 1:
        tem.append("dividem também o MESMO telefone")
    elif not tels:
        indisp.append("telefone")
    # setores muito diferentes na mesma sala é sinal de casca (CNAE de 2 dígitos)
    setores = {str(c["cnae_principal"] or "")[:2] for c in cnpjs if c["cnae_principal"]}
    if len(setores) >= max(3, n - 1):
        tem.append(f"{len(setores)} setores econômicos diferentes na mesma sala")
    return tem, indisp


def ninhos_por_sala(db_path: str | None = None, receita_path: str | None = None,
                    min_cnpjs: int = 2, limite: int = 120) -> dict:
    """Grupos de CNPJs na MESMA SALA em que mais de um recebe dinheiro público.

    Retorna ``{ok, grupos, n, explicacao, ressalva}``. `INDISPONÍVEL` (dump ausente) devolve
    ``ok=False`` com o motivo — nunca lista vazia fingindo "não há ninho".
    """
    dbp = Path(db_path) if db_path else _DB
    rec = Path(receita_path) if receita_path else _DB_RECEITA
    if not rec.exists():
        return {"ok": False, "erro": f"dump da Receita ausente ({rec}) — rodar "
                                     "ingest_estabelecimentos; INDISPONÍVEL ≠ ausência de ninho"}
    con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    rc = sqlite3.connect(f"file:{rec}?mode=ro", uri=True); rc.row_factory = sqlite3.Row
    try:
        recebem = {r["favorecido_cpf"]: (r["total_pago"] or 0.0)
                   for r in con.execute("SELECT favorecido_cpf, total_pago FROM favorecido_resumo "
                                        "WHERE total_pago > 0 AND length(favorecido_cpf)=14")}
        if not recebem:
            return {"ok": False, "erro": "favorecido_resumo vazio — sem materialidade para cruzar"}
        # 1) endereço de quem RECEBE — lookup por CHAVE PRIMÁRIA, partindo do lado PEQUENO.
        # Tentei trocar isto por uma junção SQL com tabela temporária achando que 74 mil
        # ida-e-volta fossem o gargalo: ficou **148,7 s contra 15,8 s**, dez vezes pior. O
        # SQLite dirigiu a junção pelos 6,17 milhões de estabelecimentos em vez dos 74 mil
        # recebedores. Medido, revertido, e registrado para ninguém "otimizar" de novo.
        enderecos: set[str] = set()
        for cnpj_ob in recebem:
            r = rc.execute("SELECT endereco_norm FROM estabelecimentos WHERE cnpj=?",
                           (cnpj_ob,)).fetchone()
            if r and (r["endereco_norm"] or "").strip():
                enderecos.add(r["endereco_norm"])
        # 2) quem mais mora nesses endereços — agora sim pelo índice de endereço
        salas: dict[tuple, list] = {}
        for end in enderecos:
            for r in rc.execute(
                    "SELECT cnpj, complemento, situacao_cadastral, data_inicio_atividade, "
                    "       telefone1, cnae_principal, nome_fantasia "
                    "FROM estabelecimentos WHERE endereco_norm=?", (end,)):
                compl = norm_complemento(r["complemento"])
                if compl:
                    salas.setdefault((end, compl), []).append(dict(r))
        # 3) veredito por CONJUNTO de fatores
        grupos = []
        for (end, compl), membros in salas.items():
            if len(membros) < min_cnpjs:
                continue
            n_rec = sum(1 for m in membros if m["cnpj"] in recebem)
            if n_rec < MIN_RECEBEM:
                continue                       # 1 recebedor = fornecedor com vizinhos
            if len(membros) > SALA_MASSA:
                continue                       # escritório virtual, não sala
            tem, indisp = _fatores(membros, recebem)
            if not tem:
                continue
            total = round(sum(recebem.get(m["cnpj"], 0.0) for m in membros), 2)
            grupos.append({
                "sala": f"{end} · {compl}", "endereco": end, "complemento": compl,
                "n_cnpjs": len(membros), "n_recebem_ob": n_rec, "total_recebido_ob": total,
                "cnpjs": [m["cnpj"] for m in membros][:20],
                "fatores": tem, "indisponivel": indisp,
                # o veredito é o ACÚMULO — nunca um fator só
                "grau": "alto" if len(tem) >= 3 else ("medio" if len(tem) == 2 else "baixo"),
            })
        grupos.sort(key=lambda g: (-len(g["fatores"]), -g["total_recebido_ob"]))
        return {
            "ok": True, "grupos": grupos[:limite], "n": len(grupos),
            "n_alto": sum(1 for g in grupos if g["grau"] == "alto"),
            "total_recebido_ob": round(sum(g["total_recebido_ob"] for g in grupos), 2),
            "explicacao": (
                "CNPJs que dividem a MESMA SALA (endereço + complemento), em que mais de um "
                "recebe dinheiro público. Dividir o prédio não diz nada — 'Rua da Assembleia 10' "
                "tem 318 CNPJs e é um edifício comercial; dividir a SALA, com dois recebendo, é "
                "a assinatura de interposição. O grau vem do ACÚMULO de fatores (situação "
                "cadastral, abertura em lote, telefone comum, setores díspares), nunca de um só."),
            "ressalva": (
                "Indício ≠ acusação. Dividir sala é lícito e comum entre empresas do mesmo dono "
                "ou de sócios conhecidos. Escritório virtual (>%d CNPJs na mesma sala) e "
                "matriz+filiais da mesma raiz são excluídos por construção. Fator que a base não "
                "traz aparece em `indisponivel` e NÃO conta contra — INDISPONÍVEL ≠ irregular."
                % SALA_MASSA),
        }
    finally:
        con.close(); rc.close()
