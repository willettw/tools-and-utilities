#!/bin/bash
# encrypt_roster_password.sh - Helper script to encrypt SQL passwords for processRoster.py

KEY_FILE="$HOME/.processRoster.key"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if Python and cryptography are available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

# Create Python script to encrypt password
read -sp "Enter SQL password to encrypt: " PASSWORD
echo

python3 << EOF
from cryptography.fernet import Fernet
from pathlib import Path
import sys

key_file = Path('$KEY_FILE')

# Generate or load key
if not key_file.exists():
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    print(f"Generated new encryption key: {key_file}", file=sys.stderr)
else:
    key = key_file.read_bytes()

# Encrypt password
cipher = Fernet(key)
encrypted = cipher.encrypt('$PASSWORD'.encode()).decode()

print("\nEncrypted password (copy this to your processRoster.yml file):")
print(f"encrypted:{encrypted}")
print(f"\nKey file: {key_file}")
EOF

echo -e "\nUsage in processRoster.yml:"
echo "sql_password: \"encrypted:<paste-encrypted-string-here>\""
