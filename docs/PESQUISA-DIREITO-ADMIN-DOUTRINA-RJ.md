# Lex — Base citável de Direito Administrativo, Improbidade e Controle (com foco RJ)

> Deep-research verificada (06/06/2026): 82 claims extraídos → **25 verificados em votação adversarial 3-0
> (0 refutados)** → 10 achados sintetizados. Fontes primárias: editoras, STF, STJ, CGU, TCU/ISSAI, ALERJ,
> TCE-RJ, CGE-RJ. **Toda tese é fundamento de PARECER DE INDÍCIOS — nunca acusação.** Insumo para `lex.py`
> e `compliance_agent/knowledge/`. Complementa `LEX-DOUTRINA-IMPROBIDADE.md` e `LEX-APRENDIZADOS-CGE-CASHPAGO.md`.

## ⚠️ Correções que esta pesquisa impõe ao projeto
- **Controle externo no RJ = Constituição Estadual arts. 122-123** (a ALERJ fiscaliza; o controle externo é
  exercido **com auxílio do TCE-RJ**, art. 123). **NÃO é o art. 97** (numeração federal, assumida por engano no
  CLAUDE.md). Corrigir onde aparecer.
- **Dano efetivo** (fim do dano presumido, pós-14.230) aplica-se **só ao art. 10** (dano ao erário) — **não** aos
  arts. 9 ou 11. O Lex deve especificar o artigo.

## 1. Doutrina (base citável)
- **Celso Antônio Bandeira de Mello** (*Curso de Direito Administrativo*, 35ª ed., atual. até EC 109/2021 e Lei
  14.133/2021): competências são **"deveres-poderes"** instrumentais ao interesse coletivo, **adstritas ao
  indispensável** no caso concreto (base para análise de proporcionalidade/excesso). Controle judicial: na conduta
  **vinculada** não há dificuldade; na **discricionária**, o exame é verificar se houve **extrapolação** da
  discrição efetivamente detida. *(3-0)*
- **Hely Lopes Meirelles** (*Direito Administrativo Brasileiro*): (a) **legalidade positiva** (art. 37 caput CF) —
  na Administração só se faz o que a lei autoriza; (b) **presunção de legitimidade** dos atos (independe de norma;
  autoriza execução imediata; válidos até pronunciamento de nulidade) — é **relativa (juris tantum)**; (c)
  **ônus da prova da invalidade recai sobre quem a invoca** (o impugnante/órgão de controle); (d)
  **discricionariedade** (liberdade dentro da lei; ato válido) **× arbítrio** (ação contrária/excedente à lei;
  sempre inválido). *(3-0)* — **fundamento central da postura do Lex: ato presumidamente regular, apontamento = indício.**

## 2. Improbidade (Lei 8.429/92 pós-Lei 14.230/2021)
- **STF Tema 1199 (ARE 843989/PR, repercussão geral, 2022, vinculante):** exige-se **DOLO** (responsabilidade
  subjetiva) nos arts. **9, 10 e 11**; a revogação da modalidade **culposa** é **irretroativa** (art. 5º XXXVI CF) —
  não alcança coisa julgada/execução; o **novo regime prescricional é irretroativo** (marcos a partir de 26/10/2021).
  Item 3 admite norma benéfica em processos sem trânsito em julgado (aferindo então o dolo). *(3-0)*
