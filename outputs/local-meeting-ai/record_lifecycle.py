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
        if row['status']=='purging':raise ValueError('Окончательное удаление уже начато.')
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

RETENTION_SECONDS = 30 * 24 * 60 * 60


def purge(key, cutoff=None):
    """Delete only owned files; mark first so a partial failure cannot be restored."""
    import re
    from pathlib import Path
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ValueError('Неверный идентификатор записи.')
    with core.database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM jobs WHERE id=?', (key,)).fetchone()
        if not row:
            return False
        if row['status'] not in {'deleted', 'purging'}:
            if cutoff is not None: return False
            raise ValueError('Окончательно удалять можно только записи из корзины.')
        if row['status'] == 'deleted' and cutoff is not None and (row['deleted_at'] is None or row['deleted_at'] > cutoff):
            return False
        root = core.ROOT.resolve()
        audio = Path(row['path'])
        targets = [audio, root/'results'/key[:16], root/'state/trash-backups'/key]
        parents = [root/'inbox', root/'results', root/'state/trash-backups']
        # Validate all resolved paths BEFORE any recursive deletion (including junctions).
        for target, parent in zip(targets, parents):
            if not parent.resolve().is_relative_to(root) or target.resolve().parent != parent.resolve():
                raise ValueError('Путь записи выходит за служебную папку; удаление отменено.')
        if audio.stem != key:
            raise ValueError('Неожиданное имя серверной копии.')
        if db.execute('SELECT 1 FROM jobs WHERE id!=? AND substr(id,1,16)=?', (key,key[:16])).fetchone():
            raise ValueError('Общая папка результатов; удаление отменено.')
        db.execute("UPDATE jobs SET status='purging' WHERE id=?", (key,))
    for target in targets:
        if target.is_dir(): shutil.rmtree(target)
        else: target.unlink(missing_ok=True)
    with core.database() as db:
        db.execute("DELETE FROM jobs WHERE id=? AND status='purging'", (key,))
    return True


def purge_expired(now=None):
    cutoff = (time.time() if now is None else now) - RETENTION_SECONDS
    with core.database() as db:
        keys = [r['id'] for r in db.execute(
            "SELECT id FROM jobs WHERE (status='deleted' AND deleted_at<=?) OR status='purging'", (cutoff,))]
    errors = []
    for key in keys:
        try: purge(key, cutoff)
        except (OSError, ValueError) as exc: errors.append(f'{key[:16]}: {exc}')
    if errors: raise RuntimeError('Очистка корзины: ' + '; '.join(errors))
