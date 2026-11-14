"""A lista de abas do painel tem UMA fonte: o proprio painel.

Os dois auditores (contraste e layout) carregavam uma copia manual de 9 abas. O
painel tem 51. Copia de lista diverge — foi assim que a constante de dispensa
ganhou uma terceira copia dentro de um detector e produziu falso positivo publico.
Aqui a divergencia era pior porque silenciosa: o auditor dizia "9 abas limpas" e
o laudo era lido como "o painel esta limpo".

Este teste nao roda navegador — le o HTML. Custa milissegundos e vale na VM-2.
"""

from tools.painel_abas import abas, abas_por_esfera

# Se o painel ganhar ou perder aba, ATUALIZE estes numeros de proposito: a
# mudanca tem de ser uma decisao, nao um efeito colateral que ninguem viu.
# 2026-07-28: 51 → 52 e estado 14 → 15. Entrou a aba "Responsáveis" (esfera Estado), que expõe
# `/api/responsaveis` — capacidade que existia desde 27/07 sem nenhuma tela.
# 2026-07-29: 52 → 57 e geral 22 → 27. A auditoria mediu 57 de 158 rotas SEM ponto de entrada no
# painel; entraram cinco abas transversais que ligam o que estava implementado e invisível:
# Vínculos (beneficiário final, parentesco, histórico societário), Peças (dossiê completo, dossiê
# mestre, minuta .docx, PPP, acatamento, conjunto), Fontes externas (os seis providers),
# Hub físico (detector que nasceu sem tela) e Acurácia (/api/eval/hermeneutica e /api/eval/lift).
# Segunda onda do mesmo dia: Detectores (dez leituras que existiam sem tela), Instrumentação
# (agenda, pipelines, memória, UGs, SIAFE, radar, núcleo) e Missões (a fila paralela do Hermes, que
# só existia no backend). Órfãs: 57 → 22.
# 2026-08-22: 60 → 61 e estado 15 → 16. Entrou "Lentes cruzadas" (`e_lentes`), que expõe
# `/api/lentes`. Mesmo motivo da aba "Responsáveis" acima: quatro lentes de detecção existiam
# como CLI e nenhuma tinha caller — o 7º "construído, testado, nunca rodado" da casa. Quem
# acusou foi `test_rotas_sem_superficie`, cujo teto é 0.
# 2026-09-09: 62 → 63 e estado 17 → 18. Entrou "TAC recorrente" (`e_tac`): o coletor do DOERJ passou a
# ler o PDF integral e `doerj_tac` mostrou 1.134 Termos de Ajuste de Contas (R$ 722,7 mi) em 69 dias —
# pagamento sem contrato como rotina na saúde estadual; a aba expõe quem, quantas vezes e quanto.
# 2026-09-12: 63 → 64 e estado 18 → 19. Entrou "Imprensa por órgão" (`e_imprensa`): Google News RSS (sem chave)
# por órgão, classificado por termo de risco — pedido do dono por fontes online sem API.
# 2026-11-09: 67 → 68 e geral 32 → 33. Entrou "Requerimentos" (`g_requerimentos`): os pedidos de informação
# sugeridos pelas investigações, lidos de `~/vault/requerimentos/` — pedido do dono; só leitura.
# 2026-11-13: 68 → 69 e estado 19 → 20. Entrou "Comissão de Orçamento" (`e_comissao`): sub-aba da Comissão
# de Orçamento da ALERJ (problemas por fornecedor órgão a órgão, peças P1–P18, SICONFI por Poder) — pedido do dono.
# 2026-11-13: 69 → 70 e estado 20 → 21. Entrou "Governo Couto" (`e_couto`): tudo o que a base tem sobre a gestão do
# governador em exercício desde 23/03/2026 (atos DOERJ, contratações, OB SIAFE, controle, pontos de atenção) — pedido do dono.
# 2026-11-13: entraram "Perícia contábil" (`e_pcont`) e "CGE × JFN" (`e_cge`) — rotinas automáticas; e Íntegras
# (Município do Rio) foi de estado para prefeitura.
# 2026-11-13: 72 → 73 e geral 33 → 34. Entrou "Conformidade" (`g_conform`): o painel de conformidade das regras de
# qualidade do próprio JFN (por sistema: regras, violações abertas, tendência, juiz, dívida) — /api/qualidade/conformidade.
# 2026-11-14: 73 → 74; geral 34 → 29 e nova esfera "sistema" (6). Pedido do dono: "coloque uma outra aba
# (configurações e funcionamento do sistema) e mova o que for disso". Foram para lá Sistema (agora "Coletas e
# rotinas"), Instrumentação, Conformidade, Acurácia e Missões, e entrou "Motores" (`s_motores`) com a grade de
# motores e o cruzamento de motores que estavam no Início. Custo de API/assinatura saiu do painel.
# Mesmo dia: entrou "Comandos" (`s_comandos`, as funções mestras que ficavam no rodapé do Início) → 75, sistema 7.
# 2026-11-14: 75 → 76 e estado 22 → 23. Entrou "Orçamento por órgão" (`e_orcorg`): por órgão, unidade orçamentária e
# UG, dotação inicial e atualizada, empenhado, liquidado, pago por OB do SIAFE e taxas de execução, com ranking e
# filtro por exercício e mês (`/api/orcamento_orgao`) — pedido do dono ("quais órgãos têm orçamento e quanto executou").
TOTAL = 76
POR_ESFERA = {"inicio": 1, "estado": 23, "prefeitura": 16, "geral": 29, "sistema": 7}


def test_le_todas_as_abas_do_painel():
    lista = abas()
    assert len(lista) == TOTAL, (
        f"o painel tem {len(lista)} abas, o teste esperava {TOTAL} — se a mudanca "
        "foi de proposito, atualize TOTAL e POR_ESFERA aqui"
    )
    assert lista[0] == "i_cockpit", "a primeira aba deixou de ser o cockpit"
    assert len(set(lista)) == len(lista), "id de aba repetido no painel"


def test_agrupa_por_esfera():
    por_esf = abas_por_esfera()
    assert set(por_esf) == set(POR_ESFERA), (
        f"as esferas mudaram: {sorted(por_esf)} != {sorted(POR_ESFERA)}"
    )
    for esf, quantas in POR_ESFERA.items():
        assert len(por_esf[esf]) == quantas, (
            f"esfera {esf}: {len(por_esf[esf])} abas, esperava {quantas}"
        )


def test_os_auditores_usam_a_fonte_unica():
    """Guarda-corpo contra a volta da copia manual.

    Nao basta existir uma fonte unica; os auditores tem de CHAMAR ela. Se alguem
    colar de volta uma lista literal, o laudo volta a cobrir uma fatia e a ser
    lido como o todo.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    for nome in ("auditar_contraste.py", "auditar_layout.py"):
        fonte = (raiz / "tools" / nome).read_text(encoding="utf-8")
        assert "painel_abas" in fonte, (
            f"{nome} nao usa mais tools/painel_abas — a lista de abas voltou a ser copia"
        )
