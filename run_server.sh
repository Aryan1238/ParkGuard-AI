#!/bin/bash
# Start script for AI No-Parking Monitoring System

echo "=================================================================="
echo "    PARKGUARD AI - NO-PARKING SURVEILLANCE & ENFORCEMENT SYSTEM    "
echo "=================================================================="
echo "Starting Flask Server on http://localhost:5000 ..."
echo ""

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

./venv/bin/python app.py
