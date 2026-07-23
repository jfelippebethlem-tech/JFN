"""
Comandos do Núcleo de Inteligência Progressiva para o bot Telegram (Yoda).

Filosofia anti-"bot burro": NENHUM comando aqui depende de LLM. Tudo é
determinístico — parser de argumentos por regex, perícia por indicadores,
respostas formatadas por template. A IA fraca só entra (opcionalmente) como
última camada de interpretação de texto livre, e mesmo assim traduzindo para
UM destes comandos (nunca respondendo por conta própria sobre perícia).

⚠️ O bot de comandos de notifications/telegram.py está DESATIVADO em produção
(ver aviso no topo daquele arquivo) — estes handlers só respondem se aquele
polling for religado com token próprio.

Comandos expostos (plugados em notifications/telegram.py):

    /pericia <CNPJ | nº OB | nome>   — perícia completa na hora, com laudo
    /veredito <ref> confirmado|descartado|inconclusivo
                                     — feedback do perito (fecha o ciclo)
    /promover <ref>                  — promove perícia confirmada a caso-ouro
    /fases <nº SEI>                  — fases de contratação do arquivo SEI
    /fantasma <CNPJ>                 — sinais de empresa fantasma (8 sinais)
    /placar                          — placar do conjunto-ouro + memória
    /ciclo_nucleo                    — roda o ciclo de autoaprimoramento
    /fornecedor <CNPJ>               — perfil de reincidência aprendido
    /parametros                      — parâmetros calibráveis e overrides
    /evolucao                        — diário do autoaprimoramento

Todos os handlers são SÍNCRONOS (o dispatcher chama via asyncio.to_thread) e
NUNCA levantam exceção — devolvem sempre texto pronto para o Telegram.
"""

from __future__ import annotations

import logging

import re
import unicodedata

# ── Formatação ───────────────────────────────────────────────────────────────

_EMOJI = {"crítico": "🔴", "alto": "🔴", "médio": "🟡", "baixo": "🟢"}


logger = logging.getLogger(__name__)


def _brl(v: float | None) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {s}"


def _fmt_laudo(laudo, referencia: str = "", titulo_humano: str = "",
               contexto: str = "") -> str:
    """Laudo → mensagem Telegram compacta (Markdown), com base legal.

    ``referencia`` é a chave ÚNICA (ob:<id>) usada no /veredito; o nº de OB
    humano vai em ``titulo_humano`` (não é único entre UGs). ``contexto`` =
    favorecido/UG, para o perito saber de quem é o laudo.
    """
    v = laudo.veredito
    c = laudo.dossie.contratacao
    emoji = _EMOJI.get(v.classificacao, "⚪")
    titulo = titulo_humano or referencia or c.identificador or "sem ref."
    # confiança só faz sentido quando algo disparou ("confiança 0%" num laudo
    # limpo lê como se a perícia não valesse nada)
    conf = f" | confiança {v.confianca:.0%}" if v.achados else ""
    linhas = [
        f"{emoji} *PERÍCIA — {titulo}*",
        f"Risco: *{v.risco_score:.0f}/100 ({v.classificacao.upper()})* "
        f"— matriz TCU: probabilidade {v.probabilidade}/5, impacto {v.impacto}/5{conf}",
    ]
    if contexto:
        linhas.append(contexto)
    if c.valor:
        linhas.append(f"Valor: {_brl(c.valor)}")
    if not v.achados:
        # INDISPONÍVEL ≠ 0: dizer "nada disparou" sem dizer QUANTOS podiam disparar
        # transforma falta de dado em atestado de limpeza (caso CPASC, R$ 16,4 mi)
        from compliance_agent.nucleo.indicadores import apurabilidade
        ap = apurabilidade(laudo.dossie)
        linhas.append(f"\n✅ Nenhum dos *{ap['n_apuraveis']} de {ap['n_total']}* "
                      "indicadores apuráveis disparou.")
        if ap["indisponiveis"]:
            faltas = sorted({f.split(".")[-1] for i in ap["indisponiveis"] for f in i["falta"]})
            linhas.append(f"⚠️ *{len(ap['indisponiveis'])} INDISPONÍVEIS* (não medidos, "
                          f"≠ regulares) — falta: {', '.join(faltas)}.")
    else:
        linhas.append(f"\n*Achados ({len(v.achados)}):*")
        for a in v.achados[:6]:
            fund = f" _({a.base_legal[0]})_" if a.base_legal else ""
            linhas.append(f"• *{a.titulo}* [{a.severidade}]{fund}\n"
                          f"  {a.observado} | limite: {a.limite}")
        if len(v.achados) > 6:
            linhas.append(f"… e mais {len(v.achados) - 6} achados.")
    if v.resumo and v.achados:  # sem achados o ✅ acima já disse tudo
        linhas.append(f"\n_{v.resumo}_")
    ref_fonte = laudo.fontes.get("referencia_categoria", "")
    if ref_fonte:
        linhas.append(f"📚 Referência de preço: {ref_fonte}")
    linhas.append("\nFeedback: `/veredito {} confirmado|descartado`".format(
        (referencia or c.identificador or "REF").replace("`", "")))
    return "\n".join(linhas)


