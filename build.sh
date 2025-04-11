#!/bin/bash
# build.sh

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install

#!/usr/bin/env bash
echo "Installing Playwright browsers..."
playwright install --with-deps

# Optional: Verify installation
playwright --version