"""Launch a locally installed X32-Edit from a loopback browser session."""

import ipaddress
import os
from pathlib import Path
import shutil
import subprocess
import sys


def is_local_client(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def editor_command():
    if sys.platform == "darwin":
        for folder in (Path('/Applications'), Path.home() / 'Applications'):
            for name in ('X32-Edit.app', 'X32 Edit.app'):
                app = folder / name
                if app.is_dir():
                    return ['open', str(app)]
    for name in ('X32-Edit', 'x32-edit', 'X32-Edit.exe'):
        executable = shutil.which(name)
        if executable:
            return [executable]
    if sys.platform == 'win32':
        for root in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            folder = os.environ.get(root)
            if folder:
                for relative in ('X32-Edit/X32-Edit.exe', 'Behringer/X32-Edit/X32-Edit.exe'):
                    executable = Path(folder) / relative
                    if executable.is_file():
                        return [str(executable)]
    return None


def open_editor(host):
    if not is_local_client(host):
        raise ValueError('Open X32-Edit is available on the StageAble computer only')
    command = editor_command()
    if not command:
        raise ValueError('X32-Edit was not found. Install it in Applications or add it to PATH.')
    subprocess.Popen(command, shell=False)
    return {'opened': True}
