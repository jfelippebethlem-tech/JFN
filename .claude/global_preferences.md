# Instruções Globais — jfelippebethlem@gmail.com

Estas regras aplicam-se a **todas** as interações Claude, em qualquer projeto, sessão ou agente.

---

## 1. ESTÉTICA E QUALIDADE DE OUTPUT — REGRA ABSOLUTA

**Todo documento, relatório, análise ou resposta estruturada deve ter estética profissional impecável.**

Isso é uma preferência permanente do usuário. Não é opcional. Aplica-se sem exceção.

- Relatórios e análises seguem padrão de consultoria de topo (Kroll, Deloitte, Control Risks, McKinsey)
- Hierarquia visual clara: cabeçalho de capa, seções numeradas, tabelas alinhadas
- Números financeiros sempre com separador de milhar e duas casas decimais
- Indicadores de risco visualmente consistentes e escalas numéricas explícitas
- Alertas críticos em destaque (callouts, blockquotes, negrito)
- Fontes e referências normativas sempre citadas
- Nunca entregar um documento que não seria aceitável como entregável para um cliente corporativo

---

## 2. IDIOMA E COMUNICAÇÃO

- Responder em Português do Brasil por padrão neste projeto
- Termos técnicos jurídicos e contábeis: usar terminologia brasileira correta
- Comunicação: direta, técnica, sem excessos nem paternalismos

---

## 3. METODOLOGIA FINANCEIRA — ORÇAMENTO PÚBLICO BRASILEIRO

**Empenho ≠ Liquidação ≠ Pagamento. Sempre.**

```
EMPENHO → LIQUIDAÇÃO → ORDEM BANCÁRIA (OB) / PAGAMENTO
```

- Empenho: reserva de dotação orçamentária (pode ser cancelado)
- Liquidação: ateste de entrega de bens/serviços
- OB (Ordem Bancária): pagamento efetivo, irreversível — o dado definitivo
- Nunca apresentar valores de empenho como "total pago"
- Empenhos: sempre "valor bruto — pode incluir cancelamentos/anulações"

---

## 4. CÓDIGO E SEGURANÇA

- Nunca incluir credenciais, tokens ou senhas em código, logs ou mensagens
- Credenciais sempre via variáveis de ambiente (`os.environ.get(...)`)
- Arquivos `.env`, `auth.json` e scripts com credenciais: nunca versionar

---

## 5. GIT E VERSIONAMENTO

- Mensagens de commit: convenção semântica (`feat:`, `fix:`, `data:`, `docs:`, `ci:`)
- Todo trabalho relevante: commit + push antes de encerrar a sessão
- Nunca force push sem confirmação explícita
