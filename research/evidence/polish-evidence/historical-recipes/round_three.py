"""Explicit provider inheritance and prebuilt-package unit-test fixtures."""
import json,re
from pathlib import Path
import hcl2
import repairs as H
from adapt import ensure_requirements,_replace

def complete_mock_mappings(text):
    defaults=[H.label(text,n) for n in H.blocks(H.root(text)) if H.kind(n)=='mock_provider' and H.mock_address(text,n)[1] is None]
    edits=[];notes=[]
    for run in H.blocks(H.root(text)):
        if H.kind(run)!='run':continue
        providers=H.attribute(text,run,'providers')
        if providers is None:continue
        existing=hcl2.loads('value = '+H.value(text,providers))['value']
        names={str(n).strip('"') for n in existing}
        missing=sorted(set(defaults)-names)
        if not missing:continue
        assert H.value(text,providers).endswith('}'),'Explicit provider mapping is not a literal object'
        addition='\n'+''.join('    '+name+' = '+name+'\n' for name in missing)
        edits.append((providers.meta.end_pos-1,providers.meta.end_pos-1,addition))
        notes.append({'kind':'complete_explicit_mock_provider_map','run':H.label(text,run),'added':missing,'reason':'Explicit run.providers disables implicit inheritance of other test mocks. Preserve existing mappings and add the missing default mocks.'})
    return H.apply(text,edits),notes

def repair(root,repository,jobs,outcomes,bank):
    notes=[]
    if repository=='genai-idp-terraform':
        _replace(root/'tests/private-endpoint-gap.tftest.hcl','bedrock-runtime = "vpce-brrt0000000000000000"','bedrock-runtime = "vpce-brrt0000000000000000"\n        bedrock-agent-runtime = "vpce-bragent000000000000"',notes,'complete_positive_endpoint_fixture','The fixture explicitly mirrors all required endpoints. The current private_required_endpoints_present check additionally requires bedrock-agent-runtime; retain AppSync gap assertions and all source checks.')
    for job in jobs:
        old=outcomes[(repository,job['module'],job['test_directory'])]
        joined='\n'.join(e.get('summary','')+' '+e.get('detail','') for e in old.get('errors',[]))
        snippets='\n'.join(e.get('snippet',{}).get('code','') for e in old.get('errors',[]))
        module=root/job['module']
        files=sorted(set(module.glob('*.tftest.hcl'))|set((module/job['test_directory']).glob('*.tftest.hcl')))
        if repository=='platform-design' and job['module'] in {'terraform/modules/eks','terraform/modules/eks-cluster'} and 'Inconsistent conditional result types' in joined:
            old_expression='cluster_encryption_config = var.kms_key_arn != "" ? {\n    provider_key_arn = var.kms_key_arn\n    resources        = ["secrets"]\n  } : {}'
            new_expression='cluster_encryption_config = { for key, value in {\n    provider_key_arn = var.kms_key_arn\n    resources        = ["secrets"]\n  } : key => value if var.kms_key_arn != "" }'
            for source in module.glob('*.tf'):
                _replace(source,old_expression,new_expression,notes,'typed_empty_encryption_config','Preserve the same populated object or empty object. A filtered object avoids Terraform conditional unification of heterogeneous string/list values.')

        for p in files:
            text=p.read_text();changes=[]
            if 'credential' in joined or 'Invalid provider configuration' in joined or repository=='conf-data-processing-architecture-reference':
                text,n=complete_mock_mappings(text);changes+=n
            if repository=='platform-design' and job['module']=='terraform/modules/remote-access-vpn' and 'Unknown condition value' in joined:
                text+='\noverride_resource {\n  target = aws_security_group.nlb\n  override_during = plan\n  values = { id = "sg-0123456789abcdef0" }\n}\n'
                changes.append({'kind':'computed_upstream_id_fixture','target':'aws_security_group.nlb.id','reason':'Make the upstream computed ID known at plan. Keep the tested ingress rule reference and all assertions unchanged.'})
            if repository=='psoxy' and job['module'] in {'infra/modules/aws','infra/modules/gcp-host'} and 'External Program Execution Failed' in joined:
                # Both modules explicitly support prebuilt cloud bundle inputs.
                scheme='s3' if job['module'].endswith('/aws') else 'gs'
                implementation='aws' if scheme=='s3' else 'gcp'
                values={'deployment_bundle':json.dumps(f'{scheme}://oasis-unit-test-artifacts/psoxy-{implementation}-0.0.0.jar'),'deployment_bundle_hash':json.dumps('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')}
                existing=set()
                for node in H.blocks(H.root(text)):
                    if H.kind(node)=='variables':existing.update(H.attr_name(a) for a in H.attributes(node))
                values={k:v for k,v in values.items() if k not in existing}
                if values:
                    text,n=H.add_test_variables(text,values)
                    changes.extend({**c,'kind':'synthetic_prebuilt_bundle_input','reason':'Use the documented prebuilt-bundle path for infrastructure unit tests. No Java package is compiled or downloaded, and cloud storage is mocked.'} for c in n)
            if repository=='conf-data-processing-architecture-reference' and 'Invalid index' in joined and re.search(r'data\.external\.(?:bazel_bin|workspace)\.result\["path"\]',snippets):
                notes.extend(ensure_requirements(module,{'external':'hashicorp/external'}))
                text,n=H.ensure_mock(text,'external');changes+=n
                notes.extend(ensure_requirements(module,{'archive':'hashicorp/archive'}))
                text,n=H.ensure_mock(text,'archive');changes.extend({**c,'reason':'Mock packaging of the external application artifact; infrastructure assertions remain real mocked plans.'} for c in n)
                defaults='{ result = { path = '+json.dumps(str(root))+' } }'
                text,n=H.add_mock_data(text,'external','external',defaults);changes.extend({**c,'reason':'Synthetic Bazel path metadata for mocked infrastructure plans; no Bazel build is claimed.'} for c in n)
            if changes:p.write_text(text);notes.extend({'path':str(p),**n} for n in changes)
    return notes
