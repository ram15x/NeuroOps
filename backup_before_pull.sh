#!/bin/bash
BACKUP_DIR="/home/ec2-user/NeuroOps_backups/pre_pull"
mkdir -p $BACKUP_DIR
TIMESTAMP=$(date +\%Y\%m\%d_\%H\%M\%S)
sudo -u postgres pg_dump neuroops_db > $BACKUP_DIR/neuroops_db_${TIMESTAMP}.sql
echo "Pre-pull backup created: ${TIMESTAMP}"
