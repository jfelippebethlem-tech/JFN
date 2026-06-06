# Pesquisa — Oracle ADF Faces (`af:table`) PPR row-fetch via HTTP (extração completa do SIAFE)

> **Produto de deep-research** (sessão anterior) recuperado e consolidado em 2026-06-06. Resolve a limitação
> registrada em [`SIAFE-ARQUITETURA.md`](SIAFE-ARQUITETURA.md) §8b: como **buscar TODAS as linhas** de uma
> `af:table` do SIAFE-Rio 2 (Oracle ADF) **por HTTP puro** (Python `requests`), sem depender de eventos
> sintéticos do Playwright (que não disparam o autoSubmit/PPR do ADF de forma confiável em headless).
> Referência real e funcional: o scraper open-source da **ASIC** (`connectonline.asic.gov.au`, um app ADF Rich
> Client) — `https://raw.githubusercontent.com/bianca/mapaustralianbanks/master/scraper.py`.

---

## TL;DR — as duas surpresas

1. **ADF Rich Client NÃO usa o protocolo JSF/Mojarra padrão** (`Faces-Request: partial/ajax` + `<partial-response>`).
   Usa um dialeto próprio: header **`Adf-Rich-Message: true`**, o evento vai como um **XML `<m xmlns="http://oracle.com/richClient/comm">…</m>`**, e a resposta é um envelope XML cujos fragmentos HTML vêm em
   **`<fragment><![CDATA[ …HTML… ]]></fragment>`** (não `<update id=…>`). **Não misturar** com o material de
   `partial/ajax` que se acha na internet — é outro framework.
2. **Para `af:table` quase nunca se monta um `rangeChange` cru.** O jeito comprovado é **disparar o botão de
   próxima página como evento `action`** (ou mudar o `fetchsize`) e deixar o servidor avançar o range. A posição
   é comunicada por um parâmetro separado: **`oracle.adf.view.rich.DELTAS = {tableClientId={viewportSize=N}}`**,
   incrementado a cada página. Não existe `first/rows/rangeStart/rangeSize` no fio — esses são conceitos do
   *iterator binding* no servidor (`RangeSize`), não parâmetros do request.

---

## 1. Lista de parâmetros do POST (partial submit ADF Rich Client)

Chaves **reservadas do framework** (nomes literais — os prefixos de client-id mudam por app):

| Parâmetro | O que é |
|---|---|
| `org.apache.myfaces.trinidad.faces.FORM` | nome/id do `<form>` que submete (ex.: `f1`) |
| `javax.faces.ViewState` | token ViewState — **re-ler a cada ciclo** (§4) |
| `event` | **client-id do componente** que dispara o evento (ex.: o botão "próxima") |
| `event.<clientId>` | o **payload XML do evento** (o `<m>`, §2) — o sufixo `<clientId>` = valor de `event` |
| `oracle.adf.view.rich.PROCESS` | client-id(s) a executar no lifecycle (ex.: a tabela ou a região) |
| `oracle.adf.view.rich.RENDER` | client-id(s) a re-renderizar (em geral só na busca inicial) |
| `oracle.adf.view.rich.DELTAS` | deltas de estado do cliente. **Para paginação carrega o viewport:** `{<tableId>={viewportSize=N}}` |

Mais os **campos da aplicação** (filtros, `fetchsize`/`fetchsizeTwin`, hidden inputs): pega-se o form renderizado
e sobrescreve só o que muda.

### Exemplo literal — próxima página (o row-fetch desejado)

```python
controls = {
    "org.apache.myfaces.trinidad.faces.FORM": "f1",
    "javax.faces.ViewState": vs,                       # re-lido da resposta anterior
    "oracle.adf.view.rich.DELTAS": "{TBL:t1={viewportSize=51}}",   # 11 -> 51 -> 101 ...
    "event": "TBL:pagingNextButtonTwin",
    "event.TBL:pagingNextButtonTwin":
        '<m xmlns="http://oracle.com/richClient/comm"><k v="type"><s>action</s></k></m>',
    "oracle.adf.view.rich.PROCESS": "TBL:r1",
}
```

