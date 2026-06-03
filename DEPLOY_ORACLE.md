# Como colocar o JFN Agent na Oracle Cloud

> Guia completo em linguagem simples. Se você nunca mexeu com servidor,
> não se preocupe — cada passo explica exatamente o que fazer.

---

## O que você vai conseguir no final

Um computador na nuvem (chamado de **VM**) que vai rodar o JFN Agent
**24 horas por dia, 7 dias por semana**, sem precisar deixar o seu PC ligado.
Você vai acessar o painel pelo navegador de qualquer lugar.
**É totalmente gratuito** pelo Oracle Cloud Always Free.

---

## PARTE 1 — Criar a VM na Oracle Cloud

### Passo 1 — Acessar o console

1. Abra o navegador e vá em: **cloud.oracle.com**
2. Faça login com o e-mail e senha que você cadastrou.
3. Na tela inicial, clique em **"Get Started"** ou no menu hambúrguer (≡) no canto esquerdo.

### Passo 2 — Criar a VM (o "computador na nuvem")

1. No menu lateral, procure **"Compute"** → **"Instances"**.
2. Clique no botão azul **"Create Instance"**.
3. Preencha assim:
   - **Name**: `jfn-agent` (ou qualquer nome)
   - **Image**: `Ubuntu 22.04` ← IMPORTANTE: clique em "Change Image" e escolha Ubuntu 22.04
   - **Shape**: Clique em "Change Shape" → escolha **"Ampere"** → selecione **`VM.Standard.A1.Flex`**
     - OCPUs: **2** (pode usar até 4 no plano grátis)
     - Memory: **12 GB** (pode usar até 24 GB)
   - **Boot Volume**: deixe o padrão (50 GB)

4. **SSH Keys** (sua "chave de acesso seguro"):
   - Clique em **"Save Private Key"** para baixar o arquivo `.key`.
   - **GUARDE esse arquivo** — sem ele você não consegue entrar na VM!
   - No Windows, o arquivo baixa como `ssh-key-XXXX.key`.

5. Clique em **"Create"** e aguarde ~3 minutos até a VM ficar verde (Running).

### Passo 3 — Anotar o IP da VM

1. Clique na VM que você criou.
2. Na página dela, você vai ver **"Public IP Address"** — anote esse número.
   - Exemplo: `152.67.45.123`
   - Você vai precisar dele para acessar o agente.

---

## PARTE 2 — Abrir a porta 8000 na Oracle Cloud

> A Oracle tem um "porteiro" que bloqueia acessos externos por padrão.
> Você precisa "falar com o porteiro" para liberar a porta do agente.

1. No menu lateral: **"Networking"** → **"Virtual Cloud Networks"**.
2. Clique na VCN que foi criada automaticamente (geralmente `vcn-XXXX`).
3. No menu interno, clique em **"Security Lists"** → clique na lista existente.
4. Clique em **"Add Ingress Rules"** e preencha:
   - Source CIDR: `0.0.0.0/0`
   - IP Protocol: `TCP`
   - Destination Port Range: `8000`
5. Clique em **"Add Ingress Rules"** para salvar.

---

## PARTE 3 — Conectar na VM pelo terminal

### No Windows (usando o Terminal do Windows ou PowerShell)

1. Abra o **Terminal** (tecla Windows → digite "Terminal" ou "PowerShell").
2. Vá até a pasta onde está o arquivo `.key` que você baixou:
   ```
   cd Downloads
   ```
3. Conecte na VM (substitua `SEU-IP` pelo IP que você anotou):
   ```
   ssh -i ssh-key-XXXX.key ubuntu@SEU-IP
   ```
   - Se aparecer "Are you sure you want to continue connecting?" → digite `yes` e Enter.
   - Se der erro de permissão do arquivo .key no Windows, rode:
     ```
     icacls ssh-key-XXXX.key /inheritance:r /grant:r "%USERNAME%:R"
     ```
     Depois tente o ssh de novo.

4. Quando aparecer `ubuntu@jfn-agent:~$` você está **dentro da VM**! ✓

---

## PARTE 4 — Instalar tudo automaticamente

Você está no terminal da VM agora. Cole os comandos abaixo **um de cada vez**:

### Passo 1 — Baixar o código do agente

