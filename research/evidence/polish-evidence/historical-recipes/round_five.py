"""Repair malformed mock response types without changing assertions."""
import json
import hcl2
import repairs as H
from adapt import _replace
from round_four import repair as prior_repair

def missing_data_defaults(text,provider,data_type,values):
    text,notes=H.ensure_mock(text,provider)
    providers=[n for n in H.blocks(H.root(text)) if H.kind(n)=='mock_provider' and H.mock_address(text,n)==(provider,None)]
    assert len(providers)==1
    mocks=[n for n in H.blocks(H.body(providers[0])) if H.kind(n)=='mock_data' and H.label(text,n)==data_type]
    if not mocks:
        expression='{ '+', '.join(k+' = '+v for k,v in values.items())+' }'
        result,added=H.add_mock_data(text,provider,data_type,expression)
        return result,notes+added
    assert len(mocks)==1
    defaults=H.attribute(text,mocks[0],'defaults');assert defaults is not None
    expression=H.value(text,defaults);assert expression.endswith('}')
    existing={str(k).strip('"') for k in hcl2.loads('value = '+expression)['value']}
    missing={k:v for k,v in values.items() if k not in existing}
    if not missing:return text,notes
    addition='\n'+''.join('      '+k+' = '+v+'\n' for k,v in missing.items())
    result=H.apply(text,[(defaults.meta.end_pos-1,defaults.meta.end_pos-1,addition)])
    return result,notes+[{'kind':'missing_mock_response_fields_added','provider':provider,'data_type':data_type,'fields':missing,'existing_fields_preserved':True}]

def repair(root,repository,jobs,outcomes,bank):
    notes=prior_repair(root,repository,jobs,outcomes,bank)
    if repository=='conf-data-processing-architecture-reference' and any('cannot parse "null_re"' in e.get('detail','') for job in jobs for e in outcomes[(repository,job['module'],job['test_directory'])].get('errors',[])):
        _replace(root/'tools/tftesting/tfmocks/null/null_resource.tfmock.hcl','"null_resource_id"','"1794000000123456789"',notes,'numeric_null_resource_mock_id','The source parses the first seven digits as an integer. Real null_resource IDs are numeric; the published mock label is not.')
    for job in jobs:
        old=outcomes[(repository,job['module'],job['test_directory'])]
        diagnostic='\n'.join(e.get('summary','')+' '+e.get('detail','') for e in old.get('errors',[]))
        module=root/job['module']
        files=sorted(set(module.glob('*.tftest.hcl'))|set((module/job['test_directory']).glob('*.tftest.hcl')))
        for p in files:
            text=p.read_text();changes=[]
            if 'invalid JSON policy' in diagnostic:
                text,n=H.ensure_mock(text,'aws');changes+=n
                text,n=H.add_mock_data(text,'aws','aws_iam_policy_document','{ json = jsonencode({ Version = "2012-10-17", Statement = [] }) }');changes+=n
            if 'not a valid CIDR block' in diagnostic:
                text,n=missing_data_defaults(text,'aws','aws_vpc',{'cidr_block':json.dumps('10.0.0.0/16')});changes+=n
            if repository=='conf-data-processing-architecture-reference' and 'worker subnet cidr range must be provided' in diagnostic:
                existing=set()
                for node in H.blocks(H.root(text)):
                    if H.kind(node)=='variables':existing.update(H.attr_name(a) for a in H.attributes(node))
                if 'worker_subnet_cidr' not in existing:
                    text,n=H.add_test_variables(text,{'worker_subnet_cidr':json.dumps({'us-central1':'10.240.0.0/24'})})
                    changes.extend({**c,'reason':'Supply a synthetic network input required by the positive test. Private auto.tfvars remain excluded; no original input or precondition is overwritten.'} for c in n)
            if 'is an invalid ARN' in diagnostic or 'invalid JSON policy' in diagnostic:
                arn=json.dumps('arn:aws:iam::123456789012:role/oasis-unit-test')
                text,n=missing_data_defaults(text,'aws','aws_caller_identity',{'account_id':json.dumps('123456789012'),'arn':arn});changes+=n
                text,n=missing_data_defaults(text,'aws','aws_iam_session_context',{'issuer_arn':arn});changes+=n
            if changes:p.write_text(text);notes.extend({'path':str(p),**c} for c in changes)
    return notes
