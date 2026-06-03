from __future__ import print_function
import asyncio, os, sys

sys.path.insert(0, '.')
os.chdir('C:/JFN/jfn')

print('PY:', sys.version.split()[0])

try:
    from compliance_agent.llm.free_llm import qwen_chat_async, best_free_chat_async
    ans = asyncio.run(best_free_chat_async('Diga OK.', '', smart=False))
    print('QWEN:', repr(ans.strip()))
except Exception as e:
    print('QWEN_ERR:', repr(e))

try:
    print('OPENROUTER_KEY:', os.environ.get('OPENROUTER_API_KEY','')[:8])
except Exception as e:
    print('OPENROUTER_KEY_ERR:', repr(e))

try:
    import compliance_agent.llm.memoria as _m
    print('MEMORIA_OK:', True)
except Exception as e:
    print('MEMORIA_ERR:', repr(e))

try:
    import compliance_agent.llm.hermes_agent as _h
    print('HERMES_AGENT_OK:', True)
except Exception as e:
    print('HERMES_AGENT_ERR:', repr(e))

try:
    from compliance_agent.llm.free_llm import best_free_chat
    print('BEST_CHAT:', repr(best_free_chat('ping', fallback='FALLBACK').strip()))
except Exception as e:
    print('BEST_CHAT_ERR:', repr(e))
