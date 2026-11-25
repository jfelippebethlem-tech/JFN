# -*- coding: utf-8 -*-
"""Registro de LEITURAS por job — o aceite de "leitura única" (plano mestre v2 §19; item O8.5).

Dono, 24/11/2026: "não queremos no final sobreposição de esforços e leitura das mesmas informações e documentos várias
vezes como acontecia". Critério: cada documento (sha256) é lido no máximo 1× por estágio × versão (prompt_version para
LLM; a versão da lógica do estágio para o resto); a 2ª passada seguida faz 0 leitura, 0 download e 0 chamada de LLM.

O QUE CONTA COMO LEITURA (`TIPOS`), anotada nos pontos REAIS de E/S, sem mudar o que o handler faz:
  · `download`   — documento trazido da fonte (E3; no ensaio O8.5, a cópia do acervo pelo navegador de replay);
  · `pdf`        — `fitz.open(<arquivo>)` (E4 extrai, E5 rasteriza, E6 relê) — chave = sha256 do arquivo;
  · `texto`      — `sei.acervo_texto.ler` (o texto de um documento do acervo: E8/E11) — chave = sha256 do texto;
  · `ocr_pagina` — uma página rasterizada que um motor de OCR leu (`ler_img` dos executores do E5/E6) — chave =
                   sha256 dos pixels, versão = motor@versão;
  · `llm`        — chamada CONCLUÍDA do gateway (`adaptadores/llm/gateway.chamar`) — chave = sha256 das mensagens e
                   dos documentos, versão = prompt_version. Chamada recusada (sem cota, sem provedor) não é leitura.
Dentro de UM job, abrir o mesmo arquivo de novo soma em `n` (a mesma linha): `n > 1` é releitura DENTRO do job (detalhe,
não o SLO). O SLO `leitura.repetida_pct` (E18, `fluxo/sensores.g_leitura`) conta a mesma (estágio, tipo, sha, versão)
lida por MAIS DE UM job no modo `rodar` — é a sobreposição de esforço. As releituras da CONFERÊNCIA DE EFEITO (modo
`conferir`, outro processo, por contrato §3.2) ficam registradas à parte e nunca entram no SLO.

Onde grava: tabela `leitura_registro` no esquema do fluxo (o mesmo de `fila.conectar`), criada sob demanda (CREATE
TABLE IF NOT EXISTS: não é migração do motor — `schema.verificar` de produção não muda). Ligado só com
`JFN_LEITURAS_REGISTRAR=1` (o processo-filho `fluxo.executar` instala e grava); desligado, nada muda e o sensor diz
INDISPONIVEL. Falha ao gravar o registro NUNCA derruba o job (vai ao stderr).
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ENV_LIGADO = "JFN_LEITURAS_REGISTRAR"
ENV_ROTULO = "JFN_LEITURAS_ROTULO"          # etiqueta livre (ex.: a passada do ensaio O8.5)
TABELA = "leitura_registro"
TIPOS = ("download", "pdf", "texto", "ocr_pagina", "llm")
MODOS = ("rodar", "conferir")
DDL = (f"CREATE TABLE IF NOT EXISTS {TABELA}(id BIGSERIAL PRIMARY KEY, quando TIMESTAMPTZ NOT NULL DEFAULT now(), "
       "no TEXT, estagio TEXT NOT NULL, tipo TEXT NOT NULL, sha TEXT NOT NULL, versao TEXT NOT NULL DEFAULT '-', "
       "modo TEXT NOT NULL, job_chave TEXT, ficha BIGINT, n INTEGER NOT NULL DEFAULT 1, rotulo TEXT, detalhe JSONB)")
DDL_IX = f"CREATE INDEX IF NOT EXISTS {TABELA}_quando_ix ON {TABELA}(quando)"


def ligado() -> bool:
    return os.environ.get(ENV_LIGADO) == "1"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_arquivo(p: Path | str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


@dataclass
class Registro:
    """As leituras de UM processo-filho (um job, um modo). Agrega por (tipo, sha, versão)."""
    estagio: str
    versao: str
    modo: str
    job_chave: str | None = None
    ficha: int | None = None
    no: str | None = None
    rotulo: str | None = None
    itens: dict = field(default_factory=dict)          # (tipo, sha, versao) -> {"n": int, "detalhe": dict}

    def anotar(self, tipo: str, sha: str, versao: str | None = None, **detalhe) -> None:
        if tipo not in TIPOS or not sha:
            return
        k = (tipo, sha, versao or self.versao)
        it = self.itens.setdefault(k, {"n": 0, "detalhe": {}})
        it["n"] += 1
        for c, v in detalhe.items():
            it["detalhe"].setdefault(c, v)

    def linhas(self) -> list[tuple]:
        return [(self.no, self.estagio, t, s, v, self.modo, self.job_chave, self.ficha, it["n"], self.rotulo,
                 json.dumps(it["detalhe"], ensure_ascii=False, default=str))
                for (t, s, v), it in sorted(self.itens.items())]

    def gravar(self, con) -> int:
        linhas = self.linhas()
        if not linhas:
            return 0
        con.execute(DDL)
        con.execute(DDL_IX)
        con.cursor().executemany(
            f"INSERT INTO {TABELA}(no, estagio, tipo, sha, versao, modo, job_chave, ficha, n, rotulo, detalhe) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", linhas)
        return len(linhas)


_ATUAL: Registro | None = None
_DESFAZER: list = []


def anotar(tipo: str, sha: str, versao: str | None = None, **detalhe) -> None:
    """Ponto único que os ganchos (e o navegador de replay do ensaio) chamam. Sem registro ativo, não faz nada."""
    if _ATUAL is not None:
        try:
            _ATUAL.anotar(tipo, sha, versao, **detalhe)
        except Exception as e:                                   # o registro nunca derruba o job
            print(f"leituras: anotação falhou — {type(e).__name__}: {e}", file=sys.stderr)


def _trocar(obj, nome: str, novo) -> None:
    velho = getattr(obj, nome)
    setattr(obj, nome, novo)
    _DESFAZER.append((obj, nome, velho))


def _gancho_fitz() -> None:
    try:
        import fitz
    except ImportError:
        return
    original = fitz.open

    @functools.wraps(original)
    def aberto(*a, **kw):
        alvo = a[0] if a else kw.get("filename")
        if isinstance(alvo, (str, Path)) and Path(alvo).is_file():
            anotar("pdf", sha_arquivo(alvo), arquivo=Path(alvo).name)
        return original(*a, **kw)
    _trocar(fitz, "open", aberto)


def _gancho_texto() -> None:
    from compliance_agent.sei import acervo_texto
    original = acervo_texto.ler

    @functools.wraps(original)
    def ler(pasta, doc, *a, **kw):
        t = original(pasta, doc, *a, **kw)
        if t:
            anotar("texto", sha_bytes(t.strip().encode("utf-8")), documento=str((doc or {}).get("texto") or ""))
        return t
    _trocar(acervo_texto, "ler", ler)


def _gancho_ocr() -> None:
    try:
        from compliance_agent.aplicacao.estagios import ocr as O
    except ImportError:
        return
    for cls in (O.ExecutorCPU, O.ExecutorTesseract):
        original = cls.ler_img

        def ler_img(self, img, _orig=original):
            try:
                motor = self.motor()
            except Exception:                                    # versão do motor ilegível não impede a anotação
                motor = getattr(self, "familia", "?")
            try:
                anotar("ocr_pagina", sha_bytes(img.tobytes()), versao=motor)
            except AttributeError:
                pass
            return _orig(self, img)
        _trocar(cls, "ler_img", ler_img)


def _chave_llm(mensagens, documentos) -> str:
    docs = [(getattr(d, "documento_id", None), getattr(d, "versao_sha256", None),
             sha_bytes(str(getattr(d, "texto", "")).encode("utf-8"))) for d in (documentos or [])]
    return sha_bytes(json.dumps({"m": mensagens, "d": docs}, ensure_ascii=False, sort_keys=True,
                                default=str).encode("utf-8"))


def _gancho_llm() -> None:
    from compliance_agent.adaptadores.llm import gateway as G
    original = G.chamar

    @functools.wraps(original)
    def chamar(tarefa, mensagens, *a, **kw):
        r = original(tarefa, mensagens, *a, **kw)                # recusa/exceção ⇒ não houve leitura
        anotar("llm", _chave_llm(mensagens, kw.get("documentos")), versao=str(kw.get("prompt_version") or "-"),
               tarefa=tarefa, modelo=getattr(r, "modelo", None))
        return r
    _trocar(G, "chamar", chamar)


def instrumentar(registro: Registro) -> Registro:
    """Liga os ganchos e torna `registro` o ativo. Idempotente por processo (desfaz antes de religar)."""
    global _ATUAL
    desinstrumentar()
    _ATUAL = registro
    for g in (_gancho_fitz, _gancho_texto, _gancho_ocr, _gancho_llm):
        try:
            g()
        except Exception as e:                                   # gancho que não instala é declarado, não derruba
            print(f"leituras: gancho {g.__name__} não instalou — {type(e).__name__}: {e}", file=sys.stderr)
    return registro


def desinstrumentar() -> None:
    global _ATUAL
    while _DESFAZER:
        obj, nome, velho = _DESFAZER.pop()
        setattr(obj, nome, velho)
    _ATUAL = None


def versao_do_estagio(estagio_obj) -> str:
    mod = sys.modules.get(getattr(estagio_obj.handler, "__module__", ""), None)
    return str(getattr(mod, "VERSAO", "-"))


def iniciar(ctx, modo: str, estagio_obj) -> Registro:
    """Chamado pelo processo-filho (`fluxo.executar`) antes do handler/efeito."""
    return instrumentar(Registro(estagio=ctx.tipo.split(":", 1)[0], versao=versao_do_estagio(estagio_obj),
                                 modo=modo if modo in MODOS else "rodar", job_chave=ctx.chave, ficha=ctx.ficha,
                                 no=ctx.no, rotulo=os.environ.get(ENV_ROTULO)))


def encerrar(registro: Registro, con=None) -> int:
    """Grava o registro no PG (esquema do fluxo) e desliga os ganchos. Falha ao gravar só vai ao stderr."""
    desinstrumentar()
    try:
        if con is None:
            from compliance_agent.fluxo import fila
            con = fila.conectar()
            try:
                return registro.gravar(con)
            finally:
                con.close()
        return registro.gravar(con)
    except Exception as e:
        print(f"leituras: registro não gravado — {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 0


# ── leitura do registro (puro sobre as linhas; o sensor e o ensaio usam) ─────────────────────────────────────────
def repetida_pct(leituras: int, distintas: int) -> float | None:
    """(leituras − distintas) ÷ leituras × 100. Sem leitura = None (não há o que medir — nunca 0 %)."""
    if leituras <= 0:
        return None
    return round(100.0 * (leituras - distintas) / leituras, 2)


def resumir(linhas: list[dict]) -> dict:
    """Linhas do registro → números do aceite. `linhas`: dicts com estagio, tipo, sha, versao, modo, n, job_chave."""
    rodar = [x for x in linhas if x["modo"] == "rodar"]
    por_chave: dict[tuple, list] = {}
    for x in rodar:
        por_chave.setdefault((x["estagio"], x["tipo"], x["sha"], x["versao"]), []).append(x)
    repetidas = {k: v for k, v in por_chave.items() if len(v) > 1}
    por_tipo: dict[str, int] = {}
    for x in rodar:
        por_tipo[x["tipo"]] = por_tipo.get(x["tipo"], 0) + 1
    no_job = [x for x in rodar if int(x.get("n") or 1) > 1]
    return {"leituras": len(rodar), "distintas": len(por_chave), "repetidas": sum(len(v) - 1 for v in repetidas.values()),
            "repetida_pct": repetida_pct(len(rodar), len(por_chave)),
            "downloads": por_tipo.get("download", 0), "llm": por_tipo.get("llm", 0), "por_tipo": por_tipo,
            "releituras_no_job": len(no_job),
            "releituras_no_job_por_estagio": _contar(x["estagio"] for x in no_job),
            "conferencia": len([x for x in linhas if x["modo"] == "conferir"]),
            "repetidas_lista": [{"estagio": k[0], "tipo": k[1], "sha": k[2][:16], "versao": k[3],
                                 "jobs": sorted({str(x.get("job_chave")) for x in v})[:6]}
                                for k, v in sorted(repetidas.items())[:50]]}


def _contar(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def ler_linhas(con, desde_s: float | None = None, rotulo: str | None = None) -> list[dict] | None:
    """Linhas do registro no esquema do fluxo; None = a tabela não existe (INDISPONÍVEL, não zero)."""
    if con.execute("SELECT to_regclass(%s)", (TABELA,)).fetchone()[0] is None:
        return None
    sql = f"SELECT estagio, tipo, sha, versao, modo, n, job_chave, rotulo FROM {TABELA} WHERE true"
    par: list = []
    if desde_s is not None:
        sql += " AND quando > now() - make_interval(secs => %s)"
        par.append(float(desde_s))
    if rotulo is not None:
        sql += " AND rotulo = %s"
        par.append(rotulo)
    cols = ("estagio", "tipo", "sha", "versao", "modo", "n", "job_chave", "rotulo")
    return [dict(zip(cols, r)) for r in con.execute(sql, par)]
