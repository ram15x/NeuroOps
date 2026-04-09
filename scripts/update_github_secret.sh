#!/bin/bash
# Update GitHub secret when EC2 IP changes

CURRENT_IP=$(curl -s http://checkip.amazonaws.com)
echo "Current EC2 IP: $CURRENT_IP"

# You need GitHub CLI installed
# gh secret set EC2_HOST --body "$CURRENT_IP" --repo ram15x/NeuroOps

# Or manual instruction
echo ""
echo "⚠️ EC2 IP may have changed!"
echo "Current IP: $CURRENT_IP"
echo ""
echo "To update GitHub secret:"
echo "1. Go to: https://github.com/ram15x/NeuroOps/settings/secrets/actions"
echo "2. Update EC2_HOST value to: $CURRENT_IP"
echo ""
echo "Or install GitHub CLI and run:"
echo "gh secret set EC2_HOST --body \"$CURRENT_IP\" --repo ram15x/NeuroOps"
