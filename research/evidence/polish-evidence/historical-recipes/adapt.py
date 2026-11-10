"""Reviewable execution adapters for the full-corpus repaired cohort."""
from pathlib import Path
import hashlib,json,re,sys
import hcl2
import repairs as H
from fixtures import fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'oasis-recovery-core/src'))
from tfmutate.parser import find_blocks
PURE={'random','local','archive','cloudinit','null','time','tls'}

def graph_requirements(module):
 mapping={};locations=[]
 for p in sorted(module.glob('*.tf')):
  text=p.read_text()
  try:top=H.blocks(H.root(text))
  except Exception:continue
  for n in top:
   if H.kind(n)!='terraform':continue
   for b in H.blocks(H.body(n)):
    if H.kind(b)!='required_providers':continue
    locations.append((p,b))
    for a in H.attributes(b):
     name=H.attr_name(a);src=re.search(r'\bsource\s*=\s*"([^"]+)"',H.span(text,a))
     mapping[name]=src[1] if src else 'hashicorp/'+name
 return mapping,locations

def ensure_requirements(module, additions):
 mapping,locations=graph_requirements(module);needed={n:s for n,s in additions.items() if n not in mapping}
 if not needed:return []
 content='\n'.join('    '+n+' = { source = '+json.dumps(s)+' }' for n,s in needed.items())+'\n'
 if locations:
  assert len(locations)==1,'Multiple required provider blocks need explicit review'
  p,node=locations[0];text=p.read_text();text=H.apply(text,[(node.meta.end_pos-1,node.meta.end_pos-1,'\n'+content)]);p.write_text(text)
 else:
  p=module/'oasis_research_provider_requirements.tf';assert not p.exists();p.write_text('terraform {\n  required_providers {\n'+content+'  }\n}\n')
 return [{'path':str(p),'kind':'explicit_mock_provider_requirement','providers':needed}]

def required_variables(module):
 result={}
 for p in sorted(module.glob('*.tf')):
  text=p.read_text();lines=text.splitlines(keepends=True)
  for block in find_blocks(text):
   if block.kind!='variable':continue
   fragment=''.join(lines[block.start_line-1:block.end_line])
   try:doc=hcl2.loads(fragment)
   except Exception:continue
   for b in doc.get('variable',[]):
    for name,v in b.items():
     name=name.strip('"')
     if 'default' not in v:result[name]=(str(v.get('type','any')),fragment)
 return result

def missing_test_inputs(text, variables, repository):
 tops=H.blocks(H.root(text));globals_=[n for n in tops if H.kind(n)=='variables'];existing=set()
 for b in globals_:existing.update(H.attr_name(a) for a in H.attributes(b))
 direct=[]
 for run in tops:
  if H.kind(run)!='run' or any(H.kind(b)=='module' for b in H.blocks(H.body(run))):continue
  values=set()
  for b in H.blocks(H.body(run)):
   if H.kind(b)=='variables':values.update(H.attr_name(a) for a in H.attributes(b))
  direct.append(values)
 additions={}
 for name,(typ,fragment) in variables.items():
  if name in existing or not direct or all(name in run for run in direct):continue
  value=fixture(typ,name,repository)
  # Respect simple enum validations rather than inventing a forbidden value.
  choice=re.search(r'contains\(\s*(\[[^]]+\])\s*,\s*var\.'+re.escape(name)+r'\b',fragment)
  if choice:
   try:value=json.loads(choice[1])[0]
   except (ValueError,IndexError):pass
  additions[name]=json.dumps(value)
 return additions

def _replace(path,old,new,records,kind,reason):
 if not path.exists():return
 text=path.read_text()
 if old not in text:return
 assert text.count(old)==1,'Ambiguous repair anchor: '+str(path)
 path.write_text(text.replace(old,new));records.append({'path':str(path),'kind':kind,'reason':reason,'before':old,'after':new})

