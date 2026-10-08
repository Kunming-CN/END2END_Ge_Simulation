// Requested identity is distinct from a verified primary or pulse group.
function parseViewerQuery(search, options = {}) {
  const legacy = options.legacy === true, q = new URLSearchParams(search);
  const state = {model:'AK02',event:null,group:null,view:options.view || 'assembly',invalid:''};
  const allowed = legacy ? ['model','event','group'] : ['model','event','group','view'];
  for (const key of q.keys()) if (!allowed.includes(key) || q.getAll(key).length !== 1)
    state.invalid = 'Unknown or repeated query parameter.';
  if (q.has('model')) {state.model = q.get('model');if (!(legacy ? ['AK02','SAP22'] : ['AK02','SAP22','GeRC02','KMRC01_candidate']).includes(state.model))state.invalid = 'Unknown model.';}
  if (!legacy && q.has('view')) state.view = q.get('view');
  if (!['assembly','positive'].includes(state.view)) state.invalid = 'Unknown view.';
  for (const key of ['event','group']) if (q.has(key)) {
    const raw = q.get(key), value = Number(raw);
    if (!/^(0|[1-9][0-9]*)$/.test(raw) || !Number.isSafeInteger(value) || (key === 'event' && value > 9999))
      state.invalid = 'Invalid '+key+'; use a nonnegative integer'+(key === 'event'?' from 0 to 9999.':'.');
    else state[key] = value;
  }
  if (state.group !== null && state.event === null) state.invalid = 'A group requires a primary event ID.';
  return state;
}
function canonicalViewerQuery(identity) {
  if (identity.invalid) throw Error(identity.invalid);
  const q = new URLSearchParams({model:identity.model});
  if (identity.event !== null) q.set('event', String(identity.event));
  if (identity.group !== null) q.set('group', String(identity.group));
  q.set('view', identity.view);
  const result = parseViewerQuery('?'+q);
  if (result.invalid) throw Error(result.invalid);
  return q.toString();
}
function legacyViewerTarget(search, view) {
  const requested = parseViewerQuery(search,{legacy:true,view});
  return {requested,target:requested.invalid ? null : 'events.html?'+canonicalViewerQuery(requested)};
}
function viewerHistoryTarget(identity, pathname, search, hash = '') {
  const target = pathname+'?'+canonicalViewerQuery(identity)+hash;
  return {target,changed:target !== pathname+search+hash};
}
// Only a verified case route table supplies model-specific destinations. Page
// ownership stays fixed; this changes the local selection label and view links.
function updateCaseNavigation(routes, label, invalid = '') {
  for (const node of document.querySelectorAll('[data-dataset="tenk"]'))
    node.dataset.model=invalid?'':routes?.model||'';
  for (const node of document.querySelectorAll('[data-context-label]'))
    node.textContent = invalid || label;
  for (const node of document.querySelectorAll('[data-context-link]')) {
    const kind = node.dataset.contextLink, href = routes?.[kind] ||
      (!invalid && !['result','files'].includes(kind) ? node.dataset.baseHref : null);
    if (href && !invalid) {
      node.href = href;node.hidden = false;node.removeAttribute('aria-disabled');
    } else {
      node.removeAttribute('href');node.setAttribute('aria-disabled','true');
      node.hidden = !invalid && ['result','files'].includes(kind);
    }
  }
}
function spectrumFocusState(hash, cases) {
  if (!hash || hash === '#') return {model:null,invalid:''};
  let id;
  try {id=decodeURIComponent(hash.slice(1));}
  catch {return {model:null,invalid:'Unavailable spectrum focus: malformed fragment.'};}
  const entry=Object.entries(cases).find(([model])=>id==='tenk-'+model);
  return entry ? {model:entry[0],invalid:''} :
    {model:null,invalid:'Unavailable spectrum focus: '+id+'. Choose a saved case.'};
}
function installSpectrumFocus(cases) {
  const select=document.getElementById('spectrum-case'),status=document.getElementById('spectrum-focus');
  function restore() {
    const state=spectrumFocusState(location.hash,cases),entry=state.model===null?null:cases[state.model];
    select.value=state.model||'';
    status.textContent=state.invalid || (entry ? 'Focused case: '+entry.label+'. All four cases remain below.' :
      'All four cases. Choose a case to preserve its identity when switching views.');
    status.className=state.invalid?'error':'';
    updateCaseNavigation(entry,entry?'Focused case: '+entry.label:'All four cases',state.invalid);
    return state;
  }
  select.onchange=()=>{location.hash=select.value?'tenk-'+select.value:'';restore();};
  globalThis.addEventListener('hashchange',restore);
  globalThis.addEventListener('popstate',restore);
  restore();
  return {restore};
}
function selectionGate(clear) {
  let generation = 0;
  return {
    invalidate(){++generation;clear();},
    async run(load,apply,fail){
      const ticket = ++generation;clear();
      try {const result = await load();if(ticket !== generation)return false;apply(result);return true;}
      catch(error){if(ticket === generation)fail(error);return false;}
    }
  };
}
