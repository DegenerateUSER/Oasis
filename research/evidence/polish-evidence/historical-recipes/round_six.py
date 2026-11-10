"""Remove unused Bazel-suite mocks proven absent from its closed source graph."""
import repairs as H

def repair(root,repository,jobs,outcomes,bank):
    notes=[]
    if repository!='conf-data-processing-architecture-reference':return notes
    for job in jobs:
        if job['module']!='operator/terraform/gcp/modules/bazel':continue
        module=root/job['module'];used=set();proof=[]
        for p in sorted(module.glob('*.tf')):
            text=p.read_text();assert 'provider::' not in text
            nodes=H.blocks(H.root(text));assert not any(H.kind(n)=='module' for n in nodes)
            used.update(H.label(text,n).split('_')[0] for n in nodes if H.kind(n) in {'resource','data'})
            proof.append(str(p.relative_to(root)))
        assert used=={'external'}
        for p in sorted(set(module.glob('*.tftest.hcl'))|set((module/job['test_directory']).glob('*.tftest.hcl'))):
            text=p.read_text();names={H.label(text,n) for n in H.blocks(H.root(text)) if H.kind(n)=='mock_provider'}
            for name in sorted(names-used):
                text,changes=H.remove_unused_mock(text,name)
                notes.extend({'path':str(p),**c,'closed_scope_provider_proof':sorted(used),'proof_files':proof} for c in changes)
            p.write_text(text)
    return notes