`viewportSize` 11 → 51 é o contador cumulativo do topo do viewport. `pagingNextButtonTwin` é o client-id do botão
"próxima"; dispará-lo como `type=action` faz o servidor devolver a próxima fatia.

### Headers (os dois críticos)

```python
{
  "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
  "Adf-Rich-Message": "true",            # <-- ADF-crítico
  "Adf-Ads-Page-Id": "1",                # correlação de janela (constante p/ scraping single-window)
  "Origin": "https://<host>", "Referer": "<URL .jspx>",
}
```
Não precisa de `Faces-Request: partial/ajax` (isso é JSF core, não ADF Rich Client).

## 2. O payload XML do evento (`<m>`)

Estrutura: `<m xmlns="http://oracle.com/richClient/comm">` com entradas `<k v="KEY"><TIPO>VALOR</TIPO></k>`
(`<s>`=string, `<b>`=boolean/número). A chave `type` seleciona o tipo do evento.

- **Ação / paginação** (avança linhas): `<m …><k v="type"><s>action</s></k></m>`
- **Mudança de valor** (selector de page-size/dropdown):
  `<m …><k v="autoSubmit"><b>1</b></k><k v="suppressMessageShow"><s>true</s></k><k v="type"><s>valueChange</s></k></m>`

## 3. Resposta e parsing das linhas

HTML de cada componente vem em `<fragment><![CDATA[ …HTML… ]]></fragment>`. Extrai-se o chunk que contém o id
da tabela (ou a classe `af_table_data-table`), e parseia-se os `<tr>` com BeautifulSoup. "Tem próxima página?"
= ausência da classe `p_AFDisabled` no botão next.

## 4. Sessão, cookies e rotação do ViewState

- **Cookie:** `JSESSIONID` do GET inicial do `.jspx` — usar `requests.Session()`.
- **ViewState rotaciona:** o JSF (e o ADF) reemite `javax.faces.ViewState` em cada resposta parcial; **pegar o
  novo** a cada ciclo (reusar gera `ViewExpiredException`/resposta vazia). Alguns deployments toleram ViewState
  fixo na sessão, mas **projetar defensivamente: re-extrair sempre**.
- Extração robusta (cobre CDATA do ADF e `value="…"` da página cheia):
  ```python
  m = (re.search(r'javax\.faces\.ViewState[^>]*?>\s*<!\[CDATA\[(.*?)\]\]>', resp, re.S)
       or re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', resp))
  ```
  O nome do campo pode vir sufixado (`javax.faces.ViewState:!-…`) — casar pelo **prefixo**.

## 5. Como incrementar o range a cada chamada

- **A — Botão de paginação (comprovado):** manter `event` = client-id do `pagingNextButtonTwin` com payload
  `action`, e **avançar `viewportSize`** no `DELTAS` pelo tamanho da página: `11 → 51 → 101 …`. Repetir até o
  next mostrar `p_AFDisabled`.
- **B — Scroll/disclosure (se a tabela suportar):** disparar `rowDisclosure`/scroll no **client-id da tabela** e
  subir `viewportSize` para o novo índice de fundo. Sem `first/rows` no fio — tudo em `DELTAS` + evento.

## 6. Anti-bot / monitoramento

- `oracle.adf.view.rich.monitoring.UserActivityInfo` é **telemetria opcional**, não CSRF — pode omitir (o scraper
  real omitiu). Se um deployment exigir, mandar um `<m>` de timing mínimo.
- O verdadeiro "portão" é: **sessão válida + ViewState fresco + `org.apache.myfaces.trinidad.faces.FORM` correto
  + ecoar os inputs obrigatórios do form.**

## 7. Template Python (requests)

