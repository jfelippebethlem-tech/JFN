# -*- coding: utf-8 -*-
"""C · PERFIL DO CONTRATADO (FACHADA/LARANJA) — C1/C2/C3/C5/C4 (spec V2 do dono, §5).

WRAPPER, não reimplementação. Reusa `investigacao_dd.investigar(cnpj, ...)` — a bateria doubt-driven de hipóteses
de fachada/laranja que o JFN já roda. NÃO recalculamos nada: pegamos as hipóteses (`H-*`) já avaliadas (cada uma
com `status` ∈ {INDICIO, CONFIRMADO}, `nivel` ∈ {ALTO, MEDIO} e `peso`) e MAPEAMOS cada uma para o detector C
correspondente do spec, convertendo o juízo já feito para a ÂNCORA do framework (spec §1.2/§1.4).

MAPA hipótese (investigacao_dd) → detector C (spec §5):
  H-RECENTE                                  → C1 (CNPJ recém-nascido)
  H-CAPITAL · H-END-RESID · H-PORTE          → C2 (estrutura incompatível com o objeto)
  H-SITUACAO (situação irregular/sancionada) → C3/C5 (atividade/reencarnação — empresa não-ativa/inidônea)
  H-COEND · H-SOCIO-UNICO                    → C4 (quadro societário suspeito / co-endereço — laranja)

CONVERSÃO PARA ÂNCORA (código, nunca prompt):
  status CONFIRMADO + nivel ALTO   → 'forte'   |   CONFIRMADO + MEDIO → 'medio'
  status INDICIO    + nivel ALTO   → 'medio'   |   INDICIO    + MEDIO → 'fraco'
(presunção de regularidade: um INDÍCIO nunca vira 'crítico' sozinho — crítico exige prova direta/violação legal.)

HONESTIDADE JFN: cada hipótese que `investigar` marcou INDISPONÍVEL (campo não ingerido) NÃO gera detector
'ausente=0' — simplesmente não há hipótese, logo o detector daquela família fica `nao_avaliavel` (ausência de
juízo ≠ regular). FALSOS POSITIVOS do spec (C): entidade comunitária/associação sem fins lucrativos, padronização
legítima, comércio/representação que opera com capital baixo — a exculpatória adversarial recebe essas hipóteses.

Família "perfil" (peso 0.8, §7.2)."""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora

# hipótese (codigo de investigacao_dd) → (id do detector C, nome legível, família do spec)
_MAPA_C: dict[str, tuple[str, str]] = {
    "H-RECENTE": ("C1", "CNPJ recém-nascido"),
    "H-CAPITAL": ("C2", "Estrutura incompatível com o objeto — capital ínfimo"),
    "H-END-RESID": ("C2", "Estrutura incompatível com o objeto — sede residencial"),
    "H-PORTE": ("C2", "Estrutura incompatível com o objeto — volume acima do porte"),
    "H-SITUACAO": ("C3/C5", "Situação cadastral irregular / reencarnação de sancionada"),
    "H-COEND": ("C4", "Quadro societário suspeito — co-endereço de fornecedores"),
    "H-SOCIO-UNICO": ("C4", "Quadro societário suspeito — sócio único com sinais de fachada"),
}


def _ancora_de_hipotese(status: str, nivel: str) -> str:
    """Converte o juízo JÁ feito por `investigacao_dd` (status × nível) para a âncora do framework (§1.2).
    Honesto/conservador: indício nunca vira crítico — crítico exige violação objetiva/prova direta."""
    st = (status or "").strip().upper()
    nv = (nivel or "").strip().upper()
    if st == "CONFIRMADO":
        return "forte" if nv == "ALTO" else "medio"
    # INDICIO (ou qualquer outro)
    return "medio" if nv == "ALTO" else "fraco"


def _explicacao_inocente(cid: str) -> str:
    base = ("FALSO POSITIVO a descartar (spec C): "
            "indício ≠ acusação; presunção de regularidade do ato administrativo. ")
    if cid == "C1":
        return base + ("filial nova de grupo consolidado (a idade relevante é a do grupo) ou MEI/ME em cota "
                       "reservada de pequeno valor (LC 123) é funcionamento esperado da política pública.")
    if cid == "C2":
        return base + ("comércio/representação opera legitimamente com capital baixo e equipe mínima; capital "
                       "social é dado fraco isolado — só agrava em convergência. Entidade comunitária/associação "
                       "sem fins lucrativos pode ter sede modesta sem ser fachada.")
    if cid.startswith("C3"):
        return base + ("sanção expirada não impede contratar (a vigência na DATA é o teste); CNAE brasileiro é "
                       "impreciso e empresas legítimas operam fora do código formal.")
    if cid == "C4":
        return base + ("homonímia é a maior fonte de falso positivo no Brasil (nome igual nunca basta); famílias "
                       "empresárias legítimas têm sócios recorrentes; despachante/contador compartilhado isolado "
                       "não basta — só compõe perfil com outro vínculo.")
    return base


