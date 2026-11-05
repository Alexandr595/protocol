// Folder configuration and queue controls. Rendering never overwrites an edited form.
let folderFormInitialized = false;

function describeProgress(job) {
 const p = job.progress || {};
 let text = stages[p.stage] || 'Готовим запись к обработке…';
 if (p.seconds !== undefined) text += ` ${stamp(p.seconds)} из ${stamp(p.duration || 0)}`;
 if (p.part) text += ` Часть ${p.part} из ${p.total}`;
 return text;
}

function renderQueueControls() {
 if (!state) return;
 const counts = state.counts || {};
 $('#count-all').textContent = Object.values(counts).reduce((a,b)=>a+b,0);
 $('#count-queue').textContent = counts.queued || 0;
 $('#count-active').textContent = counts.running || 0;
 $('#count-done').textContent = (counts.done || 0) + (counts.needs_review || 0) + (counts.needs_speaker_setup || 0);
 const cfg = state.folder;
 if (cfg) {
  if (!folderFormInitialized) {
   $('#folder-path').value = cfg.folder;
   $('#folder-enabled').checked = cfg.enabled;
   $('#folder-mode').value = cfg.mode;
   $('#folder-settle').value = cfg.settle_seconds;
   folderFormInitialized = true;
  }
  $('#folder-indicator').textContent = cfg.error ? 'Папка недоступна' : cfg.enabled ? 'Наблюдение включено' : 'Наблюдение выключено';
  $('#folder-status').textContent = cfg.error || (cfg.enabled
   ? `Проверка каждые 5 секунд. ${cfg.mode === 'stable' ? 'Добавляем после '+cfg.settle_seconds+' секунд без изменений.' : 'Ждём отметку .ready от программы записи.'} ${cfg.processing_enabled ? 'Обработка автоматическая.' : 'Обработка на паузе, новые файлы продолжают поступать в очередь.'}`
   : 'Автоматический приём выключен.');
  const pending = $('#pending-files');
  pending.replaceChildren();
  for (const file of cfg.pending || []) pending.append(el('div','pending-file',file.name+' · '+file.reason));
 }
 const running = state.jobs.find(j=>j.status==='running');
 if(!running&&['recording','saving','enrolling'].includes(state.recording?.status))$('#worker-label').textContent='Новые задания ждут завершения записи';
 $('#active-name').textContent = running ? running.name : 'Нет активной записи';
 $('#active-stage').textContent = running ? describeProgress(running) : state.worker ? 'Ожидаем записи в очереди' : 'Обработка приостановлена';
 const progress = $('#active-progress');
 progress.classList.toggle('hidden',!running);
 if (running && running.progress.duration > 0) progress.value = Math.min(100,running.progress.seconds/running.progress.duration*100);
 else progress.removeAttribute('value');
 if (current) {
  const row = state.jobs.find(j=>j.id===current.id) || current;
  const editable = row.status==='queued' || row.status==='held';
  $('#job-controls').classList.toggle('hidden',!editable);
  if (document.activeElement !== $('#job-priority')) $('#job-priority').value = row.priority || 0;
  $('#hold-job').textContent = row.status==='held' ? 'Вернуть в очередь' : 'Отложить';
  if (row.status==='running') $('#detail-notice').textContent = describeProgress(row);
  if (row.status==='held') {
   $('#detail-notice').textContent = 'Запись отложена. Автоматическая обработка её пропускает, пока вы не вернёте её в очередь.';
   $('#detail-notice').classList.remove('hidden');
  }
 }
}

$('#folder-form').onsubmit = async event => {
 event.preventDefault();
 const button = event.submitter;
 button.disabled = true;
 try {
  await api('/api/folder','POST',{
   folder:$('#folder-path').value.trim(), enabled:$('#folder-enabled').checked,
   mode:$('#folder-mode').value, settle_seconds:Number($('#folder-settle').value)
  });
  folderFormInitialized = false;
  toast('Папка сохранена. Готовые записи будут добавляться автоматически.');
  await refresh();
 } catch(error) { toast(error.message); }
 finally { button.disabled=false; }
};

$('#job-priority').onchange = async event => {
 if (!selected) return;
 try {
  await api('/api/jobs/'+selected+'/priority','POST',{priority:Number(event.target.value)});
  toast('Приоритет изменён. Текущая запись продолжит обработку.');
  await refresh();
 } catch(error) { toast(error.message); }
};

$('#hold-job').onclick = async () => {
 const row = state.jobs.find(j=>j.id===selected);
 if (!row) return;
 try {
  await api('/api/jobs/'+selected+(row.status==='held'?'/resume':'/hold'),'POST');
  await refresh();
 } catch(error) { toast(error.message); }
};
