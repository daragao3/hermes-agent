"""Private runtime provisioning boundaries, using only owned filesystem fixtures."""
from hermes_cli.managed_uv import _remove_tree


def test_rejected_generation_cleanup_stays_inside_runtime_root(tmp_path):
    root = tmp_path / 'private-runtime'
    rejected = root / 'rejected-generation'
    rejected.mkdir(parents=True)
    (rejected / 'artifact').write_text('owned rejected download')
    outside = tmp_path / 'unrelated'
    outside.mkdir()
    (outside / 'keep').write_text('preserve')
    _remove_tree(outside, boundary=root)
    assert (outside / 'keep').read_text() == 'preserve'
    _remove_tree(rejected, boundary=root)
    assert not rejected.exists()
    assert root.exists()


def test_private_python_runs_existing_dependencies_and_real_wal(tmp_path):
    import json
    from pathlib import Path
    from hermes_cli._subprocess_compat import run_text_capture
    root = Path(__file__).resolve().parents[1]
    evidence = Path('C:/Users/diego/architecture-map/wave-execution/2026-09-08')
    provision = json.loads((evidence / 'provision-private-python.json').read_text())
    code = r'''
import json, site, sys
from pathlib import Path
root, db_path = Path(sys.argv[1]), Path(sys.argv[2])
site.addsitedir(str(root / '.venv/Lib/site-packages'))
sys.path.insert(0, str(root))
import dotenv, fastapi, openai, prompt_toolkit, pydantic, pydantic_core, rich, uvicorn, yaml
import _ssl, sqlite3, psutil
from hermes_state import SessionDB
import hermes_state
assert Path(hermes_state.__file__).resolve().parent == root.resolve()
with SessionDB(db_path) as writer:
    assert writer._conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    writer.ensure_session('private-runtime', source='cli')
    writer.append_message('private-runtime', 'user', content='private runtime needle')
    with SessionDB(db_path, read_only=True) as reader:
        assert reader.search_messages('needle')
        assert reader.get_messages('private-runtime')[0]['content'] == 'private runtime needle'
print(json.dumps({'python':sys.executable,'base_prefix':sys.base_prefix,'sqlite':sqlite3.sqlite_version,'wal':True}))
'''
    result = run_text_capture([provision['python'], '-I', '-c', code, str(root), str(tmp_path / 'state.db')], timeout=60)
    (evidence / 'private-python-abi-wal-probe.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt['sqlite'] == provision['after']['sqlite_version_string']
    assert receipt['wal'] is True


def test_candidate_runtime_uses_private_sqlite_and_wal(tmp_path):
    import json
    import sqlite3
    import sys
    from pathlib import Path
    from hermes_state import SessionDB
    from hermes_cli.sqlite_runtime import is_sqlite_wal_reset_vulnerable
    evidence = Path('C:/Users/diego/architecture-map/wave-execution/2026-09-08')
    provision = json.loads((evidence / 'provision-private-python.json').read_text())
    assert Path(sys.base_prefix).resolve() == Path(provision['after']['base_prefix']).resolve()
    assert not is_sqlite_wal_reset_vulnerable(sqlite3.sqlite_version_info)
    with SessionDB(tmp_path / 'state.db') as db:
        assert db._conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        db.ensure_session('retargeted', source='cli')
        db.append_message('retargeted', 'user', content='safe sqlite runtime')
        with SessionDB(tmp_path / 'state.db', read_only=True) as reader:
            assert reader.search_messages('runtime')
    (evidence / 'private-runtime-consumer.json').write_text(json.dumps({
        'executable':sys.executable, 'base_prefix':sys.base_prefix,
        'sqlite':sqlite3.sqlite_version, 'wal':True}, indent=2))