def known_source_repairs(root,repository,records):
 if repository=='server-terraform':
  module=root/'nomad-gcp/modules/nomad-server-gcp'
  records.extend(ensure_requirements(module,{'google':'hashicorp/google-beta'}))
 if repository=='genai-idp-terraform':
  _replace(root/'features.tf','chat_with_document = try(var.api.chat_with_document.enabled, false)','chat_with_document = local.api_enabled && try(var.api.chat_with_document.enabled, false)',records,'dependent_feature_gate','Chat consumes processing_environment_api[0], whose count uses local.api_enabled; disabled API must not instantiate chat.')
 if repository=='platform-design':
  for name in ['eks','eks-cluster']:
   folder=root/'terraform/modules'/name
   for p in folder.glob('*.tf'):
    text=p.read_text()
    try:blocks=H.blocks(H.root(text))
    except Exception:continue
    edits=[]
    for n in blocks:
     if H.kind(n)!='module':continue
     source=H.attribute(text,n,'source');version=H.attribute(text,n,'version')
     if source is not None and version is not None and 'terraform-aws-modules/eks/aws' in H.value(text,source):
      edits.append((version.meta.start_pos,version.meta.end_pos,'version = "~> 20.0"'))
      records.append({'path':str(p),'kind':'dependency_api_compatibility_pin','module':H.label(text,n),'old':H.value(text,version),'new':'~> 20.0','reason':'Call site uses the v20 cluster_name/cluster_addons API removed in v21.'})
    if edits:p.write_text(H.apply(text,edits))
  folder=root/'terraform/modules/gpu-inference-vpc'
  _replace(folder/'main.tf','public_subnets = []','public_subnets = var.public_subnets',records,'nat_subnet_dependency','Expose optional public subnets; retain private-only default.')
  _replace(folder/'main.tf','enable_nat_gateway     = true','enable_nat_gateway     = length(var.public_subnets) > 0',records,'nat_subnet_dependency','NAT gateways require public subnets; an empty public subnet list cannot be indexed.')
  if (folder/'variables.tf').exists() and not re.search(r'variable\s+"public_subnets"', (folder/'variables.tf').read_text()):
   p=folder/'variables.tf';p.write_text(p.read_text()+'\nvariable "public_subnets" {\n  description = "Optional public subnet CIDRs required when creating NAT gateways"\n  type = list(string)\n  default = []\n}\n');records.append({'path':str(p),'kind':'optional_nat_subnets_input','default':[]})
  test=folder/'gpu-inference-vpc.tftest.hcl'
  _replace(test,'module.vpc.name == "test-gpu-vpc"','module.vpc.vpc_tags["Name"] == "test-gpu-vpc"',records,'actual_module_output_contract','VPC module exports vpc_tags, not its name input.')
  _replace(test,'module.vpc.cidr == "10.20.0.0/16"','module.vpc.vpc_cidr_block == "10.20.0.0/16"',records,'actual_module_output_contract','VPC module exports vpc_cidr_block, not its cidr input.')
  _replace(test,'aws_security_group.gpu_interconnect.name == "test-gpu-vpc-gpu-interconnect"','aws_security_group.gpu_interconnect.name_prefix == "test-gpu-vpc-gpu-interconnect-"',records,'plan_known_resource_contract','Source uses name_prefix; final provider-generated name is unknown during a plan.')
  for p in (root/'terraform/modules/vpc').glob('*.tftest.hcl'):
   _replace(p,'module.vpc.single_nat_gateway == true','length(module.vpc.natgw_ids) == 1',records,'actual_module_output_contract','Assert the actual NAT gateway topology; input single_nat_gateway is not a child-module output.')
 if repository=='terraform-duplocloud-components':
  for name in ['tenant-data-aws','vpn-data-aws']:
   for p in (root/'modules'/name).glob('*.tf'):
    text=p.read_text();updated=re.sub(r'(required_version\s*=\s*)"[^"]+"',r'\1">= 1.7.0, < 2.0.0"',text)
    if updated!=text:p.write_text(updated);records.append({'path':str(p),'kind':'test_engine_compatibility_constraint','reason':'Mock-provider tests require Terraform >=1.7; cohort uses pinned Terraform 1.15.7.'})
  p=root/'modules/env-file/tests/.env';assert not p.exists();p.write_text('FOO=bar\nMESSAGE="Hello, world!"\nNAME="John Doe"\nPASSWORD=complexPassword123\n');records.append({'path':str(p),'kind':'synthetic_env_parser_fixture','source':'Expected dictionary in the existing public main.tftest.hcl; no original .env file read.'})

