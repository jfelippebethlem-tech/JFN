# Superfície de Detecção — Quantas Irregularidades o Sistema Pega
## Inventário medido, defeitos encontrados e o que falta

| | |
|---|---|
| **Emissão** | 27 de julho de 2026 |
| **Pergunta** | Quantas irregularidades podemos pegar? Quais? |
| **Método** | Contagem no código + contagem no banco + **reconferência de cada número no dado real** |
| **Regra** | Declarado ≠ implementado ≠ validado ≠ disparando. Este documento separa os quatro. |

---

## 1. Resposta curta

**42 tipos catalogados · 31 detectores implementados · 23 com teste · 4 regras disparando em escala.**

A distância entre 42 e 4 é a resposta honesta. E o número que mais impressionava era o mais frágil:
das **59.209** marcações de fracionamento no banco, **2.225** sobrevivem a uma verificação
elementar — as outras 57 mil não são achados.

| Camada | Quantidade | O que significa |
|---|---:|---|
| Vícios catalogados (`knowledge/catalogo_vicios`) | **42** | Tipologia de referência, com lacunas declaradas |
| Red flags do parecer (`lex_redflags._RF`) | **24** | 14 regras R2–R15 + 10 hipóteses de fachada (DD/H-*) |
| Detectores estruturados (`detectores/`) | **31** | Implementados e registrados; framework com âncoras fixas |
| — destes, com teste automatizado | **23** | 8 detectores sem rede de proteção |
| Regras rodando sobre todo o acervo de pagamentos | **4** | `ob_redflag`: fracionamento (2), valor simbólico, concentração |
| Tipos de alerta persistidos nos sweeps PCRJ/emendas | **12** | 7.058 alertas gravados |

---

## 2. As 31 irregularidades que o sistema sabe caçar

Agrupadas pela fase do ciclo de contratação, com o estado real medido (arquivo existe, tem função
de detecção, está registrado, tem teste):

### Planejamento — 6 detectores
| Código | Irregularidade | Teste |
|---|---|:-:|
| P1 | Especificação dirigida / marca disfarçada | ⬜ |
| P2 | Cotações combinadas (orçamentos de fachada) | ⬜ |
| P3 | Sobrepreço na estimativa | ⬜ |
| P4 | Fracionamento de despesa (cluster por objeto, por exercício) | ✅ |
| P5 | Emergência fabricada | ⬜ |
| P6 | Contratação direta indevida | ✅ |

### Edital — 8 detectores
| Código | Irregularidade | Teste |
|---|---|:-:|
| E1 | Barreira de entrada na qualificação | ✅ |
| E2 | Publicidade e prazos minimizados | ⬜ |
| E3 | Lote-pacote (agregação anticompetitiva) | ⬜ |
| E4 | Visita técnica usada como filtro | ✅ |
| E5 | Edital iterado (republicação dirigida) | ✅ |
| E6 | Pontuação técnica dirigida | ✅ |
| E7 | Cláusula restritiva (motor validado, 0 falso positivo) | ✅ |
| E8 | Deserto dirigido | ✅ |

### Julgamento — 8 detectores
| Código | Irregularidade | Teste |
|---|---|:-:|
| J1 | Cartel / rodízio de vencedores | ⬜ |
| J2 | Propostas de cobertura | ⬜ |
| J3 | Desconto anômalo | ⬜ |
| J4 | Supressão de propostas | ⬜ |
| J5 | Digitais compartilhadas (metadados de arquivo) | ✅ |
| J6 | Subcontratação cruzada / consórcio de fachada | ✅ |
| J7 | Inabilitação seletiva (dois pesos, duas medidas) | ✅ |
| J-AT | Atestado de capacidade técnica cruzado | ✅ |

### Perfil do contratado — 3 detectores
| Código | Irregularidade | Teste |
|---|---|:-:|
| C6 | Vínculo político-financeiro (doação eleitoral) | ✅ |
| C7 | Empresa sancionada contratada | ✅ |
| C-FA | Empresa de fachada | ✅ |

### Execução — 6 detectores
| Código | Irregularidade | Teste |
|---|---|:-:|
| X1 | Crescimento por aditivo (contrato engorda) | ✅ |
| X2 | Prorrogação perpétua | ✅ |
| X3 | Execução financeira anômala | ✅ |
| X4 | Carona abusiva em ata de registro de preços | ✅ |
| X5 | Jogo de planilha | ✅ |
| X6 | Entrega fantasma / atesto de fachada | ✅ |

**O mapa interno estava desatualizado.** `detectores/base.py` declarava 9 destes como
"⬜ a construir" — mas os arquivos existem, com função de detecção e registro. Entre eles
`e2_prazos` (332 linhas), `x4_carona_abusiva` (397) e `p5_emergencia_fabricada` (259). O sistema
é **maior** do que a própria documentação afirmava.

**Os 8 sem teste** são o risco real: P1, P2, P3, P5, E2, E3, J1, J2, J3, J4 (10 arquivos, sendo 8
detectores de card e 2 auxiliares). Detector sem teste é detector que ninguém sabe se ainda funciona.

---

## 3. O defeito mais grave: 59.209 → 2.225

`R_FRACIONAMENTO_SAMEDAY` era a regra mais numerosa do banco. Marcava todo grupo de ≥2 Ordens
Bancárias ao mesmo credor, na mesma UG, no mesmo dia, somando acima do teto de dispensa.

