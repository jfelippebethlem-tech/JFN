# -*- coding: utf-8 -*-
"""Identidade de pessoa entre bases — desambiguação de HOMÔNIMOS em camadas (régua única da casa).

Pedido do dono (19/11/2026): "homônimos em tudo têm que ser desmistificados através de outros dados".
Casar duas bases pelo NOME só diz que dois registros têm o mesmo nome. Este módulo decide, com prova
declarada, se é a MESMA pessoa — e nunca devolve um par só-por-nome como achado.

CAMADAS (cada uma com o nível de prova que sustenta):

1. **CPF posicional.** Cada base expõe uma JANELA diferente do CPF de 11 dígitos, e a janela da folha
   VARIA POR FONTE, embora todas gravem `XX123456XXX`:

       QSA da Receita (`***.123.456-**`) ............ dígitos 4–9
       folha GESPERJ (Executivo estadual) ........... dígitos 4–9   (deslocamento 3)
       folha DPRJ (Defensoria) ...................... dígitos 3–8   (deslocamento 2; 4–9 em 2018-01..04)
       folha TJRJ (anexo VIII) / Câmara do Rio ...... sem CPF publicado

   Controle positivo refeito em 19/11/2026 com os sócios cujo CPF COMPLETO foi resolvido por outra
   fonte (`socios_fornecedor.cpf_resolvido`), confrontados com a folha de mesmo nome (registro×mês):
   GESPERJ bate em 4–9 em 759 e em 3–8 em 0; DPRJ bate em 3–8 em 296 e em 4–9 em 12 (um único
   servidor de 2018, coincidência de homônimo). Confere com a medição de 13/11
   (`nomeados_candidatos.DESLOC_CPF_FONTE`, folha × TSE), que é a tabela canônica e é reusada aqui.
   A casa já errou isto TRÊS vezes, cada módulo presumindo uma janela só (3–8 em
   `cruzamentos_intel.socio_servidor`/`porta_giratoria`, `c8_servidor_socio` e
   `conflito_pessoal_view`; 4–9 em `resolucao_cpf.fusao_folha_qsa`). Efeito medido no sócio-na-folha:
   911 "homônimos descartados" e 0 casamentos no Executivo — o Executivo inteiro comparava os
   dígitos errados. Por isso a comparação é POSICIONAL: cada documento vira {posição: dígito} e só a
   interseção real das janelas é comparada.
   COMPATÍVEL exige ≥ 5 posições em comum todas iguais; uma posição diferente = INCOMPATÍVEL
   (homônimo descartado); menos de 5 em comum ou fonte sem janela aferida = SEM DADO (nunca chute).

2. **Prevalência do nome** (quantas pessoas distintas com o mesmo nome na folha e no QSA). Nome
   único é dado CONVERGENTE; nome comum sem CPF não sustenta nada. A chance de coincidência do CPF
   é declarada: (pessoas com o nome na folha × documentos com o nome no QSA) / 10^posições.

3. **Faixa etária da Receita × vínculo.** Só DESCARTA (não confirma): sócio de 0–12 anos não é
   servidor ativo (só pensionista). Faixa compatível NÃO conta como convergência — acende em ~99%
   da base, mede a base e não a pessoa (doutrina da prevalência, [[perfil-laranja-prevalencia]]).

4. **CPF completo resolvido por outra fonte** (favorecidos PF/TSE/SEI — `resolucao_cpf`): conta como
   convergente só quando ACRESCENTA posição que o QSA não mostra (ex.: o dígito 3 da DPRJ).

SELO por par:
  VERIFICADO    CPF compatível + ≥1 dado convergente (nome único na folha ou no QSA; CPF de outra fonte)
  PROVÁVEL      CPF compatível, nome comum (a chance de coincidência vai no motivo)
  HOMÔNIMO      CPF incompatível OU faixa etária impossível para o vínculo — descartado, com o motivo
  INDETERMINADO sem CPF comparável — diz QUAL dado falta. Não é achado.

LGPD: nada aqui devolve CPF; só a máscara do QSA (`***.123.456-**`) e contagens.
"""
from __future__ import annotations

import re
import unicodedata

from compliance_agent.nomeados_candidatos import DESLOC_CPF_FONTE

VERIFICADO, PROVAVEL, HOMONIMO, INDETERMINADO = "VERIFICADO", "PROVAVEL", "HOMONIMO", "INDETERMINADO"
COMPATIVEL, INCOMPATIVEL, SEM_DADO = "COMPATIVEL", "INCOMPATIVEL", "SEM_DADO"
MIN_POSICOES = 5            # interseção mínima de posições do CPF para afirmar compatibilidade

