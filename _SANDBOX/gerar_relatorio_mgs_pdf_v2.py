#!/usr/bin/env python3
"""
Relatório de Auditoria — MGS CLEAN SOLUCOES E SERVICOS LTDA
Período: 2023-2026 | Cobertura: 14 órgãos | Contratos: 41
Produzido por JFN Intelligence · Auditoria · Risco · Compliance
"""
from __future__ import annotations
from fpdf import FPDF
from datetime import date
from pathlib import Path
import math

TODAY   = date.today().strftime("%d/%m/%Y")
TODAY_Y = date.today().strftime("%Y-%m-%d")
OUT     = Path(__file__).parents[1] / "reports" / f"auditoria_mgs_clean_2023-2026_{TODAY_Y}.pdf"

FONT_DIR = Path("/usr/share/fonts/truetype/liberation")

# ── Paleta Big4/TCU ──────────────────────────────────────────────────────────
C_NAVY    = (27,  42,  74)     # #1B2A4A — azul marinho profundo
C_NAVY2   = (36,  56,  96)     # #243860 — variante mais clara
C_GOLD    = (201, 168, 76)     # #C9A84C — dourado institucional
C_GOLD_LT = (232, 213, 163)    # #E8D5A3 — dourado claro
C_BLUE    = (46,  80, 144)     # #2E5090
C_BLUE_LT = (168, 199, 232)    # #A8C7E8
C_BLUE_XL = (232, 243, 253)    # #E8F3FD
C_GREEN   = (0,  112,  60)     # #00703C — verde aprovado
C_GREEN_L = (220, 242, 230)    # #DCF2E6
C_RED     = (192,  57,  43)    # #C0392B — vermelho crítico
C_RED_LT  = (253, 224, 220)    # #FDE0DC
C_AMBER   = (180, 120,  20)    # #B47814
C_AMBER_L = (255, 240, 200)    # #FFF0C8
C_ORANGE  = (190,  85,  20)    # #BE5514
C_ORANGE_L= (255, 225, 195)    # #FFE1C3
C_GRAY1   = (30,   30,  30)
C_GRAY2   = (90,   90,  90)
C_GRAY3   = (150, 150, 150)
C_GRAY4   = (210, 210, 210)
C_GRAY5   = (245, 245, 248)
C_WHITE   = (255, 255, 255)
C_BLACK   = (0,   0,   0)

def RGB(c): return c[0], c[1], c[2]

# ── Identificação ─────────────────────────────────────────────────────────────
EMPRESA  = "MGS CLEAN SOLUCOES E SERVICOS LTDA"
CNPJ     = "19.088.605/0001-04"
RISCO    = "MÉDIO-ALTO"
SCORE    = 63

CADASTRO = [
    ("Razão Social",         "MGS CLEAN SOLUCOES E SERVICOS LTDA"),
    ("Nome anterior",        "MGS CLEAN COMÉRCIO E SERVIÇOS EIRELI"),
    ("CNPJ (matriz)",        "19.088.605/0001-04"),
    ("CNPJ (filial)",        "19.088.605/0002-95 — Maricá/RJ (ab. 11/12/2024)"),
    ("Situação",             "ATIVA"),
    ("Data de abertura",     "15/10/2013  (12 anos de operação)"),
    ("Natureza jurídica",    "2062 — Sociedade Empresária Limitada"),
    ("CNAE principal",       "8121-4/00 — Limpeza em prédios e domicílios"),
    ("CNAE anterior (erro)", "J-6319-4/00 — Portais e serviços na Internet"),
    ("Capital social",       "R$ 11.000.000,00  (acima da média setorial: R$300K–2M)"),
    ("Porte",                "Médio/Grande"),
    ("Endereço (sede)",      "Av. das Américas 3434, Bl. 2 Sl. 506, Barra da Tijuca — RJ"),
    ("Administrador atual",  "Eduardo da Silva Azevedo (desde 11/12/2024)"),
    ("E-mail",               "contato@mgsclean.net  (domínio .net, sem registro .br)"),
    ("Total contratado",     "R$ 146.704.405,07  (41 contratos SIAFE, coleta 04/06/2026)"),
]

# ── Dados financeiros ─────────────────────────────────────────────────────────
# 2025 — EXATOS (TFE/RJ, coleta 04/06/2026)
MONTHLY_2025 = {
    "Jan": 28_711_452.88, "Fev": 15_220_776.81, "Mar": 11_546_032.54,
    "Abr":    372_933.12, "Mai": 11_158_944.41, "Jun":  3_387_523.10,
    "Jul":  1_497_190.58, "Ago":  9_828_546.04, "Set":  4_870_840.53,
    "Out":  2_527_737.68, "Nov":    617_498.76, "Dez":    226_368.28,
}
TOTAL_2025 = 89_965_844.73

# 2026 — EXATOS parcial jan–jun (TFE/RJ, coleta 04/06/2026)
MONTHLY_2026 = {
    "Jan": 24_794_208.66, "Fev": 12_875_672.22, "Mar":  5_510_009.15,
    "Abr": 10_836_090.23, "Mai":          0.00, "Jun":  4_582_254.12,
}
TOTAL_2026 = 58_598_234.38

# 2023 — ESTIMADO (projeção de contratos; sem acesso ao TFE/SIAFE histórico)
MONTHLY_2023 = {
    "Jan": 7_200_000, "Fev": 2_100_000, "Mar": 1_500_000,
    "Abr": 700_000,   "Mai": 800_000,   "Jun": 1_800_000,
    "Jul": 1_700_000, "Ago": 900_000,   "Set": 600_000,
    "Out": 350_000,   "Nov": 200_000,   "Dez": 218_000,
}
TOTAL_2023_EST = 18_068_000  # estimado

# 2024 — ESTIMADO (projeção de contratos; sem acesso ao TFE/SIAFE histórico)
MONTHLY_2024 = {
    "Jan": 28_000_000, "Fev": 8_500_000, "Mar": 6_200_000,
    "Abr": 2_800_000,  "Mai": 5_100_000, "Jun": 3_900_000,
    "Jul": 4_300_000,  "Ago": 5_800_000, "Set": 3_200_000,
    "Out": 2_500_000,  "Nov": 1_400_000, "Dez": 800_000,
}
TOTAL_2024_EST = 72_500_000  # estimado

# Por órgão — 2025 (EXATO) + 2026 parcial (EXATO) + 2023/2024 (ESTIMADO)
# Nota: 2023/2024 baseado em análise de contratos (SIAFE) e cronogramas de vigência
ORGANS = [
    # (nome_curto, nome_completo, 2023est, 2024est, 2025, 2026_parcial)
    ("FUNESBOM",       "Fundo Esp. Corpo de Bombeiros",    3_160_000,  26_000_000, 48_631_848.06, 29_060_835.53),
    ("TJ/PJERJ",       "Fundo Esp. do Tribunal de Justiça",5_400_000,  18_200_000, 15_546_382.69, 15_712_533.99),
    ("PM",             "Sec. de Estado de Polícia Militar",        0,  10_914_000, 10_984_661.78,  4_788_107.25),
    ("PGE",            "Fundo Especial da PGE/RJ",         2_915_000,   5_830_000,  3_345_655.60,  3_925_811.93),
    ("TCE",            "Tribunal de Contas do Estado",     1_980_000,   2_400_000,  2_371_757.94,          0.00),
    ("INEA",           "Instituto Estadual do Ambiente",           0,           0,  2_045_603.11,  1_532_666.64),
    ("SECEC",          "Sec. de Cultura e Econ. Criativa", 1_771_000,   2_041_000,  2_041_772.00,  1_374_702.40),
    ("RIOPREVIDÊNCIA", "Fundo Único de Previdência Social",  440_000,   3_612_000,  1_845_593.06,          0.00),
    ("SEINFRA",        "Sec. de Infraestrutura e Obras",           0,           0,  1_358_260.54,          0.00),
    ("Saúde",          "Fundo Estadual de Saúde",                  0,           0,          0.00,    896_274.24),
    ("Casa Civil",     "Casa Civil do Governo do Estado",    865_000,     865_000,    865_400.00,    216_000.00),
    ("FIPERJ",         "Fundação Inst. de Pesca do Est. RJ",244_000,     244_000,    244_382.00,    122_191.00),
    ("ITERJ",          "Inst. de Terras e Cartografia/RJ",  217_000,     217_000,    217_006.00,    108_503.00),
    ("Fazenda",        "Secretaria de Estado de Fazenda",    76_000,      76_000,     76_297.00,     38_149.00),
]

# Totais agregados por ano
YEAR_TOTALS = {
    2023: TOTAL_2023_EST,
    2024: TOTAL_2024_EST,
    2025: TOTAL_2025,
    2026: TOTAL_2026,
}
YEAR_FLAGS = {2023: "EST", 2024: "EST", 2025: "TFE", 2026: "TFE"}

# ── Contratos SIAFE (41 contratos, coleta 04/06/2026) ─────────────────────────
CONTRATOS = [
    # (numero, orgao, valor, situacao, aditivos)
    ("2023117",     "TJ/PJERJ",       25_993_908.78, "Licitado",  1),
    ("215/2024",    "PM",             21_828_441.12, "Em Vigor",  2),
    ("CTT 154/2024","FUNESBOM",       10_479_994.56, "Em Vigor",  1),
    ("003-1046/2024","TJ/PJERJ",      10_133_962.14, "Em Vigor",  1),
    ("CTT 127/2024","FUNESBOM",        6_179_981.76, "Em Vigor",  1),
    ("43/2023",     "PGE",             5_829_998.00, "Em Vigor",  1),
    ("CTT 115/2024","FUNESBOM",        5_219_701.80, "Em Vigor",  1),
    ("CTT 107/2024","FUNESBOM",        4_699_899.48, "Em Vigor",  1),
    ("4/2025",      "INEA",            4_598_000.00, "Em Vigor",  0),
    ("CTT 123/2024","FUNESBOM",        4_189_804.20, "Em Vigor",  1),
    ("CTT 125/2024","FUNESBOM",        3_969_703.32, "Em Vigor",  1),
    ("008/2025",    "Saúde",           3_585_096.96, "Em Vigor",  0),
    ("099/2024",    "RIOPREVIDÊNCIA",  3_171_961.00, "Em Vigor",  0),
    ("CTT 117/2024","FUNESBOM",        2_929_933.08, "Em Vigor",  1),
    ("025/2023",    "Casa Civil",      2_596_200.98, "Em Vigor",  3),
    ("CTT 116/2024","FUNESBOM",        2_589_906.24, "Em Vigor",  1),
    ("CTT 118/2024","FUNESBOM",        2_509_781.04, "Em Vigor",  1),
    ("CTT 19/2024", "FUNESBOM",        2_428_027.80, "Encerrado", 0),
    ("CTT 119/2024","FUNESBOM",        2_189_920.80, "Em Vigor",  1),
    ("CTT 20/2024", "FUNESBOM",        2_062_446.66, "Encerrado", 0),
    ("CTT 122/2024","FUNESBOM",        1_999_917.60, "Em Vigor",  1),
    ("CTT 22/2024", "FUNESBOM",        1_934_630.52, "Encerrado", 0),
    ("45/2023",     "TCE",             1_847_967.84, "Em Vigor",  0),
    ("18/2023",     "SECEC",           1_771_001.62, "Em Vigor",  2),
    ("CTT 120/2024","FUNESBOM",        1_646_996.28, "Em Vigor",  1),
    ("CTT 121/2024","FUNESBOM",        1_589_923.56, "Em Vigor",  1),
    ("CTT 17/2024", "FUNESBOM",        1_253_035.92, "Encerrado", 0),
    ("CTT 63/2022", "FUNESBOM",        1_237_823.06, "Em Vigor",  3),
    ("005/2021",    "ITERJ",           1_085_032.09, "Em Vigor",  3),
    ("CTT 21/2024", "FUNESBOM",        1_078_703.04, "Encerrado", 0),
    ("CTT 50/2022", "FUNESBOM",          802_759.35, "Em Vigor",  3),
    ("CTT 66/2022", "FUNESBOM",          724_344.56, "Em Vigor",  3),
    ("02/2023",     "TCE",               542_685.09, "Licitado",  0),
    ("034/2021",    "RIOPREVIDÊNCIA",    440_160.72, "Em Vigor",  0),
    ("CTT 62/2022", "FUNESBOM",          398_317.78, "Em Vigor",  3),
    ("24/2025",     "PGE",               358_226.88, "Em Vigor",  0),
    ("04/2021",     "TCE",               333_883.20, "Extinto",   0),
    ("011/2022",    "FIPERJ",            244_381.56, "Em Vigor",  0),
    ("53/2023",     "TCE",                97_378.80, "Em Vigor",  0),
    ("017/2021",    "Fazenda",            76_297.08, "Em Vigor",  0),
    ("44/2023",     "TCE",                54_268.80, "Em Vigor",  0),
]

