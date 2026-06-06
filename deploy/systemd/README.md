# Units systemd (--user) do ecossistema — VM Linux

Instalar/atualizar:
```bash
cp deploy/systemd/*.service deploy/systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now chrome-jfn.service massare-market.timer
```

- `chrome-jfn.service` — ponte Chrome headless CDP na porta 9222 (coleta TFE/SIAFE ao vivo do JFN).
- `massare-market.service` + `.timer` — Massare no pregão (dias úteis 12:50–21:00 UTC = 09:50–18:00 BRT, a cada 15min).

Já existentes (não versionados aqui, criados anteriormente): `jfn.service`, `hermes-gateway.service`,
`jfn-tfe.timer`, `jfn-tfe-ob.timer`, `jfn-ronda.timer`, `massare-daily.timer`. Ver `../../AMBIENTE.md`.

> ⚠️ O `yoda.service` (nível de SISTEMA) foi DESABILITADO em 2026-06-06 (duplicava o hermes-gateway). Não reativar.
