# Manual — JFN (motor de auditoria/compliance)

## O que é
Servidor 24h (FastAPI, `server.py`) que faz perícia de gastos públicos do RJ e gera relatórios.
É o cérebro: o Yoda (Telegram) chama a API dele.

## Como ligar/desligar/ver
```bash
systemctl --user status jfn.service       # estado
systemctl --user restart jfn.service      # reiniciar
journalctl --user -u jfn -f               # logs ao vivo
curl -s http://127.0.0.1:8000/api/lista   # o que ele sabe fazer (200 = vivo)
```

## Dados (onde está a verdade)
- **Banco principal:** `data/compliance.db`
  - `ordens_bancarias` (1,12M) — OB do espelho TFE
  - `ob_orcamentaria_siafe` (135k) — OB rica do SIAFE (com NL/RE/PD/processo) → **fonte de pagamento**
  - `pericia_fornecedor` (6,4k) — perícia por fornecedor×UG, com grau 🔴🟡🟢
  - `sancoes_federais` (24,7k) — CEIS/CNEP (refresh semanal)
- **Regra:** pagamento sai SEMPRE do SIAFE, nunca do espelho TFE.

## O que ele entrega (produtos)
`/relatorio` fornecedor · `/orgao` UG · `/dossie` 360 · `/pericia` na hora · **Lex** (rating jurídico).
Tudo em PDF Kroll (`reporting/render_html` + `html_to_pdf`).

## Perícia progressiva (autoaprimoramento)
- `pericia_sweep` — periciou 6.446 fornecedores (0🔴/1.774🟡/4.672🟢).
- `nucleo-ciclo` (timer 06:30) — roda perícias, calibra, aprende.
- **Loop humano:** `/veredito <ref> confirmado|descartado` grava em `memoria_aprendizado` e no ledger
  `docs/vereditos_pericia.md` (entra no RAG). **Sem veredito do perito, a calibração gira em vazio** —
  por isso a fila semanal 🟡 (`tools/triagem_amarelos.py`, seg 09:00) pede seu veredito.

## Testes
```bash
cd ~/JFN && .venv/bin/python -m pytest tests/ -q     # 1.385 passam (~20min)
```

## Quando algo falha
- `compliance.db malformed` → quase sempre é a conexão viva; backup→integrity_check na cópia→restart.
  NUNCA reparar às cegas.
- OCR devolvendo vazio → checar imports `pytesseract/fitz/pdfminer` ANTES de culpar lógica.
