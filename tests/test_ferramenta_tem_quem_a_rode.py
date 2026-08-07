# -*- coding: utf-8 -*-
"""Ferramenta pronta, testada e SEM NINGUÉM QUE A RODE — a falha que mais se repetiu nesta casa.

Em 2026-08-04, duas mordidas no mesmo dia:

* `tools/sei_reparar_vazios.py`, escrita em 2026-07-24 com a docstring *"por isso esta ferramenta
  roda primeiro"*, tinha **zero callers e zero cron** — e, quando finalmente rodou, recuperou
  documentos que estavam declarados vazios desde julho;
* a fila de recaptura do cap de 20k vinha de uma lista **curada uma vez** e nunca regerada: 103
  processos truncados depois da curadoria jamais voltariam à fila.

O antídoto tem de ser verificável por qualquer um — inclusive por uma IA fraca, ou por ninguém.
Aqui a regra é literal: **toda ferramenta que precisa rodar periodicamente é citada por um script
de sweep do repositório**, e os sweeps é que estão no crontab. Um `grep` decide; não há julgamento.

Quando uma ferramenta nova precisar de rotina, some-a à tabela abaixo com o MOTIVO — a tabela é a
documentação executável de quem roda o quê.
"""
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# ferramenta → por que ela PRECISA de rotina (e não pode depender de alguém lembrar)
PRECISAM_DE_ROTINA = {
    "tools.sei_reparar_vazios":
        "recupera texto de documento vazio a partir do PDF já em cache — de graça, sem tocar o "
        "SEI; ficou 11 dias sem caller",
    "tools.sei_reparar_truncados":
        "devolve à fila o que foi cortado no cap de 20k, medindo o alvo a cada rodada",
    "tools.tac_ranking_ugs":
        "recalcula o ranking de pagamento fora de contrato regular; o JSON envelhece a cada "
        "ingestão de OB",
    "tools.sei_cpf_sweep":
        "enriquecimento de CPF a partir dos processos capturados",
    # Terceira mordida da mesma família, em 2026-08-05: `sei_sweep --recaptura` existia desde
    # 2026-08-03 e NENHUM agendamento o acionava. A fila de 540 processos com documento sem texto
    # lido não tinha quem a drenasse — e nela estava o nº 1 da fila do fiscal
    # (SEI-270131/000548/2023: árvore de 65, 40 lidos). Recapturado à mão, ele saiu de
    # NAO_AVALIAVEL para EXTREMO 94,9, o mais alto do acervo. O modo entrou no `sweep_sei.sh`,
    # sequencial e depois do sweep normal, porque a sessão itkava é única.
    # Quarta mordida (2026-08-06): a ferramenta que vigia a QUALIDADE do que os pipelines
    # produzem estava fora de qualquer agendamento. Quem vigia o vigia?
    "tools.sentinela_integridade":
        "vigia a QUALIDADE do que os pipelines produzem (texto cortado, anexo serializado, "
        "leitura devolvendo 0 docs); sem rotina, o defeito só aparece quando alguém tropeça nele",
    # Quinta mordida (2026-08-06): `osint/persistencia.salvar_grafo` estava escrita e testada, e as
    # tabelas `pessoas`/`relacionamentos` a ZERO — sem caller, o grafo se desfazia a cada execução.
    # Precisa de rotina porque o universo tem 5.615 credores e a passada é em fatia.
    "tools.grafo_persistir":
        "persiste o grafo de vínculos dos credores do SIAFE em fatias; sem rotina, as 5.615 "
        "empresas nunca terminam de ser percorridas e o grafo nunca sobrevive à execução",
    # Sexta mordida da familia 8 seria esta: o verificador que CLICA em cada metrica do painel e
    # confere com a gaveta. Sem rotina, a divergencia so aparece quando alguem tropeca nela — e ela
    # ja apareceu duas vezes no mesmo dia (68 vs 55 e 647 vs 0).
    "tools.painel_drill_check":
        "clica cada metrica clicavel do painel e compara com as linhas da gaveta; sem rotina, "
        "metrica que mente volta em silencio a cada mudanca de rota ou de limite de pagina",
    "tools.osint_x_processos":
        "liga a fila de agente publico aos processos ja lidos; as DUAS pontas mudam (fichas novas "
        "a cada sweep SEI, fila nova a cada dump da Receita) e sem rotina a correlacao envelhece",
    "tools.empresas_rj_build":
        "razão social e natureza jurídica das 5,86 mi de raízes com estabelecimento; o dump da "
        "Receita é mensal e os ZIPs são apagados ao fim do refresh — fora dele, a tabela envelhece "
        "sem fonte para se refazer",
    "tools.agente_publico_reverso":
        "cruza as folhas que conhecemos com o cadastro nacional de sócios; as DUAS pontas mudam — "
        "a folha a cada competência e o dump da Receita todo mês — e sem rotina o índice envelhece "
        "sem que ninguém perceba",
    "tools.sei_sweep --recaptura":
        "drena a fila de recaptura integral (documento na árvore sem texto lido); sem ela, todo "
        "processo truncado fica truncado para sempre",
}