ROTULO_FONTE = {
    "gesperj_estado": "Executivo estadual (GESPERJ)",
    "dprj_transparencia": "Defensoria Pública (DPRJ)",
    "tjrj_anexo8": "Tribunal de Justiça (TJRJ)",
    "camara_csv": "Câmara Municipal do Rio",
}
# Por que a fonte não permite conferir CPF (o "qual dado falta" do INDETERMINADO)
FALTA_CPF_FONTE = {
    "tjrj_anexo8": "a folha do TJRJ (anexo VIII) não publica CPF",
    "camara_csv": "a folha da Câmara Municipal do Rio não publica CPF",
}

# Faixa etária da Receita (QSA): código → rótulo
FAIXA_ETARIA = {"1": "0 a 12 anos", "2": "13 a 20 anos", "3": "21 a 30 anos", "4": "31 a 40 anos",
                "5": "41 a 50 anos", "6": "51 a 60 anos", "7": "61 a 70 anos", "8": "71 a 80 anos",
                "9": "mais de 80 anos"}
_RX_PENSAO = re.compile(r"PENS|BENEF|BENEFEC|DEPENDENT")


def normalizar_nome(s: str) -> str:
    """Maiúsculas, sem acento, só letras e espaço simples (mesma régua de `cruzamentos_intel._norm_nome`)."""
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", s)).strip()


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def posicoes_qsa(doc) -> dict[int, str]:
    """Documento do sócio no QSA → {posição 1..11: dígito}. Máscara `***123456**` = posições 4–9;
    CPF completo (11 dígitos, sem máscara) = todas. CNPJ/vazio/formato estranho → {}."""
    s = str(doc or "").strip()
    d = _dig(s)
    if "*" in s and len(d) == 6:
        return {4 + k: ch for k, ch in enumerate(d)}
    if "*" not in s and len(d) == 11:
        return {1 + k: ch for k, ch in enumerate(d)}
    return {}


# Exceção medida (19/11/2026, mesmo controle positivo): a DPRJ publicou a janela 4–9 — e não a 3–8 de sempre —
# nas competências 2018-01 a 2018-04 (os 3 servidores com CPF completo conhecido batem em 4–9 exatamente nesses
# 4 meses e em 3–8 em todos os outros, de 2016-10 a 2025). A janela é da FONTE NO MÊS, não só da fonte.
EXCECOES_JANELA = [("dprj_transparencia", "2018-01", "2018-04", 3)]


def deslocamento(fonte: str | None, competencia: str | None = None) -> int | None:
    """Deslocamento (posição inicial − 1) da janela de 6 dígitos que a folha publica; None = não aferido."""
    comp = (competencia or "")[:7]
    for f, ini, fim, desl in EXCECOES_JANELA:
        if fonte == f and comp and ini <= comp <= fim:
            return desl
    return DESLOC_CPF_FONTE.get(fonte or "")


def posicoes_folha(cpf, fonte: str | None, competencia: str | None = None) -> dict[int, str]:
    """CPF da folha → {posição: dígito}, pela janela AFERIDA da fonte (no mês, quando há exceção). Fonte sem
    janela aferida → {} (presumir a janela é exatamente o erro que este módulo existe para impedir)."""
    s = str(cpf or "").strip().upper()
    m = re.fullmatch(r"X{2}(\d{6})X{3}", s)
    desl = deslocamento(fonte, competencia)
    if m and desl is not None:
        return {desl + 1 + k: ch for k, ch in enumerate(m.group(1))}
    d = _dig(s)
    if len(d) == 11 and "X" not in s:
        return {1 + k: ch for k, ch in enumerate(d)}
    return {}


def comparar_cpf(a: dict[int, str], b: dict[int, str]) -> tuple[str, int]:
    """(COMPATIVEL|INCOMPATIVEL|SEM_DADO, nº de posições comparadas)."""
    comuns = sorted(set(a) & set(b))
    if any(a[p] != b[p] for p in comuns):
        return INCOMPATIVEL, len(comuns)
    if len(comuns) < MIN_POSICOES:
        return SEM_DADO, len(comuns)
    return COMPATIVEL, len(comuns)


def mascarar(doc) -> str:
    """Máscara de exibição a partir do documento do QSA (nunca expõe dígito que a Receita não expõe)."""
    p = posicoes_qsa(doc)
    if not p:
        return "CPF não informado no QSA"
    d = "".join(p.get(i, "") for i in range(4, 10))
    return f"***.{d[:3]}.{d[3:6]}-**" if len(d) == 6 else "CPF não informado no QSA"


def _chance(n_folha: int, n_qsa: int, posicoes: int) -> str:
    """Chance de o CPF coincidir por acaso entre homônimos, em texto ('1 em 100 mil')."""
    pares = max(1, n_folha) * max(1, n_qsa)
    um_em = max(1, int(10 ** posicoes / pares))
    return "1 em " + f"{um_em:,}".replace(",", ".")


