from __future__ import print_function
import sys

print('PY', sys.version)

# DB
try:
    from compliance_agent.database.models import get_session, init_db
    init_db()
    s = get_session()
    print('DB_OK')
    s.close()
except Exception as e:
    print('DB_ERR:', repr(e))

# Goal import
try:
    from compliance_agent.hermes_goal import HermesGoalAgent
    print('GOAL_OK')
except Exception as e:
    print('GOAL_ERR:', repr(e))

# TXT export
try:
    from compliance_agent.reporting.export_relatorios import generate_report
    r = generate_report('txt')
    print('TXT:', r.get('path', 'missing'))
except Exception as e:
    print('TXT_ERR:', repr(e))

# HTML interface
import os
p = os.path.join('static', 'hermes.html')
print('WEB:', p if os.path.exists(p) else 'missing')
