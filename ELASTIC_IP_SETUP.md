# For Stable Production, Use Elastic IP

Your EC2 public IP changes on restart. To avoid updating GitHub secrets every time:

## Option 1: Allocate Elastic IP (Recommended)
1. AWS Console → EC2 → Elastic IPs → Allocate new address
2. Associate with your instance
3. IP becomes static (free when attached to running instance)

## Option 2: Use Route53 Domain
1. Register a domain (e.g., neuroops.example.com)
2. Create A record pointing to your EC2 IP
3. Update script to use domain instead of IP

## Option 3: Current Setup (IP changes)
- Update EC2_HOST secret manually when IP changes
- Run: `./scripts/update_github_secret.sh` to check current IP
