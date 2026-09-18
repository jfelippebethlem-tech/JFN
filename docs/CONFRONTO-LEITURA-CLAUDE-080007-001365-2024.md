# Confronto nº 3: leitura integral do original × conclusões do sistema
### Processo SEI-080007/001365/2024 — contratação emergencial CANCELADA (Fundação Saúde do ERJ)

> **Método.** Leitura dos 20 documentos capturados (90.623 caracteres). Indício ≠ acusação.

## 1. O que os autos dizem

Contratação emergencial de reparos e conservação predial (subestações e geradores) nas unidades
da Fundação Saúde. Os autos trazem, em sequência:

- **Termo de Referência** completo (doc 9, 20.000 caracteres) com **onze anexos**: síntese do
  plano de manutenção, acordo de nível de serviço, ferramentas, modelos de uniforme, formulário
  de visita, atestado de visita, definições dos termos, procedimentos de serviço;
- e-mail de comunicação às empresas participantes;
- **"Processo Cancelado com Sucesso"** — anexo do SIGA (doc 3);
- **Termo de Encerramento** (doc 7, 26/09/2025), assinado pelo Chefe de Protocolo.

Ou seja: o planejamento foi feito, a consulta ao mercado começou, e **a contratação foi
cancelada antes de se consumar**. Não há contrato, não há pagamento, não há OB.

## 2. Confronto com o sistema

| Conclusão do sistema | Veredito da leitura |
|---|---|
| score **78,9** · grau C | **falso do início ao fim** — os três achados eram falsos positivos |
| lacuna "Planejamento (ETP/TR/pesquisa de preços)" | ❌ o TR está nos autos, com 11 anexos |
| lacuna "Seleção (edital, julgamento, homologação)" — ALTA | ❌ o processo foi **cancelado** |
| lacuna "Contrato/ata formalizados" | ❌ idem: não há contrato porque não houve contratação |
| acatamento `PARECER_SEM_RESSALVA` | ✅ correto |

**Depois das correções: score 51,0 e ZERO achados.** É o que os autos sustentam.

## 3. As duas causas, medidas

### 3.1 A fase ignorava o tipo que a própria casa já tinha resolvido
O TR está no manifesto com `tipo: termo_referencia` — o classificador de documentos **acertou**.
Mas `fases.classificar()` decide pelo TÍTULO, e o título é *"Formulário de solicitação de material
ou serviço"*, que não casa padrão nenhum. Resultado: `fase: indefinida`, a fase de planejamento
não conta como presente, e a lacuna é cobrada com a peça dentro dos autos.

**Correção:** `fases.classificar_com_tipo()` — o título continua mandando quando diz algo (é ele
que desmente o classificador por conteúdo, que já rotulou certidão como parecer), e o tipo entra
só quando o título é mudo.

**Alcance medido:** **923 documentos** do acervo ganham fase — 675 de contratação, 158 de despesa,
70 de seleção, 20 de planejamento. Cada um deles é uma lacuna que deixa de ser cobrada
indevidamente.

### 3.2 Processo cancelado seguia sendo cobrado pelas fases que nunca teria
Nova natureza `cancelado`: cancelamento expresso da compra, sem instrumento assinado, dispensa
seleção e formalização. O **planejamento continua cobrado** (antecede o cancelamento e é onde
mora a motivação) e a evidência de execução também — cancelar e ainda assim pagar seria o oposto
de inocente. Encerramento sozinho **não** basta: todo processo termina com um.

## 4. O padrão que se repete nos três processos lidos

| Processo | Natureza real | Falsos positivos | Causa |
|---|---|---|---|
| 270131/000548/2023 | aditivo | 1 (Seleção) | fases do processo de origem |
| 080001/018592/2026 | pagamento | 3 (Planejamento, Seleção, Contrato) | uma menção a "licitação" no título |
| 080007/001365/2024 | cancelado | 3 (Planejamento, Seleção, Contrato) | fase cega ao tipo + cancelamento ignorado |

**A mesma falha em três formas:** o sistema cobra de um processo as fases que ele estruturalmente
não tem. Somados, **752 processos** (55 aditivos + 697 pagamentos) mais os 923 documentos que
ganham fase — o suficiente para mudar a ordem da fila do fiscal, que é onde isso dói.