def adapt_repository(root, repository, jobs, outcomes, bank):
 records=[];known_source_repairs(root,repository,records)
 # Extend checksum metadata only, keeping provider versions and constraints.
 for p in root.rglob('.terraform.lock.hcl'):
  if '.terraform' in p.relative_to(root).parts:continue
  text,changes=H.merge_platform_hashes(p.read_text(),bank)
  if changes:p.write_text(text);records.extend({'path':str(p),**c} for c in changes)
 selected=set()
 for job in jobs:
  module=root/job['module'];selected.update(module.glob('*.tftest.hcl'));selected.update((module/job['test_directory']).glob('*.tftest.hcl'))
 for p in sorted(selected):
  text=p.read_text()
  try:text,changes=H.drop_invalid_constant_assertions(text)
  except Exception:continue
  if changes:p.write_text(text);records.extend({'path':str(p),**c} for c in changes)
 for job in jobs:
  module=root/job['module'];key=(repository,job['module'],job['test_directory']);old=outcomes.get(key,{})
  summaries=[e.get('summary','') for e in old.get('errors',[])];joined='\n'.join(summaries)
  files=sorted(set(module.glob('*.tftest.hcl'))|set((module/job['test_directory']).glob('*.tftest.hcl')))
  locks=H.provider_blocks((module/'.terraform.lock.hcl').read_text()) if (module/'.terraform.lock.hcl').exists() else []
  current,_=graph_requirements(module);providers={n:s for n,s in current.items()};aliases=[]
  for config in module.glob('*.tf'):
   try:
    for node in H.blocks(H.root(config.read_text())):
     if H.kind(node)=='provider':aliases.append(H.mock_address(config.read_text(),node))
   except Exception:continue
  cloud=any(s in joined for s in ['credential','credential sources','Duplocloud','Invalid provider configuration']) or old.get('status')=='empty_suite'
  if old.get('status')=='empty_suite':
   p=module/job['test_directory']/'oasis_research_smoke.tftest.hcl';p.parent.mkdir(exist_ok=True);p.write_text('run "research_smoke_plan" {\n command = plan\n}\n');files.append(p);records.append({'path':str(p),'kind':'new_plan_smoke_for_empty_suite','semantic_assertion_count':0})
  if cloud:
   for item in locks:
    source='/'.join(item['address'].split('/')[-2:]);basename=item['address'].split('/')[-1]
    names=[name for name,src in current.items() if src in {source,item['address']}]
    name=names[0] if names else basename
    if name in PURE:continue
    if name in providers and providers[name] not in {source,item['address']}:continue
    providers[name]=source
   records.extend(ensure_requirements(module,providers))
  for p in files:
   text=p.read_text();changes=[]
   for name in re.findall(r'unknown provider [^\s]+/([^\s:]+)',joined):
    text,notes=H.remove_unused_mock(text,name);changes.extend(notes)
   if cloud:
    for name in providers:
     if name in PURE:continue
     text,notes=H.ensure_mock(text,name);changes.extend(notes)
    for name,alias in aliases:
     if name not in PURE and alias is not None:
      text,notes=H.ensure_mock(text,name,alias);changes.extend(notes)
   if 'Unknown condition value' in joined:
    text,notes=H.enable_plan_mock_values(text);changes.extend(notes)
   if 'invalid JSON' in joined or ('gpu-inference-vpc' in job['module'] and repository=='platform-design'):
    text,notes=H.ensure_mock(text,'aws');changes.extend(notes)
    text,notes=H.add_mock_data(text,'aws','aws_iam_policy_document','{ json = jsonencode({ Version = "2012-10-17", Statement = [] }) }');changes.extend(notes)
   if 'Failed to identify fetch peer certificates' in joined:
    records.extend(ensure_requirements(module,{'tls':'hashicorp/tls'}));text,notes=H.ensure_mock(text,'tls');changes.extend(notes)
    text,notes=H.add_mock_data(text,'tls','tls_certificate','{ certificates = [{ sha1_fingerprint = "1111111111111111111111111111111111111111" }] }');changes.extend(notes)
   variables=required_variables(module)
   # Fill absent required inputs; explicit existing fixtures/run overrides win.
   try:missing=missing_test_inputs(text,variables,repository)
   except Exception as exc:missing={};records.append({'path':str(p),'kind':'fixture_inference_needs_review','reason':str(exc)})
   if missing:text,notes=H.add_test_variables(text,missing);changes.extend(notes)
   if changes:p.write_text(text);records.extend({'path':str(p),**c} for c in changes)
 return records
