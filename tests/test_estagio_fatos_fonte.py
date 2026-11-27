# -*- coding: utf-8 -*-
"""E8 `fatos` — fonte do texto e porta pela SAÍDA DO ESTÁGIO (O8.5, frente B1).

Reproduz as duas quebras do ensaio O8.5 (25/11/2026): (1) a porta do E8 lia a confirmação de OCR do LEGADO
(`sei/ocr_confirmacao`) e barrou 7 de 9 processos que o E6 tinha conferido; (2) o texto vinha de `data/sei_arquivo`
(legado), não do E4/E5. Aqui o PG da captura (esquema temporário) recebe o que E3/E4/E5/E6 gravariam — aquisição,
documentos, versão binária, `transformacao` + lateral, `ocr_conferencia` — e o E8 tem de: ler o texto do E4/E5 pela
mesma chave (documento + sha256), abrir a porta SÓ com `confirmado` do E6 para o mesmo texto, barrar o resto com o
motivo de cada documento, voltar ao legado só sem saída do estágio (declarado) e ler cada documento UMA vez.
LLM sempre FALSO. Só roda com JFN_EVIDENCIAS_DSN (VM-2) — nunca no esquema `public` real."""
import json
import uuid
from pathlib import Path

import pytest

from compliance_agent import evidencias as EV
from compliance_agent import leitura_integral as LI
from compliance_agent.aplicacao.estagios import fatos as F
from compliance_agent.aplicacao.estagios import texto as T
from tests.fluxo_pg import DSN, precisa_pg
from tests.test_estagio_fatos import _TEXTO_CPF, CPF, _acervo, _Falso

PROC = "999002/000001/2026"
NATIVO = "Despacho: encaminhe-se à unidade de liquidação para as providências de praxe, com urgência. " * 2
OCR_P2 = "NOTA FISCAL 3890 ACME LTDA valor R$ 1.234,56 emitida em 10/04/2026 conforme o atesto do fiscal."


@pytest.fixture()
def cap():
    import psycopg
    nome = f"tmp_b1cap_{uuid.uuid4().hex[:10]}"
    T.aplicar_schema(DSN, nome)
    con = T.conectar(DSN, nome)
    try:
        yield con
    finally:
        con.close()
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')


@pytest.fixture()
def fat():
    import psycopg
    nome = f"tmp_b1fat_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        F.aplicar_schema(con, nome)
        yield con
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


