# Confronto nº 2: leitura integral do original × conclusões do sistema
### Processo SEI-080001/018592/2026 — pagamento da competência maio/2026 (SES/FES × BREF GESTÃO EMPRESARIAL LTDA.)

> **Método.** Leitura dos 20 documentos capturados (109.643 caracteres), com reconciliação do
> dinheiro documento a documento. Indício ≠ acusação.

## 1. A reconciliação do dinheiro FECHA

| Peça | Valor |
|---|---|
| Nota Fiscal 39 (competência 05/2026) | R$ 252.516,92 |
| OB 2026OB08665 — líquido ao credor BREF | R$ 221.709,86 |
| OB 2026OB08628 — IRRF (Tesouro do Estado) | R$ 3.030,20 |
| OB 2026OB09769 — INSS (Ministério da Fazenda) | R$ 27.776,86 |
| **Soma das OBs** | **R$ 252.516,92** ✅ |

Líquido + retenções batem com a NF ao centavo. **Não há indício de sobrepagamento.**

## 2. O que a leitura encontrou

### 2.1 🟡 Diferença de R$ 24.608,94 com "glosa 0,00"
A CI SES/COOSG nº 162 declara, no mesmo quadro: **Valor do Contrato R$ 277.125,86 · Valor da
Glosa 0,00 · Valor NF R$ 252.516,92**. A diferença não é explicada em nenhum documento. Ou o
"valor do contrato" é teto mensal e a coluna de glosa não se aplica, ou houve glosa não
declarada. Indício de inconsistência formal do quadro-resumo, não de dano.

### 2.2 🟡 A OB de INSS é de competência 06/2026; todo o resto é 05/2026
NF, liquidação e a OB principal são da competência **05/2026**; a OB 2026OB09769 (INSS,
R$ 27.776,86) sai como **06/2026**. Retenção de uma competência lançada em outra desalinha a
conciliação por competência — a lente que a casa usa para duplicidade de contrato contínuo.

### 2.3 ⚪ Termo de Encerramento cancelado por "ERRO DE MATEIRAL"
O Termo de Encerramento 135954065 foi invalidado (Termo de Cancelamento 136569037, 14/07/2026)
com a razão grafada **"ERRO DE MATEIRAL"** [sic], e o processo reaberto para a OB de INSS. O
cancelamento é regular e está documentado; registra-se porque encerramento revogado é ponto de
atenção em conciliação.

### 2.4 🟡 A prova de execução é uma INFERÊNCIA, não um atesto de serviço
A CI conclui: *"Considerando que o referido documento foi devidamente atestado por 02 (dois)
servidores identificados por matrícula funcional, **conclui-se pela efetiva execução** dos
serviços"*. O atesto de dois servidores na NF é exigência do art. 90 da Lei estadual 287/79 e é o
que a norma pede — mas o processo não traz medição, relatório de execução nem ANS da unidade. É
cumprimento formal; a prova material da entrega vive fora destes autos.

## 3. Confronto com o sistema

| Conclusão do sistema | Veredito da leitura |
|---|---|
| score 91,6 · EXTREMO · grau C | **superestimado** — três dos cinco achados eram falsos |
| lacuna "Planejamento (ETP/TR/pesquisa de preços)" | ❌ **falso positivo** |
| lacuna "Seleção (edital, julgamento, homologação)" — ALTA | ❌ **falso positivo** |
| lacuna "Contrato/ata formalizados" | ❌ **falso positivo** |
| lacuna crítica "Evidência de execução apesar de haver pagamento" | ✅ **procede**, com a ressalva do item 2.4 |
| suficiência de emissor (ato 'contrato' exige parecer nível 3) | ⚠️ decorre da mesma confusão: não há ato de contrato aqui |
| despacho 16 em escala 3 ("Autorizo a execução da PD") | ✅ **procede** — autoriza sem motivar |

**Por que os três falsos positivos.** Este é um processo **financeiro**, e os próprios autos dizem
onde a contratação mora: *"o presente processo financeiro encontra respaldo no processo
administrativo SEI-080001/004018/2023, vinculado ao Contrato n.º 051/2023, com vigência até
31/01/2027"*. Planejamento, seleção e contrato estão lá, não aqui.

A causa foi medida, não suposta: `natureza()` conta palavras nos TÍTULOS e **uma única ocorrência
de "licitação"** bastou para vencer a contagem (`if c and c > r`) e classificar o processo como
contratação.

## 4. O que foi corrigido a partir deste confronto

Nova natureza **`pagamento`**: processo com a cadeia empenho→liquidação→OB e sem peça de seleção
ou contrato próprios não carrega as fases do processo-pai. A evidência de execução **continua**
sendo cobrada — é o achado que mais importa num processo de pagamento.

Efeito medido no acervo: **697 processos** deixam de carregar lacunas de contratação indevidas.
Neste processo, o score cai de **91,6 para 80,4** e sobram apenas os achados que a leitura
confirma.
