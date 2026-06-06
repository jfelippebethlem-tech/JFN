# HANDOFF 2026-06-06 — Barramento de agentes, /relatorio de inteligência e UGs canônicas

> **Para a próxima IA (leia isto inteiro antes de mexer).** Passos explícitos e idempotentes.
> Ambiente = VM Linux (NÃO Windows). Verdade do ambiente: [`../AMBIENTE.md`](../AMBIENTE.md) + [`../ambiente.json`](../ambiente.json).
> Regra do Mestre Jorge: código em branch dedicada, testado, honesto (REAL vs CACHE; nunca fabricar número), commit ao final.

## 1. O que existe agora (visão de 1 minuto)

O **Yoda** (bot Telegram, `hermes-gateway.service`) é o MAESTRO. Ele NÃO faz auditoria na mão: chama a
**API do JFN** (`http://127.0.0.1:8000`, `jfn.service`, FastAPI em `server.py`). Rotas principais:

| Rota | O que faz |
|---|---|
| `POST /api/relatorio/inteligencia` | Relatório de Inteligência de **Fornecedor** (por nome/CNPJ) |
| `POST /api/relatorio/orgao` | Relatório de Inteligência de **Órgão** (por nome/UG) |
| `GET /api/massare/placar` · `GET /api/massare/cenarios` · `POST /api/massare/prever` | Massare (mercado) |
| `POST /api/hermes/missao` | Auditoria autônoma em texto livre (já existia) |

## 2. Como gerar um relatório (3 formas)

**a) Pela API (como o Yoda faz):**
```bash
curl -s -X POST http://127.0.0.1:8000/api/relatorio/inteligencia -H 'Content-Type: application/json' -d '{"empresa":"MGS Clean"}'
curl -s -X POST http://127.0.0.1:8000/api/relatorio/orgao        -H 'Content-Type: application/json' -d '{"orgao":"iterj"}'
```
Retorno: `{ok, ..., resumo, path_md, path_pdf, fonte}`. Se `ambiguo:true`, há o campo `pergunta` (lista de
candidatos) — o Yoda repassa ao Mestre Jorge e chama de novo com o CNPJ/UG escolhido.

**b) Pela CLI (offline, para depurar):**
```bash
cd ~/JFN
.venv/bin/python -m compliance_agent.reporting.inteligencia "MGS Clean"      # ou o CNPJ
.venv/bin/python -m compliance_agent.reporting.inteligencia_orgao "iterj"    # ou a UG 133100
```
Saída em `reports/inteligencia_<empresa>_<data>.{md,pdf}` e `reports/inteligencia_orgao_<orgao>_<data>.{md,pdf}`.

**c) Enviar no Telegram** (chat do Mestre Jorge = `45338178`):
```bash
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '"'"'"')
curl -s -F chat_id=45338178 -F document=@reports/SEU_RELATORIO.pdf -F caption="..." \
  "https://api.telegram.org/bot${TOKEN}/sendDocument"
```

## 3. Arquivos que importam

| Arquivo | Papel |
|---|---|
| `compliance_agent/reporting/inteligencia.py` | Motor do relatório de **fornecedor** (resolução por nome/CNPJ, tabelas de OB por ano, HHI, **parecer jurídico/mérito** `parecer_fornecedor`, PDF DejaVu). |
| `compliance_agent/reporting/inteligencia_orgao.py` | Motor do relatório de **órgão** (reusa helpers do de fornecedor; concentração por fornecedor; `parecer_orgao`). |
| `compliance_agent/ugs.py` + `data/ug_canonico.json` | **Mapa canônico de UG → nome da unidade.** Corrige o nome do órgão pelo CÓDIGO da UG (ver §4). |
| `server.py` | Endpoints REST (o barramento). |
| `massare/market.py` + `massare-market.timer` | Massare no pregão (cenários multi-horizonte). |
| `data/compliance.db` | Base real: `ordens_bancarias` (612k OBs = pagamentos), `contratos`, `despesa_execucao` (empenhos). |
| `data/empresas_target.json` | Registro de fornecedores conhecidos (resolução por nome). |
| `tests/test_relatorio_inteligencia.py` | Testes (rodar: `.venv/bin/python -m pytest tests/test_relatorio_inteligencia.py -q`). |

## 4. APRENDIZADO CRÍTICO — UGs (não repita o erro)

**Cada UG (Unidade Gestora) é um código de órgão.** Nas OBs (`ordens_bancarias.ug_nome`), a UG às vezes
vem rotulada com o nome do **órgão SUPERIOR**, não da unidade real. Caso resolvido:

- **ITERJ = UG `133100`** (no espelho TFE/`compliance.db`). No SIAFE-Rio 2 o código é `270042` (sistema diferente).
- As OBs rotulavam a UG 133100 como "Secretaria de Estado de Infraestrutura e Obras" → os pagamentos do
  ITERJ "sumiam" na Secretaria. A `despesa_execucao.nome_ug` tem o nome correto ("INST. DE TERRAS E CARTOGR").
- **Correção:** `compliance_agent/ugs.py` resolve o nome pelo CÓDIGO da UG (mapa `data/ug_canonico.json`,
  gerado de `despesa_execucao`, + `OVERRIDES` curados). Os relatórios usam `ugs.rotulo(ug_codigo, ug_nome)`.

**Para adicionar/corrigir uma UG:** edite `OVERRIDES` em `compliance_agent/ugs.py` e rode
`.venv/bin/python -m compliance_agent.ugs --reconstruir`. Para regerar do zero a partir do banco, idem.

## 5. O parecer (o diferencial — "nosso padrão sempre")

Todo relatório traz a seção **"Análise Jurídica e de Mérito — Parecer Preliminar do JFN"**
(`parecer_fornecedor` / `parecer_orgao`). É **data-driven e honesto**: descreve mérito (materialidade,
concentração, evolução), avaliação jurídica (CF/88 art. 37, Lei 14.133, Lei 8.666, Lei 4.320, TCU/ACFE),
um **grau de atenção** (MODERADO/MÉDIO/ALTO) e **ressalvas** (são indícios a verificar, não conclusão de
irregularidade; presunção de regularidade). **NUNCA** afirme irregularidade nem invente fatos/números —
só interprete o que os dados mostram.

## 6. Checklist se for mexer

1. `git checkout claude/ambiente-e-relatorio` (ou crie sua branch a partir dela).
2. Edite. Rode `pytest tests/test_relatorio_inteligencia.py -q` (deve passar 12+).
3. Gere um relatório de teste (MGS e ITERJ) e confira md+pdf.
4. Se mexeu no `server.py`: `systemctl --user restart jfn.service` e espere ~15s (o uvicorn só escuta
   depois do startup que tenta login SIAFE).
5. Documente em `hermes-yoda/process_documentation.md` (append) e faça commit + push.
