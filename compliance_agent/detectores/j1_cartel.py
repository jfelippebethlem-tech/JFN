# -*- coding: utf-8 -*-
"""J1 · CONLUIO / CARTEL — RODÍZIO DE VENCEDORES (spec V2 do dono, §4/J1).

WRAPPER, não reimplementação. Reusa o que o JFN JÁ tem (MAPA dos 30 detectores no docstring de `base.py`):
  • `grafo_cartel.concentracao_por_grupo(ug)` — colapsa a UG por GRUPO ECONÔMICO (sócio em comum) e revela
    concorrência FICTÍCIA: muitos CNPJs que parecem concorrentes mas são UM grupo multi-raiz com share alto.
  • `rodizio_temporal.rodizio_orgao(ug)` — alternância temporal de campeões (bid rotation) sobre as OBs.

Entrada = UG (unidade gestora). Saída = `ResultadoDetector` no schema fixo (spec §1.4). A LÓGICA de detecção
fica nos módulos reusados; aqui só ADAPTAMOS ao schema, convertendo os indícios para ÂNCORA (spec §1.2):

  REGRA DE ÂNCORA (código, nunca prompt):
    • grupo MULTI-CNPJ (≥2 raízes) com share alto + sócio-elo em comum  → 'critico' (sócio comum entre
      "concorrentes" é prova direta de concorrência fictícia — §1.2 anchor crítico)
    • grupo multi-CNPJ com share alto, MAS sem sócio-elo materializado    → 'medio' (anomalia clara; exige
      confirmação — pode ser coincidência de raiz/grupo sem vínculo societário provado)
    • rodízio temporal corroborado (alternância de campeões)              → reforça (sobe um nível, teto forte)
    • nada disso                                                          → 'descartado'

Família "conluio" (peso 0.9, §7.2). Destinatário implícito MP + CADE (já tratado no Lex).

HONESTIDADE JFN: indício ≠ acusação; presunção de regularidade. FALSO POSITIVO do spec (J1): mercado restrito
genuíno (poucos fornecedores reais na região) gera concentração SEM cartel — por isso concentração isolada (sem
sócio-elo nem alternância) NÃO sobe acima de 'medio', e a exculpatória adversarial recebe a hipótese inocente
"mercado concentrado natural / consórcio legítimo". INDISPONÍVEL (sem dados na UG) → `nao_avaliavel`, nunca 0.
"""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora


def _share(d: dict) -> float:
    mm = d.get("maior_grupo_multi") or {}
    return float(mm.get("share") or 0.0)