def _sessao():
    from compliance_agent.database.models import get_session
    return get_session()


# ── /pericia ─────────────────────────────────────────────────────────────────

def cmd_pericia(args: str) -> str:
    """Perícia por CNPJ (14 dígitos), nº de OB ou nome de fornecedor."""
    alvo = (args or "").strip()
    if not alvo:
        return ("Use: `/pericia <CNPJ | nº OB | nome do fornecedor>`\n"
                "Ex.: `/pericia 19.088.605/0001-04` ou `/pericia 2024OB01234`")
    try:
        from compliance_agent.database.models import OrdemBancaria
        from compliance_agent.nucleo.adaptador_db import periciar_ob

        session = _sessao()
        try:
            digitos = re.sub(r"\D", "", alvo)
            obs = []
            if len(digitos) == 14:  # CNPJ → maiores OBs do fornecedor (raiz ANCORADA: pega filiais
                # sem casar a raiz no meio de outro documento — armazenamento é 14 dígitos crus)
                obs = (session.query(OrdemBancaria)
                       .filter(OrdemBancaria.favorecido_cpf.isnot(None))
                       .filter(OrdemBancaria.favorecido_cpf.like(
                           f"{digitos[:8]}%"))
                       .order_by(OrdemBancaria.valor.desc()).limit(3).all())
                if not obs:  # tolerância a máscara no banco
                    obs = (session.query(OrdemBancaria)
                           .filter(OrdemBancaria.favorecido_cpf == alvo)
                           .order_by(OrdemBancaria.valor.desc())
                           .limit(3).all())
            if not obs:  # nº de OB exato (NÃO é único: cada UG numera as suas)
                obs = (session.query(OrdemBancaria)
                       .filter(OrdemBancaria.numero_ob == alvo)
                       .order_by(OrdemBancaria.valor.desc()).limit(3).all())
            if not obs and len(alvo) >= 4 and not digitos:  # nome
                obs = (session.query(OrdemBancaria)
                       .filter(OrdemBancaria.favorecido_nome.ilike(f"%{alvo}%"))
                       .order_by(OrdemBancaria.valor.desc()).limit(3).all())
            if not obs:
                # sem OB coletada → tenta CONTRATOS (fornecedor só no PNCP)
                resp = _pericia_contratos(session, alvo, digitos)
                if resp:
                    return resp
                return (f"Nada encontrado para `{alvo}`.\n"
                        "Aceito CNPJ, nº de OB, nome do fornecedor ou contrato.")
            blocos = []
            for ob in obs:
                # periciar_ob já registra na memória (usar_memoria=True);
                # interativo → enriquece cadastro na hora se faltar
                laudo = periciar_ob(session, ob, enriquecer=True)
                blocos.append(_fmt_laudo(laudo, referencia=f"ob:{ob.id}",
                                         titulo_humano=ob.numero_ob or "",
                                         contexto=f"{ob.favorecido_nome or '?'}"
                                                  f" · UG {ob.ug_codigo or '?'}"))
            extra = ""
            if len(obs) > 1:
                extra = f"_(3 maiores OBs de {obs[0].favorecido_nome})_\n\n"
            return extra + "\n\n———\n\n".join(blocos)
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro na perícia: {exc}"


