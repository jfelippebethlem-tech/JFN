# ROTINA: quanto um fornecedor (CNPJ) recebeu do Estado RJ, por mês
## (passo a passo MECÂNICO — uma IA fraca consegue seguir)

> Descobre, para qualquer **CNPJ** e **ano**, o total **por mês** e **por órgão**.
> Fonte: **Transparência Fiscal RJ (TFE)** — pública, sem login. Testado e validado
> em 2026-06-04 com a MGS CLEAN (CNPJ 19.088.605/0001-04).

## MODO FÁCIL (1 comando) ⭐
Pré-requisito: ter um Chrome aberto com `--remote-debugging-port=9222` (o mesmo da ponte que já usamos).

```
python C:\JFN\jfn\_SANDBOX\tfe_fornecedor.py <CNPJ> <ANO>
```
Exemplo:
```
python C:\JFN\jfn\_SANDBOX\tfe_fornecedor.py 19.088.605/0001-04 2025
```
Sai: tabela **por mês** + **por órgão** + total; salva bruto em `data/sei_cache/tfe_<cnpj>_<ano>.json`.
Para outro ano, troque o número (2024, 2026...). 2026 também funciona (dado mais novo que os dados abertos).

## MODO MANUAL (se precisar conferir na mão)
1. Abrir `https://tfe.fazenda.rj.gov.br/tfe/web/fornecedor` (navegador normal).
2. Marcar **"Fornecedor Específico"**.
3. Digitar o **CNPJ** no campo CNPJ.
4. Escolher **Mês/Ano inicial = 01 / ano** e **final = 12 / ano**.
5. Clicar **Pesquisar**.
6. Abre o relatório **"Despesas de Fornecedor por Empenho"** com colunas:
   Data do Empenho · Data da Emissão · Credor · Unidade Gestora · Órgão · Empenho · Natureza · Histórico · **Total (R$)**.
7. Somar a coluna **Total (R$)** agrupando pela **Data do Empenho** (mês) e pelo **Órgão**.

## REGRAS
- Só **leitura** (dado público). Ritmo humano (não martelar).
- ⚠️ Valor = **EMPENHADO** (comprometido), **não** necessariamente pago.
- Salvar bruto em `data/sei_cache/` (fora do git).

## 2ª ETAPA — aprofundar (precisa login SIAFE; ver `SIAFE-rotina-auditoria.md`)
- **PAGO/liquidado** (quanto saiu de fato): SIAFE → Execução Financeira → Ordens Bancárias, filtro por favorecido.
- **Nº do processo (SEI)** de cada empenho/OB → abrir com `python _SANDBOX/sei_auditor.py <numero>`.
- **Contratos** (nº/objeto/vigência/valor): SIAFE → Contratos e Convênios.
- **Red flags**: pago > contratado, aditivos sucessivos, empenho sem contrato, datas incompatíveis.

## EXEMPLO DE RESULTADO REAL (MGS CLEAN)
- 2025 (empenhado): **R$ 89.965.844,73** (84 empenhos). Maior contratante: Corpo de Bombeiros (R$ 48,6M).
- 2026 jan–jun (empenhado): **R$ 58.598.234,38** (47 empenhos).
- Relatório completo: `_SANDBOX/auditorias/MGS-CLEAN-2025-2026.md`.
