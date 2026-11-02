"""Create a portable runtime bundle without study records or local credentials."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'output/aliyun'
MODULES = ['server', 'activity', 'daily_review', 'daily_practice', 'knowledge',
           'knowledge_sessions', 'note_images', 'migrate_subjects']


def ignore(directory, names):
    return [name for name in names if name in {'.DS_Store', '__pycache__', 'backups'}
            or name.endswith(('.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.pyc'))]


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='shiti-build-') as temp:
        bundle = Path(temp) / 'shiti-deploy'
        app = bundle / 'app'
        app.mkdir(parents=True)
        for name in MODULES:
            shutil.copy2(ROOT / 'app' / f'{name}.py', app)
        for name in ['data', 'static']:
            shutil.copytree(ROOT / 'app' / name, app / name, ignore=ignore)
        # Preserve all paper routes while removing dependence on source folders
        # beside the original project. Only the packaged catalog is rewritten.
        catalog_path = app / 'data/catalog.json'
        catalog = json.loads(catalog_path.read_text())
        sources = bundle / 'sources'
        sources.mkdir()
        for paper in catalog['papers']:
            source = (ROOT / paper['source']).resolve()
            if not source.is_relative_to(ROOT) or not source.is_file():
                raise ValueError(f'原卷文件不存在或位于项目外：{paper["id"]}')
            relative = f'sources/{paper["id"]}.pdf'
            shutil.copy2(source, bundle / relative)
            paper['source'] = relative
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
        deployment = bundle / 'deploy'
        deployment.mkdir()
        for name in ['install-ubuntu.sh', 'requirements.txt', 'backup.py', 'README.md']:
            shutil.copy2(ROOT / 'deploy/aliyun' / name, deployment / name)
        files = sorted(p for p in bundle.rglob('*') if p.is_file())
        if any('.sqlite3' in p.name for p in files):
            raise ValueError('部署包不应包含学习数据库')
        # macOS source PDFs can be owner-readable only. The server runs under
        # a dedicated account, so normalize modes on staged copies.
        bundle.chmod(0o755)
        for directory in bundle.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
        for file in files:
            file.chmod(0o644)
        manifest = {str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in files}
        (bundle / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        destination = OUTPUT / 'shiti-ubuntu24.tar.gz'
        temporary = OUTPUT / '.shiti-ubuntu24.tar.gz.tmp'
        try:
            with tarfile.open(temporary, 'w:gz', compresslevel=1) as archive:
                archive.add(bundle, arcname='shiti-deploy')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(destination.suffix + '.sha256').write_text(f'{sha}  {destination.name}\n')
        print(json.dumps({'archive': str(destination), 'size_mb': round(destination.stat().st_size / 1024**2, 1),
                          'files': len(files), 'sha256': sha, 'includes_study_records': False}, ensure_ascii=False))


if __name__ == '__main__':
    build()