def _pericia_contratos(session, alvo: str, digitos: str) -> str | None:
    """Fallback do /pericia: fornecedor sem OB → pericia os CONTRATOS (PNCP).
    Retorna None se também não houver contrato."""
    try:
        from compliance_agent.database.models import Contrato, Empresa
        from compliance_agent.nucleo.adaptador_db import periciar_contrato

        q = session.query(Contrato).join(Empresa, Contrato.empresa_id == Empresa.id)
        if len(digitos) == 14:
            q = q.filter(Empresa.cnpj == digitos)
        elif len(alvo) >= 4 and not digitos:
            q = q.filter(Empresa.razao_social.ilike(f"%{alvo}%"))
        else:
            return None
        contratos = (q.order_by(Contrato.valor_total.desc()).limit(3).all())
        if not contratos:
            return None
        blocos = []
        for ct in contratos:
            laudo = periciar_contrato(session, ct.id)
            if laudo is None:
                continue
            blocos.append(_fmt_laudo(
                laudo, referencia=f"ct:{ct.id}",
                titulo_humano=f"Contrato {ct.numero or ct.id}",
                contexto=f"{ct.orgao_contrat or '?'} · sem OB coletada"))
        if not blocos:
            return None
        aviso = "_(sem OB coletada — periciando contratos/PNCP)_\n\n"
        return aviso + "\n\n———\n\n".join(blocos)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fallback de contratos da perícia falhou (responderá 'nada encontrado'): %s", exc)
        return None


# ── /veredito ────────────────────────────────────────────────────────────────

def cmd_veredito(args: str) -> str:
    """`/veredito <ref> confirmado|descartado|inconclusivo` — fecha o ciclo."""
    partes = (args or "").rsplit(None, 1)
    if len(partes) != 2:
        return ("Use: `/veredito <referência> confirmado|descartado|inconclusivo`\n"
                "Ex.: `/veredito 2024OB01234 confirmado`")
    ref, decisao = partes[0].strip(), partes[1].strip().lower()
    try:
        from compliance_agent.nucleo import memoria_pericial
        n = memoria_pericial.registrar_veredito(ref, decisao)
        if n == 0 and re.fullmatch(r"\d{4}OB\d+", ref, re.IGNORECASE):
            # perito digitou o nº humano da OB — resolve p/ ob:<id> (o nº não é
            # único entre UGs; se houver mais de uma perícia, pede a exata)
            try:
                from compliance_agent.database.models import OrdemBancaria
                session = _sessao()
                try:
                    ids = [f"ob:{i}" for (i,) in session.query(OrdemBancaria.id)
                           .filter(OrdemBancaria.numero_ob == ref).all()]
                finally:
                    session.close()
                na_memoria = [r for r in ids if memoria_pericial.tem_pericia(r)]
                if len(na_memoria) == 1:
                    n = memoria_pericial.registrar_veredito(na_memoria[0], decisao)
                    ref = na_memoria[0]
                elif len(na_memoria) > 1:
                    return (f"`{ref}` é ambíguo (o nº de OB se repete entre UGs). "
                            "Periciadas: " + ", ".join(f"`{r}`" for r in na_memoria)
                            + f"\nUse: `/veredito ob:<id> {decisao}`")
            except Exception as exc:  # noqa: BLE001
                logger.warning("veredito %r não registrado na memória pericial: %s", ref, exc)
        if n == 0:
            return (f"Nenhuma perícia com referência `{ref}` na memória.\n"
                    "Rode `/pericia` primeiro — o laudo entra na memória "
                    "automaticamente.")
        return (f"✅ Veredito *{decisao}* registrado em {n} perícia(s) de `{ref}`.\n"
                "O feedback já alimenta a calibração — o próximo `/ciclo_nucleo` "
                "usa isso para se autoaprimorar.")
    except ValueError as exc:
        return f"❌ {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro ao registrar veredito: {exc}"


# ── /promover ────────────────────────────────────────────────────────────────

