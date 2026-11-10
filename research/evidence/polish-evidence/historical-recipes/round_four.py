"""Mock-harness compatibility projections, with original configurations recorded."""
from pathlib import Path
import json
import repairs as H
from adapt import ensure_requirements
from round_three import repair as prior_repair

def repair(root,repository,jobs,outcomes,bank):
    notes=prior_repair(root,repository,jobs,outcomes,bank)
    if repository=='conf-data-processing-architecture-reference':
        targets=set()
        for job in jobs:
            module=root/job['module']
            for error in outcomes[(repository,job['module'],job['test_directory'])].get('errors',[]):
                if 'credential' not in error.get('summary',''):continue
                address=error.get('address','')
                if not address.startswith('module.') or '.provider[' not in address:continue
                filename=error.get('range',{}).get('filename')
                if not filename:continue
                target=(module/filename).resolve()
                assert target.is_relative_to(root.resolve()) and '.terraform' not in target.relative_to(root.resolve()).parts
                targets.add(target)
        for p in sorted(targets):
            text=p.read_text();edits=[]
            for node in H.blocks(H.root(text)):
                if H.kind(node)!='provider' or H.mock_address(text,node)!=('google',None):continue
                original=H.span(text,node)
                edits.append((node.meta.start_pos,node.meta.end_pos,''))
                notes.append({'path':str(p),'kind':'test_only_child_provider_projection','original':original,
                   'reason':'This legacy child configuration prevents inheritance of the declared test mock. In the isolated mock cohort only, remove the child-owned provider configuration so the existing root mock applies. No resource blocks or assertions are removed. This is not a production configuration change.',
                   'reference':'https://developer.hashicorp.com/terraform/language/modules/develop/providers'})
            if edits:p.write_text(H.apply(text,edits))
    for job in jobs:
        module=root/job['module'];old=outcomes[(repository,job['module'],job['test_directory'])]
        joined='\n'.join(e.get('summary','')+' '+e.get('detail','') for e in old.get('errors',[]))
        files=sorted(set(module.glob('*.tftest.hcl'))|set((module/job['test_directory']).glob('*.tftest.hcl')))
        for p in files:
            text=p.read_text();changes=[]
            if repository=='platform-design' and 'invalid JSON policy' in joined:
                text,n=H.ensure_mock(text,'aws');changes+=n
                fixtures={'aws_iam_policy_document':'{ json = jsonencode({ Version = "2012-10-17", Statement = [] }) }',
                   'aws_partition':'{ partition = "aws", dns_suffix = "amazonaws.com", reverse_dns_prefix = "com.amazonaws" }',
                   'aws_caller_identity':'{ account_id = "123456789012" }'}
                for kind,defaults in fixtures.items():
                    text,n=H.add_mock_data(text,'aws',kind,defaults);changes+=n
            if repository=='psoxy' and job['module']=='infra/modules/aws' and 'coalesce' in joined:
                existing=set()
                for node in H.blocks(H.root(text)):
                    if H.kind(node)=='variables':existing.update(H.attr_name(a) for a in H.attributes(node))
                if 'artifacts_bucket_name' not in existing:
                    text,n=H.add_test_variables(text,{'artifacts_bucket_name':json.dumps('oasis-unit-test-artifacts')})
                    changes.extend({**c,'kind':'synthetic_prebuilt_artifacts_bucket','reason':'Match the synthetic S3 prebuilt bundle location; the source requires a bucket when local package upload is disabled.'} for c in n)
            if changes:p.write_text(text);notes.extend({'path':str(p),**c} for c in changes)
    return notes
