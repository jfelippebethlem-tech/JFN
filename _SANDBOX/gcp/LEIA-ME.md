# Rodar o Yoda no servidor GCP — 1 clique

## Situação
Preparei TUDO para o Yoda (bot do Telegram + Hermes) rodar no servidor Google
(`server-1`, projeto `jfn-vps`, IP 34.95.162.244). Falta **um único passo que só
você pode fazer**: o **login do Google** (por segurança, eu não mexo na sua sessão
pessoal do Google nem tenho sua senha).

## O que fazer (1 passo)
1. Dê **duplo-clique** em `rodar-tudo-no-gcp.cmd`.
2. Vai abrir o navegador no login do Google → escolha **jfelippebethlem@gmail.com**
   e clique **Permitir**.
3. Pronto. O script faz **sozinho** todo o resto (3–6 min) e te avisa no fim.

## O que o script faz automaticamente (depois do seu login)
1. Define o projeto `jfn-vps`.
2. Libera SSH seguro via túnel IAP (sem expor porta na internet).
3. Monta um `.env` enxuto (SÓ as chaves do bot: Telegram + IAs; **não** envia
   segredos do SEI/Oracle/GCP).
4. **Para o bot local** (pra não conflitar com o do servidor — o Telegram só
   aceita um bot por token).
5. Envia config + script para a VM (túnel IAP).
6. Roda o `bootstrap-vm.sh` na VM, que:
   - instala Python, Node 22, Claude Code, ffmpeg;
   - clona o `hermes-agent` (NousResearch) e instala;
   - copia sua config (`config.yaml`, `.env`, `auth.json` com o rodízio de Gemini);
   - cria o serviço **`yoda`** (systemd) que sobe sozinho e **reinicia se cair**.

## Como conferir depois
- **Teste real:** mande uma mensagem pro bot no Telegram.
- Status:  `gcloud compute ssh server-1 --zone=southamerica-east1-b --tunnel-through-iap --command="systemctl status yoda"`
- Logs:    `... --command="journalctl -u yoda -n 50"`

## Importante
- Depois disso, o bot roda **no servidor** (8GB RAM, melhor que o PC). O PC pode
  até ser desligado que o Yoda continua no ar.
- Se algum passo falhar, o script mostra a mensagem e para — me chame que a gente
  ajusta (ou o próprio Claude que está na VM pode continuar).
- Arquivos: `bootstrap-vm.sh` (roda na VM) · `rodar-tudo-no-gcp.cmd` (roda no PC).
