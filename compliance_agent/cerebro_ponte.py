# -*- coding: utf-8 -*-
"""cerebro_ponte — liga a AUTOMELHORIA e as PERÍCIAS POR AGENTE ao segundo cérebro (docs/ARQUITETURA-SEGUNDO-CEREBRO.md).

Duas fontes que aprendiam e não registravam:
  · `data/autoaprimoramento/auto.db` — cada versão da rubrica e o que o PORTÃO decidiu dela (candidato, reprovado,
    sombra, campeão). Vira o fato `autoaprimoramento:<versão>`; mudou o status, o texto muda e o cérebro recebe a
    correção com `supersedes` (quem controla é o registro de `cerebro_compartilhado`, chave estável).
  · `data/pericia_agentes/<tag>.json` — laudo de leitura integral. Vira `pericia-agente:<tag>` (fato do caso) e
    `licao-pericia:<tag>` (lição CANDIDATA: não validada pelo portão, não entra em prompt).

Nível de prova é MEDIDO aqui, por código, não declarado pelo agente: a citação literal do achado (o trecho entre
aspas de `prova`) tem de existir no texto arquivado do processo (`data/sei_arquivo/<tag>/texto`, `data/sei_cache/
integra_<tag>`); cada OB listada tem de existir no SIAFE com o mesmo valor. Achado com citação conferida = nível 2
(fonte primária) e vai ao cérebro com o grau; os demais ficam contados como nível 1 e só aparecem na nota do vault,
marcados. Texto do processo indisponível = nível 1 (INDISPONÍVEL ≠ conferido).

Cruzamento por entidade: tabela `ponte_entidade` (CNPJ, processo, UG × fato × papel) no mesmo banco do registro —
`entidade <termo>` devolve tudo o que se sabe de uma empresa/processo/UG; `cruzar` lista o CNPJ que aparece em mais
de um processo (credor num, licitante perdedor noutro). Notas geradas em `~/vault/jfn/` (pasta dos retratos gerados).

Nada aqui chama LLM nem a rede: `sincronizar` só registra; quem envia é o despachante da propagação (*/5).
CPF e e-mail são mascarados antes de sair; texto que cite WhatsApp é barrado (regra do dono).

CLI:  python -m compliance_agent.cerebro_ponte sincronizar [--max-novos N] | entidade <termo> | cruzar
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from compliance_agent import cerebro_compartilhado as cerebro
from compliance_agent import cores_orgaos
from compliance_agent.autoaprimoramento import armadilhas, config as auto_config
from compliance_agent.certeza.fatos import brl

RAIZ = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data")
VAULT = Path(os.environ.get("JFN_VAULT") or Path.home() / "vault")
MIN_TRECHO = 20             # caracteres alfanuméricos: abaixo disso o trecho casa por acaso e não prova nada
AVISO = "Indício é hipótese a verificar, não acusação; vigora a presunção de legitimidade."

DDL = """
CREATE TABLE IF NOT EXISTS ponte_entidade(tipo TEXT, valor TEXT, chave TEXT, papel TEXT, PRIMARY KEY(tipo, valor, chave, papel));
CREATE TABLE IF NOT EXISTS ponte_laudo(tag TEXT PRIMARY KEY, hash TEXT, conferencia TEXT);
"""
_PESSOAL = tuple(rx for nome, rx in cerebro._RECUSAS if nome in ("cpf", "cpf mascarado", "e-mail"))
_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_ASPAS = re.compile(r'"([^"]+)"|“([^”]+)”')
_CORTE = re.compile(r"\[\s*(?:\.\.\.|…)\s*\]|\(\s*(?:\.\.\.|…)\s*\)|\.\.\.|…")


def limpar(texto) -> str:
    """Mascara CPF (inteiro ou já mascarado) e e-mail. CNPJ fica: é dado público."""
    guardados: list[str] = []

    def guarda(m):
        guardados.append(m.group(0))
        return f"\x00{len(guardados) - 1}\x00"
    t = _CNPJ.sub(guarda, str(texto or ""))
    for rx in _PESSOAL:
        t = rx.sub("[dado pessoal omitido]", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: guardados[int(m.group(1))], t)


def normalizar(texto: str) -> str:
    """Só letras e dígitos, sem caixa: quebra de linha, espaço duplo e pontuação do OCR não atrapalham. O acento
    fica (o agente cita o texto que leu); tirar acento em Python custava ~3 s por MB com a máquina carregada."""
    return re.sub(r"[\W_]+", "", (texto or "").lower())


def citacao_conferida(prova: str, corpus_norm: str) -> bool | None:
    """True se ALGUM trecho entre aspas existe literalmente no processo (todas as partes de um trecho com reticências
    têm de existir); False se há trecho longo e nenhum existe; None se não há trecho que se possa conferir."""
    viu = False
    for m in _ASPAS.finditer(prova or ""):
        partes = [p for p in (normalizar(x) for x in _CORTE.split(m.group(1) or m.group(2))) if len(p) >= MIN_TRECHO]
        if partes:
            viu = True
            if all(p in corpus_norm for p in partes):
                return True
    return False if viu else None


def conferir(laudo: dict, corpus: str | None, ob_siafe) -> dict:
    """Confere o laudo NA FONTE por código. `corpus` = texto arquivado do processo (None = indisponível);
    `ob_siafe(numero, ug) -> [valores]` (None = não conferido)."""
    achados = laudo.get("achados_principais") or []
    norm = normalizar(corpus) if corpus else None
    marcas = [citacao_conferida(a.get("prova", ""), norm) if norm else None for a in achados]
    obs = [o for o in ((laudo.get("pago_ob") or {}).get("obs") or []) if isinstance(o, dict) and o.get("numero_ob")]
    ok = None
    if ob_siafe is not None:
        ok = sum(1 for o in obs if isinstance(o.get("valor"), (int, float))
                 and any(abs(v - o["valor"]) < 0.01 for v in ob_siafe(str(o["numero_ob"]), str(o.get("ug") or ""))))
    return {"achados": marcas, "nivel": 2 if any(m is True for m in marcas) else 1, "fonte_lida": norm is not None,
            "ob_total": len(obs), "ob_ok": ok}


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _dinheiro(v) -> str:
    return brl(v) if isinstance(v, (int, float)) else "INDISPONÍVEL"


def _entidades(laudo: dict) -> list[tuple]:
    ents = [("processo", str(laudo.get("processo") or "").removeprefix("SEI-"), "processo")]
    cred = _digitos((laudo.get("credor") or {}).get("cnpj"))
    if len(cred) == 14:
        ents.append(("cnpj", cred, "credor"))
    for lic in laudo.get("licitantes") or []:
        c = _digitos(lic.get("cnpj")) if isinstance(lic, dict) else ""
        if len(c) == 14 and (c != cred or not lic.get("venceu")):
            ents.append(("cnpj", c, "licitante vencedor" if lic.get("venceu") else "licitante perdedor"))
    for o in (laudo.get("pago_ob") or {}).get("obs") or []:
        if isinstance(o, dict) and _digitos(o.get("ug")):
            ents.append(("ug", _digitos(o["ug"]), "ug pagadora"))
    return sorted(set(ents))


def fatos_do_laudo(laudo: dict, conf: dict) -> list[dict]:
    """Fato do caso (+ lição candidata, se houver) prontos para o registro do cérebro. Só achado com citação conferida
    leva título e grau; o resto é contado."""
    tag, proc = laudo["tag"], laudo.get("processo") or laudo["tag"]
    cred = laudo.get("credor") or {}
    lido = laudo.get("lido") or {}
    achados = laudo.get("achados_principais") or []
    provados = [a for a, m in zip(achados, conf["achados"]) if m is True]
    pago = laudo.get("pago_ob") or {}
    ob = ("OB não conferidas por código" if conf["ob_ok"] is None
          else f"{conf['ob_ok']} de {conf['ob_total']} OB conferidas no SIAFE por número e valor")
    partes = [f"Perícia por agente (JFN, data/pericia_agentes/{tag}.json; {lido.get('docs_lidos', '?')} de "
              f"{lido.get('docs_total', '?')} documentos lidos) — {proc} · credor {cred.get('nome', 'INDISPONÍVEL')} "
              f"(CNPJ {cred.get('cnpj', 'INDISPONÍVEL')}) · objeto: {str(laudo.get('objeto') or '')[:160]} · contratado "
              f"{_dinheiro(laudo.get('valor_contratado'))} · pago por OB {_dinheiro(pago.get('total'))} ({ob})."]
    if provados:
        partes.append("Achados com citação literal localizada no texto do processo (nível 2, fonte primária): " + "; ".join(
            f"{a.get('grau', '')} {a.get('titulo', '')}"
            + (f" ({brl(a['valor_envolvido'])})" if isinstance(a.get("valor_envolvido"), (int, float)) else "")
            for a in provados) + ".")
    else:
        partes.append("Nenhum achado com citação conferida por código (nível 1: "
                      + ("citações não localizadas" if conf["fonte_lida"] else "texto do processo indisponível") + ").")
    resto = len(achados) - len(provados)
    if resto and provados:
        partes.append(f"{resto} achado(s) sem conferência por código (nível 1) ficam só no laudo.")
    partes.append(AVISO)
    fatos = [{"chave": f"pericia-agente:{tag}", "kind": "semantica", "assunto": limpar(cred.get("nome") or proc)[:120],
              "texto": limpar(" ".join(partes)), "entidades": _entidades(laudo)}]
    licao = " ".join(str(laudo.get("aprendizado") or "").split())
    if licao:
        fatos.append({"chave": f"licao-pericia:{tag}", "kind": "procedural", "assunto": "lição candidata da perícia",
                      "texto": limpar(f"LIÇÃO CANDIDATA da perícia por agente ({proc}; leitura integral do processo; NÃO "
                                      f"validada pelo portão da automelhoria; não entra em prompt): {licao}"),
                      "entidades": []})
    for f in fatos:
        if "whatsapp" in f["texto"].lower():
            raise ValueError(f"{tag}: texto cita WhatsApp — não vai para nenhuma camada")
    return fatos


def fatos_da_automelhoria(con: sqlite3.Connection) -> list[dict]:
    """Um fato por versão da rubrica, com o status vigente e quem o decidiu (último evento do registro)."""
    fatos = []
    for chave, conteudo, status, origem, criado in con.execute(
            "SELECT chave, conteudo, status, origem, criado_em FROM versao ORDER BY n").fetchall():
        c = json.loads(conteudo)
        ev = con.execute("SELECT motivo, quem, em FROM evento_registro WHERE chave=? ORDER BY id DESC LIMIT 1",
                         (chave,)).fetchone() or (origem, "sistema", criado)
        licoes = "; ".join(armadilhas.POR_ID[i]["licao"] for i in c.get("licoes") or []) or "nenhuma (rubrica de partida)"
        estado = "CANDIDATO (aguarda o portão)" if status == "candidato" and ev[1] != "portao" else status.upper()
        fatos.append({"chave": f"autoaprimoramento:{chave}", "kind": "experiencial", "assunto": "automelhoria da perícia",
                      "status": status, "em": ev[2], "motivo": ev[0] or "", "quem": ev[1], "licoes": licoes,
                      "texto": limpar(f"Automelhoria da perícia de execução (JFN, data/autoaprimoramento/auto.db) — versão "
                                      f"{chave}, origem: {origem}. Status {estado} em {ev[2]}, decidido por {ev[1]}: "
                                      f"{ev[0] or 'sem motivo registrado'}. Lições da versão: {licoes}. Filtros: "
                                      f"{', '.join(c.get('filtros') or []) or 'nenhum'}."),
                      "entidades": [("versao", chave, status)]})
    return fatos


def _corpus(tag: str, completo: bool = True) -> str | None:
    """Texto arquivado do processo. `completo=False` lê só `sei_arquivo` (o grosso das citações está lá); o cache das
    íntegras (OCR dos escaneados) só é lido quando sobra citação por localizar — ler tudo sempre custava minutos."""
    pastas = [DATA / "sei_arquivo" / tag / "texto"] + ([DATA / "sei_cache" / f"integra_{tag}"] if completo else [])
    textos = [f.read_text(encoding="utf-8", errors="replace") for p in pastas if p.is_dir() for f in sorted(p.glob("*.txt"))]
    return "\n".join(textos) if textos else None


def _ob_siafe_ro():
    db = DATA / "compliance.db"
    if not db.exists():
        return None, None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    from compliance_agent.cruzamentos_intel import _ob_paga
    paga = _ob_paga(con)                   # OB citada só confere se PAGA (devolvida/erro não valida laudo) — CNF-02

    def achar(numero: str, ug: str) -> list[float]:
        return [v for (v, u) in con.execute("SELECT valor, ug_emitente FROM ob_orcamentaria_siafe WHERE numero_ob=? "
                                            f"AND {paga}", (numero,))
                if isinstance(v, (int, float)) and (not ug or str(u) == ug)]
    return achar, con


def _nota_laudo(laudo: dict, conf: dict, mtime: float) -> str:
    tag, cred = laudo["tag"], laudo.get("credor") or {}
    pago = laudo.get("pago_ob") or {}
    nivel = {True: "nível 2 — citação localizada", False: "nível 1 — citação NÃO localizada", None: "nível 1 — não conferível"}
    lin = [f"| {a.get('grau', '')} | {limpar(a.get('titulo', '')).replace('|', '/')} | {_dinheiro(a.get('valor_envolvido'))} | "
           f"{nivel[m]} |" for a, m in zip(laudo.get("achados_principais") or [], conf["achados"])]
    links = sorted(set(re.findall(r"vault/(casos/[\w.-]+?)\.md", json.dumps(laudo.get("cruzamentos") or [], ensure_ascii=False))))
    if (VAULT / "processos" / f"{tag}.md").exists():
        links.append(f"processos/{tag}")
    ob = "não conferidas por código" if conf["ob_ok"] is None else f"{conf['ob_ok']} de {conf['ob_total']} conferidas no SIAFE"
    ugs = Counter(_digitos(o.get("ug")) for o in pago.get("obs") or [] if isinstance(o, dict) and _digitos(o.get("ug")))
    ug = next((u for u, n in ugs.most_common(1) if 2 * n > sum(ugs.values())), None)     # maioria estrita das OB, ou nenhuma
    return cores_orgaos.marcar_nota("\n".join([
        "---", "tipo: pericia-agente", f"processo: {laudo.get('processo', tag)}",
        f"entidade: {limpar(cred.get('nome', '')).replace(':', ' -')}", f"cnpj: {cred.get('cnpj', '')}",
        f"nivel_prova: {conf['nivel']}", f"atualizado: {datetime.fromtimestamp(mtime):%Y-%m-%d}",
        "tags: [jfn, pericia, fonte/sei, fonte/siafe]", "---", "",
        f"# Perícia por agente — {laudo.get('processo', tag)}", "",
        f"> GERADO por `compliance_agent/cerebro_ponte.py` a partir de `data/pericia_agentes/{tag}.json` — não editar à mão. {AVISO}", "",
        "| Item | Valor | Fonte / estado |", "|---|---:|---|",
        f"| Contratado | {_dinheiro(laudo.get('valor_contratado'))} | laudo do agente (PENDENTE de conferência por código) |",
        f"| Pago por OB | {_dinheiro(pago.get('total'))} | SIAFE — OB {ob} |",
        f"| Documentos lidos | {(laudo.get('lido') or {}).get('docs_lidos', '?')} de {(laudo.get('lido') or {}).get('docs_total', '?')} | laudo do agente |",
        "", f"**Credor:** {limpar(cred.get('nome', 'INDISPONÍVEL'))} · CNPJ {cred.get('cnpj', 'INDISPONÍVEL')}  ",
        f"**Objeto:** {limpar(laudo.get('objeto', ''))}", "",
        f"## Achados (laudo: nível {conf['nivel']})", "",
        "Nível 2 = o trecho citado entre aspas foi localizado por código no texto arquivado do processo. "
        + ("" if conf["fonte_lida"] else "**Texto do processo INDISPONÍVEL nesta máquina: nada foi conferido.**"), "",
        "| Grau | Achado | Valor envolvido | Prova |", "|---|---|---:|---|", *lin, "",
        "## Lição candidata (não validada pelo portão)", "", limpar(laudo.get("aprendizado") or "—"), "",
        "## Ligações", "", " · ".join(f"[[{x}]]" for x in links) or "—", "[[jfn/pericias-agente]] · [[jfn/automelhoria-licoes]]", ""]), ug, cores_orgaos.nomes_ug())


def _escrever(caminho: Path, texto: str) -> int:
    """Só regrava se mudou (o vault é sincronizado: escrita inútil vira tráfego e conflito)."""
    if caminho.exists() and caminho.read_text(encoding="utf-8") == texto:
        return 0
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    return 1


def cruzar(con: sqlite3.Connection) -> list[dict]:
    """CNPJ que aparece em mais de um fato (processo): a empresa que é credora num e perdedora noutro, por exemplo."""
    out = []
    for (valor,) in con.execute("SELECT valor FROM ponte_entidade WHERE tipo='cnpj' GROUP BY valor "
                                "HAVING COUNT(DISTINCT chave) > 1 ORDER BY COUNT(DISTINCT chave) DESC, valor"):
        out.append({"cnpj": valor, "onde": [{"chave": c, "papel": p} for c, p in con.execute(
            "SELECT chave, papel FROM ponte_entidade WHERE tipo='cnpj' AND valor=? ORDER BY chave", (valor,))]})
    return out


def entidade(termo: str, con: sqlite3.Connection | None = None) -> list[dict]:
    """Tudo o que o registro tem de uma empresa (CNPJ), processo (SEI) ou UG: [{chave, papel, id, texto}]."""
    proprio = con is None
    con = con or cerebro._con()
    try:
        con.executescript(DDL)
        d = _digitos(termo)
        return [{"tipo": t, "chave": c, "papel": p, "id": i, "texto": x} for t, c, p, i, x in con.execute(
            "SELECT e.tipo, e.chave, e.papel, c.mem_id, c.conteudo FROM ponte_entidade e LEFT JOIN cerebro c ON c.chave=e.chave "
            "WHERE (e.tipo IN ('cnpj','ug') AND e.valor=?) OR (e.tipo='processo' AND replace(replace(e.valor,'/',''),'.','')=?) "
            "ORDER BY e.chave", (d, d))]
    finally:
        if proprio:
            con.close()


def _cnpj_fmt(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def sincronizar(con: sqlite3.Connection | None = None, ob_siafe="padrao", max_novos: int = 10**6) -> dict:
    """Laudos e vereditos → registro do cérebro (fila do despachante) + índice de entidades + notas do vault.
    `max_novos` = quantos laudos novos/alterados conferir na fonte nesta rodada (a leitura do processo é o custo)."""
    novos = 0
    proprio = con is None
    con = con or cerebro._con()
    siafe_con = None
    if ob_siafe == "padrao":
        ob_siafe, siafe_con = _ob_siafe_ro()
    r = {"laudos": 0, "nivel2": 0, "adiados": 0, "ilegiveis": [], "barrados": [], "notas_escritas": 0,
         "registro": {"novo": 0, "corrigido": 0, "igual": 0, "recusado": 0}}
    linhas, licoes = [], []

    def registrar(f: dict) -> None:
        st = cerebro.registrar(f["chave"], f["texto"], f["kind"], f["assunto"], con=con)
        r["registro"]["recusado" if st.startswith("recusado") else st] += 1
        con.execute("DELETE FROM ponte_entidade WHERE chave=?", (f["chave"],))
        con.executemany("INSERT OR IGNORE INTO ponte_entidade VALUES (?,?,?,?)", [(t, v, f["chave"], p) for t, v, p in f["entidades"]])
        con.commit()
    try:
        con.executescript(DDL)
        for arq in sorted((DATA / "pericia_agentes").glob("*.json")):
            if arq.name.startswith("lote_"):
                continue
            bruto = arq.read_bytes()
            try:
                laudo = json.loads(bruto)
                laudo["tag"]
            except (ValueError, KeyError, TypeError):
                r["ilegiveis"].append(arq.name)
                continue
            h = hashlib.sha1(bruto).hexdigest()
            ant = con.execute("SELECT hash, conferencia FROM ponte_laudo WHERE tag=?", (laudo["tag"],)).fetchone()
            if ant and ant[0] == h:
                conf = json.loads(ant[1])
            elif novos >= max_novos:
                r["adiados"] += 1                            # fica para a próxima rodada; nada é registrado sem conferir
                continue
            else:
                novos += 1
                conf = conferir(laudo, _corpus(laudo["tag"], completo=False), ob_siafe)
                if not all(m is True for m in conf["achados"]):
                    conf = conferir(laudo, _corpus(laudo["tag"]), ob_siafe)
            try:
                fatos = fatos_do_laudo(laudo, conf)
            except ValueError as exc:
                r["barrados"].append(str(exc))
                continue
            con.execute("INSERT OR REPLACE INTO ponte_laudo VALUES (?,?,?)", (laudo["tag"], h, json.dumps(conf)))
            for f in fatos:
                registrar(f)
            r["laudos"] += 1
            r["nivel2"] += conf["nivel"] == 2
            cred = laudo.get("credor") or {}
            linhas.append(f"| [[jfn/pericias-agente/{laudo['tag']}\\|{laudo.get('processo', laudo['tag'])}]] | "
                          f"{limpar(cred.get('nome', '')).replace('|', '/')[:60]} | {cred.get('cnpj', '')} | "
                          f"{_dinheiro((laudo.get('pago_ob') or {}).get('total'))} | {conf['nivel']} | "
                          f"{sum(1 for m in conf['achados'] if m is True)} de {len(conf['achados'])} |")
            if len(fatos) > 1:
                licoes.append(f"- **{laudo.get('processo', laudo['tag'])}** — {fatos[1]['texto'].split('): ', 1)[-1]}")
            if VAULT.is_dir():
                r["notas_escritas"] += _escrever(VAULT / "jfn" / "pericias-agente" / f"{laudo['tag']}.md",
                                                 _nota_laudo(laudo, conf, arq.stat().st_mtime))
        versoes = []
        if auto_config.banco().exists():
            auto = sqlite3.connect(f"file:{auto_config.banco()}?mode=ro", uri=True, timeout=30)
            try:
                versoes = fatos_da_automelhoria(auto)
            finally:
                auto.close()
            for f in versoes:
                registrar(f)
        if VAULT.is_dir():
            cruz = cruzar(con)
            topo = ["---", "tipo: retrato", "tags: [jfn, pericia]", "---", "", "# Perícias por agente — índice", "",
                    f"> GERADO por `compliance_agent/cerebro_ponte.py` — não editar à mão. {AVISO}", "",
                    f"{r['laudos']} laudos; {r['nivel2']} com ao menos um achado de nível 2 (citação localizada por código no processo).", "",
                    "| Processo | Credor | CNPJ | Pago por OB (SIAFE) | Nível | Achados conferidos |", "|---|---|---|---:|:-:|:-:|", *linhas, "",
                    "## Empresas em mais de um processo", ""]
            topo += [f"- **{_cnpj_fmt(x['cnpj'])}** — {len({o['chave'] for o in x['onde']})} processos: " + "; ".join(
                f"[[jfn/pericias-agente/{o['chave'].split(':', 1)[1]}]] ({o['papel']})" for o in x["onde"]) for x in cruz] or ["—"]
            r["notas_escritas"] += _escrever(VAULT / "jfn" / "pericias-agente.md", "\n".join(topo) + "\n")
            auto_md = ["---", "tipo: retrato", "tags: [jfn, aprendizado, pericia]", "---", "", "# Automelhoria da perícia — lições e portão", "",
                       "> GERADO por `compliance_agent/cerebro_ponte.py` — não editar à mão. Fonte: `data/autoaprimoramento/auto.db` "
                       "e `data/pericia_agentes/*.json`. Só lição de versão CAMPEÃ entra em prompt.", "",
                       "## Versões da rubrica e veredito do portão", "", "| Versão | Status | Quando | Quem | Motivo | Lições |", "|---|---|---|---|---|---|",
                       *[f"| {v['chave'].split(':', 1)[1]} | {v['status']} | {v['em']} | {v['quem']} | {v['motivo'].replace('|', '/')} | "
                         f"{v['licoes'].replace('|', '/')} |" for v in versoes], "",
                       f"## Lições candidatas das perícias por agente ({len(licoes)})", "",
                       "Cada uma veio de UM processo lido por inteiro; nenhuma passou pelo portão.", "", *licoes, ""]
            r["notas_escritas"] += _escrever(VAULT / "jfn" / "automelhoria-licoes.md", "\n".join(auto_md))
        return r
    finally:
        if siafe_con is not None:
            siafe_con.close()
        if proprio:
            con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cerebro_ponte")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sincronizar").add_argument("--max-novos", type=int, default=10**6)
    sub.add_parser("cruzar")
    sub.add_parser("entidade").add_argument("termo")
    a = ap.parse_args(argv)
    if a.cmd == "sincronizar":
        r = sincronizar(max_novos=a.max_novos)
        r["cores"] = cores_orgaos.aplicar_vault() if VAULT.is_dir() else None     # ug/orgao + cor por órgão no grafo
        r["em"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (DATA / "cerebro_ponte_estado.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False))
        return 0
    elif a.cmd == "entidade":
        print(json.dumps(entidade(a.termo), ensure_ascii=False, indent=1))
    else:
        con = cerebro._con()
        try:
            con.executescript(DDL)
            print(json.dumps(cruzar(con), ensure_ascii=False, indent=1))
        finally:
            con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
