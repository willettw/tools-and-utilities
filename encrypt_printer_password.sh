#!/bin/bash
# Helper script to encrypt password for get_printer_ip.yml

cd "$(dirname "$0")"
./get_printer_ip.py --encrypt-password
