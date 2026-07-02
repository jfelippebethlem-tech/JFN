# JFN — serviço 24h + ronda automática (systemd --user)

Mantém o agente JFN **sempre ativo** nesta VM Linux e faz uma **ronda** periódica que
checa o serviço e os alertas (e notifica via Telegram, se configurado). Roda independente
de qualquer sessão do Claude.

## Componentes
| Unit | Papel |
|---|---|
| `jfn.service` | Sobe `server.py` (porta 8000), reinicia se cair (`Restart=always`). |
| `jfn-ronda.service` | Oneshot: executa `tools/ronda.py` (checa serviço + alertas, loga, notifica). |
| `jfn-ronda.timer` | Dispara a ronda a cada 10 min (`OnUnitActiveSec=10min`). |
| `jfn-nucleo-ciclo.service` | Oneshot: ciclo de inteligência progressiva (`compliance_agent.nucleo.ciclo`) — pericia OBs novas, alimenta a memória e roda o loop de autoaprimoramento com freio no conjunto-ouro. |
| `jfn-nucleo-ciclo.timer` | Dispara o ciclo diariamente às 06:30 UTC (antes do resumo do dia). |

## Instalar numa VM nova
```bash
cd ~/JFN
./start_linux.sh --setup            # venv + deps + chromium
mkdir -p ~/.config/systemd/user
cp deploy/systemd/jfn*.service deploy/systemd/jfn*.timer ~/.config/systemd/user/
sudo loginctl enable-linger "$USER" # sobrevive a logout/reboot
systemctl --user daemon-reload
systemctl --user enable --now jfn.service jfn-ronda.timer jfn-nucleo-ciclo.timer
```

## Operar
```bash
systemctl --user status jfn jfn-ronda.timer   # estado
systemctl --user list-timers jfn-ronda.timer  # próxima ronda
journalctl --user -u jfn -f                    # logs do servidor
tail -f ~/JFN/data/ronda.log                   # log da ronda
~/JFN/.venv/bin/python tools/ronda.py --test   # testar notificação Telegram
```

## Notificações Telegram
A ronda só envia mensagem em **eventos** (serviço caiu, API fora, novos alertas, LLM fora)
e **somente** se `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` estiverem preenchidos de verdade
no `.env` (os placeholders `SEU_...` do `.env.example` são ignorados). Sem isso, a ronda
apenas grava em `data/ronda.log`.

> Os arquivos aqui usam `%h` (home), então são portáveis entre usuários/VMs.
> Bind em `127.0.0.1` por padrão (painel não exposto à internet — ver CLAUDE.md).