def _semear(con, raiz: Path, docs: list[dict], omitidos=(), proc: str = PROC) -> dict:
    """Grava no PG da captura o que E3/E4/E5/E6 gravariam. `docs`: {doc_id, titulo, paginas: [(perfil, texto)],
    ocr: [texto OCR por página escaneada] | None, e6: 'confirmado' | 'a_conferir' | None | 'outra_versao'}."""
    aid = f"aq-{uuid.uuid4().hex[:8]}"
    con.execute("INSERT INTO aquisicao(id, fonte, concluida_em, detalhe) VALUES (%s, 'sei:e3', now(), %s)",
                (aid, json.dumps({"processo": proc, "omitidos": list(omitidos)})))
    shas = {}
    for pos, d in enumerate(docs):
        bin_sha = T.sha256_texto(f"pdf de {d['doc_id']}")
        shas[d["doc_id"]] = bin_sha
        con.execute("INSERT INTO documentos(processo, doc_id, posicao, titulo, tipo, fase, visto_em) VALUES "
                    "(%s,%s,%s,%s,'','','2026-11-25 10:00:00')", (proc, d["doc_id"], pos, d["titulo"]))
        if d.get("sem_binario"):
            continue
        con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, ocr, vista_em, hash_de, "
                    "aquisicao_id) VALUES (%s,%s,%s,0,'sei:e3',NULL,'2026-11-25 10:00:00','binario',%s)",
                    (proc, d["doc_id"], bin_sha, aid))
        pags = [{"pagina": n, "perfil": p, "texto": t, "chars": len(t)} for n, (p, t) in enumerate(d["paginas"], 1)]
        perfis = {p for p, _ in d["paginas"]}
        lat4 = {"paginas": pags, "perfil": perfis.pop() if len(perfis) == 1 else T.MISTA, "entrada_sha": bin_sha,
                "escaneadas": [x["pagina"] for x in pags if x["perfil"] == T.ESCANEADA]}
        lat4["texto_sha"] = T.sha256_texto(T.texto_composto(lat4))
        p4 = T.caminho_lateral(proc, d["doc_id"], bin_sha, "e4", raiz)
        s4 = T.gravar_lateral(p4, lat4)
        con.execute(T._INS_TR, (proc, d["doc_id"], T.TIPO_TRANSFORMACAO, bin_sha, lat4["texto_sha"], T.MOTOR, "x",
                                json.dumps({"perfil": lat4["perfil"], "lateral": str(p4), "lateral_sha": s4,
                                            "paginas": [[x["pagina"], x["perfil"], x["chars"]] for x in pags]})))
        if d.get("ocr") is None:
            continue
        it = iter(d["ocr"])
        compostas = [next(it) if p == T.ESCANEADA else t for p, t in d["paginas"]]
        lat5 = {"compostas": compostas, "texto_sha": T.sha256_texto(T.QUEBRA.join(compostas)), "paginas": {}}
        p5 = T.caminho_lateral(proc, d["doc_id"], bin_sha, "e5", raiz)
        s5 = T.gravar_lateral(p5, lat5)
        con.execute(T._INS_TR, (proc, d["doc_id"], "ocr", bin_sha, lat5["texto_sha"], "rapidocr", "x",
                                json.dumps({"lateral": str(p5), "lateral_sha": s5})))
        if d.get("e6"):
            ts = lat5["texto_sha"] if d["e6"] != "outra_versao" else "0" * 64
            est = "confirmado" if d["e6"] in ("confirmado", "outra_versao") else d["e6"]
            con.execute("INSERT INTO ocr_conferencia(processo, doc_id, texto_sha, estado, numeros, a_conferir, "
                        "job_chave, ficha) VALUES (%s,%s,%s,%s,3,%s,'confirmar_ocr:x',1)",
                        (proc, d["doc_id"], ts, est, 0 if est == "confirmado" else 1))
    return shas


def _dois(e6="confirmado", **extra) -> list[dict]:
    # o PDF do SEI abre com o rótulo "[<título>]" e o DOERJ traz \r: o E8 lê como o leitor do piloto
    return [{"doc_id": "sei:111", "titulo": "Despacho (111)",
             "paginas": [(T.NATIVA, "[Despacho (111)]\n" + NATIVO.replace("praxe, ", "praxe,\r\n").replace(
                 "urgência.", "urgência.\r"))]},
            {"doc_id": "sei:222", "titulo": "Nota fiscal (222)", "paginas": [(T.NATIVA, _TEXTO_CPF),
                                                                            (T.ESCANEADA, "")],
             "ocr": [OCR_P2], "e6": e6, **extra}]


