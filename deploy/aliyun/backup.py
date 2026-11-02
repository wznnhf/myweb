"""Back up a running SQLite database, including WAL, and keep 14 daily copies."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo


def backup(directory):
    directory = Path(directory).resolve()
    source = directory / 'study.sqlite3'
    if not source.is_file():
        raise FileNotFoundError('学习数据库不存在，未创建空备份')
    backups = directory / 'backups'
    backups.mkdir(mode=0o700, exist_ok=True)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    target = backups / f'daily-{day}.sqlite3'
    fd, temporary = tempfile.mkstemp(prefix='.backup-', dir=backups)
    os.close(fd)
    try:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(temporary) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('备份完整性校验未通过')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    for old in sorted(backups.glob('daily-????-??-??.sqlite3'), reverse=True)[14:]:
        old.unlink()
    return target


if __name__ == '__main__':
    print(backup(sys.argv[1]))
