# Skills do Yoda (Hermes) — parte da Onda 13 do JFN 2.0

Skills isoladas que adicionam slash commands ao Yoda SEM tocar o core do gateway
(`gateway/run.py`). Instalar copiando para `~/.hermes/skills/` e rodando `/reload-skills`
no Telegram (não exige reiniciar o bot).

- `capacidades/` → comando **/capacidades** = bridge para a skilltree do JFN
  (GET /api/skills, /api/skill, POST /api/skills/reload, GET /api/skills/validate).
  Obs.: `/skills` é built-in do Hermes (gerenciar skills) — por isso o comando do JFN é `/capacidades`.
