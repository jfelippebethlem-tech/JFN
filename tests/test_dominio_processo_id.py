# -*- coding: utf-8 -*-
"""O4.1 — `dominio.processo_id`: UMA chave de processo, com PARIDADE contra as cópias antigas.

Chave canônica = a do `evidencias` (campo `processo` do manifest) = `UUUUUU/NNNNNN/AAAA`. As cópias antigas
achadas em 24/11/2026 escrevem a MESMA identidade em 5 formas; cada teste compara a antiga com a projeção da nova
na forma dela (`ProcessoId.curta`, `.digitos`, `.canonica`, `.pasta`, `.legivel`):

  forma curta 'U/N/AAAA'   tools/lex_execucao.py:162 `_chave_processo` (a "régua da casa"), compliance_agent/
                           foto_quantitativo.py:749 (cópia), ob_processo.py:49 (delega), lex_fatos.py:64 (delega, "")
  canônica 'U/NNNNNN/AAAA' padroes/_aditivos_comum.py:41, tools/sei_integra_fila.py:42 `_proc_limpo`,
                           evidencias.py:149 (campo `processo` do manifest, sem normalizar)
  16 dígitos               pericia_contabil.py:194 `chave_sei`, :215 `chave_processo_ob`,
                           detectores/est_valor_contratual.py:50 `processo_canonico`
  pasta / legível          sei/acervo_texto.py:51 `numero_para_pasta`, :60 `pasta_para_numero`,
                           lex_fatos.py:74 `processo_legivel`, :80 `_slug_acervo`, leitura_integral.py:413 `_pasta_do`,
                           ob_processo.py:76 `_canonico`
  só dígitos (não é chave) collectors/tcerj_aberto.py:74 `sei_norm`, tools/sei_sweep.py:550 `_norm_proc_global`,
                           tools/sei_analise_em_serie.py:55 `_chave`, sei/reuso_documento_execucao.py:317 `_chave_proc`
  SEI.RIO                  pcrj/sei_prefeitura.py:43 `normalizar_processo`

Entrada: `tests/fixtures/dominio_processos.json` — 2.067 grafias reais (até 2 por forma das 5 colunas de processo
do `compliance.db`) + 207 manifests. Regra de cada comparação:
  igual                       → ok;
  antiga None, nova com chave → AMPLIAÇÃO (grafia que a antiga não lia); exige que unidade, sequencial e ano da
                                nova estejam escritos na entrada (a nova não inventa número);
  antiga com chave ≠ nova     → só se cair num BUG_DOCUMENTADO abaixo; qualquer outra diferença falha o teste.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from compliance_agent.dominio import processo_id as P

FIX = json.loads((Path(__file__).parent / "fixtures" / "dominio_processos.json").read_text(encoding="utf-8"))
GRAFIAS: list[str] = FIX["grafias"]
MANIFESTS: list[dict] = FIX["manifests"]

# Bugs/limites das cópias antigas: a antiga devolve uma chave e a nova recusa (ou dá outra). Cada um explicado.
BUGS_DOCUMENTADOS = [
    ("QUATRO_SEGMENTOS", lambda s: s.split(",")[0].count("/") >= 3,
     "4 segmentos ('SEI-080007/010100/1/2023', 'E-09/102510/4000/2001'): a antiga lia o 2º segmento como UNIDADE "
     "(chave '010100/1/2023' para um processo da unidade 080007 — 492 grafias distintas no SIAFE). A nova lê "
     "'/1/' e '/A/' como sufixo de desdobramento e recusa a numeração antiga E-NN."),
    ("UNIDADE_5_DIGITOS", lambda s: len(re.match(r"\D*(\d*)", s).group(1)) == 5,
     "unidade com 5 dígitos ('SEI-80001/026550/2023'): `_aditivos_comum` completava com zero À ESQUERDA, mas o zero "
     "caído pode estar em qualquer posição (`ob_processo._chave_tolerante`: '03001' é 030001). Palpite; recusado."),
    ("UNIDADE_7_DIGITOS", lambda s: bool(re.search(r"(?<!\d)[1-9]\d{6,}\s*/", s)),
     "unidade de 7+ dígitos sem zero à esquerda ('SEI-2100106/…', '3300030/00597/2023'): a antiga ficava com os 6 "
     "ÚLTIMOS ('300030', quando o número parece 330003 com um 0 a mais). Palpite; recusado."),
    ("SEQUENCIAL_LONGO", lambda s: bool(re.search(r"\d{6}\s*/\s*\d{7,}", s)),
     "sequencial com 7+ dígitos ('SEI-350487/00063023/2023'): `chave_sei`/`est_valor` cortavam em 6 e liam o resto "
     "como ano ('000630' + '23' → outro processo). A nova tira os zeros e aceita até 6 significativos."),
    ("ANO_MALFORMADO", lambda s: bool(re.search(r"/\s*(\d{5,}|\d{3})\s*$", s)),
     "ano com dígitos a mais ou a menos ('…/20214', '…/022'): `_proc_limpo` pegava os 4 primeiros — 20214 pode ser "
     "2021 ou 2024."),
    ("SUFIXO_LIDO_COMO_ANO", lambda s: bool(re.search(r"\d{6}\s*-\s*\d{2}\s*(/|$)", s)),
     "sufixo '-17' ('350207/000140-17/2024'): `est_valor_contratual` lia '17' como o ANO (2017)."),
    ("SEPARADOR_FORA_DO_SEI",
     lambda s: bool(re.search(r"\d{6}\s*[.,\-]\s*\d{5,6}|\d{6}\s*[.,]\s*/|\d{6}/\d{10}|\d{6}/\d{6},|\d{6}[.*]+/", s)),
     "ponto, vírgula, hífen ou ano colado como separador ('SEI-070002.019349/2023', '260002/0001332025'): ponto é o "
     "separador do SEI.RIO e hífen o do DV; a antiga (`\\D*` ou `[/.]`) aceitava qualquer coisa."),
    ("TEXTO_NO_SUFIXO",
     lambda s: bool(re.search(r"\d\s*[-.]?\s*[A-Z]{2,}|\d[.][A-Z]|\d{12}-?[A-Z]|-[A-Z]\d|(?<!\d)\d{6}[A-Z]/", s, re.I)),
     "texto colado ao número ('520003/000353-ATA05/2026', '…/INFRA', '…VET/…'): `est_valor_contratual` (`\\D*`) "
     "pulava o texto e às vezes lia o número do texto como ano ('ATA05' → 2005)."),
    ("UNIDADE_PARTIDA", lambda s: bool(re.search(r"[A-Z]\d\s*-\s*\d{5}\s*/", s, re.I)),
     "unidade partida pelo prefixo ('SEI2-60007/059447/23'): a antiga completava '60007' → 060007, mas o dígito que "
     "falta é o '2' colado ao prefixo. Palpite; recusado."),
    ("DIGITOS_CORRIDOS", lambda s: bool(re.search(r"\d{13,}", s)) and not re.fullmatch(r"\*?\s*\d{16}\s*", s),
     "dígitos corridos que não são os 16 do SEI-RJ (nº CNJ de 20 dígitos, CNPJ de 14, 15 ou 17 depois de 'SEI-'): "
     "`est_valor_contratual` recortava 6+6+4 de qualquer lugar e fabricava uma chave."),
]


def _bug(s: str) -> str | None:
    return next((cod for cod, pred, _ in BUGS_DOCUMENTADOS if pred(s)), None)


def _projecao(attr: str):
    def f(s):
        p = P.analisar(s)
        return getattr(p, attr) if p else None
    return f


def _escrito_na_entrada(s: str) -> bool:
    p = P.analisar(s)
    d = re.sub(r"\D", "", s)
    return p is not None and p.unidade in d and str(p.sequencial) in d and p.ano[-2:] in d


def _comparar(antiga, attr: str, entradas=GRAFIAS) -> dict:
    nova = _projecao(attr)
    sem_explicacao, contagem = [], {"igual": 0, "ampliacao": 0}
    for s in entradas:
        a, b = antiga(s) or None, nova(s)
        if a == b:
            contagem["igual"] += 1
        elif a is None:
            assert _escrito_na_entrada(s), f"nova inventou chave para {s!r}: {b!r}"
            contagem["ampliacao"] += 1
        else:
            cod = _bug(s)
            if cod is None:
                sem_explicacao.append((s, a, b))
            contagem[cod] = contagem.get(cod, 0) + 1
    assert not sem_explicacao, f"divergências sem explicação: {sem_explicacao[:20]}"
    return contagem


def test_fixture_tem_amostra_real():
    assert len(GRAFIAS) >= 1000 and len(MANIFESTS) >= 200
    assert len(set(GRAFIAS)) == len(GRAFIAS)


@pytest.mark.parametrize("caminho", ["tools.lex_execucao:_chave_processo", "compliance_agent.foto_quantitativo:chave_processo",
                                     "compliance_agent.ob_processo:chave_processo", "compliance_agent.lex_fatos:processo_canonico"])
def test_paridade_forma_curta(caminho):
    import importlib
    mod, nome = caminho.split(":")
    c = _comparar(getattr(importlib.import_module(mod), nome), "curta")
    assert c["igual"] >= 1500   # 1.601 medidos em 24/11/2026


def test_paridade_aditivos_comum():
    from compliance_agent.padroes._aditivos_comum import chave_processo
    assert _comparar(chave_processo, "canonica")["igual"] >= 1400


def test_paridade_sei_integra_fila():
    from tools.sei_integra_fila import _proc_limpo
    assert _comparar(_proc_limpo, "canonica")["igual"] >= 1350


@pytest.mark.parametrize("nome", ["chave_sei", "chave_processo_ob"])
def test_paridade_pericia_contabil(nome):
    import compliance_agent.pericia_contabil as pc
    assert _comparar(getattr(pc, nome), "digitos")["igual"] >= 1400


def test_paridade_est_valor_contratual():
    from compliance_agent.detectores.est_valor_contratual import processo_canonico
    assert _comparar(processo_canonico, "digitos")["igual"] >= 1700


def test_paridade_evidencias_manifests():
    """A chave da nova é EXATAMENTE a do `evidencias` (campo `processo` do manifest) e a pasta do acervo.
    DIVERGÊNCIA DOCUMENTADA: 4 dos 16.598 manifests não têm número SEI-RJ completo ('SEI 330020/0007', '17513/2025',
    '406/2025') — o `evidencias` os grava crus; a nova devolve None (não há processo identificável)."""
    from compliance_agent.sei import acervo_texto
    fora = []
    for m in MANIFESTS:
        proc, pasta = m["processo"], m["pasta"]
        if re.fullmatch(r"\d{6}/\d{6}/\d{4}", proc):
            assert P.chave_processo(proc) == proc
            assert P.chave_processo(pasta) == proc == P.chave_processo("SEI-" + proc)
            assert P.pasta(proc) == pasta == acervo_texto.numero_para_pasta(proc)
            assert P.legivel(pasta) == acervo_texto.pasta_para_numero(pasta)
        else:
            assert P.chave_processo(proc) is None and P.chave_processo(pasta) is None
            fora.append(proc)
    assert len(fora) <= 4


def test_paridade_evidencias_importar_pasta(tmp_path):
    """Roda o `evidencias.importar_pasta` de verdade: a chave gravada é a da nova."""
    from compliance_agent import evidencias
    con = evidencias.conectar(tmp_path / "ev.db")
    for proc in ("080001/000123/2024", "330002/031566/2025"):
        pasta = tmp_path / proc.replace("/", "_")
        pasta.mkdir()
        (pasta / "manifest.json").write_text(json.dumps({"processo": proc, "docs": []}), encoding="utf-8")
        r = evidencias.importar_pasta(con, pasta)
        assert r["processo"] == P.chave_processo(proc) == P.chave_processo(pasta.name)


def test_paridade_formas_derivadas():
    from compliance_agent import lex_fatos
    from compliance_agent.leitura_integral import _pasta_do
    from compliance_agent.ob_processo import _canonico
    from compliance_agent.sei import acervo_texto
    for s in GRAFIAS:
        p = P.analisar(s)
        if not p:
            continue
        assert lex_fatos.processo_legivel(p.curta) == p.legivel == _canonico(p.curta)
        assert lex_fatos._slug_acervo(p.curta) == p.pasta == acervo_texto.numero_para_pasta(p.legivel)
        assert acervo_texto.pasta_para_numero(p.pasta) == p.legivel
        assert _pasta_do(p.legivel).name == p.pasta


@pytest.mark.parametrize("caminho", ["compliance_agent.collectors.tcerj_aberto:sei_norm",
                                     "tools.sei_sweep:_norm_proc_global",
                                     "compliance_agent.sei.reuso_documento_execucao:_chave_proc",
                                     "tools.sei_analise_em_serie:_chave"])
def test_chaves_so_digitos_coincidem_so_na_grafia_cheia(caminho):
    """Essas NÃO são normalização de processo: juntam os dígitos do que vier. Coincidem com `ProcessoId.digitos`
    quando a grafia já é a cheia (`[SEI-]UUUUUU/NNNNNN/AAAA`). DIVERGÊNCIA DOCUMENTADA (bug da antiga): fora disso
    o mesmo processo dá chaves diferentes — '…/24' × '…/2024', '/5954/' × '/005954/', sufixo '-A' que some ou
    '/1/' que entra — e o casamento por igualdade falha calado (ex.: `sei_norm` de contratos_tcerj)."""
    import importlib
    mod, nome = caminho.split(":")
    antiga = getattr(importlib.import_module(mod), nome)
    cheias = [s for s in GRAFIAS if re.fullmatch(r"(SEI-)?\d{6}/\d{6}/\d{4}", s)]
    assert len(cheias) >= 2
    for s in cheias:
        assert antiga(s) == P.analisar(s).digitos, s
    curta = "SEI-080001/5954/24"
    assert antiga(curta) != P.analisar(curta).digitos


def test_pcrj_paridade_sei_prefeitura():
    """DIVERGÊNCIA DOCUMENTADA: `sei_prefeitura.normalizar_processo` procura sem fronteira — em '1234567.123456/
    2025-123' recorta '234567.123456/2025-12'; a nova exige que o protocolo não venha colado a outro dígito."""
    from compliance_agent.pcrj.sei_prefeitura import normalizar_processo
    for s in ("12345.123456/2025-12", "Processo nº.: 012345 . 123456 / 2025 - 01", "06001.000123/2024-77 (SEI.RIO)",
              "sem número", "SEI-080001/000123/2024"):
        antiga = normalizar_processo(s)
        assert P.chave_pcrj(s) == (P.PREFIXO_PCRJ + antiga if antiga else None), s
    assert normalizar_processo("1234567.123456/2025-123") and P.chave_pcrj("1234567.123456/2025-123") is None


