from backend.services.aws_service import list_ec2_instances
instances = list_ec2_instances()
for inst in instances:
    if inst.get('instance_id') == 'i-00dfb80a59da9a56d':
        print(f"Instance ID: {inst['instance_id']}")
        print(f"Launch Time: {inst.get('launch_time')}")
        print(f"State: {inst.get('state')}")
