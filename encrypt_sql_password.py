#!/usr/bin/env python3
"""
encrypt_sql_password.py - Encrypt SQL Server password for use with excel_to_sql_import.py

This utility encrypts a password and saves it to a file that can be referenced
in the excel_to_sql_import.yml configuration file.

USAGE:
    python encrypt_sql_password.py

The script will:
1. Prompt you to enter the password (hidden input)
2. Generate an encryption key if one doesn't exist (~/.sql_encryption_key)
3. Encrypt the password
4. Save it to ~/.sql_encrypted_password (or custom location)

Then update your excel_to_sql_import.yml:
    destination:
      username: "your_username"
      encrypted_password_file: "~/.sql_encrypted_password"
"""

import sys
import getpass
from pathlib import Path
from cryptography.fernet import Fernet


def get_encryption_key() -> bytes:
    """Get or create encryption key."""
    key_file = Path.home() / '.sql_encryption_key'
    
    if key_file.exists():
        with open(key_file, 'rb') as f:
            return f.read()
    else:
        # Generate new key
        key = Fernet.generate_key()
        # Save with restricted permissions
        key_file.touch(mode=0o600)
        with open(key_file, 'wb') as f:
            f.write(key)
        print(f"Generated new encryption key: {key_file}")
        return key


def encrypt_password(password: str, output_file: Path) -> None:
    """Encrypt password and save to file."""
    key = get_encryption_key()
    fernet = Fernet(key)
    
    encrypted_password = fernet.encrypt(password.encode())
    
    # Save with restricted permissions
    output_file.touch(mode=0o600)
    with open(output_file, 'wb') as f:
        f.write(encrypted_password)
    
    print(f"Password encrypted and saved to: {output_file}")


def main():
    print("SQL Server Password Encryption Utility")
    print("=" * 50)
    print()
    
    # Get password from user
    password = getpass.getpass("Enter SQL Server password: ")
    
    if not password:
        print("ERROR: Password cannot be empty")
        sys.exit(1)
    
    # Confirm password
    password_confirm = getpass.getpass("Confirm password: ")
    
    if password != password_confirm:
        print("ERROR: Passwords do not match")
        sys.exit(1)
    
    # Get output file
    default_file = Path.home() / '.sql_encrypted_password'
    output_path = input(f"Output file [{default_file}]: ").strip()
    
    if not output_path:
        output_path = default_file
    else:
        output_path = Path(output_path).expanduser()
    
    # Encrypt and save
    try:
        encrypt_password(password, output_path)
        print()
        print("SUCCESS!")
        print()
        print("Update your excel_to_sql_import.yml with:")
        print("  destination:")
        print("    username: \"your_username\"")
        print(f"    encrypted_password_file: \"{output_path}\"")
        print()
        print("(Remove the 'password' field if present)")
        
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
