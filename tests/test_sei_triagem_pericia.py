

# ═══ vocabulário do manifesto e o que NÃO é o instrumento (2026-08-04) ═══

def test_manifesto_cru_e_normalizado_antes_de_classificar(tmp_path):
    """O manifesto CRU traz o tipo GROSSO do arquivador (`tramitacao`) e as regras daqui falam o
    vocabulário FINO (`despacho`). Sem normalizar, `_RESPOSTA` não achava NENHUM despacho e o A2
    anunciava "não há documento posterior que responda" num processo com 174 despachos
    (070002/012954/2022). Era o achado mais frequente da faixa EXTREMO: 80 dos 150 de maior risco.
    """
    import json
    from pathlib import Path
    import tools.sei_triagem_pericia as T
    (tmp_path / "texto").mkdir()
    docs = [
        {"i": 0, "titulo": "Parecer 1 (11)", "tipo": "parecer_juridico", "texto": "texto/000.txt"},
        {"i": 1, "titulo": "Despacho de Encaminhamento 22", "tipo": "tramitacao",
         "texto": "texto/001.txt"},
    ]
    (tmp_path / "texto" / "000.txt").write_text(
        "PARECER Nº 1. Recomenda-se a correção do termo de referência antes do prosseguimento.",
        encoding="utf-8")
    (tmp_path / "texto" / "001.txt").write_text(
        "Em atendimento ao parecer jurídico 11, informa-se que a recomendação foi cumprida.",
        encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": docs}), encoding="utf-8")
    r = T.periciar(Path(tmp_path)) or {}
    codigos = {a.get("codigo") for a in r.get("achados", [])}
    assert "A2_PARECER_COM_RESSALVA_SEM_RESPOSTA" not in codigos, \
        "o despacho posterior existe — chamá-lo de silêncio é acusação falsa"


def test_registro_de_encerramento_nao_e_o_contrato_do_A1():
    """O A1 do 070026/000410/2021 dizia "contrato antes do parecer" tendo como "contrato" um
    `Registro siafe encerramento contrato` na posição 5."""
    import tools.sei_triagem_pericia as T
    for titulo in ["Registro siafe encerramento contrato (78902494)",
                   "Publicação Extrato de termo aditivo (123085567)",
                   "Termo de apostilamento de contrato 119710337",
                   "Consulta ao Siafe-Rio - Contrato Inea nº 38/2023"]:
        assert T._RX_NAO_CONTRATO.search(titulo), titulo
    assert not T._RX_NAO_CONTRATO.search("Contrato 38/2023 - INEA (79537002)")
