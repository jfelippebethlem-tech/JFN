"""Pacote do agente de compliance/auditoria do JFN.

A SENTINELA DO WAL-INDEX sobe aqui, no import, de propósito. A bandeira `SQLITE_FCNTL_PERSIST_WAL`
é consultada por quem FECHA o banco, e 188 arquivos da casa abrem `compliance.db` com `sqlite3` cru
(91 escrevem) — sem file controls na stdlib. Migrar todos quebraria API; instalar UMA sentinela por
PROCESSO resolve com zero mudança de chamador: nenhum processo passa a ser "o último a fechar sem a
bandeira", que é a condição que desvincula `-wal`/`-shm` e deixa o servidor com mapeamento morto
(o "database disk image is malformed" com o arquivo íntegro, 7-14x/dia em 31/07/26).

Nunca levanta: falhar aqui quebraria TODO import da casa. `JFN_SENTINELA_WAL=0` desliga.
Detalhe e medições em `compliance_agent/database/guarda_wal.py`.
"""
# sem captura genérica de propósito: `instalar_automatico` trata a família específica e devolve
# False; a catraca de dívida proíbe captura genérica nova, e engolir erro no import do pacote é o
# jeito mais rápido de esconder um bug real da casa inteira.
from compliance_agent.database.guarda_wal import instalar_automatico as _instalar_sentinela

_SENTINELA_WAL = _instalar_sentinela()