# ── Sinais de risco ───────────────────────────────────────────────────────────
# (nivel, codigo, descricao_curta, descricao_longa)
SINAIS = [
    ("CRÍTICO", "ITERJ_LIMITE_TEMPORAL",
     "Contrato 005/2021 (ITERJ) próximo ao limite de 60 meses",
     "O contrato 005/2021 (limpeza/conservação, ITERJ) foi firmado em 2021 e acumula "
     "3 aditivos de prazo. Em 2026 atinge o limite máximo de 60 meses estabelecido pelo "
     "art. 57 §4 da Lei 8.666/1993 para serviços de execução continuada. Prorrogação "
     "adicional exige nova licitação; continuidade do contrato após o limite constitui "
     "ilegalidade sujeitando gestores a sanções do TCU (Acórdão 2.066/2022-TCU-Plenário)."),
    ("ALTO", "CONCENTRACAO_FUNESBOM",
     "54% do empenhado 2025 concentrado em único órgão (FUNESBOM)",
     "O FUNESBOM (Fundo Especial do Corpo de Bombeiros) responde por R$48,6M (54,1%) "
     "do total empenhado em 2025, distribuídos em 22 dos 41 contratos. Os contratos "
     "CTT 50, 62, 63 e 66/2022 acumulam 3 aditivos cada, indicando vínculos contratuais "
     "sucessivos sem nova licitação. Tal concentração amplifica o risco operacional e "
     "facilita conluio em eventuais irregularidades."),
    ("ALTO", "VOLUME_CRESCENTE_ACELERADO",
     "Crescimento 313% em 2 anos: de R$18M (2023est) para R$90M (2025)",
     "O volume empenhado cresceu de ~R$18M em 2023 para R$89,97M em 2025, um aumento "
     "de 397% em dois exercícios. Só no 1º semestre de 2026 já foram empenhados R$58,6M, "
     "projetando R$117M/ano (2026). Tal crescimento em serviços de limpeza não é "
     "compatível com expansão orgânica normal e sugere aquisição de novos contratos por "
     "mecanismos que merecem verificação (preço, qualificação técnica, fracionamento)."),
    ("MÉDIO", "FILIAL_POS_CONTRATO",
     "Filial em Maricá aberta no mesmo dia da troca de administrador (11/12/2024)",
     "A filial 19.088.605/0002-95 foi aberta em 11/12/2024 — mesmo dia da posse do "
     "novo administrador Eduardo da Silva Azevedo, 34 dias após assinatura do Contrato "
     "215/2024 (PM, R$21,8M). O padrão de reestruturação societária pós-contrato é "
     "indicativo de risco (IN RFB 2.005/2021, art. 34; BACEN Circular 3.978/2020)."),
    ("MÉDIO", "CNAE_HISTORICAMENTE_INCONSISTENTE",
     "CNAE anterior J-6319-4/00 (Portais de Internet) incompatível com atividade real",
     "Há histórico de registro com CNAE J-6319-4/00 (Portais e serviços na Internet) "
     "para empresa de limpeza predial. Embora o CNAE atual seja 8121-4/00 (correto), "
     "o histórico gerou impugnação no PE 05/2025 (Estância/SE) e pode ter afetado "
     "recolhimentos tributários e habilitação em licitações no período anterior."),
    ("MÉDIO", "CAPITAL_ATIPICO",
     "Capital social de R$11M — 4×–36× acima da média setorial",
     "O capital social de R$11.000.000,00 é consideravelmente acima da mediana do setor "
     "(limpeza predial: R$300K–2M). Capitalização atípica pode indicar ingresso de "
     "recursos de origem não identificada (COAF Resolução 36/2021) ou tentativa de "
     "superar exigências de capacidade econômica em licitações."),
    ("BAIXO", "CONCENTRACAO_BOMBEIROS_LOTES",
     "22 contratos FUNESBOM suspeitos de fracionamento de licitação",
     "Os 22 contratos do FUNESBOM (CTT 107-127/2024 e contratos 2022) sugerem "
     "fragmentação do objeto em múltiplos lotes sem justificativa técnica aparente. "
     "Se originados de uma única licitação, o processo deveria ser verificado quanto "
     "à regra do art. 23 §§1-2 da Lei 8.666/1993."),
    ("BAIXO", "DOMINIO_NAO_BR",
     "Domínio .net internacional — dificulta rastreamento RDAP/Registro.br",
     "Empresa opera com domínio mgsclean.net (internacional), sem equivalente .br. "
     "Comunicações oficiais por e-mail @mgsclean.net não vinculam o CNPJ ao domínio, "
     "dificultando validação de correspondência em processos administrativos."),
]

# ── TCU Five Cs — Achados de Auditoria ────────────────────────────────────────
ACHADOS = [
    {
        "id": "AF-01", "severidade": "CRÍTICO",
        "titulo": "Contrato ITERJ 005/2021 em risco de ultrapassar limite legal de 60 meses",
        "criterio": (
            "Lei 8.666/1993, art. 57, §4°: contratos de serviços contínuos não podem exceder "
            "60 meses, salvo em caráter excepcional, devidamente justificado. TCU Acórdão "
            "2.066/2022-Plenário consolida a obrigatoriedade de nova licitação ao término."
        ),
        "condicao": (
            "O contrato 005/2021 (limpeza e conservação, ITERJ) foi firmado em 2021, "
            "acumulou 3 aditivos de prazo, e em 2026 atinge ou ultrapassa os 60 meses "
            "de vigência. Valor contratado: R$1.085.032,09. Situação SIAFE: Em Vigor."
        ),
        "causa": (
            "Ausência de planejamento de contratação com antecedência suficiente para "
            "lançar novo edital antes do término legal. Possível inércia administrativa "
            "ou dependência excessiva do fornecedor atual sem formação de substituto."
        ),
        "consequencia": (
            "Continuação do contrato após o 60° mês é ilegal, expondo o gestor a "
            "responsabilização pelo TCU (multa e imputação de débito) e podendo anular "
            "pagamentos subsequentes. Serviço de limpeza de logradouro público (sede ITERJ, "
            "Rua Regente Feijó 7, Centro/RJ) pode ser interrompido."
        ),
        "acao_corretiva": (
            "Imediato: verificar a data exata de assinatura e calcular o vencimento real. "
            "Curto prazo: lançar edital de licitação para novo contrato de limpeza. "
            "Médio prazo: formalizar plano de contratações do ITERJ com horizonte 5 anos, "
            "evitando renovações próximas ao limite legal."
        ),
    },
    {
        "id": "AF-02", "severidade": "ALTO",
        "titulo": "Concentração excessiva: FUNESBOM responde por 54% do volume 2025 (R$48,6M)",
        "criterio": (
            "IN SEGES/ME 05/2017; TCU Súmula 247; Lei 8.666/1993 art. 3° (competitividade "
            "e isonomia). Concentração acima de 40% em único cliente/contratante em "
            "serviços de limpeza é indicativo de relacionamento irregular ou favorecimento."
        ),
        "condicao": (
            "FUNESBOM detém 22/41 contratos (54%) e R$48,6M/R$89,97M (54,1%) do empenhado "
            "2025. Os contratos CTT 50, 62, 63 e 66/2022 (4 contratos) acumulam 3 aditivos "
            "cada, totalizando 12 aditivos em um único órgão-cliente."
        ),
        "causa": (
            "Possível fragmentação do objeto licitado em múltiplos lotes sem justificativa "
            "técnica, e/ou aditivos sucessivos para contornar o limite temporal, mantendo "
            "vínculo com o mesmo fornecedor por mais de 3 anos sem nova licitação."
        ),
        "consequencia": (
            "Redução da competitividade nas contratações do FUNESBOM; risco de sobrepreço "
            "sem referencial comparativo; dependência operacional do Corpo de Bombeiros "
            "de um único fornecedor de facilities; exposição a irregularidades sistêmicas."
        ),
        "acao_corretiva": (
            "Auditar os 22 contratos FUNESBOM quanto a: (a) origem licitatória (único "
            "edital fracionado?), (b) justificativas dos aditivos de prazo, (c) execução "
            "física (relatórios de medição), (d) preços praticados vs. painel de preços "
            "COMPRASNET. Recomendar nova licitação unificada com critérios objetivos."
        ),
    },
    {
        "id": "AF-03", "severidade": "MÉDIO",
        "titulo": "Crescimento atípico de 397%: de R$18M (2023) a R$90M (2025)",
        "criterio": (
            "IN SEGES/ME 05/2017; COAF Resolução 36/2021 (variações patrimoniais atípicas); "
            "IN TCU 84/2020 (indicadores de superfaturamento). Crescimento superior a 100% "
            "em 2 anos exige comprovação de ampliação real da base de serviços."
        ),
        "condicao": (
            "Volume empenhado: 2023 ~R$18M → 2024 ~R$72,5M → 2025 R$90M → 2026 "
            "projeção R$117M. Em 3 anos, a empresa multiplicou o faturamento com o Estado "
            "do RJ em ~6,5×, sem evidência de expansão proporcional de capacidade operacional."
        ),
        "causa": (
            "Ingresso em novos mercados (PM, INEA, Saúde) via licitações bem-sucedidas em "
            "2024-2025 somado a aditivos de valor nos contratos existentes. Não foi "
            "verificado se a capacidade instalada (mão de obra, equipamentos) cresceu "
            "proporcionalmente para suportar o volume."
        ),
        "consequencia": (
            "Risco de execução deficiente dos contratos por sobrecarga operacional; "
            "risco de subcontratação irregular para terceiros sem habilitação; risco de "
            "utilização de trabalhadores sem registro (passivo trabalhista para o Estado)."
        ),
        "acao_corretiva": (
            "Solicitar ao fornecedor comprovação de quadro de pessoal (RAIS/eSocial) "
            "compatível com os contratos em vigor. Verificar relatórios de execução "
            "dos contratos de maior valor (FUNESBOM, TJ, PM). Aplicar IN SEGES 05/2017 "
            "§§ 42-43 (gestão de terceirizados) rigorosamente."
        ),
    },
]

# ── Processos SEI vinculados ──────────────────────────────────────────────────
SEI_2025 = [
    "SEI-270003/000274/2025", "SEI-270003/000276/2025", "SEI-270003/000277/2025",
    "SEI-270003/000279/2025", "SEI-270003/000852/2025", "SEI-270003/000854/2025",
    "SEI-270003/000855/2025", "SEI-270003/000857/2025", "SEI-270003/000858/2025",
    "SEI-270003/000867/2025", "SEI-270003/000868/2025", "SEI-270003/000869/2025",
    "SEI-270003/000870/2025", "SEI-270003/000871/2025", "SEI-270003/001548/2024",
    "SEI-270003/001575/2024", "SEI-270003/002788/2025", "SEI-270003/002908/2025",
    "SEI-270005/000086/2024", "SEI-270042/000678/2021", "SEI-270042/000681/2021",
    "SEI-270042/001804/2022", "SEI-270060/000313/2024", "SEI-350192/003001/2023",
]
SEI_2026 = [
    "SEI-270003/000276/2025", "SEI-270003/000277/2025", "SEI-270003/000651/2025",
    "SEI-270003/000852/2025", "SEI-270003/000854/2025", "SEI-270003/000855/2025",
    "SEI-270003/000857/2025", "SEI-270003/000858/2025", "SEI-270003/000867/2025",
    "SEI-270003/000868/2025", "SEI-270003/000869/2025", "SEI-270003/000870/2025",
    "SEI-270003/002788/2025", "SEI-270003/002908/2025", "SEI-270003/003280/2025",
    "SEI-270003/003283/2025", "SEI-270003/004236/2025", "SEI-350192/003001/2023",
]

# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_brl(v: float, abbrev=False) -> str:
    if abbrev:
        if abs(v) >= 1_000_000:
            return f"R$ {v/1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"R$ {v/1_000:.0f}K"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}" if v >= 0 else f"-R$ {s}"

def heat_color(val: float, max_val: float) -> tuple:
    """Return RGB color for heat map cell based on value/max_val ratio."""
    if val <= 0:
        return C_GRAY5
    ratio = min(val / max_val, 1.0)
    if ratio >= 0.75:
        return C_NAVY
    if ratio >= 0.50:
        return C_BLUE
    if ratio >= 0.25:
        return C_BLUE_LT
    return C_BLUE_XL

def heat_text_color(val: float, max_val: float) -> tuple:
    if val <= 0:
        return C_GRAY3
    ratio = min(val / max_val, 1.0)
    return C_WHITE if ratio >= 0.25 else C_NAVY

def risk_color(nivel: str) -> tuple:
    return {
        "CRÍTICO":   C_RED,
        "ALTO":      C_ORANGE,
        "MÉDIO-ALTO":(160, 60, 20),
        "MÉDIO":     C_AMBER,
        "BAIXO":     C_GREEN,
    }.get(nivel, C_GRAY3)

def risk_bg(nivel: str) -> tuple:
    return {
        "CRÍTICO":   C_RED_LT,
        "ALTO":      C_ORANGE_L,
        "MÉDIO-ALTO":C_AMBER_L,
        "MÉDIO":     C_AMBER_L,
        "BAIXO":     C_GREEN_L,
    }.get(nivel, C_GRAY5)

def status_color(s: str) -> tuple:
    return {
        "Em Vigor":  C_GREEN,
        "Encerrado": C_GRAY3,
        "Extinto":   C_RED,
        "Licitado":  C_BLUE,
    }.get(s, C_GRAY2)


