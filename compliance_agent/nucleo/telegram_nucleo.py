"""
Comandos do Núcleo de Inteligência Progressiva para o bot Telegram (Yoda).

Filosofia anti-"bot burro": NENHUM comando aqui depende de LLM. Tudo é
determinístico — parser de argumentos por regex, perícia por indicadores,
respostas formatadas por template. A IA fraca só entra (opcionalmente) como
última camada de interpretação de texto livre, e mesmo assim traduzindo para
UM destes comandos (nunca respondendo por conta própria sobre perícia).

Comandos expostos (plugados em notifications/telegram.py):

    /pericia <CNPJ | nº OB | nome>   — perícia completa na hora, com laudo
    /veredito <ref> confirmado|descartado|inconclusivo
                                     — feedback do perito (fecha o ciclo)
    /placar                          — placar do conjunto-ouro + memória
    /ciclo_nucleo                    — roda o ciclo de autoaprimoramento
    /fornecedor <CNPJ>               — perfil de reincidência aprendido
    /parametros                      — parâmetros calibráveis e overrides
    /evolucao                        — diário do autoaprimoramento

Todos os handlers são SÍNCRONOS (o dispatcher chama via asyncio.to_thread) e
NUNCA levantam exceção — devolvem sempre texto pronto para o Telegram.
"""

from __future__ import annotations

import re
import unicodedata

# ── Formatação ───────────────────────────────────────────────────────────────

_EMOJI = {"crítico": "🔴", "alto": "🔴", "médio": "🟡", "baixo": "🟢"}


def _brl(v: float | None) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {s}"


def _fmt_laudo(laudo, referencia: str = "") -> str:
    """Laudo → mensagem Telegram compacta (Markdown), com base legal."""
    v = laudo.veredito
    c = laudo.dossie.contratacao
    emoji = _EMOJI.get(v.classificacao, "⚪")
    linhas = [
        f"{emoji} *PERÍCIA — {referencia or c.identificador or 'sem ref.'}*",
        f"Risco: *{v.risco_score:.0f}/100 ({v.classificacao.upper()})* "
        f"— TCU P{v.probabilidade}×I{v.impacto} | confiança {v.confianca:.0%}",
    ]
    if c.valor:
        linhas.append(f"Valor: {_brl(c.valor)}")
    if not v.achados:
        linhas.append("\n✅ Nenhum indicador disparou.")
    else:
        linhas.append(f"\n*Achados ({len(v.achados)}):*")
        for a in v.achados[:6]:
            fund = f" _({a.base_legal[0]})_" if a.base_legal else ""
            linhas.append(f"• *{a.titulo}* [{a.severidade}]{fund}\n"
                          f"  {a.observado} | limite: {a.limite}")
        if len(v.achados) > 6:
            linhas.append(f"… e mais {len(v.achados) - 6} achados.")
    if v.resumo:
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
        from compliance_agent.nucleo import memoria_pericial

        session = _sessao()
        try:
            digitos = re.sub(r"\D", "", alvo)
            obs = []
            if len(digitos) == 14:  # CNPJ → maiores OBs do fornecedor
                obs = (session.query(OrdemBancaria)
                       .filter(OrdemBancaria.favorecido_cpf.isnot(None))
                       .filter(OrdemBancaria.favorecido_cpf.like(
                           f"%{digitos[:8]}%"))
                       .order_by(OrdemBancaria.valor.desc()).limit(3).all())
                if not obs:  # tolerância a máscara no banco
                    obs = (session.query(OrdemBancaria)
                           .filter(OrdemBancaria.favorecido_cpf == alvo)
                           .order_by(OrdemBancaria.valor.desc())
                           .limit(3).all())
            if not obs:  # nº de OB exato
                obs = (session.query(OrdemBancaria)
                       .filter(OrdemBancaria.numero_ob == alvo).all())
            if not obs and len(alvo) >= 4 and not digitos:  # nome
                obs = (session.query(OrdemBancaria)
                       .filter(OrdemBancaria.favorecido_nome.ilike(f"%{alvo}%"))
                       .order_by(OrdemBancaria.valor.desc()).limit(3).all())
            if not obs:
                return (f"Nada encontrado para `{alvo}`.\n"
                        "Aceito CNPJ, nº de OB ou parte do nome do fornecedor.")
            blocos = []
            for ob in obs:
                ref = ob.numero_ob or f"ob:{ob.id}"
                laudo = periciar_ob(session, ob)
                memoria_pericial.registrar_laudo(laudo, referencia=ref)
                blocos.append(_fmt_laudo(laudo, referencia=ref))
            extra = ""
            if len(obs) > 1:
                extra = f"_(3 maiores OBs de {obs[0].favorecido_nome})_\n\n"
            return extra + "\n\n———\n\n".join(blocos)
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        return f"❌ Erro na perícia: {exc}"


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
        except Exception:
            pass
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
        return "Use: `/fornecedor <CNPJ>` (14 dígitos)"
    try:
        from compliance_agent.nucleo.memoria_pericial import perfil_fornecedor
        p = perfil_fornecedor(digitos)
        if p is None:
            return (f"CNPJ `{digitos}` ainda sem perícias na memória.\n"
                    "Rode `/pericia {}` primeiro.".format(digitos))
        alerta = ("⚠️ *REINCIDENTE*" if p.criticos_e_altos >= 2 else "")
        return (f"🏢 *Perfil aprendido — CNPJ {digitos}* {alerta}\n"
                f"Perícias: {p.total_pericias} | risco médio: "
                f"*{p.risco_medio:.0f}/100*\n"
                f"Laudos crítico/alto: {p.criticos_e_altos}\n"
                f"Vereditos: {p.confirmados} confirmados, "
                f"{p.descartados} descartados")
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

    # veredito: "confirmado"/"procede"/"descarta" + referência
    if any(k in t for k in ("confirmad", "procede", "descartad", "improcede",
                            "falso alarme", "inconclusiv")):
        ref = (ob and ob.group(1)) or (cnpj and cnpj.group(0)) or ""
        if ref:
            if any(k in t for k in ("descartad", "improcede", "falso alarme")):
                return ("/veredito", f"{ref} descartado")
            if "inconclusiv" in t:
                return ("/veredito", f"{ref} inconclusivo")
            return ("/veredito", f"{ref} confirmado")

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
/parametros — limiares vigentes (🔒 legais | 🔧 calibráveis)
/evolucao — diário: o que o sistema mudou em si mesmo
_Também entendo sem comando: "pericia a MGS Clean", "2024OB01234 confirmado"…_
""".strip()
