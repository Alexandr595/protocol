let captureBusy=false,voiceFeedback='';
function recorderUrl(path){
 const url=new URL(path,location.href);
 if(!window.isSecureContext)url.protocol='https:';
 return url;
}
for(const link of document.querySelectorAll('[data-recorder]'))link.href=recorderUrl(link.href);
function openVoiceEditor(name=''){
 view('voices');$('#voice-editor').hidden=false;$('#voice-name').value=name;voiceFeedback='';renderCapture();$('#voice-name').focus();
}
function renderCapture(){
 const busy=captureBusy;
 $('#voice-status').textContent=voiceFeedback;
 $('#voice-upload').disabled=busy||$('#voice-name').value.trim().length<2;
 const url=recorderUrl('/record?voice=1');
 url.searchParams.set('name',$('#voice-name').value.trim());
 $('#browser-voice').href=url;
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
$('#voice-name').oninput=()=>renderCapture();
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
$('#recognize-again').onclick=async()=>{
 try{await api('/api/jobs/'+selected+'/recognize','POST');toast('Запись возвращена в очередь для обновления имён и конспекта.');await refresh()}catch(e){toast(e.message)}
};

if(location.hash==='#voices')view('voices');
