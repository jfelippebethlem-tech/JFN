# Handoff — 25/07/2026, rodada da noite

**Para retomar:** *"continue pelo docs/superpowers/specs/2026-07-25-handoff-noite.md"*.
Branch `feat/painel-v8-melhorias`. Sucede o handoff da manhã (`2026-07-25-handoff-continuidade.md`).

---

## 0 · LEIA PRIMEIRO — o que custou caro nesta rodada

### 0.1 Correção calibrada por instrumento não validado herda o erro do instrumento

O caso mais instrutivo do dia. O v12 "corrigiu" `--dim` para L=0,60 anotando no código
*"4,78:1 no pior caso medido"*. **4,78 é exatamente o número que o auditor de PARADAS DE COR
produz** — e ele estava errado. Medido no pixel, o valor real era **4,14:1**: a correção nunca
chegou ao mínimo, por uma versão inteira, e ninguém percebeu porque a régua confirmava.

**Antes de confiar num número, valide o instrumento que o produziu.**

### 0.2 O auditor de contraste acertava 1 de 4

`tools/auditar_contraste.py` lia as PARADAS declaradas do gradiente. Contra um gabarito de
4 casos (`tests/fixtures/contraste_gabarito.html`):

| caso | verdade | antigo |
|---|---|---|
| gradiente sob os glifos | reprova | reprova ✓ |
| faixa de 1px longe do texto | **aprova** | **reprova** — falso positivo; foi dele que nasceu a "lei" de não decorar fundo de texto |
| camada de cima transparente sobre camada clara | **reprova** | **aprova** — falso negativo, o pior dos três |
| fundo em `url()` | **reprova** | **mudo** |

`tools/auditar_contraste_pixel.py` fotografa o fundo em vez de deduzi-lo: três capturas da mesma
caixa (texto `transparent`, `#000`, `#fff`); preto contra branco dá a máscara dos glifos, a
transparente dá o fundo puro. Acerta os 4.

**Armadilha que eu mesmo caí:** a 1ª versão montava a máscara comparando a captura NATURAL com a
sem texto — e falhava justamente quando o texto era quase da cor do fundo, o pior caso. Daí as
duas sondas.

**Custo:** `captureBeyondViewport:True` custa 1,88 s por captura; `False` custa 0,97 s e dá os
mesmos pixels (delta ≤2/canal). Dedup por padrão ANTES de capturar: 413 elementos → 20 padrões.
Lote: 3 capturas de viewport por aba em vez de 3 por elemento. De 114 s para ~15 s por aba.

### 0.3 O véu de 6% que nenhum leitor de estilo enxerga

`.card::before` pinta `linear-gradient(oklch(1 0 0/.06), transparente 36%)` — o especular do v7 —
sobre o topo de TODO card. Como `::before` **não é ancestral**, nenhum leitor de estilo o alcança.
Provado pintando o card de `#000` (voltou 15,15,15) e de `#ff0000` (voltou 255,15,15).

### 0.4 Capturar canvas com `captureBeyondViewport` fotografa o quadro em BRANCO

Eu fotografei a holomesa vazia e quase acusei o código. Ela estava viva (`raf=92`, canvas com
tinta, chips posicionados). `captureBeyondViewport:True` força resize → `size()` → `canvas.width=…`
→ **limpa o bitmap**. Isso já está escrito no próprio `jfn-painel.html` e eu não li antes de
acusar. **Para capturar a mesa:** viewport alto o bastante para ela caber, clip em coordenadas de
VIEWPORT, `captureBeyondViewport:false`, e esperar quadros depois de qualquer mudança de geometria.

### 0.5 O 413 do Yoda não era foto nem histórico

`Request payload too large (413). Cannot compress further.` persistia **depois do `/new`**. O log
deu o motivo: `TPM Limit 12000, Requested 40672`. O que estoura sozinho é o **catálogo de
ferramentas** (`~/.hermes/jfn_tools.json`, 72 KB ≈ 18 mil tokens), injetado em toda requisição —
no plano gratuito do Groq as definições de ferramenta consomem TPM **antes** do prompt.

A mensagem engana duas vezes: fala em "payload" quando o limite é de **taxa**, e manda comprimir o
histórico, que não tem culpa.

**Curas:** `model.default` → `gemini-2.5-flash` (janela de 1 M, aceita imagem); `fallback_providers`
reordenado por **janela** e com **visão primeiro** (cair num modelo só-texto com foto não dá erro,
dá resposta errada); Groq foi para o fim. Mais: `_enqueue_photo_event` juntava o álbum inteiro sem
teto — agora há orçamento por BYTES e o que não cabe tem o caminho declarado no texto.

### 0.6 Regra que acusa metade do universo não é fila, é ruído

A triagem do SEI acusava 82% do acervo. Duas calibragens: (1) "liquidação sem evidência" tinha
**40% de falso positivo** — o documento existia com "Atestado" no TÍTULO e o classificador de tipo
não o reconhecia; (2) mesmo calibradas, duas regras batiam em metade do acervo por causa
**estrutural** (a pesquisa de preço vive no processo de PLANEJAMENTO). Foram para `observacoes`:
agravam somadas a um achado forte, não entram sozinhas.

---

## 1 · O QUE FICOU PRONTO

### 1.1 Auditoria (P0)
- `tools/auditar_contraste_pixel.py` + gabarito de 4 casos + 7 testes.
- `tools/auditar_contraste.py` delega o fundo não plano ao nível 2 e **assina o que mediu**
  (sha1 do disco, HTML servido, valor de `--dim`) — uma varredura inteira já saiu com cara de
  atual medindo o painel pré-correção.
