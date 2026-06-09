"""
Análise de grafo de relacionamentos para detecção de redes de corrupção.

Constrói um grafo onde:
  Nós:  pessoas (CPF), empresas (CNPJ), unidades gestoras (UG)
  Arestas:
    - pessoa → empresa  (sócio / QSA)
    - UG → empresa      (OB paga, peso = valor)
    - pessoa → UG       (servidor lotado)
    - pessoa → pessoa   (nomeação DOERJ = relação política)

Detecta:
  1. Triângulos suspeitos: servidor → empresa ← UG onde servidor trabalha
     (servidor tem empresa que recebe da sua própria UG — nepotismo/desvio)
  2. Comunidades densas: clusters de pessoas e empresas com muitas conexões
     mútuas (redes organizadas)
  3. Intermediários-chave: empresas que conectam múltiplos órgãos e pessoas
     (laranja / hub de desvio)
  4. Evolução temporal: nova aresta UG→empresa logo após nova aresta pessoa→empresa
     (empresa aberta por servidor logo antes de receber contrato)
"""

import json
from datetime import date

import networkx as nx


def construir_grafo(session) -> nx.DiGraph:
    """
    Constrói o grafo completo a partir do banco de dados.
    Retorna DiGraph do networkx.
    """
    from compliance_agent.database.models import (
        EmpresaSocio, OrdemBancaria, RegistroFolha
    )

    G = nx.DiGraph()

    # ── Sócios de empresas ─────────────────────────────────────────────────
    for socio in session.query(EmpresaSocio).all():
        if socio.cpf_cnpj and socio.empresa_id:
            pessoa_node = f"PF:{socio.cpf_cnpj}"
            empresa_node = f"PJ:{socio.empresa_id}"
            G.add_node(pessoa_node, tipo="pessoa", nome=socio.nome or "")
            G.add_node(empresa_node, tipo="empresa", empresa_id=socio.empresa_id)
            G.add_edge(pessoa_node, empresa_node,
                       tipo="socio", qualificacao=socio.qualific or "")

    # ── Ordens Bancárias (UG → empresa, peso = valor) ──────────────────────
    for ob in session.query(OrdemBancaria).filter(
        OrdemBancaria.favorecido_cpf.isnot(None),
        OrdemBancaria.valor.isnot(None),
        OrdemBancaria.valor > 0,
    ).all():
        ug_node  = f"UG:{ob.ug_codigo}"
        fav_node = f"PJ:{ob.favorecido_cpf}" if ob.favorecido_cpf and len(ob.favorecido_cpf) == 14 \
                   else f"PF:{ob.favorecido_cpf}"
        G.add_node(ug_node, tipo="ug", codigo=ob.ug_codigo)
        G.add_node(fav_node, tipo="empresa" if ob.favorecido_cpf and len(ob.favorecido_cpf) == 14 else "pessoa",
                   nome=ob.favorecido_nome or "")

        if G.has_edge(ug_node, fav_node):
            G[ug_node][fav_node]["valor"] += (ob.valor or 0)
            G[ug_node][fav_node]["n_obs"] += 1
        else:
            G.add_edge(ug_node, fav_node, tipo="ob_paga",
                       valor=ob.valor or 0, n_obs=1,
                       data=str(ob.data_emissao))

    # ── Servidores lotados em UGs (via folha de pagamento) ─────────────────
    cpfs_vistos = set()
    for reg in session.query(RegistroFolha).filter(
        RegistroFolha.cpf.isnot(None),
        RegistroFolha.orgao_codigo.isnot(None),
    ).all():
        chave = (reg.cpf, reg.orgao_codigo)
        if chave in cpfs_vistos:
            continue
        cpfs_vistos.add(chave)
        pessoa_node = f"PF:{reg.cpf}"
        ug_node     = f"UG:{reg.orgao_codigo}"
        G.add_node(pessoa_node, tipo="pessoa", nome=reg.nome or "")
        G.add_node(ug_node, tipo="ug", codigo=reg.orgao_codigo)
        G.add_edge(pessoa_node, ug_node, tipo="servidor_lotado",
                   cargo=reg.cargo or "", orgao=reg.orgao_nome or "")

    return G


def detectar_triangulos_suspeitos(G: nx.DiGraph) -> list[dict]:
    """
    Triângulo: PF → PJ ← UG  e  PF → UG
    = servidor tem empresa que recebe da sua própria UG.
    """
    alertas = []

    # Encontra pessoas que são sócias de empresas E trabalham em UGs
    for node in list(G.nodes()):
        if not node.startswith("PF:"):
            continue

        # Empresas que esta pessoa é sócia
        empresas_socio = {
            n for n in G.successors(node)
            if n.startswith("PJ:") and G[node][n].get("tipo") == "socio"
        }
        if not empresas_socio:
            continue

        # UGs onde esta pessoa trabalha
        ugs_servidor = {
            n for n in G.successors(node)
            if n.startswith("UG:") and G[node][n].get("tipo") == "servidor_lotado"
        }
        if not ugs_servidor:
            continue

        # Verifica se alguma dessas UGs paga para alguma dessas empresas
        for ug in ugs_servidor:
            for empresa in empresas_socio:
                if G.has_edge(ug, empresa) and G[ug][empresa].get("tipo") == "ob_paga":
                    valor = G[ug][empresa].get("valor", 0)
                    n_obs = G[ug][empresa].get("n_obs", 0)
                    nome_pessoa = G.nodes[node].get("nome", node)
                    alertas.append({
                        "tipo": "triangulo_nepotismo",
                        "severidade": "alta",
                        "titulo": (
                            f"Triângulo suspeito: servidor sócio de empresa "
                            f"que recebe da sua própria UG — {nome_pessoa}"
                        ),
                        "descricao": (
                            f"'{nome_pessoa}' ({node}) é servidor da {ug} E sócio "
                            f"da empresa {empresa}, que recebeu {n_obs} OB(s) "
                            f"totalizando R$ {valor:,.2f} da mesma {ug}. "
                            f"Configura nepotismo/conflito de interesse (SV 13/STF, "
                            f"Lei 9.784/99 art. 18)."
                        ),
                        "pessoa": node,
                        "empresa": empresa,
                        "ug": ug,
                        "valor_recebido": valor,
                        "n_obs": n_obs,
                    })

    return alertas