```bash
git clone https://github.com/jfelippebethlem-tech/JFN.git
cd JFN
```

### Passo 2 — Rodar o script de instalação automática

```bash
bash setup_oracle_cloud.sh
```

Esse script vai:
- Atualizar o sistema
- Instalar o Docker (o "motor" que roda o agente)
- Abrir a porta 8000 no firewall interno da VM

Aguarde terminar (pode levar 3–5 minutos).

**IMPORTANTE**: Depois que o script terminar, feche e abra o terminal de novo
(ou rode `newgrp docker`) para o Docker funcionar sem `sudo`.

---

## PARTE 5 — Configurar as chaves de API (.env)

O agente precisa das suas chaves para funcionar. Crie o arquivo de configuração:

```bash
cp .env.example .env
nano .env
```

No editor que abriu, preencha as informações. Use as setas do teclado para navegar:

```
GROQ_API_KEY=gsk_SUA_CHAVE_AQUI
TELEGRAM_BOT_TOKEN=SEU_TOKEN
TELEGRAM_CHAT_ID=SEU_CHAT_ID
SIAFE_USER=SEU_CPF
SIAFE_PASS=SUA_SENHA
```

Para **salvar e sair** do nano:
- Pressione `Ctrl + X`
- Pressione `Y` (yes)
- Pressione `Enter`

---

## PARTE 6 — Iniciar o agente

```bash
docker compose up -d --build
```

- O `--build` só é necessário na **primeira vez** (constrói a imagem).
- `-d` faz rodar em segundo plano.

Aguarde ~5 minutos na primeira vez (ele baixa e instala tudo dentro do container).

### Verificar se está rodando

```bash
docker compose logs -f
```

Quando aparecer algo como `Uvicorn running on http://0.0.0.0:8000`, o agente está no ar!
Pressione `Ctrl + C` para sair dos logs sem parar o agente.

---

## PARTE 7 — Acessar o painel

Abra o navegador no seu computador (ou celular) e acesse:

```
http://SEU-IP-DA-ORACLE:8000
```

Substitua `SEU-IP-DA-ORACLE` pelo IP que você anotou no Passo 3.

Você vai ver o **painel do JFN Agent** com o Hermes pronto para uso!

---

## Comandos úteis do dia a dia

```bash
# Ver os logs em tempo real
docker compose logs -f

# Parar o agente
docker compose down

# Iniciar o agente (sem rebuildar)
docker compose up -d

# Atualizar o código e reiniciar
git pull
docker compose up -d --build

# Ver uso de CPU/memória da VM
htop

# Ver uso de disco
df -h
```

---

## Reinício automático

O agente já está configurado com `restart: always` — se a VM reiniciar
(por manutenção da Oracle, queda de energia etc.), o agente vai subir
automaticamente sem você precisar fazer nada.

---

## O Hermes rodando 24 horas

Depois de acessar o painel em `http://SEU-IP:8000`, clique em **"Hermes"**
no menu e ative o botão **"Auditor 24 horas"**. O Hermes vai:

1. Coletar dados do SIAFE2 e DOERJ automaticamente
2. Analisar padrões de irregularidades
3. Gerar alertas e relatórios
4. Enviar notificações no Telegram (se você configurou o bot)

Tudo isso enquanto você dorme. ✓

---

## Problemas comuns

| Problema | Solução |
|----------|---------|
| "Connection refused" ao acessar o painel | Verifique se abriu a porta 8000 na Security List (Parte 2) |
| "Permission denied" no SSH | Rode o comando `icacls` mostrado no Passo 3 |
| Agente parou | `docker compose up -d` para reiniciar |
| Disco cheio | `docker system prune -f` para limpar imagens antigas |
| Não consigo conectar por SSH | Verifique se o arquivo .key é o correto para aquela VM |

---

## Segurança

- **Nunca compartilhe** o arquivo `.key` com ninguém.
- **Nunca commite** o arquivo `.env` no git (já está protegido pelo `.gitignore`).
- O painel na porta 8000 não tem senha por padrão. Se quiser proteger,
  considere colocar um reverse proxy (Nginx) com senha básica.

---

*Preparado para Oracle Cloud Ubuntu 22.04 ARM64 (Always Free Tier)*
