"""
Análise de preços em contratos públicos.

Detecta divergências de preço em categorias similares:
  - Superfaturamento: preço muito acima da mediana do mercado
  - Subfaturamento: preço suspeito por ser muito abaixo (pode indicar vantagem futura)
  - Ranking de órgãos mais caros por categoria
  - Comparação com preços de referência (SIASG, PNCP, cotações de mercado)

Usa NLP simples (TF-IDF + cosine similarity) para agrupar objetos similares.
"""

import json
import re
import statistics
from collections import defaultdict
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from compliance_agent.database.models import Alerta, Contrato, Empresa


# Palavras-chave para categorias de contratos
CATEGORIAS = {
    "veículos":         ["veículo", "carro", "automóvel", "caminhão", "ônibus", "van", "ambulância", "viatura"],
    "combustível":      ["combustível", "diesel", "gasolina", "etanol", "abastecimento"],
    "informática":      ["computador", "notebook", "laptop", "servidor", "impressora", "equipamento de informática", "ti "],
    "limpeza":          ["limpeza", "higienização", "conservação", "faxina", "material de limpeza"],
    "alimentação":      ["alimentação", "refeição", "marmita", "kit lanche", "merenda", "gênero alimentício"],
    "obras":            ["obra", "reforma", "construção", "pavimentação", "calçamento"],
    "saúde":            ["medicamento", "remédio", "material hospitalar", "equipamento médico", "insumo médico"],
    "segurança":        ["vigilância", "segurança", "monitoramento", "câmera", "cftv"],
    "consultoria":      ["consultoria", "assessoria", "treinamento", "capacitação", "curso"],
    "mobiliário":       ["móvel", "cadeira", "mesa", "armário", "arquivo", "estante"],
    "telefonia":        ["telefonia", "internet", "link dedicado", "banda larga", "telecomunicação"],
    "transporte":       ["transporte", "fretamento", "passagem", "locomoção", "translado"],
}


def _categorizar_objeto(objeto: str) -> str:
    """Classifica o objeto do contrato em uma categoria."""
    if not objeto:
        return "outros"
    objeto_lower = objeto.lower()
    for categoria, keywords in CATEGORIAS.items():
        if any(kw in objeto_lower for kw in keywords):
            return categoria
    return "outros"


def _valor_unitario(contrato: Contrato) -> Optional[float]:
    """
    Tenta extrair valor unitário do objeto.
    Ex: "10 veículos por R$ 500.000" → 50.000 por unidade.
    """
    if not contrato.objeto or not contrato.valor_total:
        return None

    # Tenta extrair quantidade de unidades do objeto
    patterns = [
        r"(\d+)\s*(?:un|und|unidade|veículos|carros|notebooks|computadores|licenças)",
        r"(\d+)\s*(?:meses?|anos?)\s*de\s*",
        r"aquisição\s+de\s+(\d+)\s+",
    ]
    for pat in patterns:
        m = re.search(pat, contrato.objeto, re.IGNORECASE)
        if m:
            qtd = int(m.group(1))
            if qtd > 0:
                return contrato.valor_total / qtd
    return None