def classificar(*, doc_qsa, cpf_folha, fonte_folha: str, n_folha_nome: int, n_qsa_nome: int,
                faixa_etaria: str | None = None, vinculo: str | None = None,
                cpf_resolvido: str | None = None, competencia: str | None = None,
                pos_folha: dict[int, str] | None = None) -> dict:
    """Selo de identidade de UM par (sócio do QSA × registro da folha) — camadas acima.

    `n_folha_nome`: pessoas distintas com o mesmo nome em todas as folhas; `n_qsa_nome`: documentos
    distintos com o mesmo nome no QSA. Retorna {selo, motivo, falta, camadas:[{camada, resultado, prova}]}."""
    camadas: list[dict] = []
    q = posicoes_qsa(doc_qsa)
    f = pos_folha if pos_folha is not None else posicoes_folha(cpf_folha, fonte_folha, competencia)
    res, npos = comparar_cpf(q, f)
    if not f:
        prova_cpf = FALTA_CPF_FONTE.get(fonte_folha) or (
            "a folha não traz CPF neste registro" if not str(cpf_folha or "").strip()
            else f"janela do CPF da fonte '{fonte_folha}' não aferida")
    elif not q:
        prova_cpf = "o QSA não traz o CPF mascarado deste sócio"
    else:
        prova_cpf = f"{npos} posições do CPF em comum ({'iguais' if res == COMPATIVEL else 'diferentes' if res == INCOMPATIVEL else 'insuficientes'})"
    camadas.append({"camada": "cpf", "resultado": res, "prova": prova_cpf})

    # CPF completo por outra fonte: só conta se acrescenta posição que o QSA não mostra
    extra = posicoes_qsa(cpf_resolvido) if cpf_resolvido else {}
    conv_extra = False
    if extra and f:
        r2, n2 = comparar_cpf(extra, f)
        novas = set(f) - set(q)
        if r2 == INCOMPATIVEL:
            camadas.append({"camada": "cpf_outra_fonte", "resultado": INCOMPATIVEL,
                            "prova": "o CPF completo resolvido por outra fonte diverge da folha"})
            res = INCOMPATIVEL
        elif r2 == COMPATIVEL and novas:
            conv_extra = True
            camadas.append({"camada": "cpf_outra_fonte", "resultado": COMPATIVEL,
                            "prova": f"CPF completo de outra fonte confere também na posição {min(novas)}, que o QSA não mostra"})

    # faixa etária: só descarta
    fx = str(faixa_etaria or "").strip()
    if fx == "1" and not _RX_PENSAO.search(normalizar_nome(vinculo or "")):
        camadas.append({"camada": "faixa_etaria", "resultado": INCOMPATIVEL,
                        "prova": "o sócio tem 0 a 12 anos pela Receita e o vínculo não é de pensionista"})
        return {"selo": HOMONIMO, "motivo": "Faixa etária da Receita (0 a 12 anos) impossível para o vínculo da folha.",
                "falta": "", "camadas": camadas}
    if fx in FAIXA_ETARIA:
        camadas.append({"camada": "faixa_etaria", "resultado": "COMPATIVEL_NAO_CONTA",
                        "prova": f"{FAIXA_ETARIA[fx]} — compatível, mas não distingue pessoas (acende em ~99% da base)"})

    prev = f"{n_folha_nome} pessoa(s) com este nome nas folhas · {n_qsa_nome} documento(s) com este nome no QSA"
    camadas.append({"camada": "prevalencia_nome", "resultado": "RARO" if min(n_folha_nome, n_qsa_nome) <= 1 else "COMUM",
                    "prova": prev})

    if res == INCOMPATIVEL:
        return {"selo": HOMONIMO, "falta": "", "camadas": camadas,
                "motivo": "Mesmo nome, outra pessoa: os dígitos do CPF que as duas bases mostram são diferentes."}
    if res == SEM_DADO:
        return {"selo": INDETERMINADO, "camadas": camadas, "falta": prova_cpf,
                "motivo": f"Só o nome coincide — {prova_cpf}; sem CPF não há como separar de homônimo."}
    convergentes = []
    if n_folha_nome <= 1:
        convergentes.append("nome único nas folhas")
    if n_qsa_nome <= 1:
        convergentes.append("nome único no QSA")
    if conv_extra:
        convergentes.append("CPF de outra fonte confere")
    chance = _chance(n_folha_nome, n_qsa_nome, npos)
    if convergentes:
        return {"selo": VERIFICADO, "falta": "", "camadas": camadas,
                "motivo": f"CPF confere em {npos} dígitos e {', '.join(convergentes)} (acaso: {chance})."}
    return {"selo": PROVAVEL, "camadas": camadas, "falta": "um segundo dado que distinga o nome (ex.: CPF completo)",
            "motivo": f"CPF confere em {npos} dígitos, mas o nome é comum ({prev}); acaso: {chance}."}


ORDEM_SELO = {VERIFICADO: 0, PROVAVEL: 1, INDETERMINADO: 2, HOMONIMO: 3}
