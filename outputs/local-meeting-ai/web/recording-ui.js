let captureDevices=[],captureBusy=false,seenCaptureResult='',capturePolling=false,voiceFeedback='';
async function refreshDevices(){
 try{
  const data=await api('/api/devices');captureDevices=data.devices;
  for(const [id,kind,key] of [['capture-device','mic','mic_name'],['capture-system','system','system_name']]){
   const select=$('#'+id),previous=select.value,items=captureDevices.filter(d=>d.kind===kind);
   select.replaceChildren();const none=el('option','','Не записывать');none.value='';select.append(none);
   for(const d of items){const option=el('option','',d.name+' · '+d.id+(d.default?' · Windows по умолчанию':''));option.value=d.id;select.append(option)}
   const matching=items.filter(d=>d.name===data.settings?.[key]);
   const saved=matching.find(d=>d.id===data.settings?.[kind+'_id'])||(matching.length===1?matching[0]:null);
   select.value=items.some(d=>String(d.id)===previous)?previous:saved?String(saved.id):Object.hasOwn(data.settings||{},key)?'':items.length?String((items.find(d=>d.default)||items[0]).id):'';
  }
  $('#capture-device-note').textContent=captureDevices.some(d=>d.kind==='mic')?'Проверьте оба индикатора после запуска. Выбор источников сохраняется.':'Микрофон не обнаружен: комнату записать нельзя. Можно записывать только звук компьютера или подключить микрофон и обновить устройства.';
 }catch(e){toast(e.message);$('#capture-device-note').textContent=e.message}
 const voiceDevice=$('#voice-device'),previousVoice=voiceDevice.value;
 voiceDevice.replaceChildren(el('option','','Выберите микрофон'));
 voiceDevice.options[0].value='';
 for(const d of captureDevices.filter(d=>d.kind==='mic')){const option=el('option','',d.name);option.value=d.id;voiceDevice.append(option)}
 voiceDevice.value=[...voiceDevice.options].some(o=>o.value===previousVoice)&&previousVoice?previousVoice:$('#capture-device').value;
 renderCapture();
}
function renderCapture(fast=false){
 if(!state)return;
 const r=state.recording||{},busy=['recording','saving','enrolling'].includes(r.status);
 $('#capture-badge').textContent=({idle:'Готов к записи',recording:'Идёт запись',saving:'Сохраняем',enrolling:'Сохраняем голос',complete:'Сохранено',error:'Ошибка записи'})[r.status]||'Готов к записи';
 const voice=$('#capture-purpose').value==='voice';
 $('#capture-start').disabled=captureBusy||busy||(voice?!$('#capture-device').value:!$('#capture-device').value&&!$('#capture-system').value);
 $('#capture-stop').disabled=captureBusy||r.status!=='recording';
 $('#capture-reset').hidden=r.status!=='error';
 $('#capture-reset').disabled=captureBusy||busy;
 for(const id of ['capture-purpose','capture-name','capture-device','capture-system','capture-refresh','voice-upload'])$('#'+id).disabled=captureBusy||busy||(id==='capture-system'&&voice);
 $('#capture-time').textContent=stamp(r.seconds||0);$('#capture-level').value=r.levels?.mic||0;$('#capture-system-level').value=r.levels?.system||0;
 $('.capture-panel').classList.toggle('is-recording',r.status==='recording');
 document.title=r.status==='recording'?'● Запись '+stamp(r.seconds||0)+' — Протокол':'Протокол — записи встреч';
 $('#capture-path').textContent=r.file?'Файл встречи: '+r.file:'';
 $('#capture-status').textContent=r.error||r.warning||(r.status==='complete'?(r.purpose==='voice'?'Голос сохранён: '+r.name+'. Следующие записи будут сравниваться с ним.':'Разговор сохранён и добавлен в очередь.') : r.status==='recording'?'Идёт запись. Остановите её после завершения разговора.':r.status==='enrolling'?'Проверяем образец и сохраняем голос…':'После остановки разговор автоматически попадёт в очередь.');
 if(!fast){
 const recovery=$('#capture-recovery');recovery.replaceChildren();
 const pending=state.recoverable||[];
 if(pending.some(item=>!item.can_recover)){
  const clear=el('button','secondary','Убрать пустые и короткие попытки');clear.disabled=busy||captureBusy;
  clear.onclick=async()=>{captureBusy=true;renderCapture();try{for(const item of pending.filter(item=>!item.can_recover))await api('/api/recording/dismiss','POST',{session:item.id});await refresh()}catch(e){toast(e.message)}finally{captureBusy=false;renderCapture()}};recovery.append(clear);
 }
 for(const item of pending){
  const row=el('div','pending-file',item.name+(item.can_recover?' · незавершённая запись · '+stamp(item.seconds):' · запись пуста или слишком короткая')+' ');
  if(item.can_recover){const button=el('button','secondary','Восстановить и обработать');button.disabled=busy||captureBusy;button.onclick=async()=>{try{await api('/api/recording/recover','POST',{session:item.id});await refresh()}catch(e){toast(e.message)}};row.append(button)}
  const dismiss=el('button','secondary','Убрать из списка');dismiss.title='Исходные файлы останутся в папке recordings';dismiss.disabled=busy||captureBusy;
  dismiss.onclick=async()=>{try{await api('/api/recording/dismiss','POST',{session:item.id});await refresh()}catch(e){toast(e.message)}};row.append(dismiss);recovery.append(row);
 }
 }
 const result=r.result?.job_id;
 if(result&&result!==seenCaptureResult){seenCaptureResult=result;select(result).catch(e=>toast(e.message))}
 renderVoices(fast);
}
$('#capture-purpose').onchange=()=>{
 const voice=$('#capture-purpose').value==='voice';
 $('#capture-name-label').textContent=voice?'Имя сотрудника':'Название разговора';
 $('#capture-name').placeholder=voice?'Например: Иван Петров':'Например: Планёрка';
 renderCapture();
};
$('#capture-device').onchange=renderCapture;$('#capture-system').onchange=renderCapture;
$('#capture-refresh').onclick=refreshDevices;
$('#capture-reset').onclick=async()=>{try{await api('/api/recording/reset','POST');await refresh()}catch(e){toast(e.message)}};
$('#capture-start').onclick=async()=>{
 captureBusy=true;renderCapture();
 try{await api('/api/recording/start','POST',{device:$('#capture-device').value===''?null:Number($('#capture-device').value),system_device:$('#capture-system').value===''?null:Number($('#capture-system').value),purpose:$('#capture-purpose').value,name:$('#capture-name').value});await refresh()}
 catch(e){toast(e.message)}finally{captureBusy=false;renderCapture()}
};
$('#capture-stop').onclick=async()=>{
 captureBusy=true;renderCapture();
 try{await api('/api/recording/stop','POST');await refresh()}catch(e){toast(e.message)}finally{captureBusy=false;renderCapture()}
};
$('#voice-upload').onclick=()=>{
 if($('#voice-name').value.trim().length<2)return toast('Введите имя и фамилию в разделе «Голоса».');
 $('#voice-file').click();
};
$('#voice-file').onchange=async e=>{
 const file=e.target.files[0];if(!file)return;
 captureBusy=true;renderCapture();
 try{
  if(file.size>100*1024**2)throw Error('Образец должен быть до 100 МБ и короче 3 минут.');
  voiceFeedback='Загружаем и проверяем образец…';$('#voice-status').textContent=voiceFeedback;
  const response=await fetch('/api/voices/upload',{method:'POST',headers:{'X-Local-App':'meeting-ai','X-Filename':encodeURIComponent(file.name),'X-Person-Name':encodeURIComponent($('#voice-name').value.trim())},body:file});
  const result=await response.json();if(!response.ok)throw Error(result.error);
  await refresh();
  voiceFeedback='Образец передан на проверку. Дождитесь завершения обработки.';
 }catch(e){toast(e.message);voiceFeedback=e.message}finally{captureBusy=false;e.target.value='';renderCapture()}
};
function openVoiceEditor(name=''){
 view('voices');$('#voice-editor').hidden=false;
 if(!captureBusy&&!['recording','saving','enrolling'].includes(state?.recording?.status)){
  $('#voice-name').value=name;voiceFeedback='';
 }
 renderVoices(true);$('#voice-name').focus();
}
function renderVoices(fast=false){
 const r=state?.recording||{},busy=captureBusy||['recording','saving','enrolling'].includes(r.status),own=r.purpose==='voice';
 const valid=$('#voice-name').value.trim().length>=2;
 for(const id of ['voice-name','voice-device','voice-refresh'])$('#'+id).disabled=busy;
 $('#voice-upload').disabled=busy||!valid;
 $('#voice-start').disabled=busy||!valid||!$('#voice-device').value;
 $('#voice-stop').disabled=captureBusy||!own||r.status!=='recording';
 $('#voice-close').disabled=busy&&own;
 $('#voice-time').textContent=stamp(own?r.seconds||0:0);
 $('#voice-level').value=own?r.levels?.mic||0:0;
 $('#voice-editor').classList.toggle('is-recording',own&&r.status==='recording');
 $('#voice-device-note').textContent=captureDevices.some(d=>d.kind==='mic')?'Запись с микрофона сервера. Для образца системный звук отключён.':'На сервере не обнаружен микрофон. Можно загрузить аудиофайл со своим голосом.';
 $('#voice-status').textContent=voiceFeedback||(own&&r.status==='recording'?'Идёт запись голоса «'+r.name+'». Говорите 20–40 секунд, затем остановите запись.':own&&['saving','enrolling'].includes(r.status)?'Проверяем образец и сохраняем голос…':own&&r.status==='complete'?'Голос сохранён: '+r.name:own&&r.error?r.error:busy?'Сейчас сервер занят другой записью. Дождитесь её завершения.':!valid?'Введите имя и фамилию, затем запишите голос или загрузите файл.':'Можно записать голос или загрузить готовый образец.');
 if(fast)return;
 const profiles=$('#voice-profiles');profiles.replaceChildren();$('#voice-count').textContent=state?.profiles?.length||0;
 for(const p of state?.profiles||[]){
  const row=el('div','voice-profile'),info=el('div','');
  info.append(el('strong','',p.name),el('p','muted','Образцов: '+p.samples+' · чистой речи: '+p.speech_seconds+' с'));
  const button=el('button','secondary','Добавить образец');button.disabled=busy;button.onclick=()=>openVoiceEditor(p.name);
  row.append(info,button);profiles.append(row);
 }
 if(!state?.profiles?.length){profiles.append(el('p','','Пока нет добавленных голосов. Начните со своего — нажмите «Добавить голос».'))}
}
$('#voice-add').onclick=()=>openVoiceEditor();
$('#voice-close').onclick=()=>{$('#voice-editor').hidden=true};
$('#voice-name').oninput=()=>renderVoices(true);
$('#voice-device').onchange=()=>renderVoices(true);
$('#voice-refresh').onclick=refreshDevices;
$('#voice-start').onclick=async()=>{
 if($('#voice-name').value.trim().length<2||!$('#voice-device').value)return;
 captureBusy=true;voiceFeedback='';renderCapture();
 try{await api('/api/recording/start','POST',{device:Number($('#voice-device').value),system_device:null,purpose:'voice',name:$('#voice-name').value.trim()});await refresh()}
 catch(e){voiceFeedback=e.message;toast(e.message)}finally{captureBusy=false;renderCapture()}
};
$('#voice-stop').onclick=async()=>{
 if(state?.recording?.purpose!=='voice'||state.recording.status!=='recording')return;
 captureBusy=true;renderCapture();
 try{await api('/api/recording/stop','POST');await refresh()}
 catch(e){voiceFeedback=e.message;toast(e.message)}finally{captureBusy=false;renderCapture()}
};
$('#recognize-again').onclick=async()=>{
 try{await api('/api/jobs/'+selected+'/recognize','POST');toast('Запись возвращена в очередь для обновления имён и конспекта.');await refresh()}catch(e){toast(e.message)}
};
window.addEventListener('DOMContentLoaded',refreshDevices);
setInterval(async()=>{
 if(capturePolling||document.hidden||!state)return;
 capturePolling=true;
 try{const before=state.recording?.status;state.recording=await api('/api/recording');renderCapture(true);if(state.recording.status!==before)await refresh()}
 catch(e){if(state.recording?.status==='recording'){$('#capture-status').textContent='Нет связи с программой: состояние записи неизвестно.';$('.capture-panel').classList.remove('is-recording')}}
 finally{capturePolling=false}
},500);
function setTheme(dark){document.documentElement.dataset.theme=dark?'dark':'light';$('#theme-toggle').textContent=dark?'Светлая тема':'Тёмная тема';$('#theme-toggle').setAttribute('aria-pressed',String(dark));try{localStorage.setItem('protocol-theme',dark?'dark':'light')}catch{}}
let initialTheme='dark';try{initialTheme=localStorage.getItem('protocol-theme')||'dark'}catch{}
setTheme(initialTheme==='dark');$('#theme-toggle').onclick=()=>setTheme(document.documentElement.dataset.theme!=='dark');
