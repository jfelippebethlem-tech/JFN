# HANDOFF — JFN 2.0 ENTREGUE E VIVO (continuar em nova sessão)

> **LER PRIMEIRO.** Continuação do `docs/JFN-2.0-IMPLEMENTACAO.md` (que tem o detalhe por onda + "Erros &
> Aprendizados"). Branch de trabalho: **`jfn-2.0`** (pushada). Data: 2026-06-08. Ambiente: VM Linux ~/JFN.

## ✅ ESTADO: TODAS as 13 ondas implementadas, testadas e DEPLOYADAS (vivas)
- **0–12 + 13** (skilltree/wiring) com core ✅. **92+ testes JFN 2.0 verdes** (`pytest tests/test_jfn2_*.py`).
- **Vivo agora:** `systemctl --user is-active hermes-gateway` (Yoda) + `jfn` (motor) = active. Sweep SIAFE 2
  rodando (`pgrep -f "siafe_sweep_full 2"`, ~144 UG:ano, supervisor no cron). Download TSE rodando.
- 39 commits nesta sessão (de `858583c` até HEAD). `git log --oneline` p/ ver.

## ⚠️ MUDANÇAS VIVAS FORA do git jfn-2.0 (importante saber — têm backup)
Estas NÃO estão no repo JFN (são do Hermes / config / credenciais). Backups com data ao lado.
1. **Gateway Hermes** (`~/hermes-agent/gateway/run.py`, repo git próprio, commit base `d8d62b53`):
   - Linha ~9418: resposta vazia `(empty)` → **"Perfeito! Fico à disposição… 🙂"** (NUNCA erro/ignora "Ok").
     Backup: `gateway/run.py.bak.jfn-empty-*`.
2. **Config Hermes** (`~/.hermes/config.yaml`): `busy_input_mode: queue` + `busy_text_mode: queue`
   (ENFILEIRA mensagem nova, não interrompe). Fallback chain: gemini-2.5-flash-lite → **groq/gemma2-9b-it** →
   mistral → nous. Backups `config.yaml.bak.*`.
3. **Pool Gemini** (`~/.hermes/auth.json` → `credential_pool.gemini`): **9 chaves de 9 PROJETOS distintos**
   (proj1–9, deduplicado) = **9× cota free**. Rotação nativa Hermes (`recover_with_credential_pool` em 429).
   Também em `GEMINI_API_KEYS` nos dois `.env` (backup). Verificador: `python -m tools.check_gemini_key "<chave>"`.

## Política de modelo (em `capabilities.yaml` politica_modelo + `docs/MODELO-ESTRATEGIA.md`)
- Free verificado jun/2026: **só gemini-2.5-flash e 2.5-flash-lite** são free (Pro e 3.x = PAGOS;
  gemini-2.0-flash desligado 01/06). Default/pesado = **gemini-2.5-flash**. Bulk = **Groq Gemma 9B** (instantâneo).
- `gemini-2.5-pro` (PAGO) só sob "usar o modelo melhor" + **confirmação** (`quer_modelo_melhor()` no roteador).
- Gemma 4 31B é free pela MESMA chave Gemini (mesma cota), mas NÃO supera o 2.5-flash.

## Relatório de fornecedor (`/relatorio`) — RECONSTRUÍDO (motor HTML, Onda 7)
`compliance_agent/reporting/inteligencia.py::render_pdf_html` (FPDF = fallback). **13 seções**, resolve as
queixas do dono (CNPJ na margem, truncamento, faltas):
cadastral · sócios/diretores · **doações eleitorais dos sócios** (conflito) · OSINT (CEIS/CNEP+OpenSanctions) ·
**pagamentos Órgão(UG)×Ano** (tabela cruzada, não lista por data) · concentração HHI · contratos ·
**matriz P×I (TCU)** · **Benford** · **co-endereço (cartel/laranja)** · **red flags c/ fundamento** ·
**recomendações** · referências. **Linhas zebradas** em todas as tabelas (`render_html.py` CSS).

## ⏳ PENDÊNCIAS (retomar aqui)
1. **/lista lento** = loop do agente Yoda (a rota `/api/lista` é 29ms). **FIX a fazer:** fast-path no gateway
   p/ comandos fixos (devolver o HTTP direto sem o loop do LLM). É no `gateway/run.py` (bot vivo, cuidado).
2. **Leitura SEI (itkava) ao vivo:** estava em teste (`/tmp/sei_test.out`) — VALIDAR se `sei_cdp.ler_processo_sei`
   (que delega ao `tools.sei_reader.ler` itkava) lê a íntegra de um processo real. O parecer Lex NÃO deve
   afirmar "leu na íntegra" se voltar vazio (honestidade — conferir `lex._ler_integra_sei`).
3. **Definição de Pronto** (no `JFN-2.0-IMPLEMENTACAO.md`): merge `jfn-2.0`→`linux` + limpeza da memória de
   retomada + anúncio. **AGUARDA OK do dono** (ação na branch estável). NÃO fazer sem confirmação.
4. Diferidos com motivo: itens SIAFE da Onda 11 (sweep rodando), crypto_ws daemon (Onda 8), enriquecedores
   key-gated (brapi/Finnhub/OpenSanctions/OpenCorporates — reportam INDISPONÍVEL até ter chave grátis).

## Como retomar
1. `cd ~/JFN && git checkout jfn-2.0` · `git log --oneline -20`.
2. Ler `docs/JFN-2.0-IMPLEMENTACAO.md` (detalhe por onda) + este handoff.
3. Conferir vivo: `systemctl --user is-active hermes-gateway jfn` · `pgrep -f siafe_sweep_full`.
4. Regras: aditivo · `pytest -q` antes do commit · NÃO tocar módulos SIAFE com sweep rodando · tudo grátis ·
   documentar cada checkpoint (com "Erros & Aprendizados") · toda skill nova → capabilities.yaml + /lista.
