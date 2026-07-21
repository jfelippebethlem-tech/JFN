# Arquivo de scripts encerrados

Scripts de uso único ou superados, mantidos por histórico/método — não são chamados por
nenhum cron, systemd unit, import ou rota (verificado antes de mover). Se algo aqui for
reaproveitado, mova de volta para `tools/`.

- **mgs_iterj_2021/** — dossiê do caso MGS/ITERJ (contrato 762/2021), já com veredito fechado
  (ver `~/vault/casos/iterj-mgs-clean-pagamentos.md`, `~/vault/aprendizados/asscont-saldo-56k-fonte-primaria.md`).
- **siafe1_exploracao/** — scripts de tentativa-e-erro que descobriram o DOM do SIAFE-1; o
  método ficou estabelecido em `tools.siafe_sweep_full --por-ug` (ver `docs/SIAFE-RIO2-GUIA-AUTOMACAO.md`).
- **sei_debug_superado/** — variações manuais de debug do SEI que duplicam o **PLAYBOOK ÚNICO**
  (`sei_reader.ler()` → `sei_proc_paginado` → `sei_integra_completa` → `sei_arquivar`, sempre via
  `vm_guard`). Mantidos arquivados para não serem redescobertos e usados fora da guarda do
  `browser_lock`/`vm_guard` — ver `docs/PLAYBOOK-SEI.md`.
