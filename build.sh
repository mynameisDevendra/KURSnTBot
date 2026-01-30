#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install system dependencies (Poppler)
# Note: This might require a custom Docker environment on some plans,
# but try this standard build command first if you are on a standard environment.
pip install --upgrade pip
pip install -r requirements.txt