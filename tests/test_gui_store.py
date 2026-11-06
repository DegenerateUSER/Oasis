"""GUI imports preserve evidence and share the CLI's score accounting."""
import pytest

from tfmutate.reporter import summary_data

CSV = ('repo_name,mutant_id,operator_id,operator_category,test_status,validate_status,log_paths\r\n'
       'tiny,m1,MUT-RES-002,resource,survived,valid,/etc/passwd\r\n')


def test_csv_import_preserves_original_and_shared_summary_across_restart(tmp_path):
    from tfmutate.gui.store import DatasetStore

    store = DatasetStore(tmp_path / 'state', sources={})
    dataset = store.import_dataset({'name': 'My upload', 'csv': CSV})
    assert dataset['provenance']['kind'] == 'imported'
    assert dataset['summary'] == summary_data(dataset['rows'])
    assert dataset['summary']['validation_problems']  # survivor lacks classification
    assert store.csv_bytes(dataset['id']) == CSV.encode()
    reopened = DatasetStore(tmp_path / 'state', sources={})
    assert reopened.get(dataset['id']) == dataset
    assert 'rows' not in reopened.list()[0]
    with pytest.raises(ValueError, match='owned|evidence'):
        reopened.log(dataset['id'], '/etc/passwd')


@pytest.mark.parametrize('body', [
    {}, {'csv': ''}, {'csv': 'x,y\n1,2\n'}, {'csv': CSV.splitlines()[0] + '\n'},
    {'csv': CSV + 'too,few\n'}, {'csv': CSV.replace('mutant_id', 'repo_name')},
    {'csv': CSV, 'path': '/etc/passwd'}, {'source_id': '../../etc/passwd'},
    {'csv': CSV, 'name': 7}, {'csv': CSV, 'name': '\u0000'},
    {'csv': CSV, 'source_id': 'master'}, {'csv': 4}, [],
])
def test_malformed_csv_and_unrecognized_inputs_are_rejected(tmp_path, body):
    from tfmutate.gui.store import DatasetStore
    store = DatasetStore(tmp_path / 'state', sources={})
    with pytest.raises(ValueError):
        store.import_dataset(body)
    assert store.list() == []


def test_historical_registration_is_explicit_and_never_verified(tmp_path):
    from tfmutate.gui.store import DatasetStore
    original = tmp_path / 'historical.csv'
    original.write_bytes(CSV.encode())
    store = DatasetStore(tmp_path / 'state', sources={'master': original})
    assert store.source_catalog()[0]['id'] == 'master'
    dataset = store.import_dataset({'source_id': 'master'})
    assert dataset['provenance']['kind'] == 'historical'
    assert store.csv_bytes(dataset['id']) == original.read_bytes()


def test_import_limits_and_symlink_artifact_reads_are_enforced(tmp_path, monkeypatch):
    import tfmutate.gui.store as module
    monkeypatch.setattr(module, 'MAX_ROWS', 1)
    store = module.DatasetStore(tmp_path / 'state', sources={})
    with pytest.raises(ValueError, match='rows'):
        store.import_dataset({'csv': CSV + CSV.splitlines()[1] + '\n'})
    monkeypatch.setattr(module, 'MAX_CSV_BYTES', 4)
    with pytest.raises(ValueError, match='bytes'):
        store.import_dataset({'csv': CSV})
    monkeypatch.setattr(module, 'MAX_CSV_BYTES', 10000)
    dataset = store.import_dataset({'csv': CSV})
    csv_path = store.datasets / (dataset['id'] + '.csv')
    csv_path.unlink()
    csv_path.symlink_to(tmp_path / 'private')
    with pytest.raises(ValueError, match='symlink|unsafe'):
        store.csv_bytes(dataset['id'])


def test_state_directory_symlinks_are_rejected(tmp_path):
    from tfmutate.gui.store import DatasetStore
    state = tmp_path / 'link'
    state.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink|unsafe'):
        DatasetStore(state, sources={})
