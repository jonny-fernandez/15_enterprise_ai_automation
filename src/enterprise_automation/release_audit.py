"""Read-only local Git publication safety audit for Project 15.

Does not open .env, contact APIs, initialize git, publish, or mutate source.
The check of Git's tracked index is authoritative only when .git exists.
"""
import fnmatch
import json
from pathlib import Path
import re
import subprocess

TEXT_EXTENSIONS = {'.py','.ps1','.md','.txt','.toml','.json','.jsonl','.csv','.yml','.yaml','.bicep','.gitignore','.gitattributes'}
FORBIDDEN_SUFFIXES = {'.exe','.dll','.so','.dylib','.sqlite','.sqlite3','.db','.parquet','.pkl','.pickle','.zip','.pem','.key','.pfx','.cer'}
HIDDEN_ALLOWED = {'.env.example','.gitignore','.gitattributes','.gitkeep'}
KNOWN_DIRS = {'src','tests','scripts','docs','data','artifacts','logs','outputs','screenshots','.github','infra'}
SKIP_DIRS = {'.git','.venv','venv','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.idea','.vscode'}
PRIVATE_PATHS = ('data/raw/','data/processed/','artifacts/','logs/','outputs/')


def _safe_path(name: str):
    path = name.replace('\\','/')
    segments = path.split('/')
    if not segments or any(s in ('','..','.') for s in segments):
        return False, 'unsafe_path'
    leaf = segments[-1]
    if leaf == '.env' or leaf.startswith('.env.') and leaf != '.env.example':
        return False, 'secret_environment_file'
    if any(s in SKIP_DIRS for s in segments):
        return False, 'local_or_cache_directory'
    if (any(path.startswith(prefix) for prefix in PRIVATE_PATHS)
            and leaf != '.gitkeep'):
        return False, 'generated_or_private_output'
    if leaf == '.gitkeep':
        if path not in {'artifacts/.gitkeep','logs/.gitkeep','outputs/.gitkeep','data/raw/.gitkeep','data/processed/.gitkeep','screenshots/.gitkeep'}:
            return False, 'unexpected_placeholder'
        return True, ''
    if (Path(leaf).suffix.lower() in FORBIDDEN_SUFFIXES or leaf in {'id_rsa','credentials.json','secrets.json'}):
        return False, 'forbidden_file_type'
    if path.startswith('screenshots/'):
        if not (re.fullmatch(r'\d\d_[A-Za-z0-9_-]+\.png',leaf)):
            return False,'unapproved_screenshot_name'
        return True, ''
    if segments[0].startswith('.') and segments[0] not in {'.github','.gitignore','.gitattributes','.env.example'}:
        return False, 'unexpected_hidden_path'
    return True, ''


def _possible_credentials(data: str) -> bool:
    # Avoid recording sensitive content in findings. Only fail if likely credential
    # *values* are present. Ordinary placeholder names are allowed.
    token_prefixes = ('sk-'+'proj-', 'gh'+'p_', 'github_'+'pat_', 'xox'+'b-', 'xox'+'p-')
    if any(re.search(re.escape(t) + r'[A-Za-z0-9_-]{12,}',data) for t in token_prefixes):
        return True
    if re.search(r'AKIA[0-9A-Z]{16}',data):
        return True
    assignment = re.compile(r'^[ \t]*(?:OPENAI_API_KEY|AZURE_CLIENT_SECRET|PROJECT15_CP3_OPERATOR_KEY|PROJECT15_CP3_REVIEWER_KEY|PROJECT15_API_KEY)[ \t]*=[ \t]*(.*)$',re.I|re.M)
    for found in assignment.finditer(data):
        v = found.group(1).strip().strip('"\'')
        if v and not v.startswith(('#','<','${','YOUR_','EXAMPLE_','placeholder','change_me')):
            return True
    return False


def _git_tracked(root: Path):
    if not (root/'.git').exists():
        return None
    p=subprocess.run(['git','-C',str(root),'ls-files','-z','--cached'],capture_output=True,check=False)
    if p.returncode!=0:
        return None
    return [s.decode('utf-8','replace') for s in p.stdout.split(b'\0') if s]


def audit_repository(root: Path, *, tracked_paths=None):
    """Return report; defaults to reading tracked Git paths if available."""
    root=Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError('Repository root does not exist')
    git_paths = _git_tracked(root) if tracked_paths is None else list(tracked_paths)
    mode = 'git_index' if git_paths is not None else 'candidate_files_without_git'
    if git_paths is None:
        git_paths=[]
        for p in root.rglob('*'):
            if not p.is_file():
                continue
            try:
                parts=p.relative_to(root).parts
            except ValueError:
                continue
            if any(part in SKIP_DIRS for part in parts):
                continue
            name=p.relative_to(root).as_posix()
            if name in {'.env','.env.local'}:
                continue
            if any(name.startswith(prefix) and p.name!='.gitkeep' for prefix in PRIVATE_PATHS):
                continue
            git_paths.append(name)
    issues=[]; scanned=0
    for name in sorted(set(git_paths)):
        allowed, reason=_safe_path(name)
        p=root/name
        if not allowed:
            issues.append({'path':name,'code':reason})
            continue
        if p.is_symlink():
            issues.append({'path':name,'code':'symlink_not_allowed'})
            continue
        if not p.is_file():
            issues.append({'path':name,'code':'tracked_missing_file'})
            continue
        if p.stat().st_size > 5_000_000:
            issues.append({'path':name,'code':'oversized_file'})
            continue
        if p.suffix.lower() in TEXT_EXTENSIONS or p.name in HIDDEN_ALLOWED or p.name.startswith('requirements'):
            try:
                data=p.read_text(encoding='utf-8')
            except (UnicodeError,OSError):
                issues.append({'path':name,'code':'unreadable_text'})
                continue
            if _possible_credentials(data):
                issues.append({'path':name,'code':'possible_secret_value'})
            scanned+=1
    return {'schema_version':'cp4.audit.v1','inspection_mode':mode,
            'inspected_paths':len(git_paths),'text_files_scanned':scanned,
            'finding_count':len(issues),'findings':issues,'code_audit_pass':not issues,
            'limitations':['Local allowlist and pattern scan only; not a comprehensive secrets/security assessment',
                           'Untracked and ignored files are not part of the Git index audit',
                           'No cloud, provider, CI or screenshot evidence is verified by this scan',
                           'Read-only filesystem check; no git operations are performed']}


def save_report(report, path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