def detectar_hubs_suspeitos(G: nx.DiGraph, min_ugs: int = 3) -> list[dict]:
    """
    Empresas que recebem OBs de múltiplas UGs distintas são 'hubs'.
    Podem ser empresas legítimas com contratos em vários órgãos,
    ou laranjas que distribuem desvios por múltiplos canais.
    """
    alertas = []

    for node in G.nodes():
        if not (node.startswith("PJ:") or
                (node.startswith("PF:") and G.nodes[node].get("tipo") != "pessoa")):
            continue

        # UGs que pagam para este nó
        ugs_pagadoras = [
            pred for pred in G.predecessors(node)
            if pred.startswith("UG:") and G[pred][node].get("tipo") == "ob_paga"
        ]

        if len(ugs_pagadoras) >= min_ugs:
            total = sum(G[ug][node].get("valor", 0) for ug in ugs_pagadoras)
            nome = G.nodes[node].get("nome", node)
            alertas.append({
                "tipo": "hub_suspeito",
                "severidade": "alta" if len(ugs_pagadoras) >= 5 else "media",
                "titulo": (
                    f"Hub de pagamentos: {nome} recebe de {len(ugs_pagadoras)} UGs — "
                    f"R$ {total:,.0f}"
                ),
                "descricao": (
                    f"'{nome}' ({node}) recebeu OBs de {len(ugs_pagadoras)} unidades "
                    f"gestoras distintas, totalizando R$ {total:,.2f}. "
                    f"Alta capilaridade em múltiplos órgãos pode indicar contrato "
                    f"de fachada ou empresa usada como intermediário de desvio."
                ),
                "n_ugs": len(ugs_pagadoras),
                "total_recebido": total,
                "ugs": ugs_pagadoras,
                "empresa": node,
            })

    return alertas


def detectar_comunidades_suspeitas(G: nx.DiGraph) -> list[dict]:
    """
    Encontra comunidades densamente conectadas usando betweenness centrality.
    Comunidades pequenas e densas com muitas transações financeiras são suspeitas.
    """
    if G.number_of_nodes() < 5:
        return []

    # Trabalha com grafo não-direcionado para detecção de comunidades
    G_undir = G.to_undirected()

    try:
        centrality = nx.betweenness_centrality(G_undir, normalized=True)
    except Exception:
        return []

    # Top 10 nós mais centrais (pontes entre grupos)
    top_central = sorted(centrality.items(), key=lambda x: -x[1])[:10]

    alertas = []
    for node, score in top_central:
        if score < 0.1:  # só alerta se for realmente central
            break
        nome = G.nodes.get(node, {}).get("nome", node)
        tipo = G.nodes.get(node, {}).get("tipo", "")
        if tipo in ("ug",):  # UGs naturalmente são centrais, não alertar
            continue
        alertas.append({
            "tipo": "hub_rede",
            "severidade": "media",
            "titulo": f"Nó altamente central na rede de pagamentos — {nome}",
            "descricao": (
                f"'{nome}' ({node}) é um intermediário-chave na rede de "
                f"relacionamentos (centralidade {score:.2f}), conectando múltiplos "
                f"grupos de pagadores e recebedores. Investigar se atua como "
                f"laranja ou intermediário de desvios."
            ),
            "centralidade": score,
            "node": node,
        })

    return alertas


async def rodar_analise_grafo(session) -> list[dict]:
    """
    Constrói o grafo completo e detecta todos os padrões suspeitos.
    Salva alertas no banco e retorna lista.
    """
    from compliance_agent.database.models import Alerta

    today = date.today()
    G = construir_grafo(session)

    todos = []
    todos += detectar_triangulos_suspeitos(G)
    todos += detectar_hubs_suspeitos(G, min_ugs=3)
    todos += detectar_comunidades_suspeitas(G)

    for a in todos:
        titulo = a.get("titulo", "")[:300]
        existe = session.query(Alerta).filter_by(titulo=titulo).first()
        if not existe:
            alerta = Alerta(
                tipo=a.get("tipo", "grafo"),
                severidade=a.get("severidade", "media"),
                titulo=titulo,
                descricao=a.get("descricao", ""),
                evidencias=json.dumps(
                    {k: v for k, v in a.items()
                     if k not in ("titulo", "descricao", "tipo", "severidade")},
                    ensure_ascii=False, default=str
                ),
                data_referencia=today,
            )
            session.add(alerta)

    session.commit()
    return todos
