# Lex — aprendizados da CGE-RJ e do relatório-ouro CASHPAGO/LiciNexus

> Material empírico para evoluir o Lex e o Relatório de Inteligência. Complementa `docs/LEX-DOUTRINA-IMPROBIDADE.md`
> (doutrina) e `docs/LEX-BASE-JURIDICA.md` (red flags). Fonte 1: relatório `RELATORIO_CASHPAGO_28584601_REDE_FRAUDE_v5.pdf`
> (LiciNexus, 26 págs., CNPJ 28.584.601/0001-08). Fonte 2: CGE-RJ (formato dos relatórios de controle interno) + CGU.

## 1. O insight central do CASHPAGO — ler a ÍNTEGRA muda o veredito

O relatório só virou "RISCO ALTO" porque **baixou do PNCP e leu na íntegra os atos de inexigibilidade**. O valor
aparente do contrato de Angra/RJ era **R$ 0,01** (economicamente impossível). O texto integral revelou um **modelo
de remuneração OCULTO e EXTRAORÇAMENTÁRIO: 12% sobre todas as transações** processadas pela plataforma — ou seja, o
valor real não era R$ 0,01 nem os R$ 2,16M visíveis, mas um percentual fora do orçamento. **Lição para o Lex:** o
número da OB/contrato pode ser **isca**; a verdade está no texto do ato. Confirma a diretriz do Mestre Jorge de o Lex
ler o inteiro teor (hoje bloqueado por WAF na VM — ver `docs/ECOSSISTEMA-EVOLUCAO.md` §3.1).

## 2. O que o CASHPAGO ensina (estrutura + técnicas a adotar no Lex)

| # | Técnica do relatório-ouro | O que adicionar ao Lex |
|---|---|---|
| 1 | **Rede por sócio comum em 3 níveis** (alvo → sócios diretos → outras empresas deles → sócios dessas) → 42 CNPJs | Automatizar com Splink (resolução de entidade) + grafo (networkx). Hoje Lex olha 1 CNPJ; passar a olhar a **rede**. |
| 2 | **Leitura integral dos atos (PNCP/SEI)** expõe cláusula oculta | `_ler_integra_sei` + baixar atos do **PNCP** (host alcançável da VM) e cruzar **valor aparente × remuneração real** |
| 3 | **Red flag "valor simbólico/impossível"** (R$ 0,01; R$ 1,00) | Nova regra: OB/contrato com valor irrisório vs. objeto → indício de remuneração extraorçamentária a apurar |
| 4 | **Sinais de risco pontuados** (13 sinais: 6 ALTOS/5 MÉDIOS/2 BAIXOS) → veredito | Lex já tem grau; padronizar a **lista numerada de sinais com nível** no parecer |
| 5 | **Fusão multifonte** (Receita + PNCP + Transparência + CEIS/CNEP/CEPIM/CEAF) | JFN já tem parte; faltam **sanções** (CEIS/CNEP) e **PNCP** como fontes de 1ª classe |
| 6 | **Vínculo a setores regulados** (fintech → BCB/Coaf) | Quando o objeto for meio de pagamento/financeiro, recomendar ciência a **BCB/Coaf** (lavagem) |
| 7 | **Marcas de honestidade**: "Conclusão preliminar", "USO INTERNO — SIGILO", recomenda apuração por órgão competente | Lex já faz; manter e reforçar (nunca afirmar crime) |

## 3. O que a CGE-RJ ensina (formato oficial do controle interno)

A CGE-RJ (controle interno do Executivo estadual) estrutura sua produção em modelos nomeados — o Lex deve
**espelhar esse formato** para que a saída "fale a língua" do controle e seja aproveitável:

- **Nota Técnica COM Achado** / **Nota Técnica SEM Achado** (fase interna/externa) — é o documento-base. *O parecer Lex
  deveria ter essa bifurcação: com indício → "Nota Técnica com Achado"; sem → "sem Achado", mantendo presunção de regularidade.*
- **PLANAT** (Plano Anual de Auditoria) e **RANAT** (Relatório Anual de Atividades) — planejamento/prestação.
- **Relatório da Unidade de Controle Interno**; formulários de **acompanhamento de execução do contrato**, **DEA & RP**
  (Despesas de Exercícios Anteriores e Restos a Pagar), **Termo de Aceitação Definitiva de Obras**.

**Anatomia de um ACHADO** (padrão CGU/auditoria governamental, usado pela CGE) — o Lex deve emitir cada indício neste molde:
1. **Situação encontrada** (o fato observado nos dados/no ato).
2. **Critério** (norma violada — Lei 14.133/8.666, decreto, súmula/acórdão TCU/TCE-RJ).
3. **Causa** (provável razão — falha de controle, planejamento de fachada…).
4. **Efeito/consequência** (dano potencial ao erário, restrição à competição).
5. **Evidência** (OB nº, ato do PNCP/SEI, valor, data).
6. **Recomendação** (diligência; representação ao TCE-RJ; ciência MP-RJ/CADE/BCB-Coaf).
7. **Manifestação do gestor** (espaço para contraditório — reforça presunção de legitimidade).

## 4. Produto final proposto para o Lex (síntese)

Evoluir o parecer Lex para o formato **"Nota Técnica de Indícios"** (espelho da Nota Técnica com/sem Achado da CGE-RJ):
- **Sumário executivo** (CNPJ, situação cadastral, núcleo direto, **rede ampliada de sócios**, nº de sinais por nível, conclusão preliminar).
- **Metodologia + fontes + limitações** (incl. "CPF mascarado", "íntegra indisponível por WAF" quando for o caso).
- **Achados no molde CGU** (situação/critério/causa/efeito/evidência/recomendação/manifestação) — um por red flag.
- **Mapa de improbidade/crime** (ver `LEX-DOUTRINA-IMPROBIDADE.md`): cada achado aponta o tipo da Lei 8.429 (art. 9/10/11)
  e/ou crime (CP/Lei 14.133), **sempre com a cautela do dolo** (Lei 14.230/2021) e linguagem condicional.
- **Encaminhamentos** (TCE-RJ; MP-RJ; CADE; BCB/Coaf quando financeiro).
- **Cláusula de honestidade** reforçada: indício ≠ condenação; presunção de legitimidade; uso interno.

## 5. Próximos passos concretos (entram no roadmap da Onda 2/3)
1. **Rede por sócio comum (3 níveis)** — `compliance_agent/rede_societaria.py` (Receita/QSA + Splink + networkx). [P1]
2. **Regra "valor simbólico/impossível"** (R$ 0,01–R$ 1,00 vs. objeto) — entra no detector da Onda 1. [P0]
3. **Coletor PNCP de atos** (baixar e ler a íntegra de inexigibilidade/dispensa do PNCP — host alcançável). [P1]
4. **Achado no molde CGU** + bifurcação "com/sem Achado" no `lex.py`. [P1]
5. **Fontes de sanção** (CEIS/CNEP/CEPIM/CEAF) no enriquecimento. [P1]

> Fontes: relatório CASHPAGO/LiciNexus v5 (enviado pelo Mestre Jorge); CGE-RJ
> (cge.rj.gov.br/relatorios-da-auditoria, /formularios); CGU "Orientação Prática: Relatório de Auditoria".
