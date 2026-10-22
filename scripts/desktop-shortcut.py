"""Install a per-user shortcut to this source checkout; no administrator needed."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if os.name=='nt':
    # VBScript string literals use doubled quotes; arguments never pass through a shell.
    def vb(value):return '"'+str(value).replace('"','""')+'"'
    desktop=Path.home()/'Desktop';desktop.mkdir(exist_ok=True)
    target=ROOT/'scripts'/'start-windows.cmd'
    script=ROOT/'.venv'/'shortcut.vbs'
    script.write_text('\n'.join(['Set sh = CreateObject("WScript.Shell")','Set link = sh.CreateShortcut('+vb(desktop/'CurveDesk.lnk')+')','link.TargetPath = '+vb(target),'link.WorkingDirectory = '+vb(ROOT),'link.Save']))
    subprocess.run(['cscript','//NoLogo',str(script)],check=True);script.unlink()
else:
    apps=Path.home()/'.local/share/applications';apps.mkdir(parents=True,exist_ok=True)
    def desktop_quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
    (apps/'curvedesk.desktop').write_text('\n'.join(['[Desktop Entry]','Type=Application','Name=CurveDesk','Comment=Commodity spread and ratio research','Exec='+desktop_quote(sys.executable)+' -m curvedesk.launcher','Path='+str(ROOT),'Icon='+str(ROOT/'static/icon.svg'),'Terminal=false','Categories=Finance;Office;','']))
print('CurveDesk shortcut installed.')
