# -*- coding: utf-8 -*-
"""J5 · DIGITAIS COMPARTILHADAS (metadados, redação e origem) — spec V2 do dono, §4/J5.

Mecanismo: propostas 'concorrentes' produzidas pela MESMA pessoa/escritório carregam vestígios. Metadados de
arquivo (Author/Creator/Producer/CreateDate/ModDate, fontes embutidas), erros idênticos, mesma formatação, mesmo
IP/horário de envio, mesmo contador (CRC)/advogado (OAB)/telefone/e-mail. A OCDE lista propostas idênticas ou com
metadados/formatação similares como red flag.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Metadado NÃO-GENÉRICO compartilhado entre licitantes distintos (mesmo Author/Creator não-genérico;
    mesmo CreateDate; hash de imagem/fonte embutida idêntico) ........................................ 'forte'
  • Mesmo contador (CRC) / advogado (OAB) / telefone / e-mail entre licitantes distintos ............. 'forte'
  • Mesmo IP de envio entre licitantes distintos .................................................... 'critico'
  • Mesmo horário de envio (timestamp idêntico) entre licitantes distintos .......................... 'forte'
  Producer/Creator GENÉRICO ('Microsoft Word', 'Adobe PDF', 'LibreOffice', ...) NÃO pontua — é universal;
  só campos NÃO-genéricos sustentam a coincidência (regra exculpatória embutida no código).

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada "erros e idiossincrasias textuais compartilhados"
[sem_coincidencias / coincidencias_de_template_de_mercado / erros_identicos_improvaveis]. A última (mesmo erro
ortográfico raro, mesma frase truncada, mesmo valor digitado errado) → 'forte'. Evidência exigida: os trechos
idênticos lado a lado. Sem LLM/rubrica → o componente subjetivo fica nao_avaliavel (as coincidências objetivas de
metadado/contato permanecem).

TESTE EXCULPATÓRIO (spec): Producer idêntico genérico é universal (não pontua). Despachantes/consultorias legítimas
preparam propostas de vários clientes — mas para certames DIFERENTES; no MESMO certame a coincidência de autoria é
indício forte mesmo assim (revela compartilhamento de informação de preço). Cadeia de custódia frágil: registrar
hash/origem de cada arquivo (metadados são frágeis juridicamente se a coleta for mal documentada).

HONESTIDADE JFN: indício ≠ acusação; sem `propostas` (ou <2 com metadados/contatos) → nao_avaliavel (campo ausente
≠ 0); nunca inventa número.
"""
from __future__ import annotations

from itertools import combinations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada dos erros/idiossincrasias textuais compartilhados (spec J5). LLM-opcional; degrada honesto.
_RUBRICA_ERROS = {
    "sem_coincidencias": "ausente",                  # textos independentes
    "coincidencias_de_template_de_mercado": "fraco",  # modelo de mercado comum (explicação inocente)
    "erros_identicos_improvaveis": "forte",          # mesmo erro raro/frase truncada/valor digitado errado
}

# Termos GENÉRICOS de Producer/Creator/Author que NÃO pontuam (universais — software/conversores comuns).
# Comparação por substring case-insensitive: se o valor CONTÉM qualquer um destes, é considerado genérico.
_TERMOS_GENERICOS = (
    "microsoft word", "microsoft office", "word", "office",
    "adobe", "acrobat", "pdf", "distiller",
    "libreoffice", "openoffice", "writer", "calc",
    "pdfcreator", "ghostscript", "pdflatex", "latex", "tex",
    "google docs", "google", "wps", "foxit", "nitro", "skia",
    "printer", "scanner", "scan", "canon", "hp ", "xerox", "epson",
    "windows user", "usuario", "usuário", "user", "admin", "owner", "dono",
    "iText".lower(), "reportlab", "chromium", "chrome",
)

# Campos de metadado NÃO-GENÉRICOS cuja coincidência pontua (Producer fica de fora — é universal por natureza).
_CAMPOS_METADADO_FORTES = ("author", "creator", "create_date", "createdate")

# Mínimo de licitantes com dados para avaliar a coincidência (comparação par-a-par exige ≥2).
_MIN_LICITANTES = 2


def _norm(v) -> str:
    """Normaliza um valor de metadado/contato para comparação (lower + strip). Vazio → ''."""
    if v is None:
        return ""
    return str(v).strip().lower()


def _eh_generico(valor: str) -> bool:
    """True se o valor (normalizado) é um termo GENÉRICO/universal que NÃO deve pontuar."""
    if not valor:
        return True
    return any(t in valor for t in _TERMOS_GENERICOS)


def _licitante(p: dict) -> str:
    return str(p.get("licitante_cnpj") or p.get("cnpj") or p.get("licitante") or "?")