def cmd_promover(args: str) -> str:
    """
    `/promover <ref>` — promove uma perícia CONFIRMADA a caso-ouro: a régua
    de avaliação (F1) passa a cobrar que o sistema sempre pegue este padrão.
    Salvaguardas: exige veredito 'confirmado' do perito, achados não vazios,
    dossiê registrado e id inédito no conjunto-ouro.
    """
    ref = (args or "").strip()
    if not ref:
        return "Use: `/promover <referência>` (ex.: `/promover ob:4451813`)"
    try:
        from compliance_agent.nucleo import memoria_pericial
        from compliance_agent.nucleo.avaliacao import (
            CasoOuro, adicionar_caso_ouro, avaliar_sistema, carregar_casos,
        )
        p = memoria_pericial.obter_pericia(ref)
        if p is None:
            return f"Nenhuma perícia com referência `{ref}` na memória."
        if (p.get("veredito") or "").lower() != "confirmado":
            return (f"`{ref}` ainda não foi CONFIRMADA pelo perito.\n"
                    f"Primeiro: `/veredito {ref} confirmado` — só perícia "
                    "confirmada vira caso-ouro (salvaguarda).")
        achados = [a.get("indicador_id") for a in p.get("achados") or []]
        achados = [a for a in achados if a]
        if not achados:
            return (f"`{ref}` não teve nenhum indicador disparado — perícia "
                    "limpa não vira caso-ouro (nada a cobrar da régua).")
        if not p.get("dossie"):
            return (f"`{ref}` foi registrada sem dossiê serializado (perícia "
                    "antiga). Rode `/pericia` de novo e repita o /promover.")
        caso_id = f"ouro_{re.sub(r'[^0-9A-Za-z]+', '_', ref)}"
        if any(c.id == caso_id for c in carregar_casos()):
            return f"`{ref}` já está no conjunto-ouro (`{caso_id}`)."
        adicionar_caso_ouro(CasoOuro(
            id=caso_id,
            descricao=f"Caso real confirmado pelo perito (ref {ref})",
            dossie=p["dossie"],
            deve_disparar=achados,
        ))
        placar = avaliar_sistema()
        return (f"🏅 `{ref}` promovida a caso-ouro (`{caso_id}`).\n"
                f"A régua agora cobra: {', '.join(achados)}.\n"
                f"Placar do conjunto-ouro: F1 {placar.f1_global:.2f} "
                f"({len(carregar_casos())} casos).")
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro ao promover: {exc}"


# ── /fases ───────────────────────────────────────────────────────────────────

def cmd_fases(args: str) -> str:
    """
    `/fases <processo SEI>` — linha do tempo das fases da contratação e
    LACUNAS do processo, direto do arquivo compacto em disco (grátis; ver
    docs/PLAYBOOK-SEI.md). Sem browser, sem IA.
    """
    import json as _json
    import os as _os
    from pathlib import Path as _Path
    proc = (args or "").strip()
    so_dig = re.sub(r"\D", "", proc)
    if len(so_dig) == 14 and "/" not in proc:  # mandaram CNPJ — fases é por PROCESSO SEI
        return ("Fases são por *processo SEI* (ex.: `/fases 330020/000762/2021`), não por CNPJ.\n"
                "Para o fornecedor use `/pericia " + so_dig + "` ou `/fantasma " + so_dig + "`.")
    if not proc:
        return "Use: `/fases 330020/000762/2021`"
    raiz = _Path(_os.environ.get("SEI_ARQUIVO_DIR")
                 or _Path(__file__).resolve().parents[2] / "data" / "sei_arquivo")
    tag = re.sub(r"[^0-9]", "_", proc)
    mpath = raiz / tag / "manifest.json"
    if not mpath.exists():
        return (f"Processo `{proc}` não arquivado ainda.\n"
                "Baixe e arquive: `tools/sei_integra_completa.py` + "
                "`tools/sei_arquivar.py` (ver docs/PLAYBOOK-SEI.md).")
    m = _json.loads(mpath.read_text(encoding="utf-8"))
    linhas = [f"🗂 *PROCESSO {m['processo']}* — modalidade "
              f"{m['modalidade'] or '?'} · {len(m['docs'])} docs · "
              f"{m['fotos_total']} fotos de medição"]
    linhas.append("Fases: " + " · ".join(
        f"{f}={n}" for f, n in m["linha_do_tempo"].items() if n))
    for l in m.get("lacunas", []):
        icone = "🔴" if l["gravidade"] == "critica" else "🟡"
        linhas.append(f"{icone} Lacuna ({l['gravidade']}): {l['falta']}")
    if not m.get("lacunas"):
        linhas.append("✅ Sem lacunas de fase para a modalidade.")
    linhas.append("\nDetalhe: `tools/sei_consultar.py \"" + proc + "\"`")
    return "\n".join(linhas)


# ── /fantasma ─────────────────────────────────────────────────────────────────