```python
import re, requests
from bs4 import BeautifulSoup

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 ... Chrome/124 ...",
                  "Accept": "*/*", "Accept-Language": "pt-BR,pt;q=0.9"})

PAGE    = "https://siafe2.fazenda.rj.gov.br/.../page.jspx"
TABLE   = "pt:r1:0:t1"             # <-- client-id da af:table do SIAFE (descobrir na página)
NEXTBTN = "pt:r1:0:t1:pagingNext"  # <-- botão next/scroll da tabela
FORM    = "f1"
PROCESS = "pt:r1"
EV_ACTION = '<m xmlns="http://oracle.com/richClient/comm"><k v="type"><s>action</s></k></m>'

def get_viewstate(text):
    m = (re.search(r'javax\.faces\.ViewState[^>]*?>\s*<!\[CDATA\[(.*?)\]\]>', text, re.S)
         or re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', text))
    return m.group(1)

def unwrap_fragment(text, marker):
    for ch in text.split("<fragment><![CDATA["):
        if marker in ch:
            return ch.split("]]></fragment>")[0]
    return None

def parse_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find(class_="af_table_data-table")
    rows = [[td.get_text(strip=True) for td in tr.find_all("td")]
            for tr in (body.find_all("tr") if body else [])]
    last = bool(soup.find(True, {"class": ["pageNavNextButton", "p_AFDisabled"]}))
    return rows, last

r = S.get(PAGE); vs = get_viewstate(r.text)
base = {i.get("name"): i.get("value","")
        for i in BeautifulSoup(r.text,"html.parser").select(f'form#{FORM} input') if i.get("name")}
# (rodar o POST da BUSCA aqui, mesma forma; atualizar vs da resposta)

viewport, PAGE_SIZE, todas = 50, 50, []
while True:
    data = dict(base, **{
        "org.apache.myfaces.trinidad.faces.FORM": FORM,
        "javax.faces.ViewState": vs,
        "oracle.adf.view.rich.PROCESS": PROCESS,
        "oracle.adf.view.rich.DELTAS": "{%s={viewportSize=%d}}" % (TABLE, viewport),
        "event": NEXTBTN,
        "event.%s" % NEXTBTN: EV_ACTION,
    })
    resp = S.post(PAGE, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Adf-Rich-Message": "true", "Adf-Ads-Page-Id": "1",
        "Origin": PAGE.split("/")[0]+"//"+PAGE.split("/")[2], "Referer": PAGE})
    vs = get_viewstate(resp.text)
    frag = unwrap_fragment(resp.text, "af_table_data-table")
    if not frag: break
    linhas, last = parse_rows(frag)
    todas += linhas
    if last or not linhas: break
    viewport += PAGE_SIZE
```

---

## 8. Aplicação ao SIAFE-Rio 2 (próximos passos)

1. **Descobrir os client-ids reais** da `af:table` de "OB Orçamentária" e do botão next — pelo DevTools/Network
   ao paginar manualmente uma vez (ou inspecionando o HTML renderizado pelo coletor atual via Chrome 9222).
2. **Capturar UM POST de paginação real** (HAR/Network) e conferir os campos obrigatórios que o SIAFE valida
   (filtros de UG/exercício, `fetchsize`). Espelhar no `base`.
3. **Reaproveitar a sessão autenticada** do coletor existente (`siafe_ob_orcamentaria.py`): pegar `JSESSIONID`
   e o ViewState pós-login e alimentar o loop HTTP — assim some a dependência do Playwright para a varredura.
4. **Integrar** como modo "varredura completa" no `siafe_ob_orcamentaria.py` (passar do limite de 1000/consulta).
5. O WAF do SIAFE bloqueia IP de datacenter (VM/GCP) — rodar de IP gov/autorizado ou via GitHub Actions
   (Azure), como já se faz na coleta (ver CLAUDE.md §COLETA SIAFE).

> **Status:** pesquisa concluída e consolidada; **implementação pendente** (itens 1-4 acima). É o caminho
> recomendado no §8b do `SIAFE-ARQUITETURA.md` ("replay HTTP do request de filtro"), agora com o formato exato.

_Fonte primária: scraper ASIC (ADF Rich Client real) + docs Oracle/Apache PPR. Recuperado de deep-research da
sessão `4eee4c2c` (subagente a0a7c60c)._