**O problema conceitual:** fracionamento é dividir uma contratação para fugir do certame. Pagar
duas parcelas de um contrato **licitado** no mesmo dia é execução normal. A regra não checava nada
disso. Nem podia: rodava sobre `ordens_bancarias` (o espelho TFE), onde o campo `numero_processo`
está **vazio em 100% dos casos** — o discriminante não existe naquela tabela.

Reconstruindo na fonte autoritativa (`ob_orcamentaria_siafe`, que tem processo e empenho):

| Filtro aplicado | Grupos restantes | Corte |
|---|---:|---|
| Regra como estava | 59.209 | — |
| Na fonte certa (SIAFE, com processo e empenho preenchidos) | 4.453 | −92% |
| Exigindo **processos distintos** e **empenhos distintos** | 2.574 | −42% |
| Excluindo repasse intragoverno e fundo-a-fundo do SUS | **2.225** | −14% |

**26× de redução.** E mesmo 2.225 não é "2.225 fracionamentos": a concentração dos maiores casos
em 23–30 de dezembro aponta pagamento em lote no fecho do exercício. Falta o discriminante final —
os processos eram contratação **direta**? Sem isso, o sinal é fila de triagem, não achado.

### O que foi corrigido no código

1. **Teto de dispensa por exercício, da fonte única.** `anomalias.py` tinha o valor de 2024
   (R$ 59.906,02) fixo, aplicado a todos os anos: falso positivo em 2025 e 2026 (tetos reais
   R$ 62.725,59 e R$ 65.492,11) e falso negativo em 2021–2023. É a **4ª cópia divergente** do teto
   encontrada no projeto — e existe um módulo canônico (`limites_dispensa`) cujo docstring
   literalmente proíbe duplicar a tabela. A 5ª cópia está em `lex_analise_conteudo.py:307`.
2. **Filtro de intragoverno dentro das regras.** `eh_nao_fornecedor` já era importado por
   `anomalias.py` — e usado **só no relatório**. As regras rodavam sobre tributo, encargo e
   repasse a fundo municipal de saúde, onde fracionamento é juridicamente impossível.
3. **Âncora rebaixada de 0,6 para 0,3.** Pelo próprio glossário do projeto, 0,3 é "compatível com
   irregularidade mas com explicações inocentes comuns; só vale em convergência" — exatamente o
   caso. O parecer agora **declara** que não foi possível excluir execução de um mesmo contrato.

---

## 4. Irregularidades novas, que antes eram inalcançáveis

Habilitadas pelas capacidades construídas nesta sessão:

| Nova verificação | Fundamento | Base que faltava |
|---|---|---|
| **Execução paga sem fiscal designado** | Art. 117, Lei 14.133/2021 | Extração de agentes do texto SEI |
| **Segregação de funções violada** (ordenador que atesta a própria execução) | Art. 5º, Lei 14.133/2021 | idem |
| **Citação jurisprudencial fabricada em peça oficial** | Integridade da peça | Acervo real do TCU indexado |
| **Objeto já sub judice** (muda representação → subsídio ao MP) | — | DataJud/CNJ |
| **Restrição de acesso em processo com pagamento** | Art. 5º XXXIII CF; art. 13 Lei 14.133 | Inventário de sigilo |

Medido no acervo (2.007 processos com texto):

| Sinal | Contagem | Leitura honesta |
|---|---:|---|
| Processos com algum responsável identificado | 171 (8%) | Cobertura baixa — é o gargalo a atacar |
| Agentes públicos nominados e persistidos | 387 | 198 nomes distintos |
| Lacuna art. 117 (execução sem fiscal identificado) | 1.680 | **Fila de triagem, não 1.680 violações** |
| Sem ordenador identificado | 1.976 | Idem |
| Segregação de funções violada | 0 | Nenhuma encontrada — mas a interseção possível é pequena |

> **Por que "fila" e não "achado":** com 8% de cobertura, a ausência de fiscal no texto capturado
> é, na esmagadora maioria, ausência de **captura** — não ausência de designação. A verificação só
> vira achado quando o processo estiver integralmente capturado. É por isso que a lacuna nasce com
> a frase "conferir se o ato de designação existe e não foi capturado".

**Um falso positivo corrigido no caminho:** "NFs Consig" foi extraído como fiscal de contrato em
6 processos. O título do documento era `Nota Fiscal - NFs Consig`, e a lista de ruído barrava `NF`
com limite de palavra — o "s" de "NFs" furava o `\b`. A guarda robusta não é a lista: é a palavra
**anterior**. Se vem "Nota" ou "DANFE" antes de "Fiscal", é documento, nunca pessoa.

---

## 5. Ordem de ataque para aumentar a captura de irregularidades

| # | Ação | Ganho esperado |
|---|---|---|
| 1 | Escrever teste para os 8 detectores sem teste | Deixa de ser fé; passa a ser garantia |
| 2 | Atualizar `detectores/base.py` (mapa mente sobre 9 cards) | Para de esconder capacidade própria |
| 3 | Migrar o fracionamento para a fonte SIAFE com guarda de processo/empenho | 59.209 → 2.225, mais o filtro de contratação direta |
| 4 | Remover a 5ª cópia do teto (`lex_analise_conteudo.py:307`) | Fecha a família de bug |
| 5 | Subir a cobertura de responsáveis de 8% para ≥30% | Destrava art. 117 e segregação como achado |
| 6 | Rodar os 31 detectores em lote e persistir num só lugar | Hoje só 4 regras têm resultado no banco |
| 7 | Fila formal para os processos sob sigilo | Ver documento de inventário de captura |
