# AUDITORIA PROFUNDA DE FORNECEDOR — passo a passo MECÂNICO
### (feito para uma IA FRACA, ex.: modelos gratuitos do Nous, seguir sem pensar muito)

> Dado um **CNPJ**, descobre: quanto a empresa recebeu do Estado do RJ **por mês**, em quais
> **órgãos**, sob quais **contratos** e **processos (SEI)** — e a lista OFICIAL de contratos.
> Validado com **MGS CLEAN (19.088.605/0001-04)**: R$ 89,97mi (2025) + R$ 58,60mi (2026); 41 contratos, R$146,7mi.

## REGRAS DE OURO (NUNCA quebre)
1. **Só LEITURA.** Nunca emitir/alterar/assinar/excluir nada.
2. **Ritmo humano.** Espere as pausas; uma consulta por vez. Não dispare em rajada (são sistemas do governo).
3. **Se der erro/captcha/bloqueio: PARE** e reporte. Não fique tentando rápido.
4. **Segredos só no `~/.hermes/.env`.** Nunca escreva senha/token em arquivo, git, chat ou log.
5. Salve resultados em `data/sei_cache/` e relatórios em `reports/`.

## PRÉ-REQUISITO (uma vez)
Tenha um Chrome aberto com a "ponte" ligada:
```
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\JFN\jfn\data\tmp\chrome_debug_profile"
```
(Em Linux/VM: `google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-jfn`.)

---

## ETAPA 1 — DADOS PÚBLICOS (1 comando, SEM login) ⭐ comece sempre aqui
```
python -m compliance_agent.auditoria.auditar_fornecedor <CNPJ> 2024 2025 2026
```
Ex.: `python -m compliance_agent.auditoria.auditar_fornecedor 19.088.605/0001-04 2025 2026`

Faz tudo sozinho (Transparência Fiscal RJ): **por mês, por órgão, contratos e processos SEI**.
Gera `reports/auditoria_<cnpj>.md` e dados em `data/sei_cache/tfe_<cnpj>_<ano>.json`.
> Valor = **EMPENHADO** (comprometido). É o panorama. Para PAGO e lista oficial, siga as etapas 2–4.

## ETAPA 2 — LISTA OFICIAL DE CONTRATOS (SIAFE, precisa login)
Pré: estar **logado no SIAFE** (`SIAFE_USUARIO/SIAFE_SENHA` no `.env`) e na tela
**Execução → Contratos e Convênios → Contrato** (a grade aberta), no Chrome da ponte.
```
python -m compliance_agent.auditoria.siafe_contratos <CNPJ>
```
Traz TODOS os contratos (nº, órgão, **Valor do Contrato**, situação, nº de aditivos).
🔑 Técnica que faz funcionar (já embutida): abrir filtro pelo disclosure `sdtFilter::disAcr`
(o texto "Filtro" é falso), Propriedade=7 (Cod. Contratado), Operador=0 (igual), e
**DIGITAR** o CNPJ com keystrokes (o `fill` não dispara a query do Oracle ADF) + Enter.

## ETAPA 3 — ABRIR CADA PROCESSO (SEI)
Para cada processo `SEI-...` da Etapa 1/2:
```
python _SANDBOX/sei_auditor.py <NUMERO_DO_PROCESSO>
```
Lê metadados/documentos do processo (objeto, partes, datas). Salva em `data/sei_cache/`.

## ETAPA 4 — CRUZAR e marcar RED FLAGS
Compare o que achou e anote no relatório:
- **Pago × Contratado**: pagou mais que o valor do contrato?
- **Aditivos sucessivos** (ex.: contratos com 3+ aditivos) — revisar.
- **Empenho sem contrato** no histórico — abrir a Nota de Empenho no SIAFE p/ achar o contrato.
- **Concentração**: um órgão concentra a maior parte? (ex.: Bombeiros na MGS CLEAN).
- **Datas/valores incompatíveis** entre empenho, contrato e processo.

---

## ONDE FICA CADA PEÇA
- `auditar_fornecedor.py` — orquestrador da Etapa 1 (público, 1 comando).
- `siafe_contratos.py` — Etapa 2 (lista oficial de contratos, SIAFE).
- `sei_auditor.py` — Etapa 3 (abre processo SEI).
- Detalhes do SIAFE (login, navegação, filtro): `_SANDBOX/SIAFE-rotina-auditoria.md`.
- Exemplo completo pronto: `_SANDBOX/auditorias/MGS-CLEAN-2025-2026.md`.

## DICA PRA MODELO FRACO
Faça **só a Etapa 1** primeiro (é 1 comando e não falha). Ela já entrega 80–90% do valor.
Só vá pras Etapas 2–4 se o Mestre Jorge pedir aprofundar. Sempre devagar, sempre só leitura.
