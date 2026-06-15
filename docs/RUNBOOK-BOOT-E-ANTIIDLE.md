# RUNBOOK — Boot (systemd --user) e Guarda Anti-Idle (Oracle Always Free)

Host: VM Linux ARM (Oracle Cloud, provável Always Free Ampere A1), user `ubuntu`,
home `/home/ubuntu`. Tudo roda como **systemd --user** com **linger habilitado**
(`loginctl show-user ubuntu -p Linger` → `Linger=yes`), portanto os serviços sobem
no boot mesmo sem sessão SSH aberta.

> Para qualquer `systemctl --user` / `journalctl --user` fora de uma sessão de login:
> ```bash
> export XDG_RUNTIME_DIR=/run/user/$(id -u)
> ```

---

## 1. Units que sobem no boot

### Serviços de longa duração (`WantedBy=default.target`, `Restart=always`)
| Unit | O que é | ExecStart (resumo) |
|------|---------|--------------------|
| `jfn.service` | API/servidor JFN (uvicorn em `127.0.0.1:8000`) | `.venv/bin/python server.py --host 127.0.0.1 --port 8000` |
| `chrome-jfn.service` | Chromium headless, ponte CDP `127.0.0.1:9222` (coleta TFE/SIAFE) | `/snap/bin/chromium --headless=new ... --remote-debugging-port=9222` (`Nice=10`) |
| `hermes-gateway.service` | Hermes Agent Gateway (Yoda / mensageria) | `hermes-agent/.venv/bin/python -m hermes_cli.main gateway run` |

Observação: `jfn.service` roda `server.py` (FastAPI/uvicorn). A rota de saúde é
`GET /status` (e `GET /`). **Não** existem `/health` nem `/ping`.

### Timers (`WantedBy=timers.target`)
| Timer | Cadência | Aciona |
|-------|----------|--------|
| `jfn-ronda.timer` | a cada 10 min (boot+2min) | `jfn-ronda.service` — checa serviço/API e alerta |
| `keepalive.timer` | a cada ~7 min (boot+3min) | `keepalive.service` — **guarda anti-idle** (ver §3) |
| `jfn-tfe.timer` | diário 05:00 | coleta TFE |
| `jfn-tfe-ob.timer` | diário 06:00 | coleta TFE-OB |
| `massare-daily.timer` | diário 04:30 | sweep diário Massare |
| `massare-market.timer` | diário 09:00 | sweep de mercado Massare |

---

## 2. Como verificar a saúde

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Estado dos 3 serviços principais
systemctl --user is-enabled chrome-jfn jfn hermes-gateway
systemctl --user is-active  chrome-jfn jfn hermes-gateway

# Linger (garante boot sem sessão)
loginctl show-user ubuntu -p Linger        # esperado: Linger=yes

# API JFN viva?
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/status   # esperado: 200

# Timers agendados
systemctl --user list-timers --all

# Logs
journalctl --user -u jfn -n 50 --no-pager
journalctl --user -u hermes-gateway -n 50 --no-pager
journalctl --user -u keepalive -n 20 --no-pager
tail -n 20 /home/ubuntu/JFN/data/ronda.log
tail -n 20 /home/ubuntu/JFN/data/keepalive.log
```

Estado esperado de cada serviço: `enabled` + `active`.

> Nota: `/status` pode devolver **500/timeout transitório** durante um pico
> (ex.: enquanto a ronda ou um sweep está rodando). Reteste após alguns segundos;
> 200 estável significa saudável.

---

## 3. Guarda anti-idle (Oracle Always Free)

### Por que existe
O Oracle "Always Free" pode **reclamar/parar** instâncias compute consideradas
ociosas. Critério oficial, avaliado em janela de **7 dias** — a instância só é
candidata a reclaim se **TODAS** as condições baterem simultaneamente:
- **CPU** < 20% (no agregado ~<10%) em 95%+ do tempo, **E**
- **rede** utilizada < 10%, **E**
- **memória** < 10%.

Risco real aqui: a `jfn-ronda` (a cada 10 min) é levíssima e bate só em
**localhost** (loopback praticamente não conta como rede externa); os sweeps são
rajadas **diárias**. Em períodos quietos a instância podia ficar perto de "ociosa"
nos três eixos ao mesmo tempo. A guarda elimina esse risco com custo mínimo.

### O que foi implementado
- **Script:** `/home/ubuntu/JFN/tools/keepalive.sh`
  A cada disparo faz, em conjunto e de forma LEVE:
  1. ~2 s de CPU em 1 core (loop de aritmética limitado por relógio);
  2. `curl http://127.0.0.1:8000/status` (toque no serviço local);
  3. **rede externa real**: GETs minúsculos em
     `cloudflare.com/cdn-cgi/trace`, `1.1.1.1`, `google.com/generate_204`
     (poucos KB no total) + `ping -c 3 1.1.1.1`;
  4. grava uma linha em `/home/ubuntu/JFN/data/keepalive.log` (mantido em ~500 linhas).
- **Service:** `/home/ubuntu/.config/systemd/user/keepalive.service`
  `Type=oneshot`, `Nice=19`, `IOSchedulingClass=idle`, `TimeoutStartSec=60`.
- **Timer:** `/home/ubuntu/.config/systemd/user/keepalive.timer`
  `OnBootSec=3min`, `OnUnitActiveSec=7min`, `RandomizedDelaySec=45s`,
  `Persistent=true`, `WantedBy=timers.target`.

Consumo: alguns segundos de 1 core e poucos KB de rede a cada ~7 min — o suficiente
para não parecer ociosa, **sem gerar custo** (apenas requisições HTTP/DNS triviais).
Não excede cotas do Always Free.

### Operação
```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Habilitar (idempotente)
systemctl --user daemon-reload
systemctl --user enable --now keepalive.timer

# Estado
systemctl --user is-enabled keepalive.timer   # enabled
systemctl --user is-active  keepalive.timer   # active
systemctl --user list-timers keepalive.timer --all

# Disparo manual de teste
systemctl --user start keepalive.service
tail -n 5 /home/ubuntu/JFN/data/keepalive.log
# linha esperada: ... local_status=200 net_ok=3/3 ping=yes

# Desabilitar, se necessário
systemctl --user disable --now keepalive.timer
```

---

## 4. Recuperação rápida

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Reiniciar um serviço caído
systemctl --user restart jfn.service          # ou chrome-jfn / hermes-gateway

# Reaplicar arquivos de unit após edição
systemctl --user daemon-reload

# Garantir que linger continua ligado (sobrevive a reboot sem sessão)
sudo loginctl enable-linger ubuntu
```