# ── a nova por si ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada,chave,sufixo", [
    ("SEI-330002/031566/2024", "330002/031566/2024", ""),
    ("sei-330002/31566/2024", "330002/031566/2024", ""),
    ("SEI-330002/031566/24", "330002/031566/2024", ""),
    ("330002/031566/2024", "330002/031566/2024", ""),
    ("330002_031566_2024", "330002/031566/2024", ""),
    ("3300020315662024", "330002/031566/2024", ""),
    ("*SEI-330002/031566/2024", "330002/031566/2024", ""),
    ("SEI 330002 031566 2024", "330002/031566/2024", ""),
    ("SEI-080001002471/2024", "080001/002471/2024", ""),
    ("S07-030001/037771/2025", "030001/037771/2025", ""),
    ("I-270002/001543/2025", "270002/001543/2025", ""),
    ("Sei 020001/001450/2025", "020001/001450/2025", ""),
    ("SEI080001/000188/2022", "080001/000188/2022", ""),
    ("SEI-260007/05954/2025", "260007/005954/2025", ""),
    ("SEI-020002/000026//2023", "020002/000026/2023", ""),
    ("SEI-0080004/002071/24", "080004/002071/2024", ""),
    ("SEI-350487/00063023/2023", "350487/063023/2023", ""),
    ("SEI-020001/000697A/2025", "020001/000697/2025", "A"),
    ("SEI-070001/000180-A/2025", "070001/000180/2025", "A"),
    ("SEI-080002/000208-1/2024", "080002/000208/2024", "1"),
    ("SEI-020002/000192/2/2023", "020002/000192/2023", "2"),
    ("SEI-080007/010100/1/2023", "080007/010100/2023", "1"),
    ("SEI-270032/000072-A/2022, SEI-270032/000072-B/2022", "270032/000072/2022", "A"),
])
def test_grafias_aceitas(entrada, chave, sufixo):
    p = P.analisar(entrada)
    assert p and p.canonica == chave and p.sufixo == sufixo
    assert P.chave_processo(entrada) == chave


