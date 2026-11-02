"""One-time, transactional migration that keeps legacy records in mathematics."""
import sqlite3
from datetime import datetime

def migrate(path):
    c=sqlite3.connect(path)
    try:
        columns={r[1] for r in c.execute('PRAGMA table_info(folders)')}
        if 'subject' in columns:return
        backup=path.parent/'backups';backup.mkdir(exist_ok=True)
        dest=sqlite3.connect(backup/f'before-subjects-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3')
        c.backup(dest);dest.close()
        c.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE folders_new(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL,
          subject TEXT NOT NULL DEFAULT 'math' CHECK(subject IN ('math','408')),UNIQUE(subject,name));
        INSERT INTO folders_new(id,name,created_at) SELECT id,name,created_at FROM folders;
        DROP TABLE folders;
        ALTER TABLE folders_new RENAME TO folders;
        CREATE TABLE daily_batches_new(day TEXT NOT NULL,created_at TEXT NOT NULL,pool_size INTEGER NOT NULL,
          repeated_previous INTEGER NOT NULL DEFAULT 0,subject TEXT NOT NULL DEFAULT 'math',PRIMARY KEY(day,subject));
        INSERT INTO daily_batches_new(day,created_at,pool_size,repeated_previous)
          SELECT day,created_at,pool_size,repeated_previous FROM daily_batches;
        CREATE TABLE daily_items_new(day TEXT NOT NULL,position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 5),
          paper_id TEXT NOT NULL,number INTEGER NOT NULL CHECK(number>=1),result TEXT CHECK(result IN ('correct','wrong')),
          answered_at TEXT,subject TEXT NOT NULL DEFAULT 'math',PRIMARY KEY(day,subject,position),
          UNIQUE(day,subject,paper_id,number),FOREIGN KEY(day,subject) REFERENCES daily_batches(day,subject) ON DELETE CASCADE);
        INSERT INTO daily_items_new(day,position,paper_id,number,result,answered_at)
          SELECT day,position,paper_id,number,result,answered_at FROM daily_items;
        DROP TABLE daily_items;
        DROP TABLE daily_batches;
        ALTER TABLE daily_batches_new RENAME TO daily_batches;
        ALTER TABLE daily_items_new RENAME TO daily_items;
        CREATE INDEX daily_question_history ON daily_items(paper_id,number,day);
        INSERT OR IGNORE INTO settings(key,value) SELECT 'last_read:math',value FROM settings WHERE key='last_read';
        COMMIT;
        ''')
        if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Migration foreign key check failed')
    finally:c.close()