class CFachada(Detector):
    """Detector(es) C — perfil do contratado (fachada/laranja), via `investigacao_dd.investigar`.

    Diferente dos demais, UMA investigação produz VÁRIOS detectores (um por hipótese mapeada). O método
    `avaliar(contexto)` devolve o ResultadoDetector da hipótese de MAIOR âncora (o achado-líder), p/ encaixar na
    interface `Detector`; use `avaliar_todos(contexto)` para a LISTA completa (C1/C2/C3-5/C4), que é o que o
    orquestrador consome.

    `avaliar(contexto)` / `avaliar_todos(contexto)` esperam:
      contexto["cnpj"] (ou ["processo"]): o fornecedor investigado.
      contexto["investigacao"] (opcional): retorno pré-computado de `investigacao_dd.investigar` (p/ teste/cache,
          SEM tocar rede/DuckDB). Ausente → chama `investigar(cnpj, cadastral=..., pagamentos=...)`.
      contexto["cadastral"] / contexto["pagamentos"] (opcionais): repassados a `investigar`.

    Honesto: investigação sem nenhuma hipótese mapeável ⇒ `nao_avaliavel` (não 0)."""

    id = "C"  # família-mãe; os filhos carregam C1/C2/C3-5/C4
    nome = "Perfil do contratado (fachada/laranja)"
    familia = "perfil"

    def _investigar(self, contexto: dict):
        inv = contexto.get("investigacao")
        if inv is not None:
            return inv, None
        cnpj = str(contexto.get("cnpj") or contexto.get("processo") or contexto.get("id") or "")
        try:
            from compliance_agent.investigacao_dd import investigar
            inv = investigar(
                cnpj,
                cadastral=contexto.get("cadastral"),
                pagamentos=contexto.get("pagamentos"),
                usar_rede=bool(contexto.get("usar_rede", False)),  # default OFF em teste/leve
                geocode=bool(contexto.get("geocode", False)),
                usar_beneficios=bool(contexto.get("usar_beneficios", False)),
            )
            return inv, None
        except Exception as e:  # noqa: BLE001 — investigar indisponível (rede/DuckDB): honesto, não 0
            return None, f"nao_avaliavel: investigacao_dd.investigar indisponível ({str(e)[:60]})"

    def avaliar_todos(self, contexto: dict) -> list[ResultadoDetector]:
        proc = str(contexto.get("cnpj") or contexto.get("processo") or contexto.get("id") or "?")
        inv, erro = self._investigar(contexto)
        if inv is None:
            r = ResultadoDetector(detector="C", processo=proc, status="nao_avaliavel",
                                  motivo_refutacao=erro or "nao_avaliavel: investigação indisponível")
            return [r]

        cnpj = str(inv.get("cnpj") or proc)
        resultados: list[ResultadoDetector] = []
        for h in (inv.get("hipoteses") or []):
            cod = h.get("codigo")
            if cod not in _MAPA_C:
                continue  # H-PEP/H-BENEFICIO/H-END-EXISTE etc. → outros cards (C6 etc.), não estes
            cid, nome = _MAPA_C[cod]
            nivel = _ancora_de_hipotese(h.get("status"), h.get("nivel"))
            r = ResultadoDetector(detector=cid, processo=cnpj, score=ancora(nivel), status="confirmado")
            r.valores = {
                "hipotese": cod,
                "titulo": h.get("titulo"),
                "status_investigacao": h.get("status"),
                "nivel_investigacao": h.get("nivel"),
                "ancora": nivel,
                "peso_investigacao": h.get("peso"),
                "grau_geral": inv.get("grau"),
                "score_investigacao": inv.get("score"),
            }
            r.add_evidencia(fonte=h.get("fonte") or "investigacao_dd",
                            trecho=str(h.get("evidencia") or h.get("titulo") or cod))
            r.motivo_refutacao = f"{cod} ({h.get('status')}/{h.get('nivel')}) → {cid} âncora {nivel}"
            r.explicacao_inocente = _explicacao_inocente(cid)
            resultados.append(r)

        if not resultados:
            r = ResultadoDetector(detector="C", processo=cnpj, status="nao_avaliavel",
                                  motivo_refutacao=("nenhuma hipótese de fachada/laranja mapeável (campos não "
                                                    "ingeridos ou empresa sem sinais) — ausência de juízo ≠ regular"))
            r.valores = {"cobertura": inv.get("cobertura"), "grau_geral": inv.get("grau")}
            return [r]
        # ordena por score desc (achado-líder primeiro)
        resultados.sort(key=lambda x: -x.score)
        return resultados

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        """Interface `Detector`: devolve o achado-líder (maior âncora). A lista completa vem de `avaliar_todos`."""
        return self.avaliar_todos(contexto)[0]
