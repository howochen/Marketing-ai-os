"""Assert-based drill on the dedicated P0.5 synthetic Docker project only."""
import json
import os
import subprocess
import time
from pathlib import Path

PROJECT = os.getenv('MOS_DRILL_PROJECT', 'mos-p05-test')
if PROJECT not in {'mos-p05-test','mos-p11-test','mos-p13-test','mos-p14-test','mos-pub-test','mos-pub002-test'}:
    raise RuntimeError('Only dedicated synthetic test projects are allowed')
CONTAINER = PROJECT + '-db-1'
SOURCE = 'mos_p05_dr_source_001'
TARGET = 'mos_p05_dr_restore_001'
ARCHIVE = '/tmp/mos-p05-backups/drill.dump'


def docker(*args, ok=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=120)
    if ok and result.returncode:
        raise RuntimeError('Docker drill operation failed: ' + result.stderr)
    return result


def sql(database, query):
    return docker('exec', CONTAINER, 'psql', '-U', 'postgres', '-d', database, '-Atc', query).stdout.strip()


def fingerprint(database):
    result = {}
    for table in ('tenants', 'tasks', 'credentials', 'login_challenges', 'cost_events', 'audit_logs', 'publications', 'rate_versions', 'rate_limits', 'draft_revisions', 'revision_approvals', 'revision_scores', 'test_batches', 'batch_attempts', 'reconciliation_evidence', 'spend_authorizations','threads_connections','threads_oauth_states'):
        key = 'key' if table == 'rate_limits' else 'id'
        result[table] = sql(database, f'SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, chr(10) ORDER BY "{key}"), \'\')) FROM {table} t')
    return result


def main():
    labels = json.loads(docker('inspect', CONTAINER).stdout)[0]['Config']['Labels']
    assert labels['com.docker.compose.project'] == PROJECT
    assert labels['com.docker.compose.service'] == 'db'
    for script in ('pg_backup.sh', 'pg_restore.sh'):
        docker('cp', str(Path('scripts') / script), CONTAINER + ':/tmp/' + script)
    # Only the isolated project's synthetic test DB is cloned; no customer volume is used.
    docker('exec', CONTAINER, 'createdb', '-U', 'postgres', SOURCE)
    docker('exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', 'mos', '-Fc', '-f', '/tmp/synthetic-seed.dump')
    docker('exec', CONTAINER, 'pg_restore', '-U', 'postgres', '--exit-on-error', '--no-owner', '-d', SOURCE, '/tmp/synthetic-seed.dump')
    before = fingerprint(SOURCE)
    assert int(before['credentials'].split('|')[0]) > 0
    started = time.perf_counter()
    docker('exec', '-e', 'PGUSER=postgres', '-e', 'PGDATABASE=' + SOURCE, CONTAINER, 'sh', '/tmp/pg_backup.sh', ARCHIVE)
    backup_seconds = time.perf_counter() - started
    assert docker('exec', CONTAINER, 'stat', '-c', '%a', ARCHIVE).stdout.strip() == '600'
    assert docker('exec', CONTAINER, 'stat', '-c', '%a', '/tmp/mos-p05-backups').stdout.strip() == '700'
    denied = docker('exec', '-u', 'postgres', CONTAINER, 'pg_restore', '--list', ARCHIVE, ok=False)
    assert denied.returncode != 0  # root-owned 0700 directory / 0600 archive
    sql(SOURCE, 'DELETE FROM credentials')
    assert sql(SOURCE, 'SELECT count(*) FROM credentials') == '0'
    started = time.perf_counter()
    docker('exec', '-e', 'PGUSER=postgres', '-e', 'PGDATABASE=' + TARGET, CONTAINER, 'sh', '/tmp/pg_restore.sh', ARCHIVE)
    assert fingerprint(TARGET) == before
    rto_seconds = time.perf_counter() - started
    repeated = docker('exec', '-e', 'PGUSER=postgres', '-e', 'PGDATABASE=' + TARGET, CONTAINER, 'sh', '/tmp/pg_restore.sh', ARCHIVE, ok=False)
    assert repeated.returncode != 0
    refused = docker('exec', '-e', 'PGUSER=postgres', '-e', 'PGDATABASE=mos', CONTAINER, 'sh', '/tmp/pg_backup.sh', ARCHIVE, ok=False)
    assert refused.returncode != 0
    failed_archive = '/tmp/mos-p05-backups/failed.dump'
    failed = docker('exec', '-e', 'PGUSER=postgres', '-e', 'PGDATABASE=mos_p05_dr_source_missing', CONTAINER, 'sh', '/tmp/pg_backup.sh', failed_archive, ok=False)
    assert failed.returncode != 0
    assert docker('exec', CONTAINER, 'test', '-e', failed_archive, ok=False).returncode != 0
    report = {'result': 'PASS', 'project': PROJECT, 'backup_seconds': backup_seconds,
              'restore_and_verify_seconds': rto_seconds, 'synthetic_snapshot_rows_lost': 0,
              'rpo_scope': 'Snapshot only; no writes during backup. No PITR or continuous RPO guarantee.',
              'fingerprints_before_and_restored': before,
              'permission_mode': '0600 file / 0700 directory', 'negative_checks': 4,
              'scope': 'isolated synthetic data only; credentials deleted in source and restored to independent target'}
    output=Path({'mos-p05-test':'docs/p05','mos-p11-test':'docs/p11','mos-p13-test':'docs/p13','mos-p14-test':'docs/p14','mos-pub-test':'docs/threads','mos-pub002-test':'docs/pub002'}[PROJECT])/'backup-restore.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'fingerprints_before_and_restored'}))


if __name__ == '__main__':
    main()
