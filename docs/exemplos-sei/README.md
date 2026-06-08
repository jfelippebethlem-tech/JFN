# Exemplos de processo SEI completo — para avaliação por outra IA

> **Propósito:** dar a uma IA revisora **processos SEI reais e completos** (íntegra extraída) +
> os **parâmetros de avaliação** que o JFN aplica sobre eles, para que ela julgue se a lógica de
> avaliação é correta, honesta e suficiente. Dados públicos (OB do SIAFE/TFE). Sem segredos.

## Os exemplos (JSON da íntegra, como o reader devolve)
- `exemplo1_pagamento_emop_330003-000675-2025.json` — EMOP (Obras Públicas), processo de **pagamento**
  (R$ 12M, contratado CNPJ 19.024.253/0001-23). 10 docs, títulos como **ID numérico**.
- `exemplo2_pagamento_emop_330003-002262-2024.json` — idem, outro pagamento EMOP.
- `exemplo3_acessivel_520003-000026-2025.json` — processo acessível com 8 docs (caso que destravou o reader).

Cada JSON tem: `numero, url, documentos[{titulo, tipo_bruto, url, formato}], relacionados[],
conteudo_documentos[{doc, conteudo}], cnpjs[], valores[], cadeado, n_docs_restritos, motivo_zero`.

## Parâmetros de avaliação que o JFN aplica (o que pedir à IA revisora p/ julgar)
1. **Classificação do documento** (`compliance_agent/sei/classificador_doc.py`): tipo por **título** e,
   se o título é ID numérico, pelo **cabeçalho do conteúdo** (~400 chars). Tipos: parecer_juridico,
   homologacao, ata_rp, contrato, mapa_lances, planilha_preco, pesquisa_precos, etp, tr, edital, empenho,
   liquidacao, autorizacao_despesa, tramitacao, outros. **Avaliar:** os rótulos cobrem os docs reais? Há
   falso-positivo/negativo? (vimos 'tr' casar em 'adminisTRacao' → corrigido com keyword ≥7 no conteúdo.)
2. **Valor fiscalizatório** (`valor_doc`): alto (extrai+guarda texto: parecer/homologação/ATA/contrato/
   planilha/pesquisa/ETP/TR/edital) · médio (empenho/liquidação/NAD) · baixo (tramitação/ofício/recibo →
   só título+contagem). **Avaliar:** a política do que guardar é defensável (storage vs valor)?
3. **Diagnóstico de 0 docs** (`navegador.py::motivo_zero`): `acesso_restrito` (🔴 red flag se há OB paga) ·
   `nenhum_resultado` (processo não localizado/fora de escopo) · `busca_nao_resolveu` · `arvore_vazia`.
   **Avaliar:** a distinção é honesta? (ver "Dificuldades" abaixo.)
4. **Acesso restrito** (`cadeado`/`acesso_restrito`): ícone de cadeado > texto. Red flag = processo
   concluído com OB paga mas restrito (deveria ser público).
5. **Conluio em propostas** (`sei/conluio_propostas.py`): markup uniforme / preços idênticos / texto
   similar (Art. 90 Lei 8.666 / Art. 36 Lei 12.529). **Depende de ter as PROPOSTAS — ver Dificuldades.**
6. **Extração de preço unitário** (`sei/extrator_precos.py`): camadas tabela(pdfplumber)→LLM→visão.
   **Depende de uma ARP/homologação com tabela — ver Dificuldades.**

## ⚠️ DIFICULDADES E LIMITAÇÕES (honesto — o dono pediu)
1. **Escopo de acesso do login (itkava/ITERJ).** O reader só abre processos no escopo de acesso da
   unidade. Dos 6 processos de alto valor testados, **3 retornaram "Nenhum resultado encontrado"** (Saúde
   296100, Previdência 123400) — fora de escopo. **Não dá** para varrer os 41.545 `numero_sei` às cegas.
2. **`numero_sei` das OBs é ruidoso** ("0", "000 048 0 26"); só ~5.356 são bem-formados.
3. **Os processos acessíveis via OB são de PAGAMENTO, não de licitação.** Têm CNPJ + valores totais, mas
   **NÃO a tabela de preço unitário (ARP)**. A ARP vive no processo de licitação/pregão (SRP, Lei 14.133
   arts. 82-86), que **não é alcançável** pela cadeia: os `relacionados` dos pagamentos são só
   "Financeiro: Pagamento" (outros pagamentos), sem nº para seguir até a licitação.
4. **Consequência:** **`extrator_precos` NÃO foi travado** (sem ARP acessível) e **`conluio_propostas`
   não roda** (sem as propostas). **PIVOT recomendado:** a tabela de itens/preço unitário da Lei 14.133
   está ESTRUTURADA no **PNCP (API pública)** — usar PNCP como fonte de preço em vez de raspar a árvore SEI.
5. **Títulos como ID numérico** (ex.: "101230489") quebram a tipagem por título — mitigado classificando
   pelo conteúdo, mas é um sinal de que a árvore renderiza diferente entre órgãos.
6. **WAF do SEI por fingerprint:** só o chromium próprio (UA spoofado) vence; o Chrome CDP `:9222` é
   derrubado (`ERR_CONNECTION_CLOSED`). Cada leitura faz login (lento, ~40-60s) e usa 1 browser (CPU).

## Pergunta para a IA revisora
Dadas as dificuldades 1–6: **(a)** o pivot para PNCP (preço estruturado) é a decisão certa, ou há um
caminho viável dentro do SEI? **(b)** os parâmetros de avaliação (1–6) são suficientes e honestos para um
parecer de controle externo, ou falta algo? **(c)** algum rótulo/classificação está incorreto nos 3
exemplos reais anexos?
