#!/bin/bash
# build.sh

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install

# Optional: Verify installation
playwright --version