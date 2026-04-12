#!/bin/bash
# NeuroOps S3 Backup Script
# Backs up PostgreSQL database and ML models to S3

set -e

BUCKET="neuroops-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/tmp/neuroops_backup_$TIMESTAMP"
DB_NAME="neuroops_db"
DB_USER="postgres"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================="
echo "   NeuroOps S3 Backup"
echo "========================================="
echo "Started: $(date)"
echo ""

mkdir -p "$BACKUP_DIR"

# 1. Backup PostgreSQL
echo "📦 Backing up database..."
if PGPASSWORD="postgres" pg_dump -h localhost -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/db_$TIMESTAMP.sql"; then
    gzip "$BACKUP_DIR/db_$TIMESTAMP.sql"
    echo -e "${GREEN}✅ Database backup complete${NC}"
else
    echo -e "${RED}❌ Database backup failed${NC}"
    exit 1
fi

# 2. Backup ML Models
echo "📦 Backing up ML models..."
mkdir -p "$BACKUP_DIR/models"
cp ml_models/saved/*.pkl "$BACKUP_DIR/models/" 2>/dev/null || true
echo -e "${GREEN}✅ Models backup complete${NC}"

# 3. Backup Redis (optional - dump.rdb)
echo "📦 Backing up Redis..."
if redis-cli save &>/dev/null; then
    cp /var/lib/redis/dump.rdb "$BACKUP_DIR/redis_$TIMESTAMP.rdb" 2>/dev/null || true
    echo -e "${GREEN}✅ Redis backup complete${NC}"
else
    echo -e "${YELLOW}⚠️ Redis backup skipped${NC}"
fi

# 4. Upload to S3
echo "📤 Uploading to S3..."
aws s3 cp "$BACKUP_DIR/db_$TIMESTAMP.sql.gz" "s3://$BUCKET/database/db_$TIMESTAMP.sql.gz" --quiet
aws s3 sync "$BACKUP_DIR/models/" "s3://$BUCKET/models/" --quiet
aws s3 cp "$BACKUP_DIR/redis_$TIMESTAMP.rdb" "s3://$BUCKET/redis/redis_$TIMESTAMP.rdb" --quiet 2>/dev/null || true

echo -e "${GREEN}✅ Upload complete${NC}"

# 5. Cleanup old backups (keep last 7 days)
echo "🧹 Cleaning old backups..."
aws s3 ls "s3://$BUCKET/database/" | grep ".sql.gz" | sort -r | tail -n +8 | awk '{print $4}' | xargs -I {} aws s3 rm "s3://$BUCKET/database/{}" --quiet 2>/dev/null || true

# Cleanup temp files
rm -rf "$BACKUP_DIR"

echo ""
echo "========================================="
echo -e "${GREEN}✅ Backup completed: $TIMESTAMP${NC}"
echo "========================================="