- `tools/painel_abas.py`: fonte única das **51 abas**, lida do próprio HTML. Os dois auditores
  olhavam 9.

### 1.2 Esferas estanques (P2) — **211 de 439 órgãos estavam no balde errado**
`compliance_agent/pcrj/esfera.py` ganhou `municipal-outro`. Não criei classificador novo: o
canônico já existia e é bom. O teste apontou uma "cópia" em `collectors/pncp_resultados.py` — ao
LER, não é cópia: usa o `esferaId` oficial do PNCP, fonte mais forte. Isento com motivo, e um
teste trava a **equivalência dos baldes**.

### 1.3 Redação-conforme (P3)
`Vicio.redacao_conforme`: a cláusula REESCRITA, na voz do edital, citável. 16 vícios de texto.
O teste travou três redações **sem dispositivo** e redação escrita como **conselho**. Vício de
CONDUTA é declarado isento com motivo.

### 1.4 Rotas sem superfície (P5) — **68 era teto, 23 é o laudo**
137 rotas · 49 sem menção · 26 de plano de controle · 19 falso positivo do próprio probe (rota
concatenada) · **23 capacidades reais sem superfície**. Teste trava o número.

### 1.5 Perícia SEI (P4)
**Fonte da fila estava errada em dois eixos:** lia o espelho TFE (19.837 processos invisíveis) e
somava OB CANCELADA como paga (R$ 3,93 bi "Excluído" + R$ 417 mi "Anulado" = 26% de inflação).
Universo real: **40.152 processos · 36.419 nunca tocados · R$ 13,17 bi** (a memória registrava
18.843 e R$ 2,11 bi).

`tools/sei_triagem_pericia.py`: **188 processos com achado forte** (9,2%) — 138 parecer com
ressalva sem resposta, 80 **contrato ANTES do parecer**, 2 sem acatamento. Cruzado com o SIAFE:
**161 com OB paga = R$ 316,4 mi**.

**Repasse separado de contratação**, em três voltas: (1) "empenho" na lista de contratação fazia
tudo virar contratação — todo pagamento tem empenho; (2) decidir por CONTAGEM perdia 14 a 1
porque repasse cita "contrato" em anexo; (3) **override forte** (`Ordens Bancárias Externas` =
pagamento a outro ente), com contrato forte tendo precedência. Quatro Fundos Municipais de Saúde
saíram da fila de vício contratual.

### 1.6 Visão com Gemini
`JFN_VISAO_PROVEDORES=gemini` funciona. Extrai o lado CONTRATADO ("440 unidades habitacionais",
"30 meses"). **O lado ENTREGUE não tem lastro**: as pastas `fotos/` contêm páginas de documento —
notas fiscais, tabelas de medição. Dos 5.525 arquivos, ~30% têm fotografia, e elas quase não
coincidem com os processos de maior valor.

---

## 2 · PENDENTE, declarado

1. **Painel v14 REVERTIDO.** O dono reprovou o resultado visual. Preservado no commit `62ffd7dc`
   e em `/tmp/painel-v14-preservado.html`. Os testes de assinatura **pulam sozinhos e se re-armam**
   quando o registro voltar ao painel.
   **O defeito exato, medido na foto do celular:** rótulos longos caem na **grade compacta de 3
   colunas** e quebram **letra por letra na vertical** ("M A I S A R E C"). Qualquer rótulo do
   núcleo tem de ser medido na grade compacta, não só na mesa.
2. **`coverage` não está instalado** no venv, embora `pyproject.toml` tenha a configuração. O
   critério de "retestar cada linha" ficou sem instrumento.
3. **Varredura de foto reciclada** nas 5.525 imagens: rodando em segundo plano ao fim da sessão.
4. **Detector de "região de foto" confunde tabela com fotografia** — pega nota fiscal e tabela de
   medição. Os 30% medidos por amostragem são otimistas.
5. **Comparação quantitativo entregue × contratado**: sem lastro no acervo atual (ver 1.6).

---

## 3 · COMANDOS

```bash
# auditores do painel (CDP 9222) — o de contraste agora assina o que mediu
.venv/bin/python tools/auditar_contraste.py            # 51 abas, nivel 1 + nivel 2
.venv/bin/python tools/auditar_contraste_pixel.py      # gabarito de 4 casos
.venv/bin/python -m pytest tests/test_auditor_contraste.py -q

# pericia SEI
.venv/bin/python -m tools.sei_triagem_pericia --json /tmp/triagem.json
.venv/bin/python -m tools.sei_fila_por_dinheiro        # agora le o SIAFE, sem OB cancelada

# visao com Gemini (teto e kill-switch existem — use-os antes de volume)
JFN_VISAO_PROVEDORES=gemini JFN_VISAO_TETO=200 .venv/bin/python ...

# suite, nome a nome (contagem esconde regressao)
./tools/testar_na_vm2.sh > /tmp/s.log
grep '^FAILED' /tmp/s.log | sed 's/ - .*//;s/^FAILED //' | sort > /tmp/agora.txt
comm -13 <(grep -v '^#' tests/BASE-FALHAS-VM2.txt | sed 's/^FAILED //' | sort) /tmp/agora.txt
```

**Yoda:** `systemctl --user restart hermes-gateway`. Config em `~/.hermes/config.yaml`
(`model:` na linha ~550, `fallback_providers:` na ~401). Backups `config.yaml.bak-*`.
