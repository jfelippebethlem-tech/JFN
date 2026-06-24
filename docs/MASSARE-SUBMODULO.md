# Massare — agora é um repositório próprio (submódulo)

**Data:** 2026-06-23

O módulo de mercado/finanças **Massare** foi extraído do repo JFN para o seu **próprio repositório**,
com histórico preservado, e voltou ao JFN como **submódulo git**.

- Repo próprio: **https://github.com/jfelippebethlem-tech/Massare** (privado)
- No JFN: continua em `massare/`, agora como submódulo apontando para o repo acima.
- **Nada quebrou:** os imports (`python -m massare.X`, `from massare import ...`), os systemd timers
  (`massare-daily`, `massare-market`) e o server seguem funcionando — os arquivos continuam fisicamente em `massare/`.
- `massare/data/` (dados de runtime) é preservado e fica fora do versionamento do repo Massare.

## Como clonar o JFN com o Massare junto
```bash
git clone --recurse-submodules <JFN.git>
# ou, num clone já existente:
git submodule update --init --recursive
```

## Como atualizar o Massare a partir do JFN
```bash
cd ~/JFN/massare
git pull origin main          # puxa as novidades do repo Massare
cd ~/JFN
git add massare               # registra o novo commit do submódulo
git commit -m "chore(massare): bump submódulo"
```

## Como trabalhar direto no Massare
```bash
cd ~/Massare                  # ou ~/JFN/massare
# editar, commitar, git push origin main
# depois, no JFN: git add massare && git commit (bump do ponteiro)
```

---

## Faxina de submódulos mortos (mesma data)
Removidos dois submódulos **órfãos e vazios** (gitlink sem `.gitmodules`, sem conteúdo, nunca funcionaram):
- `tools/simple-captcha`
- `tools/tutorial_quebrar_captcha`

> **Atenção:** o captcha que **funciona** NÃO foi tocado — é o `compliance_agent/captcha_solver.py`
> (+ `compliance_agent/collectors/sei_captcha_crawler.py`), o solver interno usado nos sweeps do SEI.
> Os submódulos removidos eram tentativas antigas abandonadas quando esse solver passou a resolver.