# AGENDAMENTO NÃO É SÓ `*.sh`. Em 2026-08-06 eu quase dupliquei a `tools.autoauditoria` no
# `sweep_dados.sh` por ter conferido crontab e scripts — e não os DROP-INS DO SYSTEMD. Ela já
# rodava diariamente às 07:10 pelo `ExecStartPost` de
# `~/.config/systemd/user/jfn-intel-cache.service.d/autoauditoria.conf`, com os fingerprints de
# 03, 04, 05 e 06/08 em `data/autoauditoria/` como prova. Duplicar tarefa pesada em VM de 2 vCPU é
# o oposto do conserto. A busca passou a cobrir as três superfícies.
_SYSTEMD = Path.home() / ".config" / "systemd" / "user"


def _scripts_de_sweep() -> str:
    partes = [p.read_text(encoding="utf-8", errors="ignore")
              for p in sorted((RAIZ / "tools").glob("*.sh"))]
    if _SYSTEMD.is_dir():
        partes += [p.read_text(encoding="utf-8", errors="ignore")
                   for p in sorted(_SYSTEMD.rglob("*.service"))]
        partes += [p.read_text(encoding="utf-8", errors="ignore")
                   for p in sorted(_SYSTEMD.rglob("*.conf"))]
    return "\n".join(partes)


@pytest.mark.parametrize("modulo,motivo", sorted(PRECISAM_DE_ROTINA.items()))
def test_ferramenta_periodica_e_citada_por_um_sweep(modulo, motivo):
    corpo = _scripts_de_sweep()
    alvo = modulo.replace("tools.", "")
    assert (modulo in corpo) or (f"tools/{alvo}.py" in corpo), (
        f"`{modulo}` precisa de rotina ({motivo}) e nenhum script de sweep a chama — "
        "é a família 'construído, testado, nunca rodado'")


def test_o_360_avalia_sem_NENHUMA_ia():
    """O caminho determinístico não pode depender de LLM. `avaliar()` só chama IA com
    `com_llm=True`, e o lote do cron NÃO passa esse sinalizador: com as chaves ausentes, o motor
    continua produzindo faixa, achados e lacunas. É o que garante o sistema rodando com uma IA
    fraca — ou sem nenhuma."""
    import inspect

    from compliance_agent import processo_360

    assinatura = inspect.signature(processo_360.avaliar)
    assert assinatura.parameters["com_llm"].default is False

    fonte = (RAIZ / "tools" / "sweep_360.sh").read_text(encoding="utf-8")
    linha = [ln for ln in fonte.splitlines() if "processo_360.py --lote" in ln]
    assert linha, "o sweep_360 deixou de rodar o lote determinístico"
    assert "--com-llm" not in linha[0], (
        "o lote do cron passou a exigir IA — o caminho determinístico tem de sobreviver sem ela")


def test_a_pipeline_pos_correcao_nao_exige_ia():
    """`tools/pos_correcao` é o comando único depois de mexer num detector; se ele dependesse de
    LLM, a convergência do acervo passaria a depender de cota de API."""
    fonte = (RAIZ / "tools" / "pos_correcao.py").read_text(encoding="utf-8")
    assert "com_llm=True" not in fonte
    assert "avaliar(" in fonte
