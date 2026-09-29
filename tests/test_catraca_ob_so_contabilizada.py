"""Catraca: detector que SOMA pagamento no SIAFE só conta OB Contabilizada.

Em 24/09/2026 os 7 detectores de `cruzamentos_intel` (e 5 consultas em outros módulos) somavam OB Anulada,
Excluída e Não contabilizada — R$ 13.998.871.152,03 na base. A manchete "pago a empresa morta" caiu de
R$ 586.272.022,50 para R$ 579.308.009,79 e o "pago a sancionado durante a vigência" de R$ 555.760.571,39 para
R$ 522.882.326,69. Uma consulta nova sem o filtro faz a inflação voltar calada; este teste pega na hora.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQS = ["compliance_agent/cruzamentos_intel.py", "compliance_agent/contratos/estado.py",
        "compliance_agent/osint/grupo_economico.py", "compliance_agent/retro_auditoria.py",
        "compliance_agent/grafo_comunidades.py", "compliance_agent/correlacao_sei.py"]
FILTRO = re.compile(r"_OB_PAGA|status\s*=\s*'Contabilizado'", re.I)


def test_toda_consulta_de_ob_siafe_filtra_contabilizada():
    faltando = []
    for rel in ARQS:
        linhas = (RAIZ / rel).read_text(encoding="utf-8").splitlines()
        for i, linha in enumerate(linhas):
            if re.search(r"FROM\s+ob_orcamentaria_siafe", linha, re.I):
                janela = "\n".join(linhas[i:i + 3])          # o WHERE vem na mesma linha ou nas 2 seguintes
                excecao = "ob-qualquer-status" in "\n".join(linhas[max(0, i - 2):i + 1])  # metadado, não soma
                if not FILTRO.search(janela) and not excecao:
                    faltando.append(f"{rel}:{i + 1}: {linha.strip()[:90]}")
    assert not faltando, "consulta de OB do SIAFE sem filtro de OB Contabilizada:\n" + "\n".join(faltando)