def cmd_fantasma(args: str) -> str:
    """
    `/fantasma <CNPJ>` — triagem de empresa fantasma/fachada por sinais
    objetivos cruzados (situação, capital, endereço-ninho, sanção…). Indício,
    não acusação. Determinístico, sem IA.
    """
    alvo = re.sub(r"\D", "", (args or ""))
    if len(alvo) != 14:
        return "Use: `/fantasma 19.088.605/0001-04` (CNPJ, 14 dígitos)"
    try:
        from compliance_agent.empresa_fantasma import avaliar_cnpj
        session = _sessao()
        try:
            r = avaliar_cnpj(session, alvo)
        finally:
            session.close()
        if r is None:
            return f"CNPJ `{alvo}` sem dados cadastrais na base."
        emoji = {"alto": "🔴", "medio": "🟡", "baixo": "🟢"}[r["classificacao"]]
        linhas = [f"{emoji} *FANTASMA? — {r['razao_social'] or alvo}*",
                  f"Score de fachada: *{r['score']}/100 ({r['classificacao'].upper()})*"]
        if r["sinais"]:
            linhas.append("\n*Sinais:*")
            for s in r["sinais"]:
                linhas.append(f"• {s['id']} — {s['detalhe']}")
        else:
            linhas.append("\n✅ Nenhum sinal de fachada.")
        linhas.append("\n_Triagem por indícios cruzados — verificar in loco / "
                      "foto de fachada antes de concluir._")
        return "\n".join(linhas)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro: {exc}"


# ── /certame ──────────────────────────────────────────────────────────────────

def cmd_certame(args: str) -> str:
    """
    `/certame <nº controle PNCP>` — ficha do Índice de Direcionamento do certame
    (score 0-100, faixa, famílias com INDISPONÍVEL explícito, drivers, matriz
    S×V e narrativa quando houver). Determinístico, lê `certame_indice`; sem
    linha persistida, calcula na hora.
    """
    import json as _json
    import re as _re

    alvo = (args or "").strip()
    m = _re.search(r"\d{14}-\d-\d{6}/\d{4}", alvo)
    if not m:
        return "Use: `/certame 12345678000190-1-000012/2025` (nº de controle PNCP)"
    certame = m.group(0)
    try:
        from compliance_agent.editais.db import conectar
        con = conectar()
        try:
            row = con.execute("SELECT score, faixa, confianca, familias_json, drivers_json "
                              "FROM certame_indice WHERE certame=?", (certame,)).fetchone()
            nar = None
            try:
                import sqlite3 as _sq
                nrow = con.execute("SELECT narrativa_json FROM certame_indice WHERE certame=?",
                                   (certame,)).fetchone()
                nar = _json.loads(nrow[0]) if nrow and nrow[0] else None
            except (_sq.OperationalError, ValueError, TypeError):
                nar = None  # coluna narrativa ainda não existe nesta base / json inválido
        finally:
            con.close()
        if row:
            score, faixa, conf = row[0], row[1], row[2]
            fams = _json.loads(row[3] or "{}")
            drivers = _json.loads(row[4] or "[]")
        else:
            from compliance_agent.editais.indice_certame import calcular
            r = calcular(certame)
            score, faixa, conf = r["score"], r["faixa"], r["confianca"]
            fams, drivers = r["familias"], r["drivers"]
        emoji = {"EXTREMO": "🔴", "ALTO": "🟠", "MEDIO": "🟡", "BAIXO": "🟢"}.get(faixa, "❔")
        linhas = [f"{emoji} *CERTAME {certame}*",
                  f"Índice de Direcionamento: *{score:.0f}/100 ({faixa})* · "
                  f"confiança {conf:.0%} das famílias apuráveis"]
        linhas.append("\n*Famílias:*")
        for nome, f in (fams or {}).items():
            if isinstance(f, dict) and f.get("apuravel"):
                pior = max((x.get("valor", 0) for x in f.get("flags", [])), default=0)
                linhas.append(f"• {nome}: {pior:.2f}")
            else:
                linhas.append(f"• {nome}: INDISPONÍVEL (≠ 0)")
        if drivers:
            linhas.append("\n*Drivers:* " + ", ".join(
                d.get("flag", d.get("familia", "?")) for d in drivers[:4]))
        if nar and nar.get("tese"):
            linhas.append(f"\n_{str(nar['tese'])[:400]}_")
        linhas.append("\n_Score é indício interno de priorização — não é acusação; "
                      "famílias INDISPONÍVEIS não pontuam nem zeram._")
        return "\n".join(linhas)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro: {exc}"


# ── /placar ──────────────────────────────────────────────────────────────────

