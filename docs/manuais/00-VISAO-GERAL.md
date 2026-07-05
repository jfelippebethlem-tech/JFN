# Manual do Ecossistema JFN — Visão Geral

> Estado verificado em 2026-07-05. Cada sistema tem seu manual próprio nesta pasta.
> Norte: fiscalização/controle externo do Estado do RJ (deputado estadual).

## Mapa dos sistemas

| Sistema | O que é | Onde vive | Manual |
|---|---|---|---|
| **JFN** | Motor de auditoria/compliance (API 24h, perícia, relatórios Kroll) | `~/JFN`, `jfn.service` :8000 | [01-JFN.md](01-JFN.md) |
| **Hermes / Yoda** | Gateway de mensagens (Telegram) que aciona o JFN em linguagem natural | `~/hermes-agent`, `hermes-gateway.service` | [02-HERMES-YODA.md](02-HERMES-YODA.md) |
| **SEI itkava** | Leitura autenticada de processos do SEI-RJ (login interno, sem captcha) | `~/JFN/tools/sei_reader.py` + cron | [03-SEI-ITKAVA.md](03-SEI-ITKAVA.md) |
| **PCRJ / Fantasmas** | Cruzamento de folhas Câmara×Prefeitura; detector de funcionário fantasma | `~/JFN/compliance_agent/pcrj/`, `pcrj.db` | [04-PCRJ-FANTASMAS.md](04-PCRJ-FANTASMAS.md) |
| **Polimonitor / Bond** | Monitor de Instagram (curtidores, interações, viral) | `~/polimonitor` :3000, `~/likers-sync` | [05-POLIMONITOR-BOND.md](05-POLIMONITOR-BOND.md) |
| **Painel + hosting** | Painel web do JFN e túnel público | `/painel`, `painel-tunnel.service` | [06-PAINEL-HOSTING.md](06-PAINEL-HOSTING.md) |
| **Crons & timers** | Agendamentos (coleta, sweeps, backup, manutenção) | crontab + systemd user timers | [07-CRONS-TIMERS.md](07-CRONS-TIMERS.md) |

## Como pedir qualquer coisa (o jeito humano)
Fale com o **Yoda no Telegram** em português normal. Ele entende linguagem natural e também comandos:
- `/relatorio <empresa>` — due diligence de um fornecedor (PDF)
- `/orgao <UG/nome>` — quanto um órgão pagou e a quem
- `/dossie <alvo>` — dossiê 360
- `/pericia <CNPJ|OB|nome>` — perícia na hora, com laudo
- `/veredito <ref> confirmado|descartado` — você fecha o ciclo (treina o sistema)

## Regras de ouro (valem para tudo)
1. **OB (Ordem Bancária) = pagamento = verdade.** Empenho ≠ pago.
2. **Indício ≠ acusação.** INDISPONÍVEL ≠ 0. Nunca inventar número.
3. **SEI = sempre login interno itkava**, nunca captcha/público.
4. **Não crashar a VM** (2 vCPU): 1 tarefa pesada por vez; nunca 2 browsers.
5. **Relatório = produto da casa** (PDF Kroll), nunca .txt à mão.

## Saúde rápida (um comando)
```bash
systemctl --user --failed        # deve vir vazio
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/lista   # 200
```
