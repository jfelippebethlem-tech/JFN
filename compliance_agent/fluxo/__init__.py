# -*- coding: utf-8 -*-
"""Motor de fluxo `jfn-fluxo` (plano mestre v2 §3.3; ADR-012): fila durável no PostgreSQL da VM-2 (schema `fluxo`),
um supervisor por máquina que SÓ escolhe (o trabalho roda em subprocesso isolado), planejador eleito por advisory
lock e governador de capacidade pelo PSI. Substitui cron, timers, despachante e supervisores avulsos (O2).

Peças:
    schema       aplica/verifica deploy/vm2/postgres/fluxo_*.sql
    fila         enfileirar · reservar · heartbeat · concluir · falhar · recuperar_vencidos
    governador   PSI + disco + swap → slots livres por recurso (funções puras)
    planejador   liderança, agenda → jobs, eventos → jobs dependentes, leases, saúde honesta
    supervisor   o laço por máquina; executar = o processo-filho que roda o estágio
"""