def cmd_placar() -> str:
    """Placar do conjunto-ouro + estado da memória pericial."""
    try:
        from compliance_agent.nucleo.ciclo import status
        s = status()
        p, m = s["placar_ouro"], s["memoria"]
        linhas = [
            "🎯 *PLACAR DO NÚCLEO (conjunto-ouro)*",
            f"F1: *{p['f1']:.0%}* | precisão {p['precisao']:.0%} "
            f"| cobertura {p['cobertura']:.0%} | falsos alarmes {p['falsos_alarmes']}",
            "",
            "🧠 *Memória pericial*",
            f"Perícias: {m['total_pericias']} "
            f"({m['com_achados']} com achados, "
            f"{m['confirmadas_pelo_perito']} confirmadas pelo perito)",
        ]
        if m["categorias_mais_periciadas"]:
            cats = ", ".join(f"{c['categoria']} ({c['n']})"
                             for c in m["categorias_mais_periciadas"][:5])
            linhas.append(f"Categorias: {cats}")
        linhas.append(f"Evoluções registradas: {s['evolucoes_registradas']}")
        return "\n".join(linhas)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro: {exc}"


# ── /ciclo_nucleo ────────────────────────────────────────────────────────────

def cmd_ciclo_nucleo() -> str:
    """Roda um ciclo completo de autoaprimoramento e resume o resultado."""
    try:
        from compliance_agent.nucleo.ciclo import rodar_ciclo
        session = None
        try:
            session = _sessao()
        except Exception as exc:
            logger.warning("sessão de DB indisponível p/ o ciclo (roda degradado): %s", exc)
        rel = rodar_ciclo(session)
        if session is not None:
            session.close()
        p = rel["placar"]
        linhas = ["🔁 *CICLO DE AUTOAPRIMORAMENTO CONCLUÍDO*"]
        if "varredura" in rel:
            v = rel["varredura"]
            linhas.append(f"Perícias novas: {v['pericias_novas']} "
                          f"({v['com_achados']} com achados)")
        linhas.append(f"Placar: F1 {p['f1_inicial']:.0%} → *{p['f1_final']:.0%}* "
                      f"| falsos alarmes: {p['falsos_alarmes']}")
        if rel["calibracoes_mantidas"]:
            linhas.append(f"\n⚙️ *Calibrações mantidas "
                          f"({len(rel['calibracoes_mantidas'])}):*")
            for m in rel["calibracoes_mantidas"][:5]:
                linhas.append(f"• `{m['parametro']}` → {m['valor_novo']} "
                              f"(F1 {m['f1_antes']:.0%}→{m['f1_depois']:.0%})")
        else:
            linhas.append("Nenhuma calibração melhorou o placar — sistema já "
                          "está no ótimo atual. "
                          f"({rel['calibracoes_revertidas']} tentativas revertidas)")
        if rel.get("red_flags_propostas"):
            linhas.append("\n🚩 *Red flags novas propostas (mineradas dos casos "
                          "confirmados):* " + ", ".join(rel["red_flags_propostas"][:5]))
        return "\n".join(linhas)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro no ciclo: {exc}"


# ── /fornecedor ──────────────────────────────────────────────────────────────

def cmd_fornecedor(args: str) -> str:
    """Perfil de reincidência aprendido de um CNPJ."""
    digitos = re.sub(r"\D", "", args or "")
    if len(digitos) != 14:
        # nome também serve — mesma semântica do /relatorio (único segue; ambíguo pergunta)
        termo = (args or "").strip()
        if not termo:
            return "Use: `/fornecedor <CNPJ ou nome>`"
        import sqlite3 as _sq
        try:
            from compliance_agent.reporting.inteligencia import buscar_candidatos, fmt_cnpj
            cands = buscar_candidatos(termo)
        except (ImportError, OSError, ValueError, KeyError, _sq.Error) as exc:
            return f"❌ Erro ao resolver o nome: {exc}"
        if not cands:
            return f"Não encontrei empresa para {termo!r}. Use o CNPJ (14 dígitos) ou outro nome."
        if len(cands) > 1:
            linhas = [f"{i+1}) {c['nome'] or '(sem nome)'} — CNPJ {fmt_cnpj(c['cnpj'])}"
                      for i, c in enumerate(cands[:6])]
            return ("Encontrei mais de uma empresa para "
                    f"\"{termo}\" — repita com o CNPJ:\n" + "\n".join(linhas))
        digitos = cands[0]["cnpj"]
    try:
        from compliance_agent.nucleo.memoria_pericial import perfil_fornecedor
        p = perfil_fornecedor(digitos)
        if p is None:
            return (f"CNPJ `{digitos}` ainda sem perícias na memória.\n"
                    "Rode `/pericia {}` primeiro.".format(digitos))
        alerta = ("⚠️ *REINCIDENTE*" if p.criticos_e_altos >= 2 else "")
        txt = (f"🏢 *Perfil aprendido — CNPJ {digitos}* {alerta}\n"
               f"Perícias: {p.total_pericias} | risco médio: "
               f"*{p.risco_medio:.0f}/100*\n"
               f"Laudos crítico/alto: {p.criticos_e_altos}\n"
               f"Vereditos: {p.confirmados} confirmados, "
               f"{p.descartados} descartados")
        # perícia de OB é cega ao vetor político — emenda entra como sinal aditivo
        import sqlite3 as _sq
        try:
            from compliance_agent.reporting.intel_md import emendas_do_favorecido
            em = emendas_do_favorecido(digitos)
            if em.get("tem_dados") and (em.get("n_autores") or 0) >= 1:
                from compliance_agent.reporting.intel_base import moeda
                txt += (f"\n📌 *Emendas parlamentares:* {em['n_autores']} autor(es), "
                        f"R$ {moeda(em['total'])} pagos"
                        + (" — *operador de emendas* (≥5 padrinhos); ver /relatorio"
                           if em["n_autores"] >= 5 else " (ver /relatorio)"))
        except (ImportError, OSError, ValueError, KeyError, TypeError, _sq.Error) as exc:
            logger.debug("sinal de emendas indisponível no perfil: %s", exc)
        return txt
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro: {exc}"


