function renderLifecycle(){
 const box=$('#trash-list');box.replaceChildren();
 for(const item of state?.trash||[]){const row=el('div','pending-file',item.name+' · '+date(item.deleted_at)+' '),button=el('button','secondary','Восстановить');button.onclick=async()=>{try{await api('/api/jobs/'+item.id+'/restore','POST');await refresh();toast('Восстановлено. Незавершённые задачи возвращаются отложенными.')}catch(e){toast(e.message)}};row.append(button);box.append(row)}
 if(!state?.trash?.length)box.append(el('p','muted','Корзина пуста.'));
 const row=state?.jobs.find(j=>j.id===selected);
 $('#trash-job').disabled=!row||row.status==='running';
 $('#summarize-job').disabled=!row||!row.has_transcript||!['done','needs_review','needs_speaker_setup','error','held'].includes(row.status);
}
$('#trash-job').onclick=async()=>{if(!selected)return;try{await api('/api/jobs/'+selected+'/trash','POST');selected=null;current=null;$('#player').pause();$('#player').removeAttribute('src');$('#detail-content').classList.add('hidden');$('#detail-empty').classList.remove('hidden');await refresh();toast('Перемещено в корзину. Файлы сохранены.')}catch(e){toast(e.message)}};
$('#summarize-job').onclick=async()=>{if(!selected)return;try{await api('/api/jobs/'+selected+'/summarize','POST');await refresh();toast('Поставлено в очередь. Предыдущие результаты сохранены.')}catch(e){toast(e.message)}};
