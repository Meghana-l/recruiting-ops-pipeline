#!/usr/bin/env bash
# Runs the whole pipeline end to end.
set -e
python src/generate_data.py
echo
python src/pipeline.py
echo
python src/quality_checks.py
echo
python src/build_dashboard.py