# ── /parametros ──────────────────────────────────────────────────────────────

def cmd_parametros() -> str:
    """Parâmetros da perícia: valor vigente, fonte e overrides ativos."""
    try:
        from compliance_agent.nucleo import parametros as P
        calibrados = set(P._carregar_overrides())
        linhas = ["⚙️ *PARÂMETROS DA PERÍCIA*", ""]
        for p in P.listar():
            trava = "🔒" if p.fonte_valor.startswith("lei") else "🔧"
            override = " *(calibrado)*" if p.id in calibrados else ""
            linhas.append(f"{trava} `{p.id}` = {p.valor}{override}\n"
                          f"   _{p.fonte_valor}: {p.fundamento[:70]}_")
        linhas.append("\n🔒 = fonte legal (intocável) | 🔧 = calibrável pelo loop")
        return "\n".join(linhas)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro: {exc}"


# ── /evolucao ────────────────────────────────────────────────────────────────

def cmd_evolucao() -> str:
    """Diário do autoaprimoramento — o que o sistema mudou em si mesmo."""
    try:
        from compliance_agent.nucleo.autoaprimoramento import historico_evolucao
        hist = historico_evolucao()
        if not hist:
            return ("Diário vazio — o loop ainda não rodou.\n"
                    "Use `/ciclo_nucleo` para rodar agora.")
        linhas = ["📖 *DIÁRIO DE EVOLUÇÃO* (últimos 5 ciclos)", ""]
        for h in hist[-5:]:
            mantidos = len(h.get("mantidos", []))
            linhas.append(
                f"• {h['quando'][:16]} — F1 {h['f1_inicial']:.0%}→"
                f"*{h['f1_final']:.0%}* | {mantidos} calibrações mantidas, "
                f"{h.get('revertidos', 0)} revertidas")
            for m in h.get("mantidos", [])[:3]:
                linhas.append(f"    ↳ `{m['parametro']}` → {m['valor_novo']}")
        return "\n".join(linhas)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro: {exc}"


# ── Roteador de linguagem natural (determinístico, SEM IA) ───────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


_CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_OB_RE = re.compile(r"\b(\d{4}OB\d{3,6})\b", re.IGNORECASE)


