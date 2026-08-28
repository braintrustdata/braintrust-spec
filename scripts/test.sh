#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# TODO: we can verify valid test/semconv yaml once things mature more

python -m unittest discover -s scripts -p 'test_*.py'
python scripts/validate-capabilities.py
python scripts/compatibility_csv.py --check
