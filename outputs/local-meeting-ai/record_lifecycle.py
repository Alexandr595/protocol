"""Reversible deletion: audio stays in place and a metadata snapshot is kept."""
import time
import uuid
import shutil
import meeting_ai as core


def change(key, action):
    with core.database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
        if not row: raise ValueError('Запись не найдена.')
        if row['status']=='running':raise ValueError('Дождитесь завершения обработки. Работающую запись удалять нельзя.')
        if action=='trash':
            if row['status']=='deleted':return
            backup=core.ROOT/'state/trash-backups'/key
            backup.mkdir(parents=True,exist_ok=True)
            core.save(backup/(str(time.time_ns())+'.json'),dict(row))
            db.execute("UPDATE jobs SET previous_status=status,status='deleted',deleted_at=? WHERE id=?",(time.time(),key))
        elif action=='restore':
            if row['status']!='deleted':raise ValueError('Запись не находится в корзине.')
            status=row['previous_status'] or 'held'
            if status in {'queued','running','deleted'}:status='held'
            db.execute('UPDATE jobs SET status=?,deleted_at=NULL,previous_status=NULL WHERE id=?',(status,key))
        elif action=='summarize':
            if row['status'] not in {'done','needs_review','needs_speaker_setup','error','held'}:raise ValueError('Дождитесь завершения обработки.')
            folder=core.ROOT/'results'/key[:16]
            if not (folder/'transcript.json').exists():raise ValueError('Сначала нужна расшифровка.')
            archive=folder/('previous-summary-'+uuid.uuid4().hex[:8]);archive.mkdir()
            for name in ['summary.md','minutes.md','summary-method.json','context-audit.md']:
                file=folder/name
                if file.exists():
                    shutil.copy2(file,archive/name)
                    file.unlink()
            db.execute("UPDATE jobs SET status='queued',error='' WHERE id=?",(key,))
        else:raise ValueError('Неизвестное действие.')
