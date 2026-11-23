# Repasse — suíte noturna na nuvem (23/11/2026) → Claude da VM-1

Branch vivo testado: `ui/painel-v61-tron-claro` @ `4aafed34`. Branch de conserto: **`nuvem/testes-20261123`**
(sem PR, sem push no vivo). Integrar depois de conferir.

## Resultado
- 1ª rodada: 10114 passaram · 15 falharam · 4 erros · 181 pulados.
- Após consertos (com `zstd` CLI e `zstandard` instalados): 10132 passaram · 1 falhou (rede) · 181 pulados.

## (a) Consertado — conferir e integrar
| Commit | Teste | O quê |
|---|---|---|
| `a26751d3` | `test_divida_except_pass_nao_cresce` (147 > teto 145) | 2 `except: pass` mudos novos em `tools/sei_ocr_ia_conferir.py` (vieram em 4690d7a3) viraram aviso no stderr com contexto. Teto segue 145. |
| `605f3588` | `test_todo_import_de_terceiros_esta_declarado` | `zstandard>=0.22` declarado em `requirements.txt`. **`patchright` NÃO declarado**: instalar junto quebra o `playwright==1.44.0` fixado (greenlet/pyee — o pip acusa). Virou exceção nomeada em `EXCECOES`, presa a `tools/zelador/mediafire_sessao.py`, com justificativa; o teste-guarda do conjunto esperado foi atualizado junto. **Decisão a validar na VM-1** (alternativa: venv própria do zelador, ou subir o pin do playwright). |

## (b) Ambiente — não é defeito
- 12 falhas + 4 erros: falta do binário `zstd` (`FileNotFoundError: 'zstd'`) — cache/compressão SEI, sentinela, bombeiros, recaptura, depurar. Com `apt install zstd` todos passam.
- `test_duckdb_na_copia_nao_solta_os_locks_do_banco_vivo`: sem rede para baixar a extensão `sqlite_scanner` do duckdb.
- 181 pulados: falta `data/compliance.db` e outros dados locais.

## Pendência achada (não consertada)
- Algum teste grava no `data/` REAL em vez de `tmp_path`: a suíte deixou `data/.integras_vm2_reserva.json`,
  `data/.sei_depurar_watermark` e `data/lex_contestados_sem_doc.json` (valores fictícios: `SEI-1`,
  `300000/000004/2025`). Apagados aqui; vale achar o teste e isolá-lo — na VM-1 isso pode sobrescrever estado vivo.

## Fim da rotina
O dono pediu para encerrar esta suíte noturna na nuvem depois deste repasse. A rotina agendada precisa ser
desativada pelo dono em claude.ai/code (rotinas) — a sessão na nuvem não tem como apagá-la.
