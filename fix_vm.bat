@echo off
echo Corrigindo e rodando criar_vm.py...
echo.

REM Corrige o caminho da chave no arquivo antigo (se existir)
python -c "import glob,os; f=open('C:\\JFN\\criar_vm.py',encoding='utf-8').read(); keys=[k for k in glob.glob('C:\\JFN\\*.pem') if 'public' not in k.lower()]; fixed=f.replace('oci_key.pem', os.path.basename(keys[0])) if keys else f; open('C:\\JFN\\criar_vm.py','w',encoding='utf-8').write(fixed); print('OK: chave atualizada para', os.path.basename(keys[0]) if keys else 'nenhuma encontrada')" 2>nul

REM Roda o script corrigido
python C:\JFN\criar_vm.py
pause
