// Navigation identity is separate from rendered selection. Null is not primary 0.
function parseViewerQuery(search) {
  const q=new URLSearchParams(search), state={model:'AK02',event:null,group:null,invalid:''};
  for(const key of q.keys())if(!['model','event','group'].includes(key)||q.getAll(key).length!==1)state.invalid='Unknown or repeated query parameter.';
  if(q.has('model')){state.model=q.get('model');if(!['AK02','SAP22'].includes(state.model))state.invalid='Unknown model.';}
  for(const key of ['event','group'])if(q.has(key)){
    const raw=q.get(key), value=Number(raw);
    if(!/^(0|[1-9][0-9]*)$/.test(raw)||!Number.isSafeInteger(value)||(key==='event'&&value>9999))state.invalid='Invalid '+key+'; use a nonnegative integer'+(key==='event'?' from 0 to 9999.':'.');
    else state[key]=value;
  }
  if(state.group!==null&&state.event===null)state.invalid='A group requires a primary event ID.';
  return state;
}
const navigation=parseViewerQuery(location.search);
function navigationLinks(success=false){
  const link=document.getElementById('reciprocal'), status=document.getElementById('identity');
  if(navigation.invalid){link.removeAttribute('href');link.setAttribute('aria-disabled','true');status.textContent='Unavailable request: '+navigation.invalid+' Query: '+location.search;return;}
  const q=new URLSearchParams({model:navigation.model});
  if(navigation.event!==null)q.set('event',navigation.event);
  if(navigation.group!==null)q.set('group',navigation.group);
  link.href=link.dataset.route+'?'+q;link.removeAttribute('aria-disabled');
  status.textContent=(success?'Selected: ':'Requested: ')+navigation.model+(navigation.event===null?'':', original primary '+navigation.event)+
    (navigation.group===null?'':', group '+navigation.group)+(link.dataset.kind==='assembly'&&navigation.group!==null?' (return-navigation context only; assembly does not render pulse groups).':'');
  if(success)history.replaceState(null,'',location.pathname+'?'+q);
}
function requestIdentity(model,event,group){Object.assign(navigation,{model,event,group,invalid:''});navigationLinks();}
function successfulIdentity(model,event,group){requestIdentity(model,event,group);navigationLinks(true);}
function unavailableSelection(message){
  document.getElementById('status').textContent='Unavailable: '+message+' No primary or group is highlighted. Use the all-event assembly for the requested primary.';
  navigationLinks();
}