@pytest.fixture()
def sem_legado(tmp_path, monkeypatch):
    """Legado vazio: nenhum acervo em `data/sei_arquivo` e NENHUMA confirmação no registro legado."""
    monkeypatch.setattr(EV, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(LI, "_CONF", set())
    return tmp_path


# ── 1. a quebra do ensaio: OCR confirmado pelo E6 era barrado pela porta (que lia o legado) ──────────────────
@precisa_pg
def test_porta_abre_com_a_confirmacao_do_e6_e_le_o_texto_do_e4_e5(cap, sem_legado):
    _semear(cap, sem_legado / "texto", _dois())
    p = F.preparar(PROC, set(), set(), con_cap=cap)
    assert p.fora_da_porta is None and p.fonte_texto == F.FONTE_ESTAGIO
    docs = {d: x for f in p.fatias for d, x in f.docs.items()}
    assert set(docs) == {"sei:111", "sei:222"}
    nativo = NATIVO.replace("praxe, ", "praxe,\n").replace("urgência.", "urgência.\n").strip()
    assert docs["sei:111"]["texto"] == nativo           # o E4, como `acervo_texto.ler` leria (sem rótulo, \n)
    assert docs["sei:222"]["texto"] == (_TEXTO_CPF + T.QUEBRA + OCR_P2).strip()   # o E5 (nativo + OCR composto)
    assert docs["sei:222"]["ocr"] and docs["sei:222"]["ocr_confirmado"]
    assert p.cobertura["leitura"] == "integral" and p.cobertura["fracao"] == 1.0
    assert all(CPF not in f.texto for f in p.fatias)                       # a máscara segue antes do envio


# ── 2. a regra de segurança: o que o E6 não confirmou continua barrado ──────────────────────────────────────
@precisa_pg
@pytest.mark.parametrize("e6, motivo", [
    (None, "sem conferência do E6 para este texto"),
    ("outra_versao", "sem conferência do E6 para este texto"),      # confirmado, mas de OUTRO texto (sha) do doc
])
def test_porta_barra_o_que_o_e6_nao_confirmou(cap, sem_legado, e6, motivo):
    _semear(cap, sem_legado / "texto", _dois(e6=e6))
    lidos = []
    original = T.ler_lateral
    T.ler_lateral = lambda pth: lidos.append(pth) or original(pth)
    try:
        p = F.preparar(PROC, set(), set(), con_cap=cap)
    finally:
        T.ler_lateral = original
    assert p.fora_da_porta == "documento de OCR ainda não confirmado" and not p.fatias
    assert p.pecas_nao_lidas == [{"doc_id": "sei:222", "motivo": f"OCR ainda não confirmado pelo E6: {motivo}"}]
    assert lidos == []                                     # barrado pelo PG: nenhum texto aberto à toa


@precisa_pg
def test_a_conferir_nao_vai_ao_modelo_mas_nao_trava_o_processo(cap, sem_legado):
    """27/11/2026: «a_conferir» é a DECISÃO do E6 (número sem confirmação nível A). O documento não é enviado nem vira
    fato — vai para as peças não lidas com o motivo — e o resto do processo é lido (antes: processo barrado para sempre)."""
    _semear(cap, sem_legado / "texto", _dois(e6="a_conferir"))
    p = F.preparar(PROC, set(), set(), con_cap=cap)
    assert p.fora_da_porta is None and p.fatias
    assert all("sei:222" not in f.docs and OCR_P2[:40] not in f.texto for f in p.fatias)   # nada do não confirmado sai
    assert {"doc_id": "sei:222", "motivo": "OCR ainda não confirmado"} in p.pecas_nao_lidas


@precisa_pg
def test_pagina_escaneada_sem_saida_do_e5_barra(cap, sem_legado):
    docs = _dois()
    docs[1]["ocr"] = None                                  # o E4 viu página escaneada; o E5 não gravou nada
    _semear(cap, sem_legado / "texto", docs)
    p = F.preparar(PROC, set(), set(), con_cap=cap)
    assert p.fora_da_porta == "documento de OCR ainda não confirmado"
    assert p.pecas_nao_lidas[0]["motivo"].endswith("página escaneada sem saída do E5")


@precisa_pg
def test_captura_incompleta_e_lateral_adulterado_barram(cap, sem_legado):
    _semear(cap, sem_legado / "texto", _dois(), omitidos=[{"doc_id": "sei:333", "i": 3}])
    assert F.preparar(PROC, set(), set(), con_cap=cap).fora_da_porta == "documentos faltando na captura"
    cap.execute("UPDATE aquisicao SET detalhe = jsonb_set(detalhe, '{omitidos}', '[]')")
    lat = next((sem_legado / "texto").rglob("sei_111.*.e4.json"))
    lat.write_text(lat.read_text(encoding="utf-8").replace("Despacho", "DESPACHO"), encoding="utf-8")
    p = F.preparar(PROC, set(), set(), con_cap=cap)
    assert p.fora_da_porta == "texto do estágio não confere com o PG" and not p.fatias
    assert "sha256" in p.pecas_nao_lidas[0]["motivo"]


# ── 3. o legado só como volta DECLARADA ─────────────────────────────────────────────────────────────────────
@precisa_pg
def test_texto_do_estagio_vence_o_legado_e_o_legado_so_volta_sem_saida(cap, tmp_path, monkeypatch):
    _acervo(tmp_path, monkeypatch, [("Despacho (111)", "TEXTO LEGADO " * 10)], proc=PROC)
    _semear(cap, tmp_path / "texto", _dois())
    p = F.preparar(PROC, set(), set(), con_cap=cap)
    assert p.fonte_texto == F.FONTE_ESTAGIO
    assert all("TEXTO LEGADO" not in f.texto for f in p.fatias)
    outro = "999002/000009/2026"                            # processo que o estágio não tem
    _acervo(tmp_path, monkeypatch, [("Despacho (111)", "TEXTO LEGADO " * 10)], proc=outro)
    q = F.preparar(outro, set(), set(), con_cap=cap)
    assert q.fora_da_porta is None and q.fonte_texto.startswith(F.FONTE_LEGADO + ":")
    assert "TEXTO LEGADO" in q.fatias[0].texto
    assert F.preparar(PROC, set(), set()).fonte_texto == F.FONTE_LEGADO + ": sem conexão com o PG da captura"


# ── 4. handler pela fonte do estágio: efeito conferido, idempotente, leitura única ─────────────────────────
@precisa_pg
def test_ler_processo_pela_saida_do_estagio_efeito_e_leitura_unica(cap, fat, sem_legado):
    _semear(cap, sem_legado / "texto", _dois()[::-1])        # o falso cita o 1º documento da fatia (o do CPF)
    lidos = []
    original = T.ler_lateral
    T.ler_lateral = lambda pth: lidos.append(pth) or original(pth)
    try:
        falso = _Falso()
        r = F.ler_processo(fat, PROC, falso, con_cap=cap)
        assert len(lidos) == 2                              # 1 lateral por documento (E4 do nativo, E5 do OCR)
        assert r["fonte_texto"] == F.FONTE_ESTAGIO and r["fatos_verificados"] >= 1
        assert CPF not in falso.chamadas[0]
        c = F.conferir(fat, r, con_cap=cap)
        assert F._efeito_ok(r, c) and c["amostra"] >= 1 and not c["divergentes"]
        with pytest.raises(F.ErroPermanente):               # declarou o estágio: conferir sem o PG da captura recusa
            F.conferir(fat, r)
        n = len(falso.chamadas)
        r2 = F.ler_processo(fat, PROC, falso, con_cap=cap)
        assert r2["ja_lido"] and len(falso.chamadas) == n    # 2ª passada: 0 LLM
    finally:
        T.ler_lateral = original


# ── 5. fatiador: a decisão do E6 que vem no documento vale (e o legado continua para o legado) ───────────────
def test_fatiar_usa_ocr_confirmado_do_documento(tmp_path):
    def doc(conf):
        return {"doc_id": "sei:1", "titulo": "t", "texto": OCR_P2, "ocr": True, "i": "0", "sha": F._sha(OCR_P2),
                **({} if conf is None else {"ocr_confirmado": conf})}
    LI._CONF = set()
    try:
        assert LI.fatiar(tmp_path, docs=[doc(True)])[1]["docs_ocr_pendente"] == []
        assert LI.fatiar(tmp_path, docs=[doc(False)])[1]["docs_ocr_pendente"] == ["sei:1"]
        assert LI.fatiar(tmp_path, docs=[doc(None)])[1]["docs_ocr_pendente"] == ["sei:1"]       # legado vazio
        LI._CONF = {(tmp_path.name, "0")}
        assert LI.fatiar(tmp_path, docs=[doc(None)])[1]["docs_ocr_pendente"] == []
        assert LI.fatiar(tmp_path, docs=[doc(False)])[1]["docs_ocr_pendente"] == ["sei:1"]      # o E6 manda
    finally:
        LI._CONF = None


# ── 6. leitura única por TEXTO (sha256 da saída do E4/E5): o mesmo texto em documentos/processos diferentes ──
# rB1 (25/11/2026): o decreto DOERJ 48.692, byte a byte igual em 3 processos liberados, era aberto 3× (sensor 0,85 %).
DECRETO = "DECRETO Nº 48.692\nDispõe sobre a retenção do imposto de renda\n" + _TEXTO_CPF + "\n"


def _decreto(doc_id: str, titulo: str) -> dict:
    return {"doc_id": doc_id, "titulo": titulo, "paginas": [(T.NATIVA, DECRETO)]}


class _Contador:
    def __init__(self):
        self.lidos, self._orig = [], T.ler_lateral

    def __enter__(self):
        T.ler_lateral = lambda pth: self.lidos.append(Path(pth).name) or self._orig(pth)
        return self

    def __exit__(self, *a):
        T.ler_lateral = self._orig


@precisa_pg
def test_texto_ja_lido_pelo_piloto_nao_e_reaberto_em_outro_processo_sem_llm(cap, fat, sem_legado):
    p1, p2 = "999002/000011/2026", "999002/000012/2026"
    _semear(cap, sem_legado / "t", [_decreto("sei:501", "Anexo Decreto 48.692 (501)"),
                                   {"doc_id": "sei:502", "titulo": "Despacho (502)", "paginas": [(T.NATIVA, NATIVO)]}],
            proc=p1)
    _semear(cap, sem_legado / "t", [_decreto("sei:601", "Decreto 48.692 (601)")], proc=p2)
    fat.execute("INSERT INTO docs_lidos(sha, versao, processo, doc_id, lote, em) VALUES (%s,'li-2','999000/000001/2025',"
                "'sei:9','piloto','2026-11-23')", (F._sha(DECRETO.strip()),))          # o piloto já leu o decreto
    sem_cota = lambda s, t: None
    with _Contador() as c:
        with pytest.raises(F.SemCota):
            F.ler_processo(fat, p1, sem_cota, con_cap=cap)                    # lê os 2 e não chama (sem cota)
        assert len(c.lidos) == 2
        r = F.ler_processo(fat, p2, sem_cota, con_cap=cap)                    # o decreto NÃO é reaberto
        assert len(c.lidos) == 2
    assert r["fatias"] == [r["fatias"][0]] and r["fatias_lidas_agora"] == 0 and r["reuso"]["docs"] == 1
    linha = fat.execute("SELECT texto_sha, chars FROM docs_lidos WHERE versao = 'li-2'").fetchone()
    assert linha[0] and linha[1] == len(DECRETO.strip())


@precisa_pg
def test_mesmo_texto_lido_1x_e_fatos_reaproveitados_por_documento(cap, fat, sem_legado):
    p1, p2 = "999002/000021/2026", "999002/000022/2026"
    _semear(cap, sem_legado / "t", [_decreto("sei:501", "Decreto 48.692 (501)"),
                                   _decreto("sei:502", "Decreto 48.692 republicado (502)")], proc=p1)
    _semear(cap, sem_legado / "t", [_decreto("sei:601", "Anexo Decreto 48.692 (601)"),
                                   {"doc_id": "sei:602", "titulo": "Atesto (602)",
                                    "paginas": [(T.NATIVA, "Outro atesto: " + _TEXTO_CPF)]}], proc=p2)
    falso = _Falso()
    with _Contador() as c:
        r1 = F.ler_processo(fat, p1, falso, con_cap=cap)
        assert len(c.lidos) == 1                                  # 2 documentos, MESMO texto: 1 leitura
        r2 = F.ler_processo(fat, p2, falso, con_cap=cap)
        assert len(c.lidos) == 2                                  # em p2 só o atesto é aberto
    assert len(falso.chamadas) == 2 and all("DECRETO" not in x for x in falso.chamadas[1:])
    fatos = {(pr, d): (sha, ini, fim, cit) for pr, d, sha, ini, fim, cit in fat.execute(
        "SELECT processo, doc_id, doc_sha, inicio, fim, citacao FROM fatos WHERE estado = %s", (F.VERIFICADO,))}
    base = fatos[(p1, "sei:501")]
    assert fatos[(p1, "sei:502")] == base == fatos[(p2, "sei:601")]   # a citação aponta para o doc de CADA processo
    for r in (r1, r2):
        c = F.conferir(fat, r, con_cap=cap)                       # a conferência relê o texto de cada documento
        assert F._efeito_ok(r, c) and not c["divergentes"]
    assert F.ler_processo(fat, p2, falso, con_cap=cap)["ja_lido"] and len(falso.chamadas) == 2
