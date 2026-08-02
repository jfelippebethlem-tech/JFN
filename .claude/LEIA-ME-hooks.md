# Por que o hook de SessionStart só faz BOOTSTRAP (e nunca mais apenda)

## O que ele fazia (até 2026-07-30)

```
if [ ! -f ~/.claude/CLAUDE.md ]; then cp .claude/global_preferences.md ~/.claude/CLAUDE.md
elif ! grep -qF "$MARKER" ~/.claude/CLAUDE.md; then cat .claude/global_preferences.md >> ~/.claude/CLAUDE.md
fi
```

Ou seja: **apendava 2.378 bytes dentro de `~/.claude/CLAUDE.md` sempre que um marcador de texto não
fosse encontrado.** `~/.claude/CLAUDE.md` é arquivo *always-on* — entra no contexto de **toda** sessão,
em **todo** projeto.

## Por que isso é uma bomba, e não uma conveniência

O guarda era um `grep` por um **título literal**: `# Instruções Globais — jfelippebethlem@gmail.com`.
Enquanto essa linha exata existir, o hook é idempotente. Mas:

1. Está em curso um trabalho de **enxugar o contexto always-on** (medido em ~10.300 tokens por
   sessão, e `~/.claude/CLAUDE.md` é parte disso). Reescrever esse arquivo é justamente o que muda
   ou remove títulos.
2. No instante em que o título muda, o hook volta a apendar **2,4 KB por sessão**, calado.
3. E o efeito é invisível pelo sintoma: ninguém percebe "o contexto está 3 KB maior" — percebe-se
   meses depois, quando a cota aperta.

Enxugar o arquivo com esse hook vivo é **encher a banheira com o ralo aberto**.

## O que faz agora

```
[ -f ~/.claude/CLAUDE.md ] || cp /home/ubuntu/JFN/.claude/global_preferences.md ~/.claude/CLAUDE.md
```

**Bootstrap e nada mais.** Cria o arquivo em máquina nova; nunca toca num arquivo que já existe.
Consequências deliberadas:

- **Sem crescimento possível.** O hook não tem caminho de escrita em arquivo existente.
- **Sem aviso todo turno.** A alternativa era avisar quando o conteúdo divergisse — mas stdout de
  hook de SessionStart **entra no contexto**, então um aviso permanente seria trocar 2,4 KB de
  crescimento por um custo fixo menor mas eterno. Divergir é decisão do dono, não anomalia.
- **Caminho absoluto.** Antes era `$(pwd)`, que só funciona se a sessão começar na raiz do repo.

Se um dia quiser reaplicar as preferências globais, é um comando manual e consciente:
`cat ~/JFN/.claude/global_preferences.md >> ~/.claude/CLAUDE.md`.

## Nota sobre redundância

`global_preferences.md` duplica boa parte do que `JFN/CLAUDE.md` já diz — e `JFN/CLAUDE.md` já é
carregado automaticamente neste projeto. Ou seja: dentro do JFN, o conteúdo apendado era pago duas
vezes. Isso é alvo da passada semântica de poda de contexto.
