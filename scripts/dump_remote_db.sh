#!/bin/bash
set -e

# ==============================================================================
# Remote MariaDB Dump Tool (Docker-based)
# ==============================================================================
# Usage: ./scripts/dump_remote_db.sh <HOST> <PORT> <USER> <PASSWORD> <DB_NAME>
# Example: ./scripts/dump_remote_db.sh 192.168.1.10 3307 root mypassword stock_db

HOST=$1
PORT=$2
USER=$3
PASS=$4
DB_NAME=$5

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ -z "$DB_NAME" ]; then
    echo -e "${RED}Usage: $0 <HOST> <PORT> <USER> <PASSWORD> <DB_NAME>${NC}"
    echo "Example: $0 host.docker.internal 3307 root mypass stock_db"
    exit 1
fi

OUTPUT_FILE="docker/init/init_dump.sql"

echo -e "${YELLOW}================================================================${NC}"
echo -e "${YELLOW} 🐘 Remote MariaDB Dump Tool${NC}"
echo -e "${YELLOW}================================================================${NC}"
echo -e "Target: ${GREEN}${USER}@${HOST}:${PORT}/${DB_NAME}${NC}"
echo -e "Output: ${GREEN}${OUTPUT_FILE}${NC}"
echo ""

echo -e "${YELLOW}⏳ Dumping database... (This may take a while)${NC}"

# Ensure output directory exists
mkdir -p docker/init

# Run mysqldump via Docker container
# --protocol=tcp is crucial for some setups
docker run --rm --network host \
    mariadb:10.11 \
    mysqldump \
    -h "$HOST" \
    -P "$PORT" \
    -u "$USER" \
    -p"$PASS" \
    --protocol=tcp \
    --single-transaction \
    --quick \
    "$DB_NAME" > "$OUTPUT_FILE"

echo -e "${GREEN}✅ Check dump file size:${NC}"
ls -lh "$OUTPUT_FILE"

echo -e "\n${GREEN}🚀 Dump Complete! You can now run install_prime.sh${NC}"