@pytest.mark.parametrize("entrada", [
    None, "", "-", "Não há", "SEI-08000/007404/2022", "E-07/002.106748/2018", "E-01/004/000939/2015",
    "PGE/001.000758/2021", "SEI-08/001/006114/2019", "SEI-070020/0002", "SEI-080001/004290/022",
    "SEI-2100106/000002/2023", "170002/002777/20214", "000061-2/2026", "2023-06005266", "4572/26",
    "SEI-080001/1234567/2024", "00205072120218190202",
])
def test_grafias_recusadas(entrada):
    assert P.analisar(entrada) is None and P.chave_processo(entrada) is None


def test_idempotente_em_toda_a_amostra():
    for s in GRAFIAS + [m["processo"] for m in MANIFESTS]:
        k = P.chave_processo(s)
        if k is not None:
            assert P.chave_processo(k) == k, s
            if not k.startswith(P.PREFIXO_PCRJ):
                assert re.fullmatch(r"\d{6}/\d{6}/\d{4}", k)
                p = P.analisar(k)
                assert P.chave_processo(p.pasta) == P.chave_processo(p.legivel) == P.chave_processo(p.digitos) == k


def test_pcrj_tem_precedencia_e_prefixo():
    assert P.chave_processo("12345.123456/2025-12") == "PCRJ:12345.123456/2025-12"
    assert P.chave_processo("PCRJ:12345.123456/2025-12") == "PCRJ:12345.123456/2025-12"
    assert P.chave_pcrj("SEI-080001/000123/2024") is None
