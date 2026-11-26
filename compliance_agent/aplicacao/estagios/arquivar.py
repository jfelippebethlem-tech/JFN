# -*- coding: utf-8 -*-
"""E7 `arquivar` — o ORIGINAL sai da VM pela PORTA ÚNICA, com md5 conferido, índice atualizado e o espaço liberado
medido (plano mestre v2 §3.2 E7, §3.5 "o PDF pendente de OCR nunca sai da VM-2"; item O3.4). Absorve
`sei_arquivo_frio`, `sei_compactar`, `arquivar_*_lane` e `hd_migracao` como DESTINO e REGRAS — o transporte é o de
`compliance_agent/armazenamento` (rclone, política por classe, pré-voo do grátis, índice único), nunca rsync/rclone
avulso (CLAUDE.md, NÃO REINVENTAR 11).

Entrada: `arquivar:<processo>|<doc_id>|<sha16>` — o evento `confirmar_ocr/*` (E6 concluído — 26/11/2026, antes era `ocr/terminado` e corria com o E6) ou `texto/sem_ocr` (E4). Payload
`{processo, doc_id, sha256, arquivo? | rel?, apagar? (padrão sim)}`.

TRAVAS, na ordem (cada uma testada):
  1. NADA QUE O E5 AINDA PRECISA SAI: a versão tem página `escaneada` no E4 e não tem `transformacao` `ocr` ⇒
     `OcrPendente` (o job volta com backoff; o PDF fica quente na VM-2). Também a fila LEGADA de OCR
     (`data/sei_ocr_gpu_fila.txt` e o que a reserva tem reservado), enquanto ela existir;
  2. o arquivo É a versão: sha256 recalculado = o da versão (senão ErroPermanente — outro arquivo no lugar);
  3. GUARDAR pela porta única (`Destino.guardar`, classe `sei_pdf` = re-obtível, 1 cópia no Drive);
  4. APAGAR SÓ DEPOIS DO HASH: a cópia conferida no índice (`Destino.conferir`: unidade com o md5 local e todas as
     vagas da política com cópia `ok`) E o md5 do arquivo RELIDO imediatamente antes de apagar = o mesmo. Qualquer
     um falhando ⇒ o arquivo fica e o efeito falha. `apagar=False` ⇒ só guarda. ORDEM: `arquivamento` apagado=false
     → unlink → `registrar_apagado` → UPDATE apagado=true; a retomada termina o apagado=false cujo arquivo já sumiu
     (só com a cópia conferida pela porta única).
Sem destino (rede, cota do grátis): erro transitório ⇒ fica quente na VM-2 até a nuvem voltar (§3.2 "sem o it-campo").
O ÍNDICE do HD externo (`tools/hd_indice --publicar`, com o 00-LEIAME, regra do dono de 23/11) é o passo `indice`
da rotina, depois do lote: a porta única já indexa cada arquivo no `data/armazenamento_indice.db`.

Saída (PG): `arquivamento` (sha256, md5, bytes, destino, chave no índice, cópias, apagado). Idempotente pela PK
(processo, doc_id, sha256, destino): repetir não duplica e o arquivo já apagado com cópia conferida é `ja_arquivado`.
Efeito conferido (outro processo): a linha existe; o índice da porta única confirma a cópia com o md5 gravado;
apagado ⇔ o arquivo não está mais no disco; não apagado ⇒ o arquivo segue com o mesmo md5.

CLI:
    python -m compliance_agent.aplicacao.estagios.arquivar indice        # tools.hd_indice --publicar (LEIAME)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Protocol

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import texto as T
from compliance_agent.fluxo.fila import Resultado

VERSAO = "e7-1"
CLASSE = "sei_pdf"
FILA_OCR_LEGADA = A.RAIZ / "data" / "sei_ocr_gpu_fila.txt"


class OcrPendente(RuntimeError):
    """O OCR desta versão ainda não terminou: o original não sai da VM-2 (o job tenta de novo depois)."""


def md5_arquivo(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ── destino (porta única; injetável) ───────────────────────────────────────────────────────────────────────────
class Destino(Protocol):
    nome: str

    def guardar(self, arquivo: Path) -> dict: ...            # {chave, md5, copias: {remoto: status}}

    def conferir(self, chave: str, md5: str) -> bool: ...

    def registrar_apagado(self, chave: str, arquivo: Path) -> None: ...


class PortaUnica:
    """`compliance_agent.armazenamento`: `guardar` (sobe + confere + indexa, SEM apagar — quem apaga é o E7, depois
    da própria conferência) e o índice para conferir e registrar o apagado (journal + `membros.local_apagado_em`)."""
    nome = "porta_unica"

    def guardar(self, arquivo: Path) -> dict:
        from compliance_agent import armazenamento as AR
        try:
            r = AR.guardar(arquivo, CLASSE, apagar_local=False)
        except AR.ErroArmazenamento as e:
            raise RuntimeError(f"porta única recusou {arquivo.name}: {e} — fica quente até a nuvem voltar") from e
        con = AR.conectar()
        try:
            u = con.execute("SELECT md5 FROM unidades WHERE chave = ?", (r["chave"],)).fetchone()
        finally:
            con.close()
        return {"chave": r["chave"], "md5": u["md5"] if u else None, "copias": r["copias"]}

    def conferir(self, chave: str, md5: str) -> bool:
        from compliance_agent import armazenamento as AR
        con = AR.conectar()
        try:
            u = con.execute("SELECT md5, natureza FROM unidades WHERE chave = ?", (chave,)).fetchone()
            oks = {c["destino"] for c in con.execute("SELECT destino FROM copias WHERE chave = ? AND status = 'ok'",
                                                     (chave,))}
        finally:
            con.close()
        return u is not None and u["md5"] == md5 and AR.vagas_satisfeitas(u["natureza"], oks)

    def registrar_apagado(self, chave: str, arquivo: Path) -> None:
        from compliance_agent import armazenamento as AR
        con = AR.conectar()
        try:
            AR.journal(con, "apagar_local", str(arquivo), "E7 arquivar: cópia conferida por md5", f"e7-{chave}")
            con.execute("UPDATE membros SET local_apagado_em = ? WHERE chave = ?", (AR.agora(), chave))
            con.commit()
        finally:
            con.close()


def obter_destino() -> Destino:
    return PortaUnica()


# ── travas ─────────────────────────────────────────────────────────────────────────────────────────────────────
def fila_ocr_legada() -> set[str]:
    """`integra_<tag>/NNN.pdf` que o OCR legado ainda vai ler: a fila da GPU e o que a reserva tem reservado."""
    out = set()
    if FILA_OCR_LEGADA.is_file():
        out |= {ln.strip() for ln in FILA_OCR_LEGADA.read_text(encoding="utf-8").splitlines() if ln.strip()}
    from tools.sei_ocr_reserva import reservados_pela_reserva
    return out | set(reservados_pela_reserva())


def ocr_pendente(con, processo: str, doc_id: str, sha: str, rel: str | None, raiz: Path | None,
                 legada: set[str]) -> str | None:
    """Motivo se o E5 ainda precisa deste original; None se pode sair."""
    if rel:                                  # item legado: o OCR dele é o da fila legada (GPU/reserva)
        return "na fila legada de OCR (GPU/reserva)" if rel in legada else None
    lat = T.ler_lateral(T.caminho_lateral(processo, doc_id, sha, "e4", raiz))
    if lat is None:
        return "sem texto do E4 (não sei se há página escaneada)"
    escaneadas = lat[0].get("escaneadas")
    if escaneadas and T.transformacao_de(con, processo, doc_id, O.TIPO_TRANSFORMACAO, sha) is None:
        return f"{len(escaneadas)} página(s) escaneada(s) sem OCR terminado"
    return None


def localizar(con, processo: str, doc_id: str, sha: str, payload: dict) -> Path | None:
    """O original local (sem baixar do frio: o que já saiu não é para trazer de volta)."""
    if payload.get("rel"):
        for raiz in O.raizes_legado():
            p = raiz / str(payload["rel"])
            if p.is_file():
                return p
        return None
    try:
        return T.localizar_binario(con, processo, doc_id, sha, payload.get("arquivo"))
    except RuntimeError:
        return None


# ── PG ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def registro(con, processo: str, doc_id: str, sha: str, destino: str) -> dict | None:
    r = con.execute("SELECT md5, bytes, chave, copias, origem, apagado FROM arquivamento WHERE processo = %s AND "
                    "doc_id = %s AND sha256 = %s AND destino = %s", (processo, doc_id, sha, destino)).fetchone()
    return None if r is None else dict(zip(("md5", "bytes", "chave", "copias", "origem", "apagado"), r))


def _marcar_apagado(con, processo: str, doc_id: str, sha: str, destino: str) -> None:
    con.execute("UPDATE arquivamento SET apagado = true, em = now() WHERE processo = %s AND doc_id = %s AND "
                "sha256 = %s AND destino = %s", (processo, doc_id, sha, destino))


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo, doc_id, sha = T.alvo_do(payload, ctx)
    raiz = Path(payload["raiz_texto"]) if payload.get("raiz_texto") else None
    apagar = payload.get("apagar", True) is not False
    destino = obter_destino()
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        pdf = localizar(con, processo, doc_id, sha, payload)
        sha = sha or (T.sha256_arquivo(pdf) if pdf is not None else "")     # item legado: o arquivo achado
        ja = registro(con, processo, doc_id, sha, destino.nome) if sha else None
        if pdf is None:
            if ja and not ja["apagado"]:                     # retomada: caiu entre o unlink e o UPDATE (1.4)
                if not destino.conferir(ja["chave"], ja["md5"]):
                    raise RuntimeError(f"{processo} {doc_id}: original {sha[:12]} sumiu do disco e a cópia "
                                       f"{ja['chave']} não confere na porta única — arquivamento fica apagado=false")
                destino.registrar_apagado(ja["chave"], Path(ja["origem"]))
                _marcar_apagado(con, processo, doc_id, sha, destino.nome)
                ja["apagado"] = True
            if ja and ja["apagado"]:                         # idempotente: já saiu com cópia conferida
                ef = {"processo": processo, "doc_id": doc_id, "sha256": sha, "destino": destino.nome, **ja,
                      "ja_arquivado": True, "liberado_bytes": 0, "versao": VERSAO}
                return Resultado(efeito=ef, eventos=[])
            raise RuntimeError(f"{processo} {doc_id}: original {sha[:12]} não está no disco e não há arquivamento")
        motivo = ocr_pendente(con, processo, doc_id, sha, payload.get("rel"), raiz, obter_fila_legada())
        if motivo:
            raise OcrPendente(f"{processo} {doc_id}: {motivo} — o original fica na VM-2")
        if T.sha256_arquivo(pdf) != sha:
            raise ErroPermanente(f"{processo} {doc_id}: {pdf.name} não é a versão {sha[:12]}")
        md5, nbytes = md5_arquivo(pdf), pdf.stat().st_size
        g = destino.guardar(pdf)
        conferido = g.get("md5") == md5 and destino.conferir(g["chave"], md5)
        apagado = False
        if conferido:                       # o registro (apagado=false) vem ANTES do unlink: INSERT que falha ⇒ fica
            with con.transaction():
                con.execute("INSERT INTO arquivamento(processo, doc_id, sha256, md5, bytes, destino, chave, copias, "
                            "origem, apagado, job_chave, ficha) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT ON CONSTRAINT arquivamento_pk DO UPDATE SET md5 = excluded.md5, copias = "
                            "excluded.copias, apagado = arquivamento.apagado OR excluded.apagado, job_chave = "
                            "excluded.job_chave, ficha = excluded.ficha, em = now()",
                            (processo, doc_id, sha, md5, nbytes, destino.nome, g["chave"],
                             json.dumps(g.get("copias") or {}), str(pdf), False, ctx.chave, ctx.ficha))
            if apagar and md5_arquivo(pdf) == md5:                       # relido IMEDIATAMENTE antes de apagar
                pdf.unlink()
                destino.registrar_apagado(g["chave"], pdf)
                _marcar_apagado(con, processo, doc_id, sha, destino.nome)
                apagado = True
    finally:
        con.close()
    ef = {"processo": processo, "doc_id": doc_id, "sha256": sha, "destino": destino.nome, "md5": md5, "bytes": nbytes,
          "chave": g["chave"], "copias": g.get("copias"), "origem": str(pdf), "conferido": conferido,
          "apagado": apagado, "pedido_apagar": apagar, "liberado_bytes": nbytes if apagado else 0,
          "ja_arquivado": False, "versao": VERSAO, "em": time.strftime("%Y-%m-%d %H:%M:%S")}
    ev = [{"fonte": "arquivar", "tipo": "arquivado", "chave": f"{processo}|{doc_id}",
           "detalhe": {"sha256": sha, "apagado": apagado, "liberado_bytes": ef["liberado_bytes"]}}] if conferido else []
    return Resultado(efeito=ef, eventos=ev)


def obter_fila_legada() -> set[str]:
    return fila_ocr_legada()


def conferir(con, ef: dict) -> dict:
    r = registro(con, ef["processo"], ef["doc_id"], ef["sha256"], ef["destino"])
    if r is None:
        return {"ok": False, "motivo": "arquivamento não está no PG (cópia não conferida — o original ficou)"}
    origem = Path(r["origem"])
    c = {"md5_declarado": r["md5"] == ef["md5"],
         "copia_no_indice": obter_destino().conferir(r["chave"], r["md5"]),
         "apagado_coerente": (not origem.exists()) if r["apagado"] else
         (origem.is_file() and md5_arquivo(origem) == r["md5"])}
    if ef.get("pedido_apagar") and not ef.get("ja_arquivado"):
        c["apagado_quando_pedido"] = bool(r["apagado"])
    c["ok"] = all(c.values())
    return c


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        c = conferir(con, resultado.efeito)
    finally:
        con.close()
    resultado.efeito["conferencia"] = c
    return bool(c["ok"])


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["disco"], prioridade=80,
                  volta={"nos": ["vm2"], "nota": "fica quente na VM-2 (com quota) até o destino voltar"})


def publicar_indice() -> int:
    """O índice + 00-LEIAME do HD externo (regra do dono, 23/11): `tools.hd_indice --publicar`, como está."""
    from tools import hd_indice
    return hd_indice.main(["--publicar"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E7 arquivar (O3.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("indice")
    ap.parse_args(argv)
    return publicar_indice()


if __name__ == "__main__":
    sys.exit(main())
