"""Run only this lab's Compose project, including Docker Desktop from WSL."""
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
docker = shutil.which('docker')
if not docker:
    candidate = Path('/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe')
    if candidate.exists():
        docker = str(candidate)
if not docker:
    raise SystemExit('Install and start Docker or Docker Desktop first.')

def host_path(path):
    if docker.endswith('.exe'):
        return subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
    return str(path)

action = sys.argv[1] if len(sys.argv) > 1 else 'status'
commands = {'up': ['up', '-d'], 'stop': ['stop'], 'status': ['ps']}
if action not in commands:
    raise SystemExit('Usage: python scripts/containers.py [up|status|stop]')
raise SystemExit(subprocess.call([docker, 'compose', '--project-name', 'healthcare-integration-lab',
    '--env-file', host_path(root / '.env'), '-f', host_path(root / 'compose.yaml'), *commands[action]], cwd=root))
