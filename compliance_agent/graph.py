"""
Grafo de relacionamentos entre pessoas, empresas e contratos.

Usa NetworkX para análise de redes: detecta clusters suspeitos,
centralidade de atores, caminhos entre servidor e empresa contratada.
"""

import json
from typing import Optional

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

from compliance_agent.database.models import (
    EmpresaSocio, Pessoa, Relacionamento, Contrato, Empresa,
)


class GrafoRelacionamentos:
    """
    Constrói e consulta o grafo de relacionamentos
    a partir do banco de dados de compliance.
    """

    def __init__(self, session):
        self.session = session
        self.G = nx.DiGraph() if HAS_NETWORKX else None

    def construir(self):
        """Reconstrói o grafo completo a partir do banco."""
        if not HAS_NETWORKX:
            return

        self.G.clear()

        # Pessoas
        for p in self.session.query(Pessoa).all():
            self.G.add_node(
                f"pessoa:{p.id}",
                label=p.nome,
                tipo="pessoa",
                subtipo=p.tipo or "servidor",
                cpf=p.cpf or "",
                cargo=p.cargo or "",
                orgao=p.orgao or "",
            )

        # Empresas
        for e in self.session.query(Empresa).all():
            self.G.add_node(
                f"empresa:{e.id}",
                label=e.razao_social,
                tipo="empresa",
                cnpj=e.cnpj or "",
                situacao=e.situacao or "",
            )

        # Sócios → arestas Pessoa → Empresa
        for s in self.session.query(EmpresaSocio).all():
            if s.pessoa_id:
                self.G.add_edge(
                    f"pessoa:{s.pessoa_id}",
                    f"empresa:{s.empresa_id}",
                    tipo="sócio",
                    qualific=s.qualific or "",
                )

        # Relacionamentos diretos
        for r in self.session.query(Relacionamento).all():
            self.G.add_edge(
                f"pessoa:{r.pessoa_a_id}",
                f"pessoa:{r.pessoa_b_id}",
                tipo=r.tipo or "relacionado",
                fonte=r.fonte or "",
            )

        # Contratos → arestas Empresa → Órgão (representado como nó texto)
        for c in self.session.query(Contrato).filter(Contrato.empresa_id.isnot(None)).all():
            orgao_node = f"orgao:{c.orgao_contrat}"
            if not self.G.has_node(orgao_node):
                self.G.add_node(orgao_node, label=c.orgao_contrat, tipo="orgao")
            self.G.add_edge(
                f"empresa:{c.empresa_id}",
                orgao_node,
                tipo="contrato",
                valor=c.valor_total or 0,
                numero=c.numero or "",
            )

    def caminho_entre(self, cpf_ou_cnpj_a: str, cpf_ou_cnpj_b: str) -> Optional[list]:
        """Encontra o menor caminho entre dois atores no grafo."""
        if not HAS_NETWORKX or not self.G:
            return None

        node_a = self._encontrar_node(cpf_ou_cnpj_a)
        node_b = self._encontrar_node(cpf_ou_cnpj_b)
        if not node_a or not node_b:
            return None

        try:
            path = nx.shortest_path(self.G.to_undirected(), node_a, node_b)
            return [self.G.nodes[n].get("label", n) for n in path]
        except nx.NetworkXNoPath:
            return None
        except Exception:
            return None

    def atores_mais_conectados(self, top_n: int = 20) -> list[dict]:
        """Retorna os atores com maior centralidade de grau (mais conexões)."""
        if not HAS_NETWORKX or not self.G:
            return []
        centrality = nx.degree_centrality(self.G.to_undirected())
        top = sorted(centrality.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [
            {
                "node":        node,
                "label":       self.G.nodes[node].get("label", node),
                "tipo":        self.G.nodes[node].get("tipo", ""),
                "centralidade": round(score, 4),
                "conexoes":    self.G.degree(node),
            }
            for node, score in top
        ]

    def clusters_suspeitos(self, min_size: int = 3) -> list[list[str]]:
        """
        Detecta comunidades (clusters) no grafo.
        Clusters com muitos servidores + empresas + contratos são suspeitos.
        """
        if not HAS_NETWORKX or not self.G:
            return []

        undirected = self.G.to_undirected()
        communities = list(nx.connected_components(undirected))
        suspeitos = []
        for community in communities:
            if len(community) < min_size:
                continue
            tipos = [self.G.nodes[n].get("tipo", "") for n in community]
            # Suspeito se mistura servidores e empresas
            if "pessoa" in tipos and "empresa" in tipos:
                labels = [self.G.nodes[n].get("label", n) for n in community]
                suspeitos.append(labels)
        return suspeitos

    def conexoes_diretas(self, cpf_ou_cnpj: str) -> dict:
        """Retorna todas as conexões diretas de um ator."""
        if not HAS_NETWORKX or not self.G:
            return {}

        node = self._encontrar_node(cpf_ou_cnpj)
        if not node:
            return {"error": f"Ator '{cpf_ou_cnpj}' não encontrado no grafo."}

        vizinhos = []
        for neighbor in self.G.neighbors(node):
            edge_data = self.G.get_edge_data(node, neighbor, {})
            vizinhos.append({
                "label": self.G.nodes[neighbor].get("label", neighbor),
                "tipo":  self.G.nodes[neighbor].get("tipo", ""),
                "relacao": edge_data.get("tipo", ""),
            })
        for pred in self.G.predecessors(node):
            edge_data = self.G.get_edge_data(pred, node, {})
            vizinhos.append({
                "label": self.G.nodes[pred].get("label", pred),
                "tipo":  self.G.nodes[pred].get("tipo", ""),
                "relacao": f"← {edge_data.get('tipo', '')}",
            })

        return {
            "ator":     self.G.nodes[node].get("label", node),
            "conexoes": vizinhos,
        }

    def exportar_json(self) -> dict:
        """Exporta grafo em formato JSON para visualização D3.js."""
        if not HAS_NETWORKX or not self.G:
            return {"nodes": [], "links": []}

        nodes = [
            {"id": n, **self.G.nodes[n]}
            for n in self.G.nodes
        ]
        links = [
            {"source": u, "target": v, **self.G.get_edge_data(u, v, {})}
            for u, v in self.G.edges
        ]
        return {"nodes": nodes, "links": links}

    def _encontrar_node(self, identifier: str) -> Optional[str]:
        """Encontra um nó pelo CPF, CNPJ, ou nome parcial."""
        clean = "".join(c for c in identifier if c.isdigit())
        for node, attrs in self.G.nodes(data=True):
            if clean and (attrs.get("cpf") == clean or attrs.get("cnpj") == clean):
                return node
            if identifier.lower() in attrs.get("label", "").lower():
                return node
        return None
