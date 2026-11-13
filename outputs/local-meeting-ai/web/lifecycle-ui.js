function renderLifecycle(){
 const box=$('#trash-list');box.replaceChildren();
 for(const item of state?.trash||[]){const row=el('div','pending-file',item.name+' · '+date(item.deleted_at)+' '),button=el('button','secondary','Восстановить');button.onclick=async()=>{try{await api('/api/jobs/'+item.id+'/restore','POST');await refresh();toast('Восстановлено. Незавершённые задачи возвращаются отложенными.')}catch(e){toast(e.message)}};button.disabled=item.status==='purging';
 const more=el('details',''),label=el('summary','','Дополнительно'),remove=el('button','secondary','Удалить окончательно');
 remove.onclick=async()=>{if(!confirm('Навсегда удалить «'+item.name+'», серверное аудио и результаты? Восстановление из корзины станет невозможным.'))return;remove.disabled=true;try{await api('/api/jobs/'+item.id+'/purge','POST');await refresh();toast('Удалено окончательно.')}catch(e){toast(e.message);remove.disabled=false}};
 more.append(label,remove);row.append(button,el('span','muted',item.status==='purging'?'Удаление ожидает завершения':'Автоудаление: '+date(item.deleted_at+30*86400)),more);box.append(row)}
 if(!state?.trash?.length)box.append(el('p','muted','Корзина пуста.'));
 const row=state?.jobs.find(j=>j.id===selected);
 $('#trash-job').disabled=!row||row.status==='running';
 $('#summarize-job').disabled=!row||!row.has_transcript||!['done','needs_review','needs_speaker_setup','error','held'].includes(row.status);
}
$('#trash-job').onclick=async()=>{if(!selected)return;try{await api('/api/jobs/'+selected+'/trash','POST');selected=null;current=null;$('#player').pause();$('#player').removeAttribute('src');$('#detail-content').classList.add('hidden');$('#detail-empty').classList.remove('hidden');await refresh();toast('Перемещено в корзину. Файлы сохранены.')}catch(e){toast(e.message)}};
$('#summarize-job').onclick=async()=>{if(!selected)return;try{await api('/api/jobs/'+selected+'/summarize','POST');await refresh();toast('Поставлено в очередь. Предыдущие результаты сохранены.')}catch(e){toast(e.message)}};
