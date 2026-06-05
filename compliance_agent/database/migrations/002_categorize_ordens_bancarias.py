
import json
import re
from sqlalchemy import text
from sqlalchemy.orm import Session
from compliance_agent.database.models import OrdemBancaria

CATEGORIAS_OB = {
    "obras": ["obra", "reforma", "construção", "pavimentação", "calçamento", "engenharia", "edificação", "infra", "obra civ", "construc"],
    "alimentação": ["alimentação", "refeição", "marmita", "kit lanche", "merenda", "gêneros alimentícios", "aliment", "restaurante", "alimentos"],
    "veículos": ["veículo", "carro", "automóvel", "caminhão", "ônibus", "van", "ambulância", "viatura"],
    "combustível": ["combustível", "diesel", "gasolina", "etanol", "abastecimento"],
    "informática": ["computador", "notebook", "laptop", "servidor", "impressora", "informática", "ti ", "software", "dados", "tecnologia"],
    "limpeza": ["limpeza", "higienização", "conservação", "faxina", "material de limpeza"],
    "saúde": ["medicamento", "remédio", "material hospitalar", "equipamento médico", "insumo médico", "hospitalar", "clínica", "médico", "consulta"],
    "segurança": ["vigilância", "segurança", "monitoramento", "câmera", "cftv"],
    "consultoria": ["consultoria", "assessoria", "treinamento", "capacitação", "curso", "serviço técnico"],
    "mobiliário": ["móvel", "cadeira", "mesa", "armário", "arquivo", "estante"],
    "telefonia": ["telefonia", "internet", "link dedicado", "banda larga", "telecomunicação"],
    "transporte": ["transporte", "fretamento", "passagem", "locomoção", "translado"],
}

UG_KEYWORDS = {
    "obras": {
        "codes": {"045200", "044100", "431200"},
        "hints": ["obras", "engenharia", "infra", "secretaria de obras", "pavimentação"],
    },
    "saúde": {
        "codes": {"139100", "139200", "139300"},
        "hints": ["saúde", "hospital", "upa", "unidade de saúde"],
    },
    "educação": {
        "codes": {"975100", "975200", "976100"},
        "hints": ["educação", "escola", "merenda", "alimentação escolar"],
    },
    "segurança": {
        "codes": {"350100", "351100", "351200"},
        "hints": ["segurança", "polícia", "PMERJ"],
    },
    "transporte": {
        "codes": {"490100", "490200"},
        "hints": ["transporte", "DER", "rodovia"],
    }
}

CODIGO_SEM_NOME = {"404310", "404400", "135400"}


def _extrair_codigos_sei(obj: str | None) -> list[str]:
    if not obj:
        return []
    try:
        data = json.loads(obj)
        text = " ".join(str(v) for v in data.values() if v is not None)
    except Exception:
        text = obj or ""
    return re.findall(r"\b\d{6}/\d{4,6}/\d{4,6}\b", text)


def _categorizar_ob(ob) -> str:
    texto = " ".join(filter(None, [
        ob.favorecido_nome or "",
        ob.observacao or "",
        ob.raw_json or "",
    ])).lower()
    texto_raw = " ".join(filter(None, [ob.observacao or "", ob.raw_json or ""]))

    # 1. Regras explícitas por chaves do JSON
    try:
        data = json.loads(ob.raw_json or "{}")
        objeto = " ".join(str(v) for v in data.values() if v is not None).lower()
        for cat, rules in (
            ("obras", ["obra", "reforma", "construção", "pavimentação", "engenharia", "calçamento"]),
            ("alimentação", ["alimentação", "refeição", "marmita", "merenda", "aliment"]),
            ("saúde", ["saúde", "hospitalar", "clínica", "médico", "consulta"]),
            ("segurança", ["segurança", "vigilância", "monitoramento"]),
        ):
            if any(k in objeto for k in rules):
                return cat
    except Exception:
        pass

    # 2. Palavras-chave diretas no texto livre
    for cat, keywords in CATEGORIAS_OB.items():
        for kw in keywords:
            if kw in texto:
                return cat

    # 3. Refino por órgão quando já conhecemos a função típica, mas o texto não deu match
    ug_codigo = (ob.ug_codigo or "").strip()
    ug_nome = (ob.ug_nome or "").strip()
    for cat, rules in UG_KEYWORDS.items():
        if ug_codigo in rules["codes"] or any(h in texto for h in rules["hints"]):
            return cat

    # 4. Se houver referência a SEI/OB/documentos, marcamos como "gestao" para diferenciar de vazio
    if _extrair_codigos_sei(ob.raw_json) or re.search(r"\b\d{6}OB\d+\b", texto_raw or ""):
        return "gestao"

    return "outros"


def upgrade(session: Session):
    print("Executando migração: 002_categorize_ordens_bancarias")
    try:
        session.execute(text("ALTER TABLE ordens_bancarias ADD COLUMN categoria VARCHAR(50)"))
        session.commit()
    except Exception:
        session.rollback()

    updated = 0
    for ob in session.query(OrdemBancaria).all():
        cat = _categorizar_ob(ob)
        if ob.categoria != cat:
            ob.categoria = cat
            session.add(ob)
            updated += 1
    session.commit()
    print(f"Migração 002 concluída. {updated} OBs categorizadas/atualizadas.")

def downgrade(session: Session):
    print("Revertendo migração: 002_categorize_ordens_bancarias")
    session.query(OrdemBancaria).update({OrdemBancaria.categoria: None})
    session.commit()
