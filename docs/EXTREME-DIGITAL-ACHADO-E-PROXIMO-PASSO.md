# Extreme Digital — achado da sessão + próximo passo (para a próxima IA)

> Investigação iniciada a pedido do dono (2026-06-08): achar DIRECIONAMENTO na licitação/certame da
> **EXTREME DIGITAL CONSULTORIA E REPRESENTAÇÕES LTDA** (CNPJ **14.139.773/0001-68**), que já tem relatório
> de inteligência no Yoda (`reports/inteligencia_extreme_digital..._2026-06-08.md`). Honesto: indício a
> apurar, NUNCA acusação.

## Perfil (do relatório + SIAFE/TFE)
- **R$ 580,3 milhões** pagos 2019–2026 · 1.716 OBs · **30 órgãos** · score de risco **70/100 (ALTO)**.
- Crescimento: R$24M (2019) → R$80M (2023) → **R$188M (2025)**.
- 2 empresas com **sócio em comum** também recebem OBs do Estado (possível frustração de competitividade,
  art. 337-F CP) — ver seção 1-B do relatório.

## ACHADO-CHAVE (hipótese do dono CONFIRMADA pelos dados)
O contrato que abre a cadeia é **Contrato INEA n.º 16/2024** (gestão de projetos/desenvolvimento/
infraestrutura de TI), lido ao vivo no SEI: processo **SEI-070002/004332/2024** (Termo Aditivo) — é de
**EXECUÇÃO**, não a licitação. **O INEA ADERIU A UMA ATA (ARP)** — a licitação NÃO foi do INEA.
**O gerenciador da ARP é quase certamente o PRODERJ:**
- **UG 403200 = Centro de Tecnologia de Informação e Comunicação (PRODERJ)** é o **MAIOR pagador** da
  Extreme Digital: **R$ 141,9 milhões** (462 OBs) — o gerenciador típico de uma ARP estadual de TI.
- **PRODERJ CNPJ = 30.121.578/0001-67.** Outra hipótese do dono: **Secretaria de Transformação Digital
  (UG 580100)**.
- Padrão clássico: **uma ARP central → muitas adesões (30 órgãos) → R$580M**. Se houver direcionamento, ele
  está na **ÚNICA licitação central** (PRODERJ/SETD), e se propaga a todos os órgãos que aderiram.

## ⚠️ POR QUE O PNCP DEU 0 — descoberta decisiva (insight do dono, confirmado por pesquisa)
O **PNCP só passou a ser obrigatório** com a Lei 14.133, cujo **período de transição terminou em
30/12/2023** (até lá a Administração podia licitar sob a **Lei 8.666**, publicando no **Diário Oficial/
ComprasNet — NÃO no PNCP**). A Extreme Digital recebe **desde 2019**; a ARP/contratos vêm de licitações
**antigas (Lei 8.666, pré-2024)** — o aditivo INEA de 2024 é de um contrato cuja **licitação original é
pré-PNCP**. **Logo o edital da ARP NÃO está no PNCP** — está no **SEI / Diário Oficial do RJ / SIGA-RJ**.
Isso explica os 0 resultados no PNCP (por fornecedor E por órgão PRODERJ) e redireciona a coleta:
**para esta empresa, a fonte do edital é o SEI/DO-RJ, não o PNCP.** (O PNCP segue ótimo para licitações
**novas**, ≥2024 — onde o `buscar_itens`/cérebro já funcionam.)

## Por que ainda NÃO travamos o edital da licitação
- O PNCP por `cnpjFornecedor` (contratos) e por `orgao_cnpj` do PRODERJ retornou **0** (autarquia publica de
  forma diferente; o filtro client-side por CNPJ não casou).
- Os processos SEI acessíveis via OB são de **execução/contrato/aditivo** (ou tela do SEI), não o edital.
- A cadeia `relacionados` do 070002 aponta para **1 processo** (`id_procedimento=77829392`, "Solicitação de
  Contratação"), cujas URLs SÃO navegáveis (`procedimento_trabalhar&id_procedimento=...`) — mas o número do
  processo de licitação não extrai limpo do texto.

## PRÓXIMO PASSO (preciso, para a próxima IA)
1. **Ler o SEI direito seguindo a cadeia:** enhancer no `sei_reader` p/ NAVEGAR as URLs dos `relacionados`
   (`procedimento_trabalhar&id_procedimento=`) na sessão autenticada e extrair a árvore de cada um — até achar
   o processo de **LICITAÇÃO** (edital/ata/atestado). As URLs do 070002 estão em `/tmp/extreme_rel_urls.json`.
2. **OU achar a licitação do PRODERJ no PNCP por OUTRO caminho:** (a) buscar contratações RJ de TI e filtrar
   pelo **vencedor** = Extreme (via `/itens/{n}/resultados` → `niFornecedor`), sem depender do filtro de órgão;
   (b) tentar a Secretaria de Transformação Digital (achar o CNPJ da UG 580100); (c) PNCP por **modalidade
   concorrência/pregão de SRP** (registro de preços) no período 2022–2023 (criação da ARP).
3. Com o edital+ata em mãos → `direcionamento_cerebro.avaliar_direcionamento(edital, ata)` (Gemini→Hermes) →
   `montar_pacote_claude` → Telegram (já implementado nesta sessão).

## Ferramentas prontas desta sessão (usar)
- `compliance_agent/direcionamento_cerebro.py` — cérebro LLM (Gemini→Hermes/Groq), com `presinais`,
  `_trechos_relevantes`, guardrails de honestidade, `montar_pacote_claude`.
- `tools/direcionamento_telegram.py` — `--id`/`--scan` envia o pacote ao Telegram.
- `compliance_agent/collectors/pncp.py::buscar_itens` — preço unitário estruturado.
- `compliance_agent/grafo_cartel.py::cartel_com_qsa` — sócio em comum entre concorrentes (ao vivo).