def interpretar_texto_livre(texto: str) -> tuple[str, str] | None:
    """
    Traduz português coloquial em (comando, args) — por REGRAS, sem LLM.

    É a primeira linha de entendimento do bot: cobre os pedidos comuns do
    perito com 100% de previsibilidade. Só o que não casar aqui cai no LLM.
    Retorna None quando não reconhece a intenção.
    """
    t = _norm(texto)
    cnpj = _CNPJ_RE.search(texto)
    ob = _OB_RE.search(texto)

    # fases/lacunas de processo SEI arquivado: "fases do 330020/000762/2021"
    if "fase" in t or "lacuna" in t:
        m = re.search(r"(\d{6}/\d{6}/\d{4})", texto)
        if m:
            return ("/fases", m.group(1))
        if cnpj:  # humano manda CNPJ p/ "fases" → o handler orienta (processo SEI, não CNPJ)
            return ("/fases", cnpj.group(0))

    # promoção a caso-ouro: "promove/promover <ref>"
    if "promov" in t:
        m = re.search(r"(ob:\d+|ct:\d+)", t)
        ref = (m and m.group(1)) or (ob and ob.group(1)) or ""
        if ref:
            return ("/promover", ref)

    # veredito: "confirmado"/"procede"/"descarta" + referência
    if any(k in t for k in ("confirmad", "procede", "descartad", "improcede",
                            "falso alarme", "inconclusiv")):
        m_ref = re.search(r"(ob:\d+|ct:\d+)", t)
        ref = ((m_ref and m_ref.group(1)) or (ob and ob.group(1))
               or (cnpj and cnpj.group(0)) or "")
        if ref:
            if any(k in t for k in ("descartad", "improcede", "falso alarme")):
                return ("/veredito", f"{ref} descartado")
            if "inconclusiv" in t:
                return ("/veredito", f"{ref} inconclusivo")
            return ("/veredito", f"{ref} confirmado")

    # fantasma/laranja: "é fantasma?", "essa empresa é laranja/fachada?" + CNPJ
    if cnpj and any(k in t for k in ("fantasma", "laranja", "fachada")):
        return ("/fantasma", cnpj.group(0))

    # certame: nº de controle PNCP na frase (ou "certame/licitação" + número)
    m_cert = re.search(r"\d{14}-\d-\d{6}/\d{4}", t)
    if m_cert and (len(t) <= 50 or any(k in t for k in ("certame", "licitac", "direcionament", "edital"))):
        return ("/certame", m_cert.group(0))

    # perícia: "pericia/audita/analisa/investiga <alvo>"
    if any(k in t for k in ("perici", "audita", "analisa", "fiscaliza")):
        alvo = (cnpj and cnpj.group(0)) or (ob and ob.group(1)) or ""
        if not alvo:
            # tenta capturar um nome após o verbo
            m = re.search(r"(?:perici\w*|audit\w*|analis\w*|fiscaliz\w*)\s+"
                          r"(?:a\s+|o\s+|em\s+)?(.{4,60})", t)
            alvo = m.group(1).strip() if m else ""
        if alvo:
            return ("/pericia", alvo)

    # placar/estado da inteligência — ANTES do ciclo: "quanto aprendeu" é
    # mais específico que o gatilho genérico "aprende".
    if any(k in t for k in ("placar", "quao inteligente", "quanto aprendeu",
                            "memoria pericial", "conjunto ouro", "score do nucleo")):
        return ("/placar", "")

    # ciclo/aprender: "roda o ciclo", "aprende", "se melhora", "autoaprimora"
    if any(k in t for k in ("ciclo", "autoaprimor", "se aprimor", "aprende",
                            "recalibra", "calibra")):
        return ("/ciclo_nucleo", "")

    # perfil do fornecedor: CNPJ solto na frase com "historico/perfil/reincid"
    if cnpj and any(k in t for k in ("historic", "perfil", "reincid", "ficha")):
        return ("/fornecedor", cnpj.group(0))

    # parâmetros / evolução
    if any(k in t for k in ("parametro", "limiar", "limite de dispensa")):
        return ("/parametros", "")
    if any(k in t for k in ("evolucao", "diario", "o que mudou", "o que voce mudou")):
        return ("/evolucao", "")

    # CNPJ sozinho na mensagem = perícia direta (atalho mais comum)
    if cnpj and len(t) <= 40:
        return ("/pericia", cnpj.group(0))
    if ob and len(t) <= 40:
        return ("/pericia", ob.group(1))

    return None


AJUDA_NUCLEO = """
🧠 *NÚCLEO DE PERÍCIA (inteligência progressiva)*
/pericia `<CNPJ|OB|nome>` — perícia na hora, com laudo e base legal
/veredito `<ref> confirmado|descartado` — seu feedback ensina o sistema
/placar — quão inteligente o sistema está (conjunto-ouro + memória)
/ciclo\\_nucleo — roda o loop de autoaprimoramento agora
/fornecedor `<CNPJ>` — perfil de reincidência aprendido
/certame `<nº PNCP>` — Índice de Direcionamento do certame (famílias + drivers)
/parametros — limiares vigentes (🔒 legais | 🔧 calibráveis)
/evolucao — diário: o que o sistema mudou em si mesmo
_Também entendo sem comando: "pericia a MGS Clean", "2024OB01234 confirmado"…_
""".strip()
