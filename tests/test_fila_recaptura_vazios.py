"""Processo arquivado só com CABEÇALHO tem de voltar para a fila.

Os ~11.9k documentos danificados pelo `insert_textbox` (ver
compliance_agent/sei/pdf_texto.py) deixaram arquivos assim:

    [Despacho de Encaminhamento (94079889)] (fase: tramitacao · tipo: despacho)

…e nada mais. `_arquivado_ok` só perguntava "existe algum .txt?" — e cabeçalho é
.txt. Resultado: a fila via "já arquivado" e nunca rebaixava. Zona morta de novo.

O corte é por DATA (`CORTE_ESCRITOR`): arquivo gerado ANTES do fix e sem teor volta
para a fila; gerado DEPOIS e ainda sem teor é aceito como vazio de verdade — senão
a fila rebaixaria para sempre um processo que realmente não tem conteúdo.
"""
import json

from tools.sei_integra_fila import _arquivado_ok


def _monta(tmp_path, *, corpo: str, gerado_em: str, chars: int):
    (tmp_path / "texto").mkdir(parents=True)
    (tmp_path / "texto" / "000_despacho.txt").write_text(
        f"[Despacho] (fase: tramitacao · tipo: despacho)\n\n{corpo}", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "processo": "080001/007110/2023", "gerado_em": gerado_em,
        "docs": [{"i": 0, "titulo": "Despacho", "texto": "texto/000_despacho.txt",
                  "chars": chars}]}), encoding="utf-8")
    return tmp_path


def test_arquivo_so_com_cabecalho_volta_para_a_fila(tmp_path):
    d = _monta(tmp_path, corpo="", gerado_em="2026-07-13T10:00:00+00:00", chars=0)
    assert _arquivado_ok(d) is False, "só cabeçalho não é processo arquivado"


def test_arquivo_com_teor_real_continua_pronto(tmp_path):
    d = _monta(tmp_path, corpo="Encaminho os autos para análise da assessoria jurídica "
                               "quanto à minuta de contrato." * 4,
               gerado_em="2026-07-13T10:00:00+00:00", chars=300)
    assert _arquivado_ok(d) is True, "processo com teor não pode ser rebaixado à toa"


def test_vazio_apos_o_fix_e_aceito_como_vazio_de_verdade(tmp_path):
    """Sem este corte a fila rebaixaria para sempre um processo genuinamente vazio."""
    d = _monta(tmp_path, corpo="", gerado_em="2026-08-01T10:00:00+00:00", chars=0)
    assert _arquivado_ok(d) is True


def test_sem_manifesto_mantem_o_criterio_antigo(tmp_path):
    (tmp_path / "texto").mkdir(parents=True)
    (tmp_path / "texto" / "000.txt").write_text("teor qualquer", encoding="utf-8")
    assert _arquivado_ok(tmp_path) is True


def test_sem_pasta_de_texto_nao_esta_arquivado(tmp_path):
    assert _arquivado_ok(tmp_path) is False


def test_manifesto_fora_do_formato_nao_derruba(tmp_path):
    """Stub `{"docs": [1]}` existe na suíte antiga — não pode virar AttributeError."""
    (tmp_path / "texto").mkdir(parents=True)
    (tmp_path / "texto" / "001_despacho.txt").write_text("conteudo real", encoding="utf-8")
    (tmp_path / "manifest.json").write_text('{"docs": [1]}', encoding="utf-8")
    assert _arquivado_ok(tmp_path) is True


def _monta_cache_e_arquivo(tmp_path, *, chars_ok, falhas_cache, nao_capturados_arq):
    """Monta um par cache/arquivo: arquivo tem texto; cache tem N docs falhos (ok=False);
    o arquivo declara M como nao_capturados."""
    tag = "080001_000749_2024"
    cache = tmp_path / "sei_cache" / f"integra_{tag}"
    arq = tmp_path / "sei_arquivo" / tag
    (cache).mkdir(parents=True)
    (arq / "texto").mkdir(parents=True)
    (arq / "texto" / "000.txt").write_text("teor real do despacho", encoding="utf-8")
    cdocs = [{"i": 0, "titulo": "Despacho", "ok": True}]
    cdocs += [{"i": 10 + k, "titulo": "Anexo minuta", "ok": False} for k in range(falhas_cache)]
    (cache / "manifest.json").write_text(json.dumps({"docs": cdocs, "completo": True}),
                                         encoding="utf-8")
    (arq / "manifest.json").write_text(json.dumps({
        "docs": [{"i": 0, "titulo": "Despacho", "chars": chars_ok}],
        "nao_capturados": nao_capturados_arq}), encoding="utf-8")
    return arq


def test_recaptura_processo_com_falha_nao_declarada(tmp_path):
    """Processo com texto MAS docs falhos no cache não declarados no arquivo → re-captura."""
    arq = _monta_cache_e_arquivo(tmp_path, chars_ok=500, falhas_cache=3, nao_capturados_arq=0)
    assert _arquivado_ok(arq) is False, "3 falhas no cache, 0 declaradas → tem de re-capturar"


def test_nao_recaptura_quando_falhas_ja_declaradas(tmp_path):
    """Pós-re-captura: as falhas restantes já estão declaradas → não repete (auto-limitante)."""
    arq = _monta_cache_e_arquivo(tmp_path, chars_ok=500, falhas_cache=2, nao_capturados_arq=2)
    assert _arquivado_ok(arq) is True, "cache falhas == declaradas → done, não re-captura eterno"
