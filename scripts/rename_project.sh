#!/bin/bash
set -e

# ==============================================================================
# Project Rename Script
# ==============================================================================
# Usage: ./scripts/rename_project.sh <OLD_NAME> <NEW_NAME>
# Example: ./scripts/rename_project.sh my-prime-jennie our-prime-jennie

OLD_NAME=$1
NEW_NAME=$2

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ -z "$OLD_NAME" ] || [ -z "$NEW_NAME" ]; then
    echo -e "${RED}Error: Usage: $0 <OLD_NAME> <NEW_NAME>${NC}"
    echo "Example: $0 my-prime-jennie our-prime-jennie"
    exit 1
fi

echo -e "${YELLOW}================================================================${NC}"
echo -e "${YELLOW} 🔄 Project Renaming Tool${NC}"
echo -e "${YELLOW}================================================================${NC}"
echo -e "Old Name: ${RED}${OLD_NAME}${NC}"
echo -e "New Name: ${GREEN}${NEW_NAME}${NC}"
echo ""
echo -e "${YELLOW}⚠️  WARNING: This will replace ALL occurrences of '${OLD_NAME}' with '${NEW_NAME}' in this directory.${NC}"
read -p "Are you sure you want to proceed? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo -e "\n${YELLOW}[1/3] Replacing text content in files...${NC}"

# Find and replace text in files
# Excludes .git, .venv, __pycache__, node_modules, and binary files
grep -rIl "${OLD_NAME}" . \
    --exclude-dir=.git \
    --exclude-dir=.venv \
    --exclude-dir=.idea \
    --exclude-dir=.vscode \
    --exclude-dir=__pycache__ \
    --exclude-dir=node_modules \
    --exclude-dir=.gemini \
    --exclude="*.png" \
    --exclude="*.jpg" \
    --exclude="*.pyc" \
    --exclude="LICENSE" | while read -r file; do
    
    echo "Processing: $file"
    # Use sed for replacement.
    # macOS requires an empty string for -i, Linux does not.
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/${OLD_NAME}/${NEW_NAME}/g" "$file"
    else
        sed -i "s/${OLD_NAME}/${NEW_NAME}/g" "$file"
    fi
done

echo -e "${GREEN}✓ Text replacement complete.${NC}"

echo -e "\n${YELLOW}[2/3] Renaming specific files and directories...${NC}"

# 1. Systemd Service File
OLD_SERVICE_FILE="infrastructure/${OLD_NAME}.service"
NEW_SERVICE_FILE="infrastructure/${NEW_NAME}.service"

if [ -f "$OLD_SERVICE_FILE" ]; then
    echo "Renaming service file: $OLD_SERVICE_FILE -> $NEW_SERVICE_FILE"
    mv "$OLD_SERVICE_FILE" "$NEW_SERVICE_FILE"
else
    echo "Skipping service file rename (not found: $OLD_SERVICE_FILE)"
fi

# 2. Logs Directory (if exists)
OLD_LOG_DIR="logs/${OLD_NAME}"
NEW_LOG_DIR="logs/${NEW_NAME}"
if [ -d "$OLD_LOG_DIR" ]; then
    echo "Renaming log directory: $OLD_LOG_DIR -> $NEW_LOG_DIR"
    mv "$OLD_LOG_DIR" "$NEW_LOG_DIR"
fi

echo -e "${GREEN}✓ File renaming complete.${NC}"

echo -e "\n${YELLOW}[3/3] Final Verification hints${NC}"
echo -e "1. Please check 'shared/version.py' to ensure PROJECT_NAME is updated."
echo -e "2. Check 'docker-compose.yml' labels."
echo -e "3. Manual check recommended: grep -r \"${OLD_NAME}\" ."

echo -e "\n${GREEN}🚀 Project rename from '${OLD_NAME}' to '${NEW_NAME}' finished!${NC}"