class J1Cartel(Detector):
    """Detector J1 — conluio/cartel por concentração de grupo econômico + rodízio temporal numa UG.

    `avaliar(contexto)` espera:
      contexto["ug"] (ou contexto["processo"]): a unidade gestora investigada.
      contexto["concentracao"] (opcional): retorno pré-computado de `grafo_cartel.concentracao_por_grupo`.
          Ausente → chama a função (best-effort; se a base/DuckDB indisponível, degrada para nao_avaliavel).
      contexto["rodizio"] (opcional): retorno pré-computado de `rodizio_temporal.rodizio_orgao`.
      contexto["min_share"] (opcional float, default 15.0): share mínimo do grupo multi-CNPJ p/ flag.

    Em TESTE, injete `concentracao`/`rodizio` no contexto (sem tocar DuckDB)."""

    id = "J1"
    nome = "Conluio/cartel — rodízio de vencedores"
    familia = "conluio"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        ug = str(contexto.get("ug") or contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(ug, status="nao_avaliavel")
        min_share = float(contexto.get("min_share") or 15.0)

        conc = contexto.get("concentracao")
        if conc is None:
            try:
                from compliance_agent.grafo_cartel import concentracao_por_grupo
                conc = concentracao_por_grupo(ug, min_share_grupo=min_share)
            except Exception as e:  # noqa: BLE001 — base/DuckDB indisponível: honesto, não 0
                res.motivo_refutacao = f"nao_avaliavel: concentracao_por_grupo indisponível ({str(e)[:60]})"
                return res

        if not isinstance(conc, dict) or conc.get("n_cnpjs", 0) == 0:
            res.motivo_refutacao = "nao_avaliavel: sem fornecedores PJ na UG (base ausente/vazia) — campo ausente ≠ 0"
            res.valores = {"n_cnpjs": (conc or {}).get("n_cnpjs", 0)}
            return res

        rodizio = contexto.get("rodizio")
        if rodizio is None:
            try:
                from compliance_agent.rodizio_temporal import rodizio_orgao
                rodizio = rodizio_orgao(ug)
            except Exception:  # noqa: BLE001 — rodízio é REFORÇO opcional; sua ausência não derruba o J1
                rodizio = None

        mm = conc.get("maior_grupo_multi") or {}
        share = _share(conc)
        n_raizes = int(mm.get("n_raizes") or 0)
        n_cnpjs_grupo = int(mm.get("n_cnpjs") or 0)
        grupo_multi = bool(mm) and n_raizes >= 2 and share >= min_share

        # sócio-elo: o grupo multi-raiz EXISTE porque `grafo_cartel` uniu CNPJs por SÓCIO em comum
        # (n_cnpjs > n_raizes ⇒ pelo menos dois CNPJs de raízes distintas colapsaram via sócio).
        socio_elo = grupo_multi and n_cnpjs_grupo > n_raizes
        rodizio_corrobora = bool(isinstance(rodizio, dict) and rodizio.get("indicio"))

        res.valores = {
            "ug": ug,
            "n_cnpjs": conc.get("n_cnpjs"),
            "n_grupos_multi": conc.get("n_grupos_multi"),
            "maior_grupo_share": share,
            "maior_grupo_n_cnpjs": n_cnpjs_grupo,
            "maior_grupo_n_raizes": n_raizes,
            "socio_elo_presente": socio_elo,
            "rodizio_indicio": rodizio_corrobora,
            "rodizio_score": (rodizio or {}).get("score") if isinstance(rodizio, dict) else None,
        }

        if not grupo_multi:
            res.status = "descartado"
            res.motivo_refutacao = (f"sem grupo multi-CNPJ com share ≥ {min_share}% "
                                    f"(maior grupo multi-raiz: share {share}%, raízes {n_raizes})")
            res.explicacao_inocente = ("concorrência real entre raízes distintas; concentração — se houver — "
                                       "compatível com mercado restrito legítimo")
            return res

        # ── ÂNCORA (código) ──
        if socio_elo:
            score = ancora("critico")
            achado = "grupo multi-CNPJ com SÓCIO EM COMUM concentrando a UG (concorrência fictícia)"
        else:
            score = ancora("medio")
            achado = "grupo multi-CNPJ com share alto, sem sócio-elo materializado (anomalia a confirmar)"

        if rodizio_corrobora:
            # rodízio temporal reforça o achado de cartel; teto 'forte' quando ainda não é crítico
            score = max(score, ancora("forte"))
            achado += " + rodízio temporal de vencedores corroborando"

        res.score = score
        res.status = "confirmado"
        res.motivo_refutacao = achado

        # evidência (higiene probatória §7.4): os CNPJs do grupo + o nome-elo (top do grupo)
        cnpjs = mm.get("cnpjs") or []
        res.add_evidencia(
            fonte=f"grafo_cartel.concentracao_por_grupo (UG {ug})",
            trecho=(f"grupo econômico de {n_cnpjs_grupo} CNPJ(s) sob {n_raizes} raiz(es) concentra {share}% "
                    f"da UG; top='{mm.get('top_nome') or '?'}'; CNPJs={', '.join(cnpjs[:8])}"),
        )
        if socio_elo:
            res.add_evidencia(
                fonte="grafo_cartel (união por sócio comum)",
                trecho=(f"{n_cnpjs_grupo} CNPJs de {n_raizes} raízes distintas foram colapsados em UM grupo por "
                        f"SÓCIO em comum — concorrência fictícia entre 'concorrentes' que dividem dono"),
            )
        if rodizio_corrobora and isinstance(rodizio, dict):
            camp = [c.get("nome", "")[:30] for c in (rodizio.get("campeoes") or [])[:4]]
            res.add_evidencia(
                fonte=f"rodizio_temporal.rodizio_orgao (UG {ug})",
                trecho=(f"rodízio score={rodizio.get('score')}, {rodizio.get('n_campeoes')} campeões revezando "
                        f"em {rodizio.get('n_anos')} exercícios (alternância {rodizio.get('alternancia')}); "
                        f"campeões: {', '.join(camp)}"),
            )

        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec J1): mercado restrito genuíno (poucos "
                                   "fornecedores reais na região) ou consórcio legítimo formalizado podem gerar "
                                   "concentração sem cartel — verificar barreiras naturais e se há alternância "
                                   "regular/perdedoras profissionais (que resistem à exculpatória estrutural).")
        return res
