"""Repairs supported by native setup errors; retain semantic assertion failures."""
from pathlib import Path
import re
import repairs as H
from adapt import adapt_repository,_replace

def repair(root,repository,jobs,outcomes,bank):
    records=adapt_repository(root,repository,jobs,outcomes,bank)
    for job in jobs:
        old=outcomes[(repository,job['module'],job['test_directory'])]
        joined='\n'.join(e.get('summary','')+' '+e.get('detail','') for e in old.get('errors',[]))
        module=root/job['module']
        files=sorted(set(module.glob('*.tftest.hcl'))|set((module/job['test_directory']).glob('*.tftest.hcl')))
        for p in files:
            text=p.read_text();notes=[]
            if 'invalid partition value' in joined:
                text,n=H.ensure_mock(text,'aws');notes+=n
                text,n=H.add_mock_data(text,'aws','aws_partition','{ partition = "aws", dns_suffix = "amazonaws.com", reverse_dns_prefix = "com.amazonaws" }');notes+=n
            if repository=='platform-design' and job['module']=='terraform/modules/gpu-inference-tgw-connect' and 'transit_gateway_route_table_id must not be empty' in joined:
                text,n=H.add_test_variables(text,{'tgw_route_table_id':'"tgw-rtb-0123456789abcdef0"'});notes+=n
            if repository=='terraform-duplocloud-components' and 'valid UUID' in joined:
                text,n=H.ensure_mock(text,'duplocloud');notes+=n
                text,n=H.add_mock_data(text,'duplocloud','duplocloud_tenant','{ id = "00000000-0000-4000-8000-000000000001" }');notes+=n
            if 'Cannot index a set value' in joined:
                # one(set) retains the asserted property and requires exactly one rule.
                new=re.sub(r'(aws_s3_bucket_server_side_encryption_configuration\.[A-Za-z_][\w]*)\.rule\[0\]',r'one(\1.rule)',text)
                if new!=text:notes.append({'kind':'set_collection_access','reason':'Provider schema represents rule as a set. one() enforces the existing single-rule expectation.'});text=new
            if notes:p.write_text(text);records.extend({'path':str(p),**n} for n in notes)
        if repository=='terraform-duplocloud-components' and job['module'] in {'modules/tenant-data-aws','modules/vpn-data-aws'}:
            for p in (module/'tests').rglob('*.tf'):
                text=p.read_text();new=re.sub(r'(required_version\s*=\s*)"~> 1\.12\.2"',r'\1">= 1.12.2, < 2.0.0"',text)
                if new!=text:p.write_text(new);records.append({'path':str(p),'kind':'test_fixture_engine_compatibility','reason':'Nested test fixture unnecessarily pins patch series 1.12; execution uses recorded engine 1.15.7.'})
        if repository=='platform-design' and job['module']=='terraform/modules/vpc':
            for p in files:
                _replace(p,'module.vpc.single_nat_gateway == false','length(module.vpc.natgw_ids) == length(var.azs)',records,'actual_nat_topology_output','Community module does not export its single_nat_gateway input. HA contract requires one actual NAT gateway per requested AZ.')
                _replace(p,'module.vpc.one_nat_gateway_per_az == true','length(module.vpc.natgw_ids) == length(var.azs)',records,'actual_nat_topology_output','Community module does not export its one_nat_gateway_per_az input. Check the actual NAT gateway topology.')
        if repository=='platform-design' and job['module']=='terraform/modules/gpu-inference-vpc':
            for p in files:
                _replace(p,'module.vpc.vpc_tags["Name"]','module.vpc.name',records,'correct_adapter_output_name','Installed VPC module outputs.tf exports name, not vpc_tags. Corrects the first-pass adapter.')
        if repository=='aws-platform-starter' and job['module'] in {'environments/dev','environments/prod','environments/dr'}:
            # Replace only globals introduced by our previous synthetic-input adapter.
            prior=root.parent/'prior-adapters.json'
            proof=__import__('json').loads(prior.read_text())['changes'] if prior.exists() else []
            generated={(str(Path(c['path'])),c.get('name')) for c in proof if c.get('kind')=='synthetic_required_input'}
            values={'environment':job['module'].split('/')[-1],'public_subnet_cidrs':['10.0.1.0/24','10.0.2.0/24'],'private_subnet_cidrs':['10.0.11.0/24','10.0.12.0/24']}
            for p in files:
                text=p.read_text();edits=[]
                for node in H.blocks(H.root(text)):
                    if H.kind(node)!='variables':continue
                    for attr in H.attributes(node):
                        name=H.attr_name(attr)
                        if name in values and any(n==name and path.endswith('/'+str(p.relative_to(root))) for path,n in generated):
                            expression=__import__('json').dumps(values[name]);edits.append((attr.meta.start_pos,attr.meta.end_pos,name+' = '+expression));records.append({'path':str(p),'kind':'synthetic_input_validation_correction','name':name,'expression':expression,'reason':'Match environment identity and required two-subnet validation; original test inputs retained.'})
                if edits:p.write_text(H.apply(text,edits))
        if repository=='platform-design' and job['module'] in {'terraform/modules/eks','terraform/modules/eks-cluster'}:
            for p in module.glob('*.tf'):
                text=p.read_text()
                # Installed v20 EKS API requires AWS >=5.95,<6. Preserve this API and use its supported provider major.
                new=re.sub(r'(version\s*=\s*)"~> 6\.0"',r'\1"~> 5.95"',text)
                if new!=text:p.write_text(new);records.append({'path':str(p),'kind':'eks_v20_provider_compatibility','reason':'Native dependency solver proved v20 module requires AWS <6; current call sites require v20 module API.'})
    return records
