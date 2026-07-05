# Manual — Painel JFN & Hosting

## Painel
Site leve servido pelo próprio `server.py` em **`/painel`** (`static/jfn-painel.html`, Tailwind CDN,
sem build). Consome os endpoints do JFN. Protegido pelo login do JFN.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/painel    # 200/303 = vivo
```

## Túnel público (Cloudflare quick tunnel)
Desde 2026-07-05 é **systemd** (`painel-tunnel.service`) — antes era um processo solto que morria.
```bash
systemctl --user status painel-tunnel.service
# a URL muda a cada restart; recuperar a atual:
journalctl --user -u painel-tunnel | grep -o 'https://[a-z-]*\.trycloudflare\.com' | tail -1
```
URL atual (pode mudar): `https://uncle-forum-relax-capture.trycloudflare.com/painel`.

## Endereço fixo (pendente do dono)
**Tailscale Funnel** daria URL fixa grátis (`https://jfn-core.tailbbe6c9.ts.net/painel`), mas depende
de 1 toggle: abrir o link do Funnel no admin da Tailscale → **Enable Funnel** → depois
`tailscale funnel --bg 8000`. O certificado HTTPS já está habilitado.

## Tudo grátis
Sem billing. Cloudflare quick tunnel e Tailscale Funnel são gratuitos.
