"""Analisa as 258 OBs e atualiza o relatório."""

if __name__ == "__main__":
    import os
    import json
    import sqlite3
    from pathlib import Path
    from collections import defaultdict, Counter

    # Portável: JFN_DATA_DIR (env) > <repo>/data (no Windows = C:\JFN\jfn\data)
    _data = Path(os.environ.get("JFN_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    db_path = _data / "compliance.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, numero_ob, data_emissao, valor, favorecido_nome, favorecido_cpf,
                   ug_codigo, ug_nome, numero_processo, numero_sei, categoria, status, tipo_ob
            FROM ordens_bancarias
            ORDER BY data_emissao DESC, id DESC
            """
        ).fetchall()
        obs = [dict(r) for r in rows]
    finally:
        conn.close()

    total = len(obs)
    valores = [o["valor"] for o in obs if o["valor"] is not None]
    valor_total = sum(valores)
    valor_medio = valor_total / len(valores) if valores else 0.0

    sem_processo = [o for o in obs if not o.get("numero_processo")]
    sem_sei = [o for o in obs if not o.get("numero_sei")]
    
    obras = [o for o in obs if (o.get("categoria") or "").lower() == "obras"]
    valores_obras = [o["valor"] for o in obras if o["valor"] is not None]
    valor_obras = sum(valores_obras)

    # Concentração por favorecido/UG
    chaves = defaultdict(list)
    for o in obs:
        chave = f"{(o.get('favorecido_nome') or '').strip()}|{(o.get('ug_codigo') or '').strip()}"
        chaves[chave].append(o)

    concentrados = []
    for chave, itens in chaves.items():
        if len(itens) >= 3:
            concentrados.append((chave, len(itens), sum(i["valor"] or 0 for i in itens)))

    concentrados.sort(key=lambda x: x[1], reverse=True)

    # Valores redondos
    redondos = []
    for o in obs:
        v = o.get("valor")
        if v is not None and abs(v - round(v, -2)) < 50.0 and v >= 5000:
            redondos.append(o)

    report = f"""# Relatório Geral das OBs — JFN

Total de OBs: {total}
Valor total: R$ {valor_total:,.2f}
Valor médio: R$ {valor_medio:,.2f}

Sem processo SEI/numero_processo: {len(sem_processo)}
Sem SEI: {len(sem_sei)}

OBs categorizadas como obras: {len(obras)}
Valor total de obras: R$ {valor_obras:,.2f}

Concentrações suspeitas (mesmo favorecido + UG, >= 3 pagamentos): {len(concentrados)}
- {chr(10).join([f'  {c[0]}: {c[1]} pagamentos, R$ {c[2]:,.2f}' for c in concentrados[:5]])}

Valores redondos suspeitos (>= R$ 5.000,00): {len(redondos)}
- {chr(10).join([f"  {o['numero_ob']} R$ {o['valor']:,.2f} ({o['favorecido_nome']})" for o in redondos[:5]])}
"""

    out_path = Path(__file__).resolve().parent / "relatorio_geral_obs.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print("OK")
    print(report)
