"""Bounded, resumable analysis with a second pass over every original fragment."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

VERSION = 5


class EarlierContext:
    """Retrieve earlier source quotes by topic; never introduce future replies."""
    def __init__(self, parts):
        self.lines = []
        self.frequency = Counter()
        for part_index, part in enumerate(parts):
            for line in part.splitlines():
                terms = self.terms(line)
                self.lines.append((part_index, line, terms))
                self.frequency.update(terms)

    @staticmethod
    def terms(text):
        # A short prefix groups common Russian inflections without a downloaded
        # language service; retrieved text always remains verbatim evidence.
        return {word[:5] for word in re.findall(r'[а-яёa-z]{5,}',text.lower())}

    def get(self, index, text, preceding):
        terms = self.terms(text)
        candidates = []
        for order,(part,line,words) in enumerate(self.lines):
            if part>=index:break
            if line in preceding:continue
            shared=terms & words
            if len(shared)<2:continue
            score=sum(math.log(1+len(self.lines)/(1+self.frequency[t])) for t in shared)
            candidates.append((score,order,line))
        selected=[];size=0
        for score,order,line in sorted(candidates,reverse=True):
            if size+len(line)>1200:continue
            selected.append((order,line));size+=len(line)
            if len(selected)==3:break
        return '\n'.join(line for _,line in sorted(selected)) or 'Другие связанные реплики не найдены.'


def run(data, folder, cfg, ask, chunks, transcript_lines, save, model):
    folder = Path(folder)
    fingerprint = hashlib.sha256(json.dumps({
        'version': VERSION, 'transcript': data, 'config': cfg,
        'model_size': model.stat().st_size, 'model_mtime': model.stat().st_mtime_ns,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cache = folder / 'summary-checkpoints' / fingerprint[:24]
    cache.mkdir(parents=True, exist_ok=True)
    save(folder/'summary-in-progress.json', {'fingerprint':fingerprint})
    calls = 0

    def cached(text, **options):
        nonlocal calls
        request_key=[text, options]
        if options.get('audit'):request_key.append('source-evidence-v4')
        if options.get('merge'):request_key.append('source-evidence-merge-v4')
        key = hashlib.sha256(json.dumps(request_key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = cache / (key[:24] + '.json')
        if path.exists():
            try:
                entry = json.loads(path.read_text(encoding='utf-8'))
                if entry['key'] == key and entry['fingerprint'] == fingerprint and entry['text'].strip():
                    return entry['text']
            except (ValueError, KeyError, TypeError):
                pass
        result = ask(text, **options)
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError('Модель вернула пустой ответ. Промежуточные результаты сохранены.')
        save(path, {'key': key, 'fingerprint': fingerprint, 'text': result})
        calls += 1
        return result

    def merge(notes, phase):
        # The depth follows the input size, rather than imposing a meeting-length limit.
        # Require progress to catch a model that repeats instead of consolidating.
        # A larger context can combine more evidence in one call, reducing both
        # latency and the number of lossy intermediate reductions. ask() still
        # checks actual token count before dispatching the request.
        merge_limit = 12000 if cfg['summary_context'] >= 16384 else 4000
        while len(notes) > 1:
            groups = list(chunks(notes, limit=merge_limit))
            save(folder/'progress.json', {'stage':'summarizing', 'phase':phase, 'part':0, 'total':len(groups)})
            merged = [cached(group, merge=True) for group in groups]
            if len(merged) >= len(notes) and sum(map(len, merged)) >= sum(map(len, notes)):
                raise RuntimeError('Модель не сокращает промежуточную сводку. Все части сохранены; повтор продолжит с контрольных точек.')
            notes = merged
        return notes[0]

    parts = list(chunks(transcript_lines(data), limit=4000))
    earlier = EarlierContext(parts)
    notes, details = [], []
    for index, text in enumerate(parts):
        save(folder/'progress.json', {'stage':'summarizing', 'phase':'details', 'part':index+1, 'total':len(parts)})
        note = cached(text)
        # Verbatim overlap avoids carrying forward a mistaken previous summary.
        context = parts[index-1][-1200:] if index else 'Это начало записи.'
        related = earlier.get(index,text,context)
        detail = cached('КОНТЕКСТ ПРЕДЫДУЩЕЙ ЧАСТИ:\n'+context+'\n\nСВЯЗАННЫЕ БОЛЕЕ РАННИЕ РЕПЛИКИ (только для понимания):\n'+related+
            '\n\nОСНОВНОЙ ФРАГМЕНТ:\n'+text, detailed=True)
        (folder/f'detail-{index+1:03d}.md').write_text(detail, encoding='utf-8')
        (folder/f'part-{index+1:03d}.md').write_text(note, encoding='utf-8')
        notes.append(note)
        details.append(f'## Часть {index+1}\n\n'+detail)
    draft = merge(notes, 'merge')
    # Independently extract positive evidence from ALL original text. Showing
    # the global draft to a local checker caused false "not in this fragment"
    # objections to valid later decisions. Absence is never counter-evidence.
    audits = []
    total = len(parts)
    for index, text in enumerate(parts):
        context = parts[index-1][-1200:] if index else 'Это начало записи.'
        save(folder/'progress.json', {'stage':'auditing', 'part':index+1, 'total':total})
        audit = cached('ПРЕДЫДУЩИЕ РЕПЛИКИ ДЛЯ КОНТЕКСТА:\n'+context+
            '\n\nИСХОДНЫЙ ФРАГМЕНТ ДЛЯ ПРОВЕРКИ:\n'+text, audit=True)
        (folder/f'audit-{index+1:03d}-001.md').write_text(audit, encoding='utf-8')
        audits.append(f'Подтверждённые исходником факты части {index+1}:\n'+audit)
    final = merge(['ПРЕДВАРИТЕЛЬНАЯ СВОДКА:\n'+draft, *audits], 'verified_merge')
    notice = ('Черновик по расшифровке. Проверьте имена, решения и отметки времени по аудио. '
              'Все части записи прошли анализ и повторную проверку, но это не гарантирует отсутствия ошибок модели.\n\n')
    # Publish the completion manifest last; partial processing is never marked ready.
    for name, content in {
        'summary.md': '# Сводка\n\n'+notice+final,
        'minutes.md': '# Подробный конспект\n\n'+notice+'## Итоги разговора\n\n'+final+'\n\n'+'\n\n'.join(details),
        'context-audit.md': '# Проверка по исходной расшифровке\n\n'+notice+'\n\n'.join(audits),
    }.items():
        temp = folder / (name+'.part')
        temp.write_text(content, encoding='utf-8')
        temp.replace(folder/name)
    save(folder/'summary-method.json', {'version':VERSION, 'parts':len(parts), 'audited_parts':len(parts),
        'audit_passes':total, 'audit_method':'independent-source-evidence-v4',
        'context':cfg['summary_context'], 'model':cfg['summary_model'],
        'detail_files':len(details), 'fingerprint':fingerprint, 'new_model_calls':calls})
    (folder/'summary-in-progress.json').unlink(missing_ok=True)