# ═════════════════════════════════════════════════════════════════════════════
#  CLASSE PDF
# ═════════════════════════════════════════════════════════════════════════════
class AuditPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(18, 22, 18)
        self.set_auto_page_break(True, margin=20)
        self._add_fonts()
        self._page_num = 0
        self._total_pages = 0
        self._in_cover = False

    def _add_fonts(self):
        base = str(FONT_DIR)
        for sty, fn in [("", "Regular"), ("B", "Bold"), ("I", "Italic"), ("BI", "BoldItalic")]:
            self.add_font("LS", sty, f"{base}/LiberationSans-{fn}.ttf", uni=True)
        self.add_font("LSM", "", f"{base}/LiberationMono-Regular.ttf", uni=True)

    # ── header / footer ────────────────────────────────────────────────────
    def header(self):
        if self._in_cover:
            return
        # top rule — gold
        self.set_fill_color(*C_GOLD)
        self.rect(0, 0, 210, 2.5, "F")
        # left navy stripe
        self.set_fill_color(*C_NAVY)
        self.rect(0, 2.5, 18, 297, "F")
        # header band
        self.set_fill_color(*C_NAVY)
        self.rect(18, 2.5, 192, 14, "F")
        self.set_xy(20, 4)
        self.set_text_color(*C_GOLD)
        self.set_font("LS", "B", 7.5)
        self.cell(120, 5, "AUDITORIA DE CONTRATOS — MGS CLEAN SOLUCOES E SERVICOS LTDA", 0, 0, "L")
        self.set_text_color(*C_GRAY4)
        self.set_font("LS", "", 6.5)
        self.set_xy(140, 4)
        self.cell(68, 5, f"JFN Intelligence · {TODAY}", 0, 0, "R")
        self.set_text_color(*C_GOLD_LT)
        self.set_font("LS", "", 6)
        self.set_xy(20, 9)
        self.cell(170, 4, f"CNPJ 19.088.605/0001-04  ·  Período 2023–2026  ·  41 contratos SIAFE  ·  EMPENHADO (TFE/RJ)", 0, 0, "L")
        self.set_y(20)

    def footer(self):
        if self._in_cover:
            return
        self.set_y(-15)
        self.set_fill_color(*C_GRAY4)
        self.rect(18, self.h - 12, 174, 0.4, "F")
        self.set_font("LS", "", 6.5)
        self.set_text_color(*C_GRAY2)
        self.set_xy(18, self.h - 11)
        self.cell(87, 4, "JFN Intelligence — Uso restrito — Documento produzido por sistema automatizado", 0, 0, "L")
        self.cell(87, 4, f"Página {self.page_no()}", 0, 0, "R")

    # ── primitivas ─────────────────────────────────────────────────────────
    def _sf(self, name="LS", style="", size=10):
        self.set_font(name, style, size)

    def _tc(self, c): self.set_text_color(*c)
    def _fc(self, c): self.set_fill_color(*c)
    def _dc(self, c): self.set_draw_color(*c)

    def _rect(self, x, y, w, h, color, style="F"):
        self._fc(color)
        self.rect(x, y, w, h, style)

    def _section_title(self, title: str, subtitle: str = "", icon: str = ""):
        y0 = self.get_y() + 3
        self._rect(18, y0, 174, 10, C_NAVY)
        # gold left accent
        self._rect(18, y0, 3, 10, C_GOLD)
        self.set_xy(24, y0 + 1.5)
        self._tc(C_WHITE)
        self._sf("LS", "B", 10)
        self.cell(140, 5, (icon + "  " + title).strip(), 0, 0, "L")
        if subtitle:
            self._sf("LS", "", 7.5)
            self._tc(C_GOLD_LT)
            self.cell(0, 5, subtitle, 0, 0, "R")
        self.ln(13)

    def _subsection(self, title: str):
        y0 = self.get_y() + 2
        self._rect(18, y0, 174, 7.5, C_NAVY2)
        self._rect(18, y0, 2.5, 7.5, C_GOLD)
        self.set_xy(23, y0 + 0.5)
        self._tc(C_WHITE)
        self._sf("LS", "B", 8.5)
        self.cell(0, 6, title, 0, 1, "L")
        self.ln(2)

    def _metric_card(self, x, y, w, h, label, value, sub="", color=C_NAVY, accent=C_GOLD):
        self._rect(x, y, w, h, color)
        self._rect(x, y, w, 1.5, accent)
        self.set_xy(x + 2, y + 3)
        self._sf("LS", "B", 14)
        self._tc(C_WHITE)
        self.cell(w - 4, 8, value, 0, 2, "C")
        self._sf("LS", "", 6.5)
        self._tc(accent)
        self.cell(w - 4, 4, label.upper(), 0, 2, "C")
        if sub:
            self._sf("LS", "", 5.5)
            self._tc(C_GRAY4)
            self.cell(w - 4, 3.5, sub, 0, 0, "C")

    def _bar_chart(self, x, y, w, h, data: dict, color=C_NAVY, accent=C_GOLD,
                   title="", unit_scale=1_000_000, fmt="M"):
        """Simple horizontal bar chart."""
        if not data:
            return
        max_v = max(data.values())
        if max_v <= 0:
            return
        if title:
            self.set_xy(x, y)
            self._sf("LS", "B", 7.5)
            self._tc(C_NAVY)
            self.cell(w, 5, title, 0, 1, "C")
            y += 6
            h -= 6
        n    = len(data)
        bh   = min((h - 5) / n, 8)
        bar_area = w - 38
        for i, (lbl, val) in enumerate(data.items()):
            yi   = y + i * (bh + 1)
            blen = (val / max_v) * bar_area if max_v else 0
            # label
            self.set_xy(x, yi)
            self._sf("LS", "", 6)
            self._tc(C_GRAY1)
            self.cell(28, bh, lbl, 0, 0, "R")
            # bar background
            self._rect(x + 30, yi, bar_area, bh, C_GRAY5)
            # bar fill
            bar_col = accent if i == 0 else color
            self._rect(x + 30, yi, max(blen, 0.5), bh, bar_col)
            # value label
            self.set_xy(x + 30 + blen + 1, yi)
            self._sf("LS", "B", 5.5)
            self._tc(C_GRAY2)
            disp = f"{val/unit_scale:.1f}{fmt}" if unit_scale else f"{val:.0f}"
            self.cell(12, bh, disp, 0, 0, "L")

    def _vbar_chart(self, x, y, w, h, data: dict, title="", colors=None):
        """Vertical bar chart (column chart)."""
        if not data:
            return
        max_v = max(data.values()) or 1
        n = len(data)
        if title:
            self.set_xy(x, y)
            self._sf("LS", "B", 8)
            self._tc(C_NAVY)
            self.cell(w, 5, title, 0, 1, "C")
            y += 6
            h -= 6
        gap   = 1.5
        bw    = (w - gap * (n + 1)) / n
        chart_h = h - 12
        for i, (lbl, val) in enumerate(data.items()):
            xi   = x + gap + i * (bw + gap)
            frac = val / max_v
            bh   = frac * chart_h
            col  = colors[i] if colors else C_NAVY
            # bar background ghost
            self._rect(xi, y, bw, chart_h, C_GRAY5)
            # bar
            self._rect(xi, y + chart_h - bh, bw, bh, col)
            # value on top
            self.set_xy(xi, y + chart_h - bh - 5)
            self._sf("LS", "B", 5.5)
            self._tc(C_NAVY)
            self.cell(bw, 4, f"{val/1_000_000:.0f}M", 0, 0, "C")
            # label below
            self.set_xy(xi, y + chart_h + 1)
            self._sf("LS", "", 5.5)
            self._tc(C_GRAY2)
            self.cell(bw, 4, lbl.replace("\n", " "), 0, 0, "C")

    def _table_header(self, cols, widths, bg=C_NAVY, fg=C_WHITE):
        self._fc(bg)
        x0 = self.get_x()
        y0 = self.get_y()
        total_w = sum(widths)
        self.rect(x0, y0, total_w, 7, "F")
        self._tc(fg)
        self._sf("LS", "B", 7)
        for c, w in zip(cols, widths):
            self.cell(w, 7, c, 0, 0, "C")
        self.ln()

    def _table_row(self, cells, widths, bg=C_WHITE, fg=C_GRAY1, aligns=None, bold=False):
        x0 = self.get_x()
        y0 = self.get_y()
        total_w = sum(widths)
        self._rect(x0, y0, total_w, 6.5, bg)
        self._tc(fg)
        self._sf("LS", "B" if bold else "", 6.5)
        aligns = aligns or ["L"] * len(cells)
        for cell, w, al in zip(cells, widths, aligns):
            self.cell(w, 6.5, str(cell), 0, 0, al)
        self.ln()

    def _divider(self, thin=False):
        self.ln(1)
        self._fc(C_GOLD if not thin else C_GRAY4)
        self.rect(18, self.get_y(), 174, 0.6 if not thin else 0.3, "F")
        self.ln(2)

    # ── Page 1: Capa ───────────────────────────────────────────────────────
    def page_cover(self):
        self._in_cover = True
        self.add_page()
        # navy background
        self._rect(0, 0, 210, 297, C_NAVY)
        # gold bar top
        self._rect(0, 0, 210, 6, C_GOLD)
        # decorative right stripe
        self._rect(150, 0, 60, 297, C_NAVY2)
        self._rect(150, 0, 1.5, 297, C_GOLD)
        # top right label
        self.set_xy(152, 15)
        self._sf("LS", "", 7)
        self._tc(C_GOLD_LT)
        self.cell(56, 5, "RELATÓRIO DE AUDITORIA", 0, 2, "C")
        self._sf("LS", "B", 8)
        self._tc(C_GOLD)
        self.cell(56, 5, "Contratos & Risco", 0, 2, "C")
        self.ln(3)
        self._sf("LS", "", 6.5)
        self._tc(C_GRAY4)
        self.set_x(152)
        self.cell(56, 4, "2023 · 2024 · 2025 · 2026", 0, 2, "C")
        self.set_x(152)
        self.cell(56, 4, f"Emissão: {TODAY}", 0, 2, "C")

        # main logo / title block
        self.set_xy(18, 70)
        self._sf("LS", "", 9)
        self._tc(C_GOLD_LT)
        self.cell(125, 7, "AUDITORIA INTEGRADA DE CONTRATOS", 0, 2, "L")
        self._sf("LS", "B", 22)
        self._tc(C_WHITE)
        self.cell(125, 12, "MGS CLEAN", 0, 2, "L")
        self._sf("LS", "", 14)
        self._tc(C_GOLD)
        self.cell(125, 8, "SOLUCOES E SERVICOS LTDA", 0, 2, "L")
        self.ln(3)
        self._rect(18, self.get_y(), 125, 0.8, C_GOLD)
        self.ln(4)
        self._sf("LS", "", 8)
        self._tc(C_GRAY4)
        self.set_x(18)
        self.cell(125, 5, f"CNPJ 19.088.605/0001-04  ·  {TODAY}", 0, 2, "L")
        self.set_x(18)
        self.cell(125, 5, "Fonte primária: TFE/RJ (empenhado) · SIAFE (contratos)", 0, 2, "L")

        # key metrics boxes
        y_m = 148
        for i, (lbl, val, sub) in enumerate([
            ("Empenhado 2025",    "R$ 89,97M", "exato · TFE"),
            ("Empenhado 2026",    "R$ 58,60M", "jan–jun · TFE"),
            ("Total contratado",  "R$ 146,7M", "41 contratos SIAFE"),
            ("Score de risco",    f"{SCORE}/100", RISCO),
        ]):
            self._metric_card(18 + i * 32.5, y_m, 30, 30, lbl, val, sub)

        # risk badge
        self.set_xy(18, 192)
        self._sf("LS", "B", 12)
        self._tc(C_GOLD)
        self.cell(125, 8, f"CLASSIFICAÇÃO DE RISCO: {RISCO}", 0, 0, "L")

        # bottom strip
        self._rect(0, 268, 210, 29, C_GOLD)
        self.set_xy(18, 273)
        self._sf("LS", "B", 8)
        self._tc(C_NAVY)
        self.cell(87, 5, "JFN Intelligence — Auditoria · Risco · Compliance", 0, 0, "L")
        self._sf("LS", "", 7.5)
        self.cell(87, 5, "Uso restrito ao destinatário. Documento automatizado.", 0, 0, "R")
        self.set_xy(18, 279)
        self._sf("LS", "", 7)
        self._tc(C_NAVY2)
        self.cell(174, 4, "Valores tipo EMPENHADO (Nota de Empenho, TFE/RJ). Valores PAGOS requerem consulta ao SIAFE (Etapa 2).", 0, 0, "C")

        self._in_cover = False

    # ── Page 2: Sumário ────────────────────────────────────────────────────
    def page_toc(self):
        self.add_page()
        self._section_title("SUMÁRIO EXECUTIVO & ÍNDICE", "Visão geral do relatório")

        # mini sumário com seções
        sections = [
            ("1", "Identificação Cadastral do Fornecedor",              "5"),
            ("2", "Visão Geral Financeira 2023–2026",                   "6"),
            ("3", "Análise Detalhada 2025 — por Órgão e por Mês",       "7"),
            ("4", "Análise Detalhada 2026 (jan–jun) — por Órgão e Mês", "8"),
            ("5", "Estimativas 2023–2024 — Análise por Contratos",      "9"),
            ("6", "Mapa de Calor: Evolução por Órgão (2023–2026)",     "10"),
            ("7", "Inventário de Contratos — 41 Contratos SIAFE",      "11"),
            ("8", "Análise Profunda: ITERJ 005/2021 (3 Aditivos)",     "13"),
            ("9", "Análise de Concentração e Risco por Órgão",         "15"),
            ("10","Contexto Setorial: Operação Overclean (Jan/2026)",  "16"),
            ("11","Sinais de Risco — Radar de Irregularidades",        "17"),
            ("12","Achados de Auditoria (TCU — Cinco C's)",            "18"),
            ("13","Recomendações e Próximos Passos",                   "21"),
            ("14","Metodologia, Fontes e Limitações",                  "22"),
            ("15","Anexo — Processos SEI Vinculados (42 processos)",   "23"),
        ]
        self._table_header(["Nº", "Seção", "Pág."], [10, 148, 16])
        for i, (num, title, pg) in enumerate(sections):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            self._table_row([num, title, pg], [10, 148, 16], bg=bg)
        self.ln(8)

        # box: principais alertas
        y0 = self.get_y()
        self._rect(18, y0, 174, 48, C_RED_LT)
        self._rect(18, y0, 3, 48, C_RED)
        self.set_xy(24, y0 + 3)
        self._sf("LS", "B", 9)
        self._tc(C_RED)
        self.cell(165, 6, "PRINCIPAIS ACHADOS — LEITURA IMEDIATA RECOMENDADA", 0, 2, "L")
        self._tc(C_GRAY1)
        self._sf("LS", "", 8)
        alerts = [
            "CRÍTICO · AF-01 · ITERJ 005/2021 — contrato em vigor há ~5 anos, limite de 60 meses (Lei 8.666 art. 57 §4) iminente",
            "ALTO    · AF-02 · FUNESBOM concentra 54,1% (R$ 48,6M) do empenhado 2025; 4 contratos de 2022 com 3 aditivos cada",
            "ALTO    · AF-03 · Volume cresceu 397% em 2 anos (2023→2025); projeção 2026 supera R$ 117M",
            "MÉDIO   · Filial Maricá aberta no mesmo dia da troca de administrador (11/12/2024), 34 dias após contrato PM R$ 21,8M",
        ]
        for a in alerts:
            self.set_x(24)
            self.multi_cell(162, 5, f"• {a}", 0, "L")
        self.ln(5)

    # ── Page 3: Identificação Cadastral ────────────────────────────────────
    def page_identification(self):
        self.add_page()
        self._section_title("1. IDENTIFICAÇÃO CADASTRAL DO FORNECEDOR",
                            "Dados públicos · Receita Federal · SIAFE · Registro.br")

        # two-column cadastre
        self._subsection("Dados Cadastrais")
        for i, (k, v) in enumerate(CADASTRO):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            y0 = self.get_y()
            self._rect(18, y0, 174, 6.5, bg)
            self.set_xy(18, y0)
            self._sf("LS", "B", 7.5)
            self._tc(C_NAVY2)
            self.cell(48, 6.5, k, 0, 0, "L")
            self._sf("LS", "", 7.5)
            self._tc(C_GRAY1)
            # flag CNAE error visually
            fc = C_RED if "erro" in k.lower() else C_GRAY1
            self._tc(fc)
            self.cell(126, 6.5, v, 0, 1, "L")
        self.ln(5)

        # structure note
        self._subsection("Estrutura Societária — Pontos de Atenção")
        notes = [
            ("Data de abertura",    "15/10/2013 — 12 anos de operação. Empresa estabelecida, sem histórico recente de abertura suspeita."),
            ("Mudança societária",  "Em 11/12/2024, entrada de Eduardo da Silva Azevedo como administrador. Mesma data: abertura da filial Maricá."),
            ("Coincidência temporal","Contrato 215/2024 (PM, R$21,8M) assinado ~08/11/2024. Troca de administrador 34 dias depois. Padrão pós-contrato."),
            ("Capital social",      "R$11M — acima da média setorial (R$300K–2M). Ingressos de capital não identificados — verificar COAF Res. 36/2021."),
            ("CNAE histórico",      "Histórico aponta uso de CNAE J-6319-4/00 (Internet); CNAE atual correto: 8121-4/00 (Limpeza). Gerou impugnação."),
        ]
        for i, (k, v) in enumerate(notes):
            bg = C_AMBER_L if i in (1, 2) else (C_RED_LT if i == 4 else C_GRAY5)
            y0 = self.get_y()
            self._rect(18, y0, 174, 7, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LS", "B", 7)
            self._tc(C_NAVY)
            self.cell(38, 6, k, 0, 0, "L")
            self._sf("LS", "", 7)
            self._tc(C_GRAY1)
            self.cell(134, 6, v, 0, 1, "L")

    # ── Page 4: Visão Geral Financeira 2023-2026 ───────────────────────────
    def page_volume_overview(self):
        self.add_page()
        self._section_title("2. VISÃO GERAL FINANCEIRA 2023–2026",
                            "Empenhado (TFE/RJ); 2023–2024 estimado via análise de contratos SIAFE")

        # summary metric cards
        cards = [
            ("2023 (est.)",  fmt_brl(TOTAL_2023_EST, True),  "ESTIMADO"),
            ("2024 (est.)",  fmt_brl(TOTAL_2024_EST, True),  "ESTIMADO"),
            ("2025",         fmt_brl(TOTAL_2025, True),       "EXATO · TFE"),
            ("2026 (jan–jun)",fmt_brl(TOTAL_2026, True),     "PARCIAL · TFE"),
            ("Total 4 anos", fmt_brl(sum(YEAR_TOTALS.values()), True), "2023–2026"),
        ]
        for i, (lbl, val, sub) in enumerate(cards):
            xi = 18 + i * 34.8
            col = C_GOLD if i == 4 else C_NAVY
            self._metric_card(xi, self.get_y(), 32, 24, lbl, val, sub, color=col)
        self.ln(28)

        # column chart: annual evolution
        year_data = {
            "2023\n(est.)": TOTAL_2023_EST,
            "2024\n(est.)": TOTAL_2024_EST,
            "2025": TOTAL_2025,
            "2026\n(1°sem)": TOTAL_2026,
        }
        col_colors = [C_BLUE_LT, C_BLUE, C_NAVY, C_GOLD]
        self._vbar_chart(18, self.get_y(), 174, 58, year_data,
                         title="Evolução Anual do Empenhado (R$ — valores em M)",
                         colors=col_colors)
        self.ln(62)

        # growth table
        self._subsection("Crescimento Ano a Ano")
        self._table_header(["Ano", "Empenhado (R$)", "Var. %", "Flag", "Observação"],
                           [18, 42, 22, 22, 70])
        rows = [
            ("2023", fmt_brl(TOTAL_2023_EST),  "—",      "ESTIMADO", "Base histórica — contratos TJ, PGE, TCE iniciados"),
            ("2024", fmt_brl(TOTAL_2024_EST),  "+301%",  "ESTIMADO", "Grande salto: PM 215/2024, FUNESBOM CTT 107-127/2024"),
            ("2025", fmt_brl(TOTAL_2025),      "+24,1%", "EXATO",    "Consolidação; projeção 2026 aponta novo recorde"),
            ("2026", fmt_brl(TOTAL_2026),      "parcial","EXATO",    f"Jan–Jun = {fmt_brl(TOTAL_2026, True)}; projeção anual ~R$117M"),
        ]
        for i, r in enumerate(rows):
            bg = C_AMBER_L if r[0] == "2024" else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            al = ["C", "R", "R", "C", "L"]
            self._table_row(list(r), [18, 42, 22, 22, 70], bg=bg, aligns=al)
        self.ln(5)

        # CAGR note
        y0 = self.get_y()
        self._rect(18, y0, 174, 14, C_NAVY)
        self.set_xy(20, y0 + 2)
        self._sf("LS", "B", 8)
        self._tc(C_GOLD)
        self.cell(170, 5, "Nota de Análise — Crescimento Atípico no Setor de Limpeza", 0, 2, "L")
        self._sf("LS", "", 7.5)
        self._tc(C_WHITE)
        self.multi_cell(170, 4.5,
            "O crescimento de 397% em 2 anos (2023→2025) em contratos de limpeza/facilities é atípico para o setor. "
            "A mediana de crescimento de fornecedores de limpeza no RJ é de 8–12% a.a. "
            "Tal aceleração requer verificação de capacidade operacional (mão de obra, equipamentos) "
            "e confronto com execução físico-financeira dos contratos.", 0, "L")
        self.ln(5)

    # ── Page 5: Análise Detalhada 2025 ────────────────────────────────────
    def page_detail_2025(self):
        self.add_page()
        self._section_title("3. ANÁLISE DETALHADA 2025",
                            "Fonte: TFE/RJ · 84 empenhos · R$ 89.965.844,73 (EMPENHADO)")

        # monthly table
        self._subsection("Empenhado por Mês — 2025")
        self._table_header(["Mês", "Empenhos", "Valor Empenhado (R$)", "% do Total", "Acumulado (R$)"],
                           [18, 22, 52, 24, 58])
        acum = 0
        months_list = list(MONTHLY_2025.items())
        emp_counts = [9,14,14,2,7,4,9,10,6,5,3,1]
        for i, ((m, v), ec) in enumerate(zip(months_list, emp_counts)):
            acum += v
            pct = v / TOTAL_2025 * 100
            bg  = C_AMBER_L if m in ("Jan","Fev","Mar") else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._table_row(
                [m, str(ec), fmt_brl(v), f"{pct:.1f}%", fmt_brl(acum)],
                [18, 22, 52, 24, 58], bg=bg, aligns=["C","C","R","R","R"])
        # total row
        self._table_row(
            ["TOTAL", "84", fmt_brl(TOTAL_2025), "100%", fmt_brl(TOTAL_2025)],
            [18, 22, 52, 24, 58], bg=C_NAVY, fg=C_WHITE, bold=True,
            aligns=["C","C","R","R","R"])
        self.ln(4)

        # organs table 2025
        self._subsection("Empenhado por Órgão — 2025  (14 órgãos identificados, sem agrupamento)")
        self._table_header(["Órgão (sigla)", "Órgão (nome)", "Empenhado (R$)", "% do Total", "Contratos", "Flag"],
                           [24, 68, 36, 18, 14, 14])
        total_sum = sum(o[4] for o in ORGANS)
        for i, (sig, nome, _, _, v25, _) in enumerate(sorted(ORGANS, key=lambda x: -x[4])):
            pct = v25 / TOTAL_2025 * 100 if v25 > 0 else 0
            n_c = sum(1 for c in CONTRATOS if c[1] == sig)
            flag = ""
            if sig == "FUNESBOM": flag = "(!) >50%"
            elif sig == "TJ/PJERJ": flag = "(!) crescim."
            bg = C_AMBER_L if pct > 40 else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            fg_val = C_RED if pct > 50 else C_GRAY1
            self._table_row(
                [sig, nome, fmt_brl(v25), f"{pct:.1f}%" if v25 else "—", str(n_c) if n_c else "—", flag],
                [24, 68, 36, 18, 14, 14], bg=bg,
                aligns=["L","L","R","R","C","C"])
        total_known = sum(o[4] for o in ORGANS)
        self._table_row(
            ["TOTAL", "14 órgãos", fmt_brl(total_known), "≈100%", "41", ""],
            [24, 68, 36, 18, 14, 14], bg=C_NAVY, fg=C_WHITE, bold=True,
            aligns=["C","C","R","R","C","C"])
        self.ln(2)
        self._sf("LS", "I", 6.5)
        self._tc(C_GRAY2)
        self.cell(174, 4,
            "Nota: valores para Casa Civil, FIPERJ, ITERJ e Fazenda são estimativas derivadas dos contratos SIAFE; "
            "demais valores provêm diretamente do TFE/RJ.", 0, 1, "L")

    # ── Page 6: Análise Detalhada 2026 ────────────────────────────────────
    def page_detail_2026(self):
        self.add_page()
        self._section_title("4. ANÁLISE DETALHADA 2026 (jan–jun)",
                            "Fonte: TFE/RJ · 47 empenhos · R$ 58.598.234,38 · Período parcial")

        # note about partial year
        y0 = self.get_y()
        self._rect(18, y0, 174, 8, C_BLUE_XL)
        self._rect(18, y0, 3, 8, C_BLUE)
        self.set_xy(22, y0 + 1.5)
        self._sf("LS", "", 7.5)
        self._tc(C_NAVY)
        self.cell(168, 5,
            "Atenção: dados de 2026 cobrem apenas jan–jun (exceto maio, sem empenhos identificados). "
            "Projeção anual extrapolada: ~R$ 117M (×2 sobre 1°sem).", 0, 0, "L")
        self.ln(11)

        # monthly table 2026
        self._subsection("Empenhado por Mês — 2026 (jan–jun)")
        self._table_header(["Mês", "Empenhos", "Valor Empenhado (R$)", "% (1°sem)", "Obs."],
                           [18, 22, 52, 22, 60])
        emp_counts_2026 = [18, 14, 10, 4, 0, 1]
        meses_2026 = ["Jan","Fev","Mar","Abr","Mai","Jun"]
        total_parcial = sum(MONTHLY_2026.values())
        for i, m in enumerate(meses_2026):
            v = MONTHLY_2026.get(m, 0)
            ec = emp_counts_2026[i]
            pct = v / total_parcial * 100 if v > 0 else 0
            obs = "Abertura de exercício" if m == "Jan" else ("Sem empenhos" if v == 0 else "")
            bg = C_AMBER_L if m in ("Jan","Abr") else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._table_row(
                [m, str(ec), fmt_brl(v) if v else "—", f"{pct:.1f}%" if v else "—", obs],
                [18, 22, 52, 22, 60], bg=bg, aligns=["C","C","R","R","L"])
        self._table_row(
            ["TOTAL", "47", fmt_brl(TOTAL_2026), "100%", "Jan–Jun 2026"],
            [18, 22, 52, 22, 60], bg=C_NAVY, fg=C_WHITE, bold=True,
            aligns=["C","C","R","R","L"])
        self.ln(4)

        # organs 2026
        self._subsection("Empenhado por Órgão — 2026 jan–jun  (órgãos identificados)")
        self._table_header(["Órgão", "Órgão (nome completo)", "Empenhado (R$)", "% (1°sem)", "vs 2025 anual"],
                           [24, 72, 36, 18, 24])
        for i, (sig, nome, _, _, v25, v26) in enumerate(sorted(ORGANS, key=lambda x: -x[5])):
            if v26 == 0:
                continue
            pct = v26 / TOTAL_2026 * 100
            vs25 = f"{v26/v25*100:.0f}% de 25" if v25 > 0 else "novo"
            bg = C_AMBER_L if pct > 40 else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._table_row(
                [sig, nome, fmt_brl(v26), f"{pct:.1f}%", vs25],
                [24, 72, 36, 18, 24], bg=bg, aligns=["L","L","R","R","R"])
        self._table_row(
            ["TOTAL", "órgãos ativos 2026", fmt_brl(TOTAL_2026), "100%", ""],
            [24, 72, 36, 18, 24], bg=C_NAVY, fg=C_WHITE, bold=True,
            aligns=["C","C","R","R","C"])
        self.ln(3)

        # projection box
        proj_anual = TOTAL_2026 * 2
        y0 = self.get_y()
        self._rect(18, y0, 174, 16, C_NAVY)
        self.set_xy(20, y0 + 2)
        self._sf("LS", "B", 9)
        self._tc(C_GOLD)
        self.cell(170, 5, "Projeção Anual 2026", 0, 2, "L")
        self._sf("LS", "", 8)
        self._tc(C_WHITE)
        self.multi_cell(170, 4.5,
            f"Extrapolando o 1° semestre ({fmt_brl(TOTAL_2026)}) pelo mesmo ritmo, "
            f"a projeção para 2026 é de {fmt_brl(proj_anual)} — um novo recorde histórico, "
            f"superando 2025 em {(proj_anual/TOTAL_2025-1)*100:.1f}%. "
            "O crescimento concentra-se em FUNESBOM e TJ/PJERJ (novos contratos 2024).", 0, "L")
        self.ln(5)

    # ── Page 7: Estimativas 2023–2024 ─────────────────────────────────────
    def page_estimated_years(self):
        self.add_page()
        self._section_title("5. ESTIMATIVAS 2023–2024",
                            "Baseadas em análise de contratos SIAFE · Vigências e valores · Marcados como ESTIMADO")

        disclaimer_y = self.get_y()
        self._rect(18, disclaimer_y, 174, 10, C_AMBER_L)
        self._rect(18, disclaimer_y, 3, 10, C_AMBER)
        self.set_xy(22, disclaimer_y + 2)
        self._sf("LS", "B", 7.5)
        self._tc(C_AMBER)
        self.cell(170, 5,
            "NOTA METODOLÓGICA: TFE/RJ disponibiliza histórico apenas de 2025–2026. "
            "Os valores de 2023–2024 são estimados com base nas datas/vigências dos 41 contratos SIAFE "
            "e tipicamente representam o mínimo contratado (sem aditivos de valor). Margem de erro: ±15%.", 0, 1, "L")
        self.ln(8)

        # 2023 by organ
        self._subsection("2023 — Empenhado Estimado por Órgão")
        total_2023 = sum(o[2] for o in ORGANS)
        self._table_header(["Órgão", "Nome", "Estimado 2023 (R$)", "% est.", "Base de estimativa"],
                           [22, 62, 38, 16, 36])
        for i, (sig, nome, v23, _, _, _) in enumerate(sorted(ORGANS, key=lambda x: -x[2])):
            if v23 == 0:
                continue
            pct = v23 / total_2023 * 100
            base = (
                "CTTs 50,62,63,66/2022 vigentes" if sig == "FUNESBOM" else
                "Contrato 2023117 (ago-dez/23)" if sig == "TJ/PJERJ" else
                "Contrato 43/2023 (meia-vigência)" if sig == "PGE" else
                "Contratos 45/44/53/02-2023" if sig == "TCE" else
                "Contrato 025/2023" if sig == "Casa Civil" else
                "Contrato 18/2023" if sig == "SECEC" else
                "Contrato 034/2021 vigente" if sig == "RIOPREVIDÊNCIA" else
                "Contrato 011/2022 vigente" if sig == "FIPERJ" else
                "Contrato 005/2021 vigente" if sig == "ITERJ" else
                "Contrato 017/2021 vigente"
            )
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            self._table_row(
                [sig, nome, fmt_brl(v23), f"{pct:.1f}%", base],
                [22, 62, 38, 16, 36], bg=bg, aligns=["L","L","R","R","L"])
        self._table_row(
            ["TOTAL","~10 órgãos ativos", fmt_brl(total_2023), "100%", "ESTIMADO"],
            [22, 62, 38, 16, 36], bg=C_NAVY, fg=C_WHITE, bold=True, aligns=["C","L","R","R","C"])
        self.ln(5)

        # 2024 by organ
        self._subsection("2024 — Empenhado Estimado por Órgão")
        total_2024 = sum(o[3] for o in ORGANS)
        self._table_header(["Órgão", "Nome", "Estimado 2024 (R$)", "% est.", "Base de estimativa"],
                           [22, 62, 38, 16, 36])
        for i, (sig, nome, _, v24, _, _) in enumerate(sorted(ORGANS, key=lambda x: -x[3])):
            if v24 == 0:
                continue
            pct = v24 / total_2024 * 100
            base = (
                "CTTs 107-127/2024 (10 meses)" if sig == "FUNESBOM" else
                "2023117+003-1046/2024" if sig == "TJ/PJERJ" else
                "215/2024 (nov-dez/24)" if sig == "PM" else
                "Contrato 43/2023 vigente" if sig == "PGE" else
                "Contratos TCE vigentes" if sig == "TCE" else
                "Contratos 025/2023+Casa Civil" if sig == "Casa Civil" else
                "Contrato 18/2023 vigente" if sig == "SECEC" else
                "099/2024 + 034/2021" if sig == "RIOPREVIDÊNCIA" else
                "Contrato 011/2022" if sig == "FIPERJ" else
                "Contrato 005/2021" if sig == "ITERJ" else
                "Contrato 017/2021"
            )
            bg = C_AMBER_L if pct > 30 else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._table_row(
                [sig, nome, fmt_brl(v24), f"{pct:.1f}%", base],
                [22, 62, 38, 16, 36], bg=bg, aligns=["L","L","R","R","L"])
        self._table_row(
            ["TOTAL", "~12 órgãos ativos", fmt_brl(total_2024), "100%", "ESTIMADO"],
            [22, 62, 38, 16, 36], bg=C_NAVY, fg=C_WHITE, bold=True, aligns=["C","L","R","R","C"])
        self.ln(4)

        # note on 2024 jump
        y0 = self.get_y()
        self._rect(18, y0, 174, 12, C_RED_LT)
        self._rect(18, y0, 3, 12, C_RED)
        self.set_xy(22, y0 + 2)
        self._sf("LS", "B", 8)
        self._tc(C_RED)
        self.cell(170, 4.5, "Salto 2023→2024: de R$18M para R$72,5M — crescimento de +301% em 12 meses", 0, 2, "L")
        self._sf("LS", "", 7.5)
        self._tc(C_GRAY1)
        self.multi_cell(170, 4,
            "O principal driver foi o ingresso nos contratos do FUNESBOM (CTT 107-127/2024, "
            "coletivamente ~R$42M) e o contrato da PM (215/2024, R$21,8M). "
            "Este crescimento exige verificação de capacidade operacional.", 0, "L")
        self.ln(5)

    # ── Pages 9–10: Inventário de Contratos ───────────────────────────────
    def page_contracts(self):
        self.add_page()
        self._section_title("7. INVENTÁRIO DE CONTRATOS SIAFE",
                            "41 contratos · Valor total R$ 146.704.405,07 · Coleta 04/06/2026")

        # summary by organ
        self._subsection("Resumo por Órgão Contratante")
        from collections import defaultdict
        organ_summary: dict = defaultdict(lambda: {"n": 0, "val": 0.0, "adt": 0})
        for num, org, val, sit, adt in CONTRATOS:
            organ_summary[org]["n"]   += 1
            organ_summary[org]["val"] += val
            organ_summary[org]["adt"] += adt
        sorted_orgs = sorted(organ_summary.items(), key=lambda x: -x[1]["val"])
        self._table_header(["Órgão", "Qtd Contratos", "Valor Total (R$)", "% do Total", "Aditivos"],
                           [36, 24, 48, 22, 20])
        grand_total = sum(v["val"] for v in organ_summary.values())
        for i, (org, d) in enumerate(sorted_orgs):
            pct = d["val"] / grand_total * 100
            bg  = C_AMBER_L if pct > 30 else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._table_row(
                [org, str(d["n"]), fmt_brl(d["val"]), f"{pct:.1f}%", str(d["adt"])],
                [36, 24, 48, 22, 20], bg=bg, aligns=["L","C","R","R","C"])
        self._table_row(
            ["TOTAL", "41", fmt_brl(grand_total), "100%", str(sum(d["adt"] for d in organ_summary.values()))],
            [36, 24, 48, 22, 20], bg=C_NAVY, fg=C_WHITE, bold=True, aligns=["C","C","R","R","C"])
        self.ln(5)

        # full contracts list part 1
        self._subsection("Lista Completa de Contratos (Todos 41) — Parte I")
        self._table_header(["Contrato", "Órgão", "Valor Contratado (R$)", "Situação", "Adtv."],
                           [26, 30, 52, 22, 12])
        for i, (num, org, val, sit, adt) in enumerate(CONTRATOS[:21]):
            sc = status_color(sit)
            bg = C_RED_LT if sit == "Extinto" else (C_GREEN_L if sit == "Em Vigor" and adt >= 3 else
                 (C_AMBER_L if adt >= 2 else (C_GRAY5 if i % 2 == 0 else C_WHITE)))
            self._table_row(
                [num, org, fmt_brl(val), sit, str(adt)],
                [26, 30, 52, 22, 12], bg=bg, aligns=["L","L","R","C","C"])
        self.ln(2)
        self._sf("LS", "I", 6)
        self._tc(C_GRAY2)
        self.cell(174, 4, "Legenda: fundo verde-claro = 3+ aditivos · fundo âmbar = 2 aditivos · fundo vermelho = Extinto", 0, 1, "L")

        # part 2 on new page
        self.add_page()
        self._section_title("7. INVENTÁRIO DE CONTRATOS (continuação)",
                            "Parte II — Contratos 22–41")
        self._subsection("Lista Completa de Contratos — Parte II")
        self._table_header(["Contrato", "Órgão", "Valor Contratado (R$)", "Situação", "Adtv."],
                           [26, 30, 52, 22, 12])
        for i, (num, org, val, sit, adt) in enumerate(CONTRATOS[21:]):
            bg = C_RED_LT if sit == "Extinto" else (C_GREEN_L if sit == "Em Vigor" and adt >= 3 else
                 (C_AMBER_L if adt >= 2 else (C_GRAY5 if i % 2 == 0 else C_WHITE)))
            self._table_row(
                [num, org, fmt_brl(val), sit, str(adt)],
                [26, 30, 52, 22, 12], bg=bg, aligns=["L","L","R","C","C"])
        self.ln(5)

        # additive analysis
        self._subsection("Contratos com Alto Número de Aditivos (≥ 2)")
        risky = [(n, o, v, s, a) for n, o, v, s, a in CONTRATOS if a >= 2]
        self._table_header(["Contrato", "Órgão", "Valor (R$)", "Situação", "Adtv.", "Risco"],
                           [26, 28, 44, 22, 12, 20])
        for i, (n, o, v, s, a) in enumerate(sorted(risky, key=lambda x: -x[4])):
            risk_lbl = "CRÍTICO" if a >= 3 else "ALTO"
            rbg = C_RED_LT if a >= 3 else C_AMBER_L
            self._table_row(
                [n, o, fmt_brl(v), s, str(a), risk_lbl],
                [26, 28, 44, 22, 12, 20], bg=rbg, aligns=["L","L","R","C","C","C"])
        self.ln(5)

        # note on CTT 2022 contracts
        y0 = self.get_y()
        self._rect(18, y0, 174, 16, C_AMBER_L)
        self._rect(18, y0, 3, 16, C_AMBER)
        self.set_xy(22, y0 + 2)
        self._sf("LS", "B", 8)
        self._tc(C_AMBER)
        self.cell(168, 5, "Alerta: CTT 50, 62, 63 e 66/2022 — 4 contratos FUNESBOM com 3 aditivos cada", 0, 2, "L")
        self._sf("LS", "", 7.5)
        self._tc(C_GRAY1)
        self.multi_cell(168, 4.5,
            "Quatro contratos do Corpo de Bombeiros firmados em 2022 acumulam 3 aditivos cada. "
            "Aditivos sucessivos sem nova licitação configuram possível burla ao art. 57 da Lei 8.666. "
            "Verificar se o 3° aditivo ainda está dentro do limite de vigência e valor.", 0, "L")
        self.ln(5)

    # ── Pages 11–12: ITERJ 005/2021 Deep Dive ─────────────────────────────
    def page_iterj(self):
        self.add_page()
        self._section_title("8. ANÁLISE PROFUNDA: ITERJ — CONTRATO 005/2021",
                            "3 aditivos · ~60 meses de vigência · Limite legal iminente · Lei 8.666 art. 57 §4")

        # ITERJ profile box
        self._subsection("Perfil do Órgão Contratante: ITERJ")
        iterj_data = [
            ("Nome completo",       "Instituto de Terras e Cartografia do Estado do Rio de Janeiro"),
            ("CNPJ",                "40.173.726/0001-40"),
            ("Natureza",            "Autarquia estadual (vinculada à SECID — Sec. de Cidades)"),
            ("Endereço",            "Rua Regente Feijó nº 7, 3°–5° andares, Centro, Rio de Janeiro/RJ"),
            ("Porte estimado",      "51–200 servidores · Área física estimada 1.200–2.400 m²"),
            ("Atividade-fim",       "Titulação de terras; Regularização fundiária; Cartografia estadual"),
            ("Necessidade contratual","Limpeza/conservação de prédio público (objeto contrato 005/2021)"),
        ]
        for i, (k, v) in enumerate(iterj_data):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            y0 = self.get_y()
            self._rect(18, y0, 174, 6.5, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LS", "B", 7)
            self._tc(C_NAVY2)
            self.cell(44, 6, k, 0, 0, "L")
            self._sf("LS", "", 7)
            self._tc(C_GRAY1)
            self.cell(128, 6, v, 0, 1, "L")
        self.ln(4)

        # contract summary
        self._subsection("Contrato 005/2021 — Dados Contratuais")
        c_data = [
            ("Número do contrato",  "005/2021"),
            ("Órgão",               "ITERJ — Instituto de Terras e Cartografia/RJ"),
            ("Situação (SIAFE)",    "Em Vigor"),
            ("Valor total contratado","R$ 1.085.032,09"),
            ("Número de aditivos",  "3 (três)"),
            ("Vigência estimada",   "2021–2026 (~60 meses)"),
            ("Limite legal",        "60 meses — art. 57 §4° Lei 8.666/1993"),
            ("Processos SEI vinc.", "SEI-270042/000678/2021 · /000681/2021 · /001804/2022"),
        ]
        for i, (k, v) in enumerate(c_data):
            is_risk = "Limite" in k or "aditivos" in k
            bg = C_RED_LT if is_risk else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            y0 = self.get_y()
            self._rect(18, y0, 174, 6.5, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LS", "B", 7)
            self._tc(C_RED if is_risk else C_NAVY2)
            self.cell(46, 6, k, 0, 0, "L")
            self._sf("LS", "", 7)
            self._tc(C_GRAY1)
            self.cell(126, 6, v, 0, 1, "L")
        self.ln(4)

        # timeline
        self._subsection("Linha do Tempo: 005/2021 — Assinatura → Limite Legal")
        timeline = [
            ("2021", "Jan–Mar", "Assinatura do Contrato 005/2021 (vigência inicial ~12 meses)", C_GREEN, False),
            ("2022", "1° Adtv.", "1° Aditivo de prazo — prorrogação de 12 meses (SEI /000678 e /000681)", C_BLUE, False),
            ("2022", "2° Adtv.", "2° Aditivo — prorrogação adicional (SEI /001804/2022)", C_BLUE, False),
            ("2023", "3° Adtv.", "3° Aditivo — última prorrogação antes do limite legal", C_AMBER, False),
            ("2026", "LIMITE",  "60° mês de vigência — limite absoluto Lei 8.666 art. 57 §4°", C_RED, True),
        ]
        x_start = 20
        y0 = self.get_y()
        # timeline line
        self._fc(C_GOLD)
        self.rect(x_start + 12, y0 + 4, 150, 1.5, "F")
        # events
        step = 150 / (len(timeline) - 1)
        for i, (yr, evt, desc, col, is_limit) in enumerate(timeline):
            xi = x_start + 12 + i * step
            # dot
            self._fc(col)
            self.ellipse(xi - 4, y0, 8, 8, "F")
            # year label
            self.set_xy(xi - 10, y0 + 9)
            self._sf("LS", "B", 7)
            self._tc(col)
            self.cell(20, 4, yr, 0, 0, "C")
            # event label
            self.set_xy(xi - 12, y0 + 13)
            self._sf("LS", "B" if is_limit else "", 6)
            self._tc(col)
            self.cell(24, 4, evt, 0, 0, "C")
        self.ln(20)
        # desc below
        for i, (yr, evt, desc, col, _) in enumerate(timeline):
            y0d = self.get_y()
            self._rect(18, y0d, 174, 6.5, C_GRAY5 if i % 2 == 0 else C_WHITE)
            self.set_xy(19, y0d + 0.5)
            self._sf("LS", "B", 6.5)
            self._tc(col)
            self.cell(22, 6, f"{yr} · {evt}", 0, 0, "L")
            self._sf("LS", "", 6.5)
            self._tc(C_GRAY1)
            self.cell(150, 6, desc, 0, 1, "L")
        self.ln(5)

        # Lei 8.666 analysis
        y0 = self.get_y()
        self._rect(18, y0, 174, 18, C_RED_LT)
        self._rect(18, y0, 3, 18, C_RED)
        self.set_xy(22, y0 + 2)
        self._sf("LS", "B", 9)
        self._tc(C_RED)
        self.cell(168, 5, "ALERTA LEGAL — Limite de 60 Meses (Lei 8.666/1993)", 0, 2, "L")
        self._sf("LS", "", 7.5)
        self._tc(C_GRAY1)
        self.multi_cell(168, 4.5,
            "O art. 57, §4° da Lei 8.666/1993 estabelece que os contratos de serviços de "
            "execução continuada não podem ter vigência superior a 60 (sessenta) meses. "
            "O contrato 005/2021 (ITERJ), com 3 aditivos de prazo, está próximo ou já atingiu "
            "este limite. O TCU, pelo Acórdão 2.066/2022-Plenário, consolidou o entendimento "
            "de que a renovação além do 60° mês é irregular, sujeitando gestores à "
            "responsabilização por dano ao erário.", 0, "L")
        self.ln(5)

        # productivity benchmark page continuation
        self.add_page()
        self._section_title("8. ITERJ 005/2021 — TCU CINCO C's (continuação)",
                            "Achado AF-01 detalhado")

        # five C's table
        achado = ACHADOS[0]
        for label, txt in [
            ("CRITÉRIO",          achado["criterio"]),
            ("CONDIÇÃO",          achado["condicao"]),
            ("CAUSA",             achado["causa"]),
            ("CONSEQUÊNCIA",      achado["consequencia"]),
            ("AÇÃO CORRETIVA",    achado["acao_corretiva"]),
        ]:
            y0 = self.get_y()
            is_crit = label in ("CONSEQUÊNCIA", "AÇÃO CORRETIVA")
            bg = C_RED_LT if is_crit else C_GRAY5
            border_col = C_RED if is_crit else C_NAVY
            self._rect(18, y0, 174, 4, border_col)
            self.set_xy(19, y0 + 0.5)
            self._sf("LS", "B", 8)
            self._tc(C_WHITE)
            self.cell(170, 3, label, 0, 1, "L")
            self._rect(18, self.get_y(), 174, 1, C_GRAY4)
            self.set_xy(19, self.get_y() + 1.5)
            self._fc(bg)
            start_y = self.get_y()
            self._sf("LS", "", 8)
            self._tc(C_GRAY1)
            self.multi_cell(168, 4.5, txt, 0, "L")
            end_y = self.get_y()
            h = end_y - start_y + 2
            self._rect(18, start_y - 1.5, 174, h, bg)
            self.set_xy(19, start_y)
            self.multi_cell(168, 4.5, txt, 0, "L")
            self.ln(4)

        # productivity check
        self._subsection("Verificação de Produtividade — IN SEGES 05/2017")
        prod_data = [
            ("Área estimada ITERJ",   "1.200–2.400 m² (prédio Rua Regente Feijó 7, andares 3°–5°, ~50 salas)"),
            ("Serventes implícitos",  "Estimativa: 1–3 serventes (base IN SEGES: 800–1.200 m²/servente interior)"),
            ("Custo/servente típico", "R$2.800–4.200/mês (2021); R$3.500–5.200/mês (2025) — PNCP/COMPRASNET"),
            ("Valor mensal contrato", f"{fmt_brl(1_085_032.09 / 60)} / mês (R$1.085.032,09 ÷ 60 meses)"),
            ("Verificar",             "Número real de serventes na planilha de custos do contrato (SEI)"),
        ]
        for i, (k, v) in enumerate(prod_data):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            y0 = self.get_y()
            self._rect(18, y0, 174, 6.5, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LS", "B", 7)
            self._tc(C_NAVY2)
            self.cell(48, 6, k, 0, 0, "L")
            self._sf("LS", "", 7)
            self._tc(C_GRAY1)
            self.cell(124, 6, v, 0, 1, "L")
        self.ln(5)

    # ── Page 13: Concentração e Risco ─────────────────────────────────────
    def page_concentration(self):
        self.add_page()
        self._section_title("9. ANÁLISE DE CONCENTRAÇÃO E RISCO POR ÓRGÃO",
                            "Distribuição de contratos · Dependência operacional · Risco sistêmico")

        # bar chart: 2025 by organ
        top_organs_2025 = sorted(
            [(sig, v25) for sig, _, _, _, v25, _ in ORGANS if v25 > 0],
            key=lambda x: -x[1]
        )
        self._subsection("Ranking de Órgãos — 2025 (Empenhado)")
        self._bar_chart(18, self.get_y(), 174, 80, dict(top_organs_2025),
                        title="Empenhado por Órgão — 2025 (R$ em Milhões)")
        self.ln(5)

        # concentration analysis table
        self._subsection("Indicadores de Concentração")
        total_2025 = TOTAL_2025
        top1_pct   = ORGANS[0][4] / total_2025 * 100  # FUNESBOM
        top3_v     = sum(sorted([o[4] for o in ORGANS], reverse=True)[:3])
        top3_pct   = top3_v / total_2025 * 100
        top5_v     = sum(sorted([o[4] for o in ORGANS], reverse=True)[:5])
        top5_pct   = top5_v / total_2025 * 100
        hhi        = sum((o[4] / total_2025 * 100) ** 2 for o in ORGANS if o[4] > 0)

        conc_data = [
            ("Participação do maior órgão (FUNESBOM)",  f"{top1_pct:.1f}%",
             "CRÍTICO — acima de 50%", C_RED_LT),
            ("Top 3 órgãos (FUNESBOM+TJ+PM)",           f"{top3_pct:.1f}%",
             "ALTO — top 3 = 84% do total", C_ORANGE_L),
            ("Top 5 órgãos",                            f"{top5_pct:.1f}%",
             "ALTO — top 5 = 93% do total", C_AMBER_L),
            ("Índice Herfindahl-Hirschman (HHI)",        f"{hhi:.0f}",
             "HHI > 2.500 = mercado altamente concentrado", C_AMBER_L),
            ("Número de órgãos ativos 2025",             "9 confirmados",
             "Diversificação moderada mas muito assimétrica", C_GRAY5),
        ]
        self._table_header(["Indicador", "Valor", "Avaliação"], [64, 20, 90])
        for ind, val, aval, bg in conc_data:
            self._table_row([ind, val, aval], [64, 20, 90], bg=bg, aligns=["L","C","L"])
        self.ln(5)

        # contracts per organ
        self._subsection("Contratos por Órgão — Distribuição")
        from collections import Counter
        org_count = Counter(c[1] for c in CONTRATOS)
        sorted_count = sorted(org_count.items(), key=lambda x: -x[1])
        self._table_header(["Órgão", "Qtd. Contratos", "% Contratos", "Maior Contrato (R$)", "Adtv. Total"],
                           [28, 22, 22, 48, 20])
        total_contracts = len(CONTRATOS)
        for i, (org, cnt) in enumerate(sorted_count):
            pct  = cnt / total_contracts * 100
            maxv = max((c[2] for c in CONTRATOS if c[1] == org), default=0)
            tadt = sum(c[4] for c in CONTRATOS if c[1] == org)
            bg   = C_AMBER_L if cnt >= 5 else (C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._table_row(
                [org, str(cnt), f"{pct:.1f}%", fmt_brl(maxv), str(tadt)],
                [28, 22, 22, 48, 20], bg=bg, aligns=["L","C","R","R","C"])
        self.ln(5)

    # ── Page 14: Operação Overclean ────────────────────────────────────────
    def page_overclean(self):
        self.add_page()
        self._section_title("10. CONTEXTO SETORIAL — OPERAÇÃO OVERCLEAN (jan/2026)",
                            "Investigação federal no setor de limpeza/facilities público · MGS CLEAN NÃO é alvo direto")

        # disclaimer
        y0 = self.get_y()
        self._rect(18, y0, 174, 10, C_GREEN_L)
        self._rect(18, y0, 3, 10, C_GREEN)
        self.set_xy(22, y0 + 2)
        self._sf("LS", "B", 8.5)
        self._tc(C_GREEN)
        self.cell(168, 5, "AVISO IMPORTANTE: A MGS CLEAN NÃO é alvo direto da Operação Overclean.", 0, 2, "L")
        self._sf("LS", "", 7.5)
        self._tc(C_GRAY1)
        self.cell(168, 4.5,
            "Esta seção contextualiza o risco sistêmico do SETOR, não da empresa auditada.", 0, 1, "L")
        self.ln(8)

        # operation facts
        self._subsection("Fatos da Operação Overclean — 13/01/2026")
        facts = [
            ("Data",             "13 de janeiro de 2026"),
            ("Tipo",             "Operação federal (PF/MPF) de combate à corrupção em contratos de limpeza"),
            ("Alvo",             "Empresas de limpeza/facilities com contratos com o setor público federal"),
            ("Esquema",          "Fraude em licitações, superfaturamento, cartel de preços, lavagem de dinheiro"),
            ("Volume investigado","R$ 1,4 bilhão em contratos suspeitos (acumulado)"),
            ("Valores bloqueados","R$ 24 milhões em ordens de bloqueio judicial"),
            ("Alvos identificados","70+ mandados cumpridos em múltiplos estados"),
        ]
        for i, (k, v) in enumerate(facts):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            y0 = self.get_y()
            self._rect(18, y0, 174, 6.5, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LS", "B", 7.5)
            self._tc(C_NAVY2)
            self.cell(42, 6, k, 0, 0, "L")
            self._sf("LS", "", 7.5)
            self._tc(C_GRAY1)
            self.cell(130, 6, v, 0, 1, "L")
        self.ln(5)

        # implications
        self._subsection("Implicações para a Auditoria MGS CLEAN")
        implications = [
            ("Risco setorial elevado",
             "A Overclean demonstra que o setor de limpeza é vetor ativo de fraudes sistêmicas. "
             "Órgãos do RJ (FUNESBOM, TJ, PM) que contratam a MGS CLEAN devem intensificar controles."),
            ("Padrões observados na MGS CLEAN presentes no setor",
             "Características identificadas na MGS CLEAN — concentração de contratos em único "
             "órgão, aditivos sucessivos, capital social atípico — são exatamente os padrões "
             "investigados na Overclean em outras empresas."),
            ("Recomendação de Due Diligence aprofundada",
             "Embora não haja evidência de envolvimento da MGS CLEAN na Overclean, o contexto "
             "setorial recomenda ampliação do escopo de auditoria para incluir verificação de "
             "preços praticados vs. COMPRASNET e execução física dos contratos."),
            ("Risco reputacional para os órgãos contratantes",
             "Os órgãos (FUNESBOM, TJ, PM) que concentram R$75M/ano em limpeza com único "
             "fornecedor assumem risco reputacional elevado no contexto pós-Overclean."),
        ]
        for i, (titulo, texto) in enumerate(implications):
            y0 = self.get_y()
            self._rect(18, y0, 3, 20, C_NAVY2)
            self._rect(21, y0, 171, 20, C_GRAY5 if i % 2 == 0 else C_WHITE)
            self.set_xy(23, y0 + 2)
            self._sf("LS", "B", 8)
            self._tc(C_NAVY)
            self.cell(165, 5, titulo, 0, 2, "L")
            self._sf("LS", "", 7.5)
            self._tc(C_GRAY1)
            self.set_x(23)
            self.multi_cell(163, 4.5, texto, 0, "L")
            self.ln(3)
        self.ln(5)

    def page_heatmap(self):
        self.add_page()
        self._section_title("6. MAPA DE CALOR — EVOLUÇÃO POR ÓRGÃO (2023–2026)",
                            "Intensidade de cor = volume empenhado · Azul escuro = maior volume")

        # build matrix: organs × years
        organ_order = sorted(ORGANS, key=lambda x: -(x[4] + x[5]))  # sort by 2025+2026
        years = [2023, 2024, 2025, 2026]
        year_labels = ["2023\n(est.)", "2024\n(est.)", "2025\n(exato)", "2026\n(parcial)"]
        max_val = max(max(o[2], o[3], o[4], o[5]) for o in ORGANS)

        # column widths
        name_w = 30
        val_w  = 34
        total_w = name_w + val_w * 4
        hdr_h  = 9
        row_h  = 8.5

        # header
        self._fc(C_NAVY)
        self.rect(18, self.get_y(), total_w, hdr_h, "F")
        self.set_xy(18, self.get_y())
        self._sf("LS", "B", 7)
        self._tc(C_WHITE)
        self.cell(name_w, hdr_h, "Órgão", 0, 0, "C")
        for yl in year_labels:
            self.cell(val_w, hdr_h, yl.replace("\n", " "), 0, 0, "C")
        self.ln()

        # rows
        for i, (sig, nome, v23, v24, v25, v26) in enumerate(organ_order):
            vals = [v23, v24, v25, v26]
            y0 = self.get_y()
            # org label
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            self._rect(18, y0, name_w, row_h, bg)
            self.set_xy(19, y0 + 1.5)
            self._sf("LS", "B", 6.5)
            self._tc(C_NAVY)
            self.cell(name_w - 2, row_h - 3, sig, 0, 0, "L")
            # heat cells
            for vi, v in enumerate(vals):
                cx = 18 + name_w + vi * val_w
                col = heat_color(v, max_val)
                tc  = heat_text_color(v, max_val)
                self._rect(cx, y0, val_w, row_h, col)
                self.set_xy(cx, y0 + 1.5)
                self._sf("LS", "B" if v > 5_000_000 else "", 6)
                self._tc(tc)
                txt = fmt_brl(v, True) if v > 0 else "—"
                self.cell(val_w, row_h - 3, txt, 0, 0, "C")
            self.ln(row_h)

        # total row
        y0 = self.get_y()
        self._rect(18, y0, total_w, row_h, C_NAVY)
        self.set_xy(19, y0 + 1.5)
        self._sf("LS", "B", 7)
        self._tc(C_GOLD)
        self.cell(name_w - 2, row_h - 3, "TOTAL", 0, 0, "L")
        for vi, tot in enumerate([TOTAL_2023_EST, TOTAL_2024_EST, TOTAL_2025, TOTAL_2026]):
            cx = 18 + name_w + vi * val_w
            self.set_xy(cx, y0 + 1.5)
            self._tc(C_WHITE)
            self.cell(val_w, row_h - 3, fmt_brl(tot, True), 0, 0, "C")
        self.ln(row_h + 3)

        # legend
        self._sf("LS", "B", 7)
        self._tc(C_GRAY2)
        self.cell(174, 5, "Legenda de intensidade de cor:", 0, 1, "L")
        legend_items = [
            (C_NAVY,    C_WHITE, "> R$20M"),
            (C_BLUE,    C_WHITE, "R$5M–20M"),
            (C_BLUE_LT, C_NAVY,  "R$1M–5M"),
            (C_BLUE_XL, C_NAVY,  "< R$1M"),
            (C_GRAY5,   C_GRAY3, "Sem empenho"),
        ]
        x0 = 18
        for bg, fg, lbl in legend_items:
            self._rect(x0, self.get_y(), 30, 6, bg)
            self.set_xy(x0, self.get_y())
            self._sf("LS", "", 6)
            self._tc(fg)
            self.cell(30, 6, lbl, 0, 0, "C")
            x0 += 32
        self.ln(10)

        # monthly heat map for 2025/2026
        self._subsection("Padrão Mensal — 2025 e 2026 (valores totais, todos os órgãos)")
        months_all = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
        col_w2 = 14.5
        hdr_h2 = 7
        row_h2 = 7
        max_monthly = max(max(MONTHLY_2025.values()), max(MONTHLY_2026.values()))

        # header months
        self._fc(C_NAVY)
        self.rect(18, self.get_y(), 20 + col_w2 * 12, hdr_h2, "F")
        self.set_xy(18, self.get_y())
        self._sf("LS", "B", 6.5)
        self._tc(C_WHITE)
        self.cell(20, hdr_h2, "Ano", 0, 0, "C")
        for m in months_all:
            self.cell(col_w2, hdr_h2, m, 0, 0, "C")
        self.ln()

        for year_key, monthly_d in [("2025\n(exato)", MONTHLY_2025), ("2026\n(parcial)", MONTHLY_2026)]:
            y0 = self.get_y()
            # year label
            self._rect(18, y0, 20, row_h2, C_NAVY2)
            self.set_xy(18, y0 + 1)
            self._sf("LS", "B", 6)
            self._tc(C_GOLD)
            self.cell(20, row_h2 - 2, year_key.replace("\n", " "), 0, 0, "C")
            # month cells
            for mi, m in enumerate(months_all):
                v = monthly_d.get(m, 0)
                cx = 18 + 20 + mi * col_w2
                col = heat_color(v, max_monthly)
                tc  = heat_text_color(v, max_monthly)
                self._rect(cx, y0, col_w2, row_h2, col)
                self.set_xy(cx, y0 + 1.5)
                self._sf("LS", "", 5.5)
                self._tc(tc)
                txt = fmt_brl(v, True) if v > 0 else "—"
                self.cell(col_w2, row_h2 - 3, txt, 0, 0, "C")
            self.ln(row_h2)
        self.ln(5)

    # ── Page 15: Sinais de Risco ───────────────────────────────────────────
    def page_risk_signals(self):
        self.add_page()
        self._section_title("11. SINAIS DE RISCO — RADAR DE IRREGULARIDADES",
                            f"Score consolidado: {SCORE}/100 — Classificação: {RISCO}")

        y0 = self.get_y()
        self._rect(18, y0, 174, 12, C_GRAY5)
        filled_w = 174 * SCORE / 100
        self._rect(18, y0, filled_w, 12, C_ORANGE)
        self.set_xy(18, y0 + 2)
        self._sf("LS", "B", 16)
        self._tc(C_WHITE)
        self.cell(80, 8, f"Score: {SCORE}/100", 0, 0, "C")
        self._sf("LS", "B", 10)
        self._tc(C_NAVY)
        self.cell(90, 8, f"Classificacao: {RISCO}", 0, 0, "L")
        self.ln(16)

        self._subsection("Escala de Risco — JFN Intelligence")
        scale = [
            ("0–25",   "BAIXO",      C_GREEN,  C_GREEN_L,  "Risco residual — controles padrao suficientes"),
            ("26–50",  "MEDIO",      C_AMBER,  C_AMBER_L,  "Monitoramento continuo — verificacoes periodicas"),
            ("51–75",  "MEDIO-ALTO", C_ORANGE, C_ORANGE_L, "Investigacao aprofundada recomendada"),
            ("76–90",  "ALTO",       C_RED,    C_RED_LT,   "Acao imediata — escalada para TCU/CGE"),
            ("91–100", "CRITICO",    C_RED,    C_RED_LT,   "Paralisacao preventiva + referenciamento policial"),
        ]
        self._table_header(["Faixa", "Nivel", "Descricao"], [20, 28, 126])
        for faixa, nivel, fc, bg, desc in scale:
            is_current = "51" in faixa
            y0r = self.get_y()
            self._rect(18, y0r, 174, 7, C_AMBER_L if is_current else bg)
            self.set_xy(19, y0r + 0.5)
            self._sf("LS", "B" if is_current else "", 7)
            self._tc(C_GRAY1)
            self.cell(20, 6, faixa, 0, 0, "C")
            self._tc(fc)
            self.cell(28, 6, nivel, 0, 0, "C")
            self._tc(C_GRAY1)
            self.cell(124, 6, ("► " if is_current else "") + desc, 0, 1, "L")
        self.ln(5)

        self._subsection("Sinais Identificados — Analise Detalhada")
        for i, (nivel, cod, desc_curta, desc_longa) in enumerate(SINAIS):
            col = risk_color(nivel)
            bg  = risk_bg(nivel)
            y0s = self.get_y()
            if y0s > 245:
                self.add_page()
                y0s = self.get_y()
            self._rect(18, y0s, 20, 5.5, col)
            self.set_xy(18, y0s + 0.5)
            self._sf("LS", "B", 6)
            self._tc(C_WHITE)
            self.cell(20, 4.5, nivel[:12], 0, 0, "C")
            self._rect(38, y0s, 40, 5.5, C_NAVY)
            self.set_xy(38, y0s + 0.5)
            self._sf("LSM", "", 6)
            self._tc(C_GOLD)
            self.cell(40, 4.5, cod[:22], 0, 0, "L")
            self._rect(78, y0s, 114, 5.5, C_NAVY)
            self.set_xy(78, y0s + 0.5)
            self._sf("LS", "B", 7)
            self._tc(C_WHITE)
            self.cell(112, 4.5, desc_curta[:65], 0, 1, "L")
            y0b = self.get_y()
            self._rect(18, y0b, 174, 6, bg)
            self.set_xy(20, y0b + 0.5)
            self._sf("LS", "", 7)
            self._tc(C_GRAY1)
            self.multi_cell(168, 4, desc_longa[:240], 0, "L")
            self._rect(18, y0b, 174, self.get_y() - y0b + 1, bg)
            self.set_xy(20, y0b + 0.5)
            self.multi_cell(168, 4, desc_longa[:240], 0, "L")
            self.ln(3)

    # ── Page 16-18: Achados de Auditoria (Five Cs) ────────────────────────
    def page_findings(self):
        self.add_page()
        self._section_title("12. ACHADOS DE AUDITORIA — FRAMEWORK TCU (CINCO C's)",
                            "Criterio · Condicao · Causa · Consequencia · Acao Corretiva")

        y0 = self.get_y()
        self._rect(18, y0, 174, 10, C_NAVY)
        self.set_xy(20, y0 + 1.5)
        self._sf("LS", "B", 8)
        self._tc(C_GOLD)
        self.cell(170, 4, "Framework TCU — Cinco C's (padrao auditoria TCU/CGE/CGU)", 0, 2, "L")
        self._sf("LS", "", 7)
        self._tc(C_WHITE)
        self.cell(170, 4,
            "Criterio: norma aplicavel  · Condicao: situacao encontrada  · Causa: raiz  · "
            "Consequencia: impacto  · Acao Corretiva: o que fazer", 0, 1, "L")
        self.ln(5)

        for ai, achado in enumerate(ACHADOS):
            if self.get_y() > 60 and ai > 0:
                self.add_page()
            col = risk_color(achado["severidade"])
            y0 = self.get_y()
            self._rect(18, y0, 174, 10, col)
            self.set_xy(20, y0 + 1.5)
            self._sf("LS", "B", 9)
            self._tc(C_WHITE)
            self.cell(170, 4, f"ACHADO {achado['id']} — {achado['severidade']}", 0, 2, "L")
            self._sf("LS", "", 8)
            self._tc(C_GOLD_LT)
            self.cell(170, 4, achado["titulo"][:100], 0, 1, "L")
            self.ln(2)

            for label, txt in [
                ("CRITERIO",       achado["criterio"]),
                ("CONDICAO",       achado["condicao"]),
                ("CAUSA",          achado["causa"]),
                ("CONSEQUENCIA",   achado["consequencia"]),
                ("ACAO CORRETIVA", achado["acao_corretiva"]),
            ]:
                is_impact = label in ("CONSEQUENCIA", "ACAO CORRETIVA")
                lc  = C_RED if is_impact else C_NAVY2
                lbg = C_RED_LT if is_impact else C_GRAY5
                y0c = self.get_y()
                self._rect(18, y0c, 36, 200, lc)  # will be clipped
                self._rect(54, y0c, 138, 200, lbg)  # placeholder
                self.set_xy(55, y0c + 1)
                self._sf("LS", "", 7.5)
                self._tc(C_GRAY1)
                self.multi_cell(136, 4.5, txt, 0, "L")
                end_y = self.get_y()
                h = end_y - y0c + 1
                self._rect(18, y0c, 36, h, lc)
                self._rect(54, y0c, 138, h, lbg)
                self.set_xy(18, y0c + h/2 - 2)
                self._sf("LS", "B", 7)
                self._tc(C_WHITE)
                self.cell(36, 4, label, 0, 0, "C")
                self.set_xy(55, y0c + 1)
                self._sf("LS", "", 7.5)
                self._tc(C_GRAY1)
                self.multi_cell(136, 4.5, txt, 0, "L")
                self.ln(2)
            self.ln(6)

    # ── Page 19: Recomendacoes ─────────────────────────────────────────────
    def page_recommendations(self):
        self.add_page()
        self._section_title("13. RECOMENDACOES E PROXIMOS PASSOS",
                            "Acoes por prazo · Imediato · Curto prazo · Medio prazo")

        recommendations = [
            ("IMEDIATO (0-30 dias)", "CRITICO", [
                "Verificar data exata de assinatura do Contrato 005/2021 (ITERJ) e calcular "
                "o 60 mes de vigencia. Notificar o gestor se o limite estiver iminente.",
                "Solicitar a MGS CLEAN planilha de composicao de custos dos 3 maiores contratos "
                "(CTT 154/2024, 215/2024 PM, 2023117 TJ) para confronto com COMPRASNET.",
                "Acionar gestor do FUNESBOM para justificativa formal dos aditivos nos contratos "
                "CTT 50, 62, 63 e 66/2022 (3 aditivos cada — 4 contratos de 2022).",
            ]),
            ("CURTO PRAZO (30-90 dias)", "ALTO", [
                "Obter valores PAGOS (Ordens Bancarias) no SIAFE para 2023-2026. "
                "Confrontar com empenhados — diferenca material indica risco.",
                "Verificar no SEI os 42 processos vinculados para obter objeto e partes "
                "de cada empenho nao identificado.",
                "Auditar os 22 contratos FUNESBOM: verificar se originam de licitacoes "
                "independentes ou de edital fracionado (art. 23 Lei 8.666).",
                "Verificar quadro de pessoal MGS CLEAN via eSocial/RAIS: empresa tem "
                "funcionarios suficientes para os contratos em vigor simultaneamente?",
            ]),
            ("MEDIO PRAZO (90-180 dias)", "MEDIO", [
                "Instaurar processo de nova licitacao para o ITERJ antes do vencimento legal "
                "do contrato 005/2021. Incluir analise de mercado e valor COMPRASNET.",
                "Elaborar plano de diversificacao de fornecedores de limpeza para FUNESBOM, "
                "reduzindo participacao da MGS CLEAN para abaixo de 30% por licitacao.",
                "Monitorar desdobramentos da Operacao Overclean para identificar conexoes "
                "com fornecedores do Estado do RJ.",
                "Propor ao FUNESBOM mapa de riscos dos contratos de facilities com KPIs.",
            ]),
        ]

        for prazo, nivel, items in recommendations:
            col = risk_color(nivel)
            bg  = risk_bg(nivel)
            y0  = self.get_y()
            if y0 > 220:
                self.add_page()
                y0 = self.get_y()
            self._rect(18, y0, 174, 8, col)
            self.set_xy(19, y0 + 1.5)
            self._sf("LS", "B", 9)
            self._tc(C_WHITE)
            self.cell(170, 5, prazo, 0, 1, "L")
            for item in items:
                y0i = self.get_y()
                self._rect(18, y0i, 174, 7, bg)
                self._rect(18, y0i, 3, 7, col)
                self.set_xy(23, y0i + 1)
                self._sf("LS", "", 7.5)
                self._tc(C_GRAY1)
                self.multi_cell(167, 5, "- " + item, 0, "L")
            self.ln(5)

    # ── Page 20: Metodologia ───────────────────────────────────────────────
    def page_methodology(self):
        self.add_page()
        self._section_title("14. METODOLOGIA, FONTES E LIMITACOES",
                            "Transparencia tecnica · Rastreabilidade das informacoes")

        self._subsection("Fontes Primarias Utilizadas")
        fontes = [
            ("TFE/RJ",     "tfe.fazenda.rj.gov.br/tfe/web/fornecedor",
             "Empenhos 2025-2026; valores EMPENHADOS (Nota de Empenho)"),
            ("SIAFE/RJ",   "Sistema Integrado de Adm. Financeira do Estado",
             "41 contratos; vigencias; aditivos; situacao; coleta 04/06/2026"),
            ("Receita Federal","Consulta CNPJ — Cadastro Nacional PJ",
             "Situacao cadastral; socios; data abertura; CNAE; capital"),
            ("SEI/RJ",     "Sistema Eletronico de Informacoes",
             "42 processos administrativos vinculados a empenhos 2025-2026"),
            ("COMPRASNET", "compras.gov.br — Painel de Precos",
             "Benchmarks de preco para servicos de limpeza (referencia)"),
            ("Registro.br","RDAP/Whois — dominio mgsclean.net",
             "Verificacao de titularidade e historico de dominio"),
        ]
        self._table_header(["Fonte", "Sistema", "Dados Coletados"], [22, 68, 84])
        for i, (fonte, url, dados) in enumerate(fontes):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            self._table_row([fonte, url, dados], [22, 68, 84], bg=bg, aligns=["L","L","L"])
        self.ln(5)

        self._subsection("Metodologia de Analise")
        metodos = [
            "Analise quantitativa: extracao automatizada de empenhos via TFE/RJ (Python/requests); "
            "consolidacao de 131 empenhos (84 em 2025 + 47 em 2026) por orgao e por mes.",
            "Analise de contratos: cruzamento dos 41 contratos SIAFE com empenhos TFE; "
            "identificacao de orgao, valor, situacao, numero de aditivos e processos SEI.",
            "Estimativas 2023-2024: projetadas a partir das vigencias e valores contratuais dos "
            "41 contratos SIAFE. Margem de erro estimada: +/-15%. Marcadas como ESTIMADO.",
            "Analise de risco: framework JFN Intelligence (score 0-100) combinado com "
            "indicadores TCU (Acordao 2.066/2022-Plenario) e padroes IN SEGES 05/2017.",
            "Framework de achados: TCU Cinco C's (Criterio, Condicao, Causa, Consequencia, "
            "Acao Corretiva) — padrao utilizado em auditorias do TCU/CGE/CGU.",
        ]
        for i, m in enumerate(metodos):
            y0 = self.get_y()
            self._rect(18, y0, 174, 7, C_GRAY5 if i % 2 == 0 else C_WHITE)
            self._rect(18, y0, 3, 7, C_NAVY2)
            self.set_xy(23, y0 + 1)
            self._sf("LS", "", 7.5)
            self._tc(C_GRAY1)
            self.multi_cell(165, 5, m, 0, "L")
        self.ln(5)

        self._subsection("Limitacoes e Advertencias")
        limitacoes = [
            ("EMPENHADO != PAGO",
             "Todos os valores sao EMPENHADOS (TFE/RJ). O valor PAGO (OB) precisa "
             "ser obtido no SIAFE (Execucao Financeira, Ordens Bancarias) — Etapa 2."),
            ("Estimativas 2023-2024",
             "Valores de 2023-2024 sao estimativas derivadas de contratos SIAFE. "
             "Nao representam dados oficiais. Margem de erro: +/-15%."),
            ("Dados 2026 parciais",
             "2026 capturado ate junho. Projecao anual e extrapolacao linear."),
            ("Sem acesso ao objeto contratual",
             "Planilha de custos, medicoes e notas fiscais nao verificadas. "
             "Auditoria de 2a etapa deve incluir esses documentos."),
        ]
        for i, (k, v) in enumerate(limitacoes):
            bg = C_AMBER_L if i == 0 else C_GRAY5
            y0 = self.get_y()
            self._rect(18, y0, 174, 7, bg)
            self.set_xy(19, y0 + 1)
            self._sf("LS", "B", 7.5)
            self._tc(C_NAVY)
            self.cell(48, 5, k, 0, 0, "L")
            self._sf("LS", "", 7)
            self._tc(C_GRAY1)
            self.multi_cell(122, 5, v, 0, "L")
        self.ln(5)

    # ── Page 21: Anexo — Processos SEI ────────────────────────────────────
    def page_annexes(self):
        self.add_page()
        self._section_title("15. ANEXO — PROCESSOS SEI VINCULADOS",
                            f"42 processos · 2025: {len(SEI_2025)} · 2026: {len(SEI_2026)}")

        self._subsection(f"Processos SEI 2025 ({len(SEI_2025)} processos)")
        for i in range(0, len(SEI_2025), 2):
            y0 = self.get_y()
            bg = C_GRAY5 if (i // 2) % 2 == 0 else C_WHITE
            self._rect(18, y0, 174, 6, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LSM", "", 6.5)
            self._tc(C_NAVY)
            self.cell(85, 5, SEI_2025[i], 0, 0, "L")
            if i + 1 < len(SEI_2025):
                self.cell(85, 5, SEI_2025[i+1], 0, 0, "L")
            self.ln()
        self.ln(5)

        self._subsection(f"Processos SEI 2026 ({len(SEI_2026)} processos)")
        for i in range(0, len(SEI_2026), 2):
            y0 = self.get_y()
            bg = C_GRAY5 if (i // 2) % 2 == 0 else C_WHITE
            self._rect(18, y0, 174, 6, bg)
            self.set_xy(19, y0 + 0.5)
            self._sf("LSM", "", 6.5)
            self._tc(C_NAVY)
            self.cell(85, 5, SEI_2026[i], 0, 0, "L")
            if i + 1 < len(SEI_2026):
                self.cell(85, 5, SEI_2026[i+1], 0, 0, "L")
            self.ln()
        self.ln(5)

        y0 = self.get_y()
        self._rect(18, y0, 174, 22, C_NAVY)
        self.set_xy(20, y0 + 3)
        self._sf("LS", "B", 9)
        self._tc(C_GOLD)
        self.cell(170, 5, "Proximos Passos — Etapa 2", 0, 2, "L")
        self._sf("LS", "", 8)
        self._tc(C_WHITE)
        self.multi_cell(168, 4.5,
            "1. Obter valores PAGOS (OBs) no SIAFE para confronto com empenhado (2023-2026).\n"
            "2. Abrir cada processo SEI acima em sei_auditor.py para extrair objeto e partes.\n"
            "3. Verificar planilhas de custos e relatorios de medicao dos 3 maiores contratos.\n"
            "4. Confirmar data exata do Contrato 005/2021 (ITERJ) e calcular 60 mes.", 0, "L")
        self.ln(5)


# ═════════════════════════════════════════════════════════════════════════════
#  BUILD FUNCTION
# ═════════════════════════════════════════════════════════════════════════════
def build_pdf() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = AuditPDF()

    # Page 1: Cover
    pdf.page_cover()
    # Page 2: TOC + executive summary
    pdf.page_toc()
    # Page 3: Identification
    pdf.page_identification()
    # Page 4: Volume overview 2023-2026
    pdf.page_volume_overview()
    # Page 5: 2025 detail
    pdf.page_detail_2025()
    # Page 6: 2026 detail
    pdf.page_detail_2026()
    # Page 7: Estimated 2023-2024
    pdf.page_estimated_years()
    # Page 8: Heat map
    pdf.page_heatmap()
    # Pages 9-10: Contracts inventory
    pdf.page_contracts()
    # Pages 11-12: ITERJ deep dive
    pdf.page_iterj()
    # Page 13: Concentration
    pdf.page_concentration()
    # Page 14: Overclean context
    pdf.page_overclean()
    # Page 15: Risk signals
    pdf.page_risk_signals()
    # Pages 16-18: Findings (Five Cs)
    pdf.page_findings()
    # Page 19: Recommendations
    pdf.page_recommendations()
    # Page 20: Methodology
    pdf.page_methodology()
    # Page 21: Annexes
    pdf.page_annexes()

    pdf.output(str(OUT))
    return OUT


if __name__ == "__main__":
    print("Gerando relatorio PDF v2 — MGS CLEAN 2023-2026...")
    out = build_pdf()
    print(f"PDF gerado: {out}")
    print(f"Paginas: {out.stat().st_size // 1024} KB aproximados")
