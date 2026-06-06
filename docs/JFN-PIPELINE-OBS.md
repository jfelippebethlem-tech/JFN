# JFN — Pipeline de Inteligência de Ordens Bancárias (workflow para IAs)

> **Para outra IA (possivelmente mais simples):** siga os passos na ordem. Cada um é idempotente
> (rodar de novo não duplica). Comandos prontos para copiar. Resultado esperado descrito.

## O que este pipeline faz
Mantém no JFN a **base completa de pagamentos do Estado do RJ** (Ordens Bancárias = liquidação, o
dado DEFINITIVO de pagamento; **empenho ≠ OB**), categorizada por **área/objeto** e indexada como
inteligência para auditoria/compliance. Hoje: **612.698 OBs (2023-2026), R$78,75 bi.**

## Fonte (gratuita, sem login/MFA, D-1)
`https://tfe.fazenda.rj.gov.br/tfe-download/fornecedor_ob.zip` (≈124 MB) — espelho D-1 do SIAFE-Rio.
1 CSV por ano (2017-2026). Colunas: `Data da OB; Credor; Nome Credor; UG; Nome UG; Orgao; Nome Órgão;
Ordem Bancaria; Histórico; Valor OB`. (latin-1, separador `;`, 5 linhas de título antes do cabeçalho.)
> Por que esta fonte e não o SIAFE direto: o SIAFE-Rio 2 é Oracle ADF e **bloqueia automação** (só
> renderiza 50 linhas, ignora filtro/scroll/export programáticos). O download do TFE dá a base TODA.
> O SIAFE só acrescentaria tempo-real (vs D-1) e o nº de processo SEI por OB.

## PASSOS

### 1. Baixar a base (1x, ou quando quiser atualizar)
```bash
cd ~/JFN && ./.venv/bin/python -m compliance_agent.collectors.tfe_ob --baixar
```
Esperado: `baixado: .../fornecedor_ob.zip (124.566.679 bytes)`. (Já roda sozinho no `jfn-tfe-ob.timer`, segunda 09:00 UTC.)

### 2. Ingerir os anos no banco (idempotente — limpa o ano antes de inserir)
```bash
for a in 2023 2024 2025 2026; do ./.venv/bin/python -m compliance_agent.collectors.tfe_ob --ano $a --ingest; done
```
Esperado: `INGERIDAS 80.826 OBs de 2026 | TOTAL PAGO: R$ 12.048.188.455,10` (e os demais anos).
Grava em `compliance.db` tabela `ordens_bancarias`, `categoria='tfe_ob'`. Campos-chave:
`numero_ob, data_pagamento, ug_nome(=Nome Órgão), favorecido_cpf(=CNPJ), favorecido_nome, valor,
tipo_ob(=área inferida), observacao(=Histórico/objeto)`.

### 3. Categorização por área/objeto
Automática na ingestão (`compliance_agent/reports/categorizar.py::area_objeto`), a partir do
**Histórico + Nome do Credor**. Áreas: Saúde, Obras/Infraestrutura, Transporte, Educação, Segurança,
Pessoal/Folha, Precatórios, Utilidades, Serviços, Tributos/Retenção, etc. (refinar regras conforme aparecem casos.)

### 4. Gerar relatório de inteligência (HTML, padrão due diligence)
```bash
./.venv/bin/python -m compliance_agent.reports.html_report --out reports/relatorio.html
# por credor: --favorecido "MGS"   |  por empresa: --cnpj 19088605000104
```
Esperado: `Relatório HTML robusto gerado: ... (25.000+ bytes)`. Seções: sumário+rating, perfil,
contratos por órgão, distribuição por **área/objeto** e **órgão pagador**, detalhe das OBs (com
Processo SEI quando houver), matriz de risco TCU P×I, red flags com fundamento legal, HHI, recomendações.

### 5. Consultar a inteligência (exemplos SQL)
```bash
./.venv/bin/python - <<'PY'
import sqlite3; c=sqlite3.connect("data/compliance.db")
# pago por área em 2026
for r in c.execute("SELECT tipo_ob,COUNT(*),SUM(valor) FROM ordens_bancarias WHERE categoria='tfe_ob' AND exercicio='2026' GROUP BY tipo_ob ORDER BY 3 DESC LIMIT 8"): print(r)
PY
```

## ⚠️ COBERTURA (honestidade — ler antes de citar totais)
`fornecedor_ob` cobre **só pagamentos a FORNECEDORES** (nominal, por credor). Em 2025: R$25,5bi.
NÃO inclui **folha/pessoal, previdência (RIOPREVIDÊNCIA), dívida, transferências** — esses não são
publicados como OB nominal (salário individual não vai à base pública). O **total pago** (com tudo) é
a `despesa_generica`: **R$51,5bi/2025** (agregado por órgão/elemento, ver `tfe_aberto.py`). O orçamento
LOA (R$100bi+) é o autorizado (inclui intra-orçamentárias/RPPS/refinanciamento — nem tudo vira caixa).
→ Para **auditar fornecedores** (foco do JFN): a base de 612k OBs é COMPLETA. Para o quadro financeiro
total: usar a despesa_generica. **Sempre deixar claro qual recorte está sendo citado.**

## Regras (NÃO violar)
- **OB = pagamento (liquidação). Empenho ≠ OB.** Nunca citar empenho como "pago".
- **Dedup:** OBs do TFE = `categoria='tfe_ob'`; as 50 do SIAFE direto = `categoria='siafe_ob'`. Não misturar/duplicar.
- **Idempotência:** a ingestão limpa o ano antes de inserir — pode rodar quantas vezes quiser.
- **Tudo gratuito, roda na VM 24/7.** Ver `jfn-tfe-ob.timer` (base completa) e `jfn-tfe.timer` (resumo D-1).

## Pendências / próximos
- Refinar `categorizar.py` (reduzir "Outros / a classificar" — hoje ~31k OBs).
- SIAFE direto (tempo-real + nº processo SEI por OB): bloqueado por ADF; ver `docs/SIAFE-NAVEGACAO.md`
  (caminhos: mitmproxy/replay de PPR, RPA ADF-aware, ou pedido institucional à SEFAZ). Baixa prioridade
  pois o TFE já dá a base completa.
- Cruzar credores com CEIS/CNEP (sanções) e PNCP (contratos por CNPJ) — ver `docs/HANDOFF` da pesquisa.
