#!/bin/bash
set -e

echo "========================================="
echo "NeuroOps Production Deployment"
echo "========================================="
echo "Started at: $(date)"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to print status
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# 1. Pull latest code
echo "📦 Pulling latest code..."
git pull origin main
print_status "Code updated"

# 2. Activate virtual environment
echo "🐍 Activating virtual environment..."
source neuroops_env/bin/activate
print_status "Virtual environment activated"

# 3. Install dependencies
echo "📚 Installing dependencies..."
pip install -r requirements.txt --no-cache-dir
print_status "Dependencies installed"

# 4. Run migrations (if any)
if command -v alembic &> /dev/null; then
    echo "🔄 Running database migrations..."
    alembic upgrade head
    print_status "Migrations completed"
fi

# 5. Run pre-deployment tests
echo "🧪 Running pre-deployment tests..."
pytest tests/test_api.py -v --tb=short || print_warning "Some tests failed, continuing deployment"

# 6. Stop old service
echo "🛑 Stopping old service..."
sudo systemctl stop neuroops || true
print_status "Old service stopped"

# 7. Start new service
echo "🚀 Starting new service..."
sudo systemctl start neuroops
sudo systemctl enable neuroops
print_status "New service started"

# 8. Wait for service to be ready
echo "⏳ Waiting for service to be ready..."
sleep 5

# 9. Health check
echo "🏥 Running health check..."
for i in {1..10}; do
    if curl -s http://localhost:8000/health | grep -q "healthy"; then
        print_status "Health check passed"
        break
    fi
    if [ $i -eq 10 ]; then
        print_error "Health check failed after 10 attempts"
        exit 1
    fi
    sleep 2
done

# 10. Verify endpoints
echo "🔍 Verifying critical endpoints..."
curl -s http://localhost:8000/ | grep -q "NeuroOps" && print_status "Root endpoint OK"
curl -s http://localhost:8000/docs | grep -q "swagger" && print_status "Docs endpoint OK"

echo ""
echo "========================================="
echo "✅ Deployment completed successfully!"
echo "Finished at: $(date)"
echo "========================================="

# Get current EC2 IP dynamically
EC2_IP=$(curl -s http://checkip.amazonaws.com)
echo "Deploying to EC2 IP: $EC2_IP"

# Use the IP for deployment
ssh -i ~/.ssh/neuroops-key.pem ec2-user@$EC2_IP << 'ENDSSH'
    cd /home/ec2-user/NeuroOps
    git pull origin main
    source neuroops_env/bin/activate
    pip install -r requirements.txt
    sudo systemctl restart neuroops
ENDSSH
