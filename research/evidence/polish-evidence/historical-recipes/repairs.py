"""Explicit research adapters. Original assertions are retained except invalid constants."""
import json,re
import hcl2

def root(text):return hcl2.parses_to_tree(text).children[0]
def blocks(body):return [n for n in body.children if getattr(n,'data',None)=='block']
def kind(n):return str(n.children[0].children[0])
def body(n):return next(c for c in n.children if getattr(c,'data',None)=='body')
def attributes(n):return [c for c in body(n).children if getattr(c,'data',None)=='attribute']
def attr_name(n):return str(n.children[0].children[0])
def span(text,n):return text[n.meta.start_pos:n.meta.end_pos]
def label(text,n):
 node=n.children[1]
 return json.loads(span(text,node))
def attribute(text,n,name):
 matches=[a for a in attributes(n) if attr_name(a)==name]
 return matches[0] if matches else None
def value(text,a):return span(text,a).split('=',1)[1].strip()
def apply(text,edits):
 previous=len(text)+1
 for start,end,replacement in sorted(edits,reverse=True):
  assert end<=previous,'Overlapping repair edits';text=text[:start]+replacement+text[end:];previous=start
 return text

def drop_invalid_constant_assertions(text):
 edits=[];records=[]
 for run in blocks(root(text)):
  if kind(run)!='run':continue
  for node in blocks(body(run)):
   if kind(node)!='assert':continue
   condition=attribute(text,node,'condition')
   if condition is not None and value(text,condition) in {'true','false'}:
    records.append({'run':label(text,run),'kind':'invalid_constant_assert_removed','original':span(text,node),'interpretation':'Run remains a plan/apply smoke test. Constant expression checks no configuration property.'})
    edits.append((node.meta.start_pos,node.meta.end_pos,''))
 return apply(text,edits),records

def mock_address(text,node):
 alias=attribute(text,node,'alias')
 return (label(text,node),json.loads(value(text,alias)) if alias is not None else None)

def ensure_mock(text,name,alias=None):
 expected=(name,alias)
 mocks=[n for n in blocks(root(text)) if kind(n)=='mock_provider' and mock_address(text,n)==expected]
 if mocks:return text,[]
 edits=[];removed=[]
 for node in blocks(root(text)):
  if kind(node)=='provider' and mock_address(text,node)==expected:
   edits.append((node.meta.start_pos,node.meta.end_pos,''));removed.append('real_test_provider_configuration')
 text=apply(text,edits)
 addition='\nmock_provider '+json.dumps(name)+' {\n'+('  alias = '+json.dumps(alias)+'\n' if alias else '')+'}\n'
 return text+addition,[{'kind':'test_provider_mock_added','provider':name,'alias':alias,'removed':removed}]

def remove_unused_mock(text,name):
 edits=[]
 for node in blocks(root(text)):
  if kind(node)=='mock_provider' and label(text,node)==name:edits.append((node.meta.start_pos,node.meta.end_pos,''))
 return apply(text,edits),[{'kind':'unused_mock_removed','provider':name,'proof_required':'Provider absent from installed/declaration graph or native unknown-provider diagnostic'}] if edits else []

def enable_plan_mock_values(text):
 edits=[];records=[]
 for node in blocks(root(text)):
  if kind(node)!='mock_provider':continue
  current=attribute(text,node,'override_during')
  if current is not None and value(text,current)=='plan':continue
  if current is None:edits.append((node.meta.end_pos-1,node.meta.end_pos-1,'\n  override_during = plan\n'))
  else:edits.append((current.meta.start_pos,current.meta.end_pos,'override_during = plan'))
  records.append({'kind':'computed_mock_values_available_during_plan','provider':label(text,node)})
 return apply(text,edits),records

def add_mock_data(text,provider,data_type,defaults):
 nodes=[n for n in blocks(root(text)) if kind(n)=='mock_provider' and mock_address(text,n)==(provider,None)]
 if len(nodes)!=1:raise ValueError('Expected exactly one default mock provider')
 node=nodes[0]
 existing=[n for n in blocks(body(node)) if kind(n)=='mock_data' and label(text,n)==data_type]
 if existing:return text,[]
 addition='\n  mock_data '+json.dumps(data_type)+' {\n    defaults = '+defaults+'\n  }\n'
 return apply(text,[(node.meta.end_pos-1,node.meta.end_pos-1,addition)]),[{'kind':'mock_data_fixture_added','provider':provider,'data_type':data_type,'defaults':defaults}]

def add_test_variables(text,values):
 nodes=[n for n in blocks(root(text)) if kind(n)=='variables'];assert len(nodes)<=1
 fields='\n'.join('  '+name+' = '+expression for name,expression in values.items())+'\n'
 if nodes:
  existing={attr_name(a) for a in attributes(nodes[0])};assert not existing.intersection(values),'Would replace an existing test fixture'
  text=apply(text,[(nodes[0].meta.end_pos-1,nodes[0].meta.end_pos-1,'\n'+fields)])
 else:text+='\nvariables {\n'+fields+'}\n'
 return text,[{'kind':'synthetic_required_input','name':n,'expression':v} for n,v in values.items()]

def provider_blocks(text):
 result=[]
 for m in re.finditer(r'provider\s+"([^"]+)"\s*\{([^}]+)\}',text,re.S):
  version=re.search(r'\bversion\s*=\s*"([^"]+)"',m[2]);hashes=re.findall(r'"((?:h1|zh):[^"\s]+)"',m[2])
  if version:result.append({'address':m[1],'version':version[1],'hashes':hashes})
 return result

def merge_platform_hashes(text,bank):
 changes=[]
 def merge(match):
  address=match[1];block=match[0];parsed=provider_blocks(block)
  if not parsed:return block
  item=parsed[0];extra=sorted(set(bank.get((address,item['version']),[]))-set(item['hashes']))
  if not extra:return block
  hashes=re.search(r'\bhashes\s*=\s*\[([^]]*)\]',block,re.S)
  if not hashes:raise ValueError('Existing provider lock has no checksum list')
  insertion=(',' if hashes[1].strip() and not hashes[1].rstrip().endswith(',') else '')+'\n'+''.join('    '+json.dumps(h)+',\n' for h in extra)
  changes.append({'kind':'platform_checksum_metadata_added','provider':address,'version':item['version'],'hashes':extra,'version_changed':False})
  return block[:hashes.end()-1]+insertion+'  '+block[hashes.end()-1:]
 return re.sub(r'provider\s+"([^"]+)"\s*\{([^}]+)\}',merge,text,flags=re.S),changes