class J5DigitaisCompartilhadas(Detector):
    """Detector J5 — digitais compartilhadas (metadados/redação/origem) (OECD bid-rigging).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["propostas"]: list[dict] — uma por licitante (ESSENCIAL; <2 úteis → nao_avaliavel). Cada item:
        {
          "licitante_cnpj": str,
          "metadados": {"author","creator","producer","create_date","mod_date", ...},  # exiftool
          "contatos": {"telefone","email","contador_crc","advogado_oab"},
          "hashes_embutidos": [str, ...],   # sha de imagens/fontes/planilhas embutidas
          "ip_envio": str,                  # log da plataforma (quando houver)
          "horario_envio": str,             # timestamp de envio (quando houver)
        }
      contexto["_rubrica_erros"] (opcional, teste): rubrica pré-classificada dos erros textuais compartilhados.
      contexto["gerar"] (opcional): callable (prompt, sistema)->str p/ a rubrica LLM. Sem ambos → subjetivo
        nao_avaliavel (honesto).

    REGRA DE PAPÉIS: o CÓDIGO faz toda comparação par-a-par e o limiar; o LLM só classifica a rubrica fechada dos
    erros textuais + cita o trecho. Producer genérico nunca pontua (universal). Honesto: sem propostas / <2 com
    metadados ou contatos → nao_avaliavel (campo ausente ≠ 0)."""

    id = "J5"
    nome = "Digitais compartilhadas (metadados, redação e origem)"
    familia = "conluio"  # J5 — peso 0.9 (conluio) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        propostas = [p for p in (contexto.get("propostas") or []) if isinstance(p, dict)]
        # propostas COM algum dado comparável (metadados, contatos, hashes, ip ou horário)
        uteis = [
            p for p in propostas
            if p.get("metadados") or p.get("contatos") or p.get("hashes_embutidos")
            or p.get("ip_envio") or p.get("horario_envio")
        ]
        if len(uteis) < _MIN_LICITANTES:
            res.motivo_refutacao = (
                "nao_avaliavel: menos de 2 propostas com metadados/contatos/origem — sem os arquivos originais "
                "(exiftool/logs da plataforma) não há digitais a cruzar (campo ausente ≠ 0). Coletar PDFs/DOCX "
                "originais — impressões/re-digitalizações destroem os metadados.")
            res.valores = {"n_propostas": len(propostas), "n_uteis": len(uteis), "tem_dados": False}
            return res

        valores: dict = {"n_propostas": len(propostas), "n_uteis": len(uteis)}
        score = 0.0
        razoes: list[str] = []
        coincidencias: dict[str, list] = {
            "metadado": [], "contato": [], "hash_embutido": [], "ip_envio": [], "horario_envio": [],
        }

        # ── comparação PAR-A-PAR (CÓDIGO faz toda a comparação e o limiar) ──
        for a, b in combinations(uteis, 2):
            la, lb = _licitante(a), _licitante(b)
            if la == lb:
                continue  # mesmo licitante (não é coincidência entre concorrentes distintos)

            # 1) metadados não-genéricos (author/creator/create_date) idênticos
            ma = {k: _norm(v) for k, v in (a.get("metadados") or {}).items()}
            mb = {k: _norm(v) for k, v in (b.get("metadados") or {}).items()}
            for campo in _CAMPOS_METADADO_FORTES:
                va, vb = ma.get(campo, ""), mb.get(campo, "")
                if va and va == vb and not _eh_generico(va):
                    score = max(score, ancora("forte"))
                    coincidencias["metadado"].append({"campo": campo, "valor": va, "licitantes": [la, lb]})
                    razoes.append(f"metadado não-genérico '{campo}'='{va}' idêntico entre {la} e {lb}")
                    res.add_evidencia(
                        fonte=f"exiftool · {campo} (licitantes {la} × {lb})",
                        trecho=f"{campo}: {va!r} idêntico em {la} e {lb} (não-genérico)")

            # 2) contatos/profissionais idênticos (telefone/email/contador CRC/advogado OAB)
            ca = {k: _norm(v) for k, v in (a.get("contatos") or {}).items()}
            cb = {k: _norm(v) for k, v in (b.get("contatos") or {}).items()}
            for campo in ("contador_crc", "advogado_oab", "telefone", "email"):
                va, vb = ca.get(campo, ""), cb.get(campo, "")
                if va and va == vb:
                    score = max(score, ancora("forte"))
                    coincidencias["contato"].append({"campo": campo, "valor": va, "licitantes": [la, lb]})
                    razoes.append(f"mesmo {campo}='{va}' entre licitantes distintos {la} e {lb}")
                    res.add_evidencia(
                        fonte=f"contatos do documento · {campo} (licitantes {la} × {lb})",
                        trecho=f"{campo}: {va!r} compartilhado por {la} e {lb}")

            # 3) hash de componente embutido (imagem/fonte/planilha) idêntico
            ha = {_norm(h) for h in (a.get("hashes_embutidos") or []) if _norm(h)}
            hb = {_norm(h) for h in (b.get("hashes_embutidos") or []) if _norm(h)}
            for h in sorted(ha & hb):
                score = max(score, ancora("forte"))
                coincidencias["hash_embutido"].append({"hash": h, "licitantes": [la, lb]})
                razoes.append(f"componente embutido (imagem/fonte) de hash idêntico entre {la} e {lb}")
                res.add_evidencia(
                    fonte=f"hash de componente embutido (licitantes {la} × {lb})",
                    trecho=f"hash embutido {h[:24]}… idêntico em {la} e {lb}")

            # 4) mesmo IP de envio → crítico
            ipa, ipb = _norm(a.get("ip_envio")), _norm(b.get("ip_envio"))
            if ipa and ipa == ipb:
                score = max(score, ancora("critico"))
                coincidencias["ip_envio"].append({"ip": ipa, "licitantes": [la, lb]})
                razoes.append(f"mesmo IP de envio {ipa} entre {la} e {lb} (origem única — crítico)")
                res.add_evidencia(
                    fonte=f"log da plataforma · IP de envio (licitantes {la} × {lb})",
                    trecho=f"IP {ipa} idêntico no envio de {la} e {lb}")

            # 5) mesmo horário de envio (timestamp idêntico) → forte
            ta, tb = _norm(a.get("horario_envio")), _norm(b.get("horario_envio"))
            if ta and ta == tb:
                score = max(score, ancora("forte"))
                coincidencias["horario_envio"].append({"horario": ta, "licitantes": [la, lb]})
                razoes.append(f"mesmo horário de envio {ta} entre {la} e {lb}")
                res.add_evidencia(
                    fonte=f"log da plataforma · horário de envio (licitantes {la} × {lb})",
                    trecho=f"horário de envio {ta} idêntico em {la} e {lb}")

        valores["coincidencias"] = coincidencias
        n_coinc = sum(len(v) for v in coincidencias.values())
        valores["n_coincidencias"] = n_coinc

        # ── PARTE SUBJETIVA (LLM-opcional): erros/idiossincrasias textuais compartilhados ──
        sub = self._avaliar_rubrica(contexto)
        valores["erros_textuais"] = sub["status"]
        if sub["status"] == "erros_identicos_improvaveis":
            score = max(score, ancora("forte"))
            razoes.append("rubrica: erros idênticos improváveis (mesmo erro raro/frase truncada/valor digitado errado)")
            trecho = sub.get("trecho") or "trechos idênticos lado a lado (ver rubrica)"
            res.add_evidencia(fonte="rubrica LLM · erros textuais compartilhados", trecho=str(trecho)[:300])
        elif sub["status"] == "coincidencias_de_template_de_mercado":
            razoes.append("rubrica: coincidências de template de mercado (registra; não pontua sozinho)")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                "sem digitais compartilhadas: metadados coincidentes são genéricos/universais (Producer 'Microsoft "
                "Word' etc. não pontua) ou ausentes; sem contato/hash/IP/horário comum entre licitantes distintos")
            res.valores = valores
            res.explicacao_inocente = (
                "coincidências apenas em campos genéricos (software universal) ou ausência de coincidência — "
                "concorrência real com ferramentas de mercado comuns")
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSOS POSITIVOS a descartar (spec J5): Producer idêntico GENÉRICO ('Microsoft Word', 'Adobe PDF') é "
            "universal — não pontua (só campos não-genéricos contam). Despachantes/consultorias de licitação legítimas "
            "preparam propostas de vários clientes — mas para certames DIFERENTES; no MESMO certame a coincidência de "
            "autoria é indício forte mesmo assim, pois revela que os 'concorrentes' compartilham informação de preço. "
            "Cadeia de custódia: metadados são frágeis juridicamente — confirmar hash/origem de cada arquivo no momento "
            "da coleta (PDFs/DOCX originais, não impressões/re-digitalizações).")
        return res

    def _avaliar_rubrica(self, contexto: dict) -> dict:
        """Rubrica fechada dos erros/idiossincrasias textuais compartilhados. Atalho de teste: `_rubrica_erros`
        injetado no contexto. Sem rubrica e sem LLM → nao_avaliavel honesto (as coincidências objetivas permanecem)."""
        pre = contexto.get("_rubrica_erros")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_ERROS)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {
                "status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(),
                "trecho": (pre.get("trecho") or pre.get("citacao") or "").strip(),
                "motivo": motivo,
            }
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — erros textuais não auditados (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Compare a redação das propostas e classifique os ERROS e "
            "idiossincrasias textuais COMPARTILHADOS conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"sem_coincidencias|coincidencias_de_template_de_mercado|erros_identicos_improvaveis",'
            '"trecho":"<os trechos idênticos lado a lado>"}. Sem trecho, não classifique.')
        propostas = contexto.get("propostas") or []
        amostras = []
        for p in propostas[:6]:
            if isinstance(p, dict) and p.get("texto"):
                amostras.append(f"{_licitante(p)}: {str(p.get('texto'))[:400]}")
        prompt = (
            "Trechos de redação das propostas (por licitante):\n" + "\n".join(amostras)[:3000] + "\n\n"
            "Há erros idênticos improváveis (mesmo erro ortográfico raro, mesma frase truncada, mesmo valor digitado "
            "errado), apenas coincidências de template de mercado, ou sem coincidências?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_ERROS)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {
            "status": (dados.get("nivel") or "").strip().lower(),
            "trecho": (dados.get("trecho") or dados.get("citacao") or "").strip(),
            "motivo": motivo,
        }
