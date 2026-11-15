"""Generate local passwords without displaying them. Never overwrite an existing .env."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env'
if path.exists():
    print('.env already exists; kept unchanged.')
else:
    content = (root / '.env.example').read_text()
    lines = []
    for line in content.splitlines():
        name = line.split('=', 1)[0]
        if name in ('SQLSERVER_PASSWORD', 'MSSQL_SA_PASSWORD', 'ORACLE_PASSWORD', 'ORACLE_PWD'):
            line = name + '=Lab_A1!' + secrets.token_hex(18)
        lines.append(line)
    path.write_text('\n'.join(lines) + '\n')
    path.chmod(0o600)
    print('Created .env with separate random passwords. Set your GCP project before running the agent.')