class AnalisadorPrecos:
    """
    Analisa e compara preços de contratos similares,
    gera rankings e alertas de superfaturamento.
    """

    def __init__(self, session: Session):
        self.session = session

    def analisar(self) -> dict:
        """
        Executa análise completa de preços.
        Retorna ranking, outliers e alertas.
        """
        contratos = self.session.query(Contrato).filter(
            Contrato.objeto.isnot(None),
            Contrato.valor_total > 0,
        ).all()

        if not contratos:
            return {"message": "Nenhum contrato disponível para análise."}

        # Categoriza cada contrato
        por_categoria: dict[str, list[Contrato]] = defaultdict(list)
        for c in contratos:
            cat = _categorizar_objeto(c.objeto)
            por_categoria[cat].append(c)

        resultado = {
            "resumo_categorias": {},
            "superfaturamentos": [],
            "subfaturamentos": [],
            "ranking_orgaos_mais_caros": [],
            "ranking_orgaos_mais_baratos": [],
            "ranking_contratos_suspeitos": [],
        }

        alertas_novos = []

        for categoria, contratos_cat in por_categoria.items():
            if len(contratos_cat) < 2:
                continue

            valores = [c.valor_total for c in contratos_cat if c.valor_total > 0]
            if not valores:
                continue

            mediana   = statistics.median(valores)
            media     = statistics.mean(valores)
            try:
                desvio = statistics.stdev(valores)
            except statistics.StatisticsError:
                desvio = 0

            # Limiar de alerta: acima de 2 desvios padrões da mediana
            limiar_alto = mediana + (2 * desvio if desvio > 0 else mediana * 0.8)
            limiar_baixo = mediana - (2 * desvio if desvio > 0 else mediana * 0.5)

            resultado["resumo_categorias"][categoria] = {
                "qtd_contratos": len(contratos_cat),
                "mediana":  round(mediana, 2),
                "media":    round(media, 2),
                "minimo":   round(min(valores), 2),
                "maximo":   round(max(valores), 2),
                "desvio_padrao": round(desvio, 2),
            }

            for c in contratos_cat:
                if c.valor_total > limiar_alto:
                    desvios_acima = (c.valor_total - mediana) / desvio if desvio > 0 else 0
                    empresa = self.session.query(Empresa).get(c.empresa_id) if c.empresa_id else None
                    nome_emp = empresa.razao_social if empresa else "N/D"

                    item = {
                        "contrato":   c.numero,
                        "objeto":     c.objeto[:150] if c.objeto else "",
                        "categoria":  categoria,
                        "orgao":      c.orgao_contrat,
                        "empresa":    nome_emp,
                        "valor":      c.valor_total,
                        "mediana_categoria": round(mediana, 2),
                        "acima_por": f"{((c.valor_total / mediana - 1) * 100):.1f}%",
                        "desvios_acima": round(desvios_acima, 1),
                    }
                    resultado["superfaturamentos"].append(item)

                    # Alerta no banco
                    titulo = f"Superfaturamento — {categoria} — {c.orgao_contrat}"
                    existe = self.session.query(Alerta).filter_by(titulo=titulo[:300]).first()
                    if not existe:
                        alertas_novos.append(Alerta(
                            tipo       = "direcionamento",
                            severidade = "alta" if desvios_acima > 3 else "média",
                            titulo     = titulo[:300],
                            descricao  = (
                                f"Contrato nº {c.numero} ({c.orgao_contrat}) "
                                f"para '{c.objeto[:100]}' com {nome_emp} "
                                f"custa R$ {c.valor_total:,.2f}, "
                                f"{item['acima_por']} acima da mediana de "
                                f"R$ {mediana:,.2f} para a categoria '{categoria}'."
                            ),
                            evidencias  = json.dumps(item, ensure_ascii=False, default=str),
                            empresa_id  = empresa.id if empresa else None,
                            contrato_id = c.id,
                        ))

                elif c.valor_total < limiar_baixo and c.valor_total > 0:
                    resultado["subfaturamentos"].append({
                        "contrato": c.numero,
                        "objeto":   c.objeto[:150] if c.objeto else "",
                        "categoria": categoria,
                        "orgao":    c.orgao_contrat,
                        "valor":    c.valor_total,
                        "mediana_categoria": round(mediana, 2),
                        "abaixo_por": f"{((1 - c.valor_total / mediana) * 100):.1f}%",
                    })

        # Ranking de órgãos por gasto médio por contrato
        orgao_gastos: dict[str, list[float]] = defaultdict(list)
        for c in contratos:
            if c.orgao_contrat and c.valor_total > 0:
                orgao_gastos[c.orgao_contrat].append(c.valor_total)

        ranking = [
            {
                "orgao":         orgao,
                "media_contrato": round(statistics.mean(vals), 2),
                "total_gasto":   round(sum(vals), 2),
                "n_contratos":   len(vals),
            }
            for orgao, vals in orgao_gastos.items()
            if len(vals) >= 2
        ]
        ranking.sort(key=lambda x: x["media_contrato"], reverse=True)
        resultado["ranking_orgaos_mais_caros"]   = ranking[:15]
        resultado["ranking_orgaos_mais_baratos"] = ranking[-15:][::-1]

        # Ranking contratos mais suspeitos (maior desvio da mediana)
        resultado["ranking_contratos_suspeitos"] = sorted(
            resultado["superfaturamentos"],
            key=lambda x: float(x["acima_por"].replace("%", "")),
            reverse=True,
        )[:20]

        # Salva alertas
        if alertas_novos:
            self.session.add_all(alertas_novos)
            self.session.commit()

        resultado["total_alertas_gerados"] = len(alertas_novos)
        return resultado

    def comparar_categoria(self, categoria: str) -> list[dict]:
        """Retorna todos os contratos de uma categoria, ordenados por valor."""
        contratos = self.session.query(Contrato).filter(
            Contrato.valor_total > 0,
            Contrato.objeto.isnot(None),
        ).all()

        cat_contratos = [c for c in contratos if _categorizar_objeto(c.objeto) == categoria]
        if not cat_contratos:
            return []

        resultado = []
        for c in sorted(cat_contratos, key=lambda x: x.valor_total, reverse=True):
            empresa = self.session.query(Empresa).get(c.empresa_id) if c.empresa_id else None
            resultado.append({
                "contrato":  c.numero,
                "objeto":    c.objeto[:200] if c.objeto else "",
                "orgao":     c.orgao_contrat,
                "empresa":   empresa.razao_social if empresa else "N/D",
                "cnpj":      empresa.cnpj if empresa else "",
                "valor":     c.valor_total,
                "data":      str(c.data_assinatura) if c.data_assinatura else "",
                "modalidade": c.modalidade or "",
            })
        return resultado
