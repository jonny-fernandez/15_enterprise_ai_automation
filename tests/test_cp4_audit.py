"""Offline CP4 security audit regression tests (no network or Git writes)."""
from pathlib import Path
from enterprise_automation.release_audit import audit_repository


def test_scan_candidate_without_git(tmp_path):
    (tmp_path/'README.md').write_text('# Synthetic Project\n')
    (tmp_path/'.env').write_text('DO_NOT_PRINT=private')
    (tmp_path/'artifacts').mkdir()
    (tmp_path/'artifacts'/'run.sqlite').write_text('local generated output')
    (tmp_path/'artifacts'/'.gitkeep').touch()
    r=audit_repository(tmp_path)
    assert r['inspection_mode']=='candidate_files_without_git'
    assert r['code_audit_pass'] and r['finding_count']==0
    assert r['inspected_paths']==2


def test_git_staged_env_blocked(tmp_path):
    (tmp_path/'.env').write_text('private')
    r=audit_repository(tmp_path,tracked_paths=['.env'])
    assert not r['code_audit_pass']
    assert r['findings'][0]['code']=='secret_environment_file'


def test_git_stage_raw_output_blocked(tmp_path):
    (tmp_path/'data/raw').mkdir(parents=True)
    (tmp_path/'data/raw'/'x.jsonl').write_text('synthetic')
    r=audit_repository(tmp_path,tracked_paths=['data/raw/x.jsonl'])
    assert not r['code_audit_pass']
    assert r['findings'][0]['code']=='generated_or_private_output'


def test_git_stage_hadoop_exe_blocked(tmp_path):
    (tmp_path/'winutils.exe').write_bytes(b'fake')
    r=audit_repository(tmp_path,tracked_paths=['winutils.exe'])
    assert not r['code_audit_pass']
    assert r['findings'][0]['code']=='forbidden_file_type'


def test_git_stage_unexpected_placeholder_blocked(tmp_path):
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'.gitkeep').touch()
    r=audit_repository(tmp_path,tracked_paths=['src/.gitkeep'])
    assert not r['code_audit_pass']


def test_safe_gitkeep_allowed(tmp_path):
    (tmp_path/'artifacts').mkdir()
    (tmp_path/'artifacts'/'.gitkeep').touch()
    r=audit_repository(tmp_path,tracked_paths=['artifacts/.gitkeep'])
    assert r['code_audit_pass']


def test_secret_value_blocked_without_echoing(tmp_path):
    (tmp_path/'config.txt').write_text('OPENAI_API_KEY = top_secret_value_example_abcdefghijklmnop')
    r=audit_repository(tmp_path,tracked_paths=['config.txt'])
    assert not r['code_audit_pass']
    assert r['findings'][0]['code']=='possible_secret_value'
    assert 'top_secret' not in str(r)


def test_placeholder_env_example_allowed(tmp_path):
    (tmp_path/'.env.example').write_text('OPENAI_API_KEY=<your-key-here>\n')
    r=audit_repository(tmp_path,tracked_paths=['.env.example'])
    assert r['code_audit_pass']


def test_screenshot_rule(tmp_path):
    (tmp_path/'screenshots').mkdir()
    (tmp_path/'screenshots'/'01_cp1.png').write_bytes(b'fake')
    good=audit_repository(tmp_path,tracked_paths=['screenshots/01_cp1.png'])
    assert good['code_audit_pass']
    (tmp_path/'screenshots'/'image.png').write_bytes(b'fake')
    bad=audit_repository(tmp_path,tracked_paths=['screenshots/image.png'])
    assert not bad['code_audit_pass']


def test_no_execution_side_effects(tmp_path):
    (tmp_path/'README.md').write_text('hi')
    before=set(tmp_path.rglob('*'))
    audit_repository(tmp_path)
    assert set(tmp_path.rglob('*')) == before


def test_real_project_candidate_security_audit():
    repo=Path(__file__).resolve().parents[1]
    result=audit_repository(repo)
    assert result['code_audit_pass'], result['findings']
