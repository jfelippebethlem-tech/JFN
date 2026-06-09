import subprocess
import os
from pathlib import Path

def open_chrome_debug():
    exe = None
    for p in [
        Path(os.environ.get('PROGRAMFILES', '')) / 'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Google/Chrome/Application/chrome.exe',
    ]:
        if p.exists():
            exe = p
            break
    if not exe:
        print('Chrome não encontrado.')
        return False
    url = 'https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp'
    user_data = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
    cmd = [str(exe), '--remote-debugging-port=9222', f'--user-data-dir={user_data}', url]
    print('Opening Chrome debug:', ' '.join(cmd))
    subprocess.Popen(cmd)
    return True

if __name__ == '__main__':
    open_chrome_debug()
