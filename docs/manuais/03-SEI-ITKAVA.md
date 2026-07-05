# Manual — SEI itkava (leitura de processos)

## Regra número 1
O SEI é lido **SEMPRE pelo login interno itkava** (usuário interno, unidade ITERJ, SEM captcha).
Captcha/pesquisa pública é EXCEÇÃO rara (processo restrito cross-unidade), nunca o plano.
Se der 0 documentos, o problema é o método/janela — **nunca** o acesso.

## Caminho canônico (não reinventar)
1. `tools/sei_reader.py::ler("SEI-UUUUUU/NNNNNN/AAAA")` — loga, abre a Pesquisa, extrai a íntegra
   (árvore de documentos + texto + OCR de scans), grava `data/sei_cache/cdp_*.json` (cache 24h).
2. Processo de outra unidade que o ITERJ não abre → fallback **CRACKED** automático (mesmo browser).
3. Arquivo compacto (texto+fases+fotos de medição) → `tools/sei_integra_completa.py` + `sei_arquivar.py`.

```bash
cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.sei_reader "SEI-070002/008633/2022"
```

## Melhorias 2026-07-05 (testadas ao vivo)
- **Esperas por condição com teto** (`_ate()`) no lugar de sleeps fixos: pós-login, abertura da
  Pesquisa e pós-submit retornam assim que a página/árvore pinta. Medido: **75s vs 103s (-27%)**,
  saída idêntica (10 docs) nos dois casos canônicos.
- **Frescor por OB:** `sei_integra_fila.py --geral` (cron 04:00) re-lê processo já arquivado que
  ganhou **OB nova** (SIAFE/TFE) depois do arquivo — OB nova = o processo andou → re-ler, senão a
  perícia roda incompleta. Bounded 10/rodada, maior valor primeiro.

## Regra da VM (crítica)
**Nunca 2 browsers ao mesmo tempo** (derruba a sessão e a VM de 2 vCPU). O reader usa `browser_lock`
e `aguardar_load`; a fila pausa os sweeps (`.pause_*`) e espera o browser livre antes de baixar.
Antes de qualquer browser manual: `tools/vm_guard.py` (preflight + mata órfãos).

## Onde ficam as coisas
- Cache de leitura: `data/sei_cache/cdp_*.json`
- Arquivo organizado: `data/sei_arquivo/<UUUUUU_NNNNNN_AAAA>/{texto,fotos,fases}`
- Log da fila: `data/sei_integra_fila.log`
- Playbook técnico completo: `docs/PLAYBOOK-SEI.md`

## Próximo passo (fase 2, pesquisado)
Migrar para `frame_locator("iframe[name=ifrArvore]")` + wait por sentinela no frame
(`page.frame()` pode devolver None cedo). `networkidle` é desencorajado — já usamos condição.
