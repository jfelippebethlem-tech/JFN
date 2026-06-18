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

## 3. METODOLOGIA FINANCEIRA — ORÇAMENTO PÚBLICO (sob demanda)

> Regra **específica de investigação/fiscalização**, não sempre-on (poupa tokens em sessões que não são de orçamento). O detalhe completo vive em `~/JFN/CLAUDE.md` (REGRAS ABSOLUTAS #2) e `~/JFN/docs/CLAUDE-REFERENCIA-COMPLETA.md`, carregados em sessões JFN.
>
> **Gatilho obrigatório:** em QUALQUER análise de gasto público, abrir essa referência ANTES de citar valores. Regra de ouro: **Empenho ≠ Liquidação ≠ OB (pagamento)** — só a Ordem Bancária é "pago"; empenho é valor bruto que pode ser cancelado. Nunca apresentar empenho como "total pago".

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
