# PLAYBOOK SEI — caminho ÚNICO (não reinvente)

> Para QUALQUER modelo/agente. Barato primeiro: o arquivo em disco responde
> 90% das perguntas sem browser, sem SEI, sem IA. Custo sobe a cada passo.

## 0. O processo já está arquivado? (grátis — comece SEMPRE aqui)
```bash
.venv/bin/python tools/sei_consultar.py --listar
.venv/bin/python tools/sei_consultar.py "330020/000762/2021"        # resumo+fases+lacunas
.venv/bin/python tools/sei_consultar.py PROC --fase execucao        # medições/atestos
.venv/bin/python tools/sei_consultar.py PROC --tipo nota_fiscal
.venv/bin/python tools/sei_consultar.py PROC --grep "reajuste"
.venv/bin/python tools/sei_consultar.py PROC --fotos                # fotos de medição (JPEG)
.venv/bin/python tools/sei_consultar.py PROC --doc 12               # texto integral do doc
```
Arquivo em `data/sei_arquivo/<TAG>/` (txt + fotos + manifest). 10-20× menor que o PDF.

## 1. Não está arquivado → baixar a ÍNTEGRA (browser, ~min; SEMPRE background)
```bash
SEI_SEM_TG=1 .venv/bin/python tools/sei_integra_completa.py "PROC"   # sem spam no Telegram
.venv/bin/python tools/sei_integra_completa.py "PROC"                # com envio ao Telegram
```
Grava `data/sei_cache/integra_<TAG>/NNN.pdf` + `manifest.json` (títulos da árvore).

## 2. Converter para o arquivo compacto (CPU local, sem browser)
```bash
.venv/bin/python tools/sei_arquivar.py "PROC"          # txt + fotos + fases + lacunas
.venv/bin/python tools/sei_arquivar.py --pendentes     # tudo que falta (o sweep já faz)
```

## 3. Leitura pontual sem íntegra (browser)
`sei_reader.ler()` → paginação `tools/sei_proc_paginado.py` (a árvore pagina de
10 em 10 — `ler()` sozinho só vê a 1ª página!). Sessão: `tools/sei_session.py`.

## Fases da contratação = CÓDIGO, não memória
`compliance_agent/sei/fases.py` (testes: `tests/test_sei_fases.py`):
planejamento → selecao → contratacao → execucao → despesa (+controle/tramitacao).
`classificar(titulo)`, `linha_do_tempo(titulos)`, `lacunas(fases, modalidade)`.
Lacuna CRÍTICA clássica: **pagamento sem evidência de execução** (OB/NF sem
medição/atesto/relatório fotográfico). Fotos de medição são PROVA — o arquivador
as preserva em `fotos/` justamente para conferir se o serviço foi feito.

## NUNCA
- ❌ Culpar acesso/WAF: o login SEMPRE funciona (cron prova). Falha = seu método.
- ❌ Browser em foreground ou 2 browsers: use background + `tools/vm_guard.py`.
- ❌ Reinventar parsing/leitura de PDF: `sei_consultar.py` já entrega texto.
- ❌ Carregar PDF/íntegra inteira no contexto: use `--grep`/`--fase`/`--doc`.
- ❌ Rodar OCR fora do `sei_arquivar.py` (ele já decide quando OCR é preciso).