- **STJ REsp 1.929.685/TO** (1ª Turma, rel. Min. Gurgel de Faria, unânime, j. 27/8/2024, Informativo 823): o
  **dano efetivo** ao erário é **obrigatório** para condenação pelo **art. 10** ("sem dano efetivo não há ato
  ímprobo"), afastado o dano presumido *in re ipsa*, **inclusive para fatos anteriores à Lei 14.230 ainda
  pendentes**. ⚠️ Decisão de **Turma** (força persuasiva alta, **não** vinculante). Aplica-se ao **art. 10**, não 9/11. *(3-0)*

## 3. Anatomia do ACHADO (molde da Nota Técnica do Lex)
- **CGU** (Orientação Prática — Relatório de Auditoria): achado = descrição sumária · parágrafo introdutório ·
  **critério** (o que deveria ser) · **condição** (o que é) · **causa** (razão da diferença) · **efeito/consequência**
  · conclusão. Só descrição sumária, introdução e conclusão têm posição fixa. *(3-0)*
- **ISSAI 100** (trad. TCU): auditoria = processo sistemático de obter/avaliar evidências para confrontar
  **condição × critério**; três tipos — **financeira, de conformidade** (aderência a leis/regulamentos/resoluções
  orçamentárias), **operacional** (economicidade/eficiência/efetividade); resultado em achados/conclusões/
  recomendações/opinião. ⚠️ A anatomia detalhada (situação/critério/causa/efeito/evidência/recomendação) deriva de
  **ISSAI 300/3000 + guias CGU/TCU**, não do §29 da ISSAI 100. *(3-0)*

## 4. Controle no Estado do RJ
- **CERJ art. 122:** fiscalização contábil/financeira/orçamentária/operacional/patrimonial (legalidade,
  legitimidade, economicidade, subvenções, renúncia de receitas) pela ALERJ + controle interno de cada Poder.
- **CERJ art. 123:** controle externo a cargo da ALERJ, **com auxílio do TCE-RJ** (espelha CF/88 arts. 70-71). *(3-0)*
- **Competências do TCE-RJ:** **parecer prévio** sobre as contas do Governador em **60 dias**; julgar contas dos
  três Poderes; apreciar legalidade de admissões de pessoal; auditorias/inspeções; **multa proporcional ao dano**;
  **sustar** ato impugnado (sustação de contrato cabe à ALERJ). *(3-0)*
- **Tomada de Contas Especial (TCE-Especial):** apura responsabilidade por **dano** à administração — quantificação
  do dano, identificação de responsáveis, finalidade de **ressarcimento** (IN TCU 71/2012; Deliberação TCE-RJ 279). *(3-0)*
- **CGE-RJ / Decreto nº 47.408/2020** (de 17/12/2020; revogou o Decreto 47.121/2020): base dos procedimentos de
  controle interno e dos **modelos de Nota Técnica "com Achado" / "sem Achado"**. *(claim do decreto: 2-1; modelos: 3-0)*

## 5. Como incorporar no Lex (regras operacionais)
1. **Indício, nunca acusação:** todo ato é presumidamente legítimo (presunção **relativa**); o ônus de provar o
   vício é de quem aponta (Meirelles). O Lex levanta **indícios a verificar**.
2. **Molde do achado** em cada apontamento: **critério** (norma: artigo+lei) → **condição** (situação encontrada) →
   **causa** → **efeito** → **evidência** → **recomendação** (CGU + ISSAI).
3. **Improbidade com cautela:** exigir **dolo** (arts. 9/10/11 — Tema 1199); no **art. 10**, exigir **dano efetivo**
   (REsp 1.929.685), evitando dano presumido. Sempre nomear o artigo.
4. **Separar os planos** sem confundir: improbidade (Lei 8.429/92) × crimes (CP 312-337; Lei 14.133 arts. 337-E a
   337-P) × red flags de controle externo (TCU/ACFE).
5. **Citar a base RJ correta:** CERJ **arts. 122-123**; competências do TCE-RJ; CGE-RJ **Decreto 47.408/2020**;
   modelos Nota Técnica com/sem Achado.

## Caveats (honestidade da pesquisa)
- Os PDFs de Meirelles (kufunda.net) e parte de Bandeira de Mello (juspodivm) **não puderam ser extraídos
  diretamente** (binário/imagem); o teor é doutrina canônica confirmada por múltiplas fontes — **citar a OBRA
  (autor, título, edição), não a URL do PDF**. A 35ª ed. de BdM (2021) já foi superada por edições posteriores.
- **REsp 1.929.685 é decisão de Turma** (não repetitivo/súmula) — persuasiva, não vinculante.
- **Tipos penais (CP 312-337; Lei 14.133 arts. 337-E a 337-P)** foram citados na pergunta mas **não verificados
  individualmente** nesta rodada — **confirmar no texto legal antes de citar** no parecer.

## Questões em aberto (próximas rodadas)
- Tipos penais específicos (CP 312-337; Lei 14.133 337-E a 337-P) e seus elementos, p/ mapear indícios criminais
  com a mesma cautela do dolo.
- Normas estaduais do RJ que regulamentam a Lei 14.133/2021 e sua integração ao fluxo SEI-RJ e às deliberações do TCE-RJ.
- Deliberações/Resoluções do TCE-RJ (além da 279) sobre rito de TCE-Especial, parecer prévio e red flags estaduais.
- Posições de Di Pietro, Carvalho Filho, Rafael Oliveira, Marçal Justen, Emerson Garcia/Pacheco Alves e Fábio
  Medina Osório, para diversificar a base citável além de BdM e Meirelles.

## Fontes primárias
- Bandeira de Mello — Curso de Direito Administrativo, 35ª ed.: https://juspodivmdigital.com.br/cdn/arquivos/jma0029_previa-do-livro.pdf
- Hely Lopes Meirelles — Direito Administrativo Brasileiro: https://www.kufunda.net/publicdocs/Direito-Administrativo-Completo-Hely-Lopes-Meirelles.pdf
- STJ REsp 1.929.685/TO (dano efetivo, art. 10): https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/2024/04092024-Exigencia-de-dano-efetivo-ao-erario-vale-para-casos-anteriores-a-reforma-da-Lei-de-Improbidade-.aspx
- STF Tema 1199 (ARE 843989/PR): https://www.tjdft.jus.br/consultas/jurisprudencia/jurisprudencia-em-temas/precedentes-qualificados-na-visao-do-tjdft/direito-administrativo-e-constitucional/improbidade-administrativa/tema-1199-improbidade-administrativa-lei-14-230-2021-irretroatividade-dolo-prazos-prescrionais-e-prescricao-intercorrente
- CGU — Orientação Prática Relatório de Auditoria: https://wiki.cgu.gov.br/index.php/Orienta%C3%A7%C3%A3o_Pr%C3%A1tica:_Relat%C3%B3rio_de_Auditoria
- ISSAI 100 (trad. TCU): https://portal.tcu.gov.br/data/files/80/04/47/3A/C1DEF610F5680BF6F18818A8/ISSAI_100_principios_fundamentais_auditoria_setor_publico.pdf
- CERJ arts. 122-123 (ALERJ): http://www3.alerj.rj.gov.br/lotus_notes/default.asp?id=73&url=L2NvbnN0ZXN0Lm5zZi8xMTcxYzViYzU1Y2M4NjFiMDMyNTY4ZjUwMDcwY2ZiNi9iNzJmNDBlMWQwYmUxMmQyMDMyNTY2N2EwMDYzNzMwZT9PcGVuRG9jdW1lbnQ%3D
- TCE-RJ — atribuições: https://www.tcerj.tc.br/portalnovo/pagina/atribuicoes
- TCE-RJ — Deliberação 279/2017: https://www.tce.rj.gov.br/documents/10180/17340/DELIBERA%C3%87%C3%83O%20N%C2%BA%20279%20de%2024%20de%20agosto%20de%202017.pdf
- CGE-RJ — formulários (Nota Técnica com/sem Achado, Dec. 47.408/2020): https://cge.rj.gov.br/formularios/
- CGE-RJ — Tomada de Contas: http://www.cge.rj.gov.br/tomada-de-contas-de-acordo-com-o-manual-da-controladoria-geral-da-uniao-e-deliberacao-tce-279/
- Lei 14.133/2021 (texto): https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14133.htm

---

# PARTE II — Penal, normas do RJ e doutrina complementar (deep-research #3, 06/06/2026)
> 10 teses sintetizadas, votação 3-0. ⚠️ **Confirmar nº/data no texto oficial antes de citar formalmente**
> (atos infralegais identificados por páginas-resumo; acórdãos do STJ via Notícias, não inteiro teor).

## 6. Tipos penais (CP + Lei 14.133)
- **Núcleo (CP):** **peculato** (art. 312 — apropriação/desvio de bem que o funcionário detém em razão do cargo);
  **concussão** (art. 316 — exigir vantagem indevida em razão da função); **corrupção passiva** (art. 317 —
  solicitar/receber vantagem ligada ao ofício); **corrupção ativa** (art. 333 — oferecer/prometer; **crime
  formal**, consuma-se na oferta, sem precisar de aceitação). Demais: 313-A, 315, 319, 321.
- **STJ REsp 2.069.436 (6ª T.):** a revogação do **art. 89 da Lei 8.666/93 NÃO é abolitio criminis** — é
  **continuidade típico-normativa** migrada para o **art. 337-E do CP**. ⚠️ Vale **só** para *dispensar/inexigir
  fora das hipóteses*; *descumprir formalidade* teve abolitio (AgRg AREsp 2.079.040). Citar a conduta com precisão.
- **STJ AREsp 2.786.212 (rel. Schietti):** a supressão da **majorante do art. 84, §2º/8.666** (cargo de confiança)
  é **novatio legis in mellius** e **retroage** (art. 2º, p.ú., CP) para afastar o aumento.
- **Lei 14.133 arts. 337-E a 337-P:** crimes em licitações/contratos (inseridos no CP) — contratação direta
  ilegal (337-E), frustração da competitividade (337-F), etc.

## 7. Normas do Estado do RJ que regulamentam a Lei 14.133
- **Decreto estadual 47.680/2021** (12.07.2021): Comitês Executivo e Técnico de Governança em Contratações +
  transição 8.666→14.133.
- **Resoluções SEPLAG 179/2023** (pesquisa de preços) e **180/2023** (hipóteses de dispensa + compras.gov.br).
- **PGE-RJ:** Resolução 4.937/2023 (comissão de implantação) e 5.059/2024.
- **CGE-RJ** (Lei estadual 7.989/2018): controle interno central — AGE/OGE/CRE/Integridade; decreto de 29/01/2026
  sobre programas de integridade (nº a confirmar).
- **TCE-RJ Deliberação 279/2017:** rito das Tomadas de Contas (arts. 4º/5º; e-TCERJ); **art. 7º fixa o limiar de
  "elementos que INDIQUEM"** — alinhado à natureza de **parecer de indícios** do Lex.

## 8. Doutrina complementar (regime sancionador)
- **Fábio Medina Osório**, *Direito Administrativo Sancionador* (2000): aplica o regime sancionador à improbidade
  (dupla natureza; tese intermediária).
- **Pimenta Oliveira & Grotti** (*Panorama…*, RDAI): a Lei 14.230/2021 lida sob a lente do direito sancionador.

## Como incorporar (Parte II)
- Na seção de **crimes** do parecer: mapear indícios a CP 312/316/317/333 e Lei 14.133 337-E..P, **com a mesma
  cautela do dolo** usada na improbidade; ao citar dispensa/inexigibilidade irregular, usar **art. 337-E (ex-art.
  89/8.666, continuidade típica — REsp 2.069.436)**, nunca afirmar crime (competência do MP/Judiciário).
- Base **RJ** citável: Decreto 47.680/2021; Resoluções SEPLAG 179/180/2023; PGE 4.937/2023; **TCE-RJ Del. 279/2017
  art. 7º** (limiar de indício). Reforça que o Lex aponta **indício**, não condenação.
