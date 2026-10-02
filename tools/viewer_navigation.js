// Requested identity is distinct from a verified primary or pulse group.
function parseViewerQuery(search, options = {}) {
  const legacy = options.legacy === true, q = new URLSearchParams(search);
  const state = {model:'AK02',event:null,group:null,view:options.view || 'assembly',invalid:''};
  const allowed = legacy ? ['model','event','group'] : ['model','event','group','view'];
  for (const key of q.keys()) if (!allowed.includes(key) || q.getAll(key).length !== 1)
    state.invalid = 'Unknown or repeated query parameter.';
  if (q.has('model')) {state.model = q.get('model');if (!['AK02','SAP22'].includes(state.model))state.invalid = 'Unknown model.';}
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
function viewerHistoryTarget(identity, pathname, search) {
  const target = pathname+'?'+canonicalViewerQuery(identity);
  return {target,changed:target !== pathname+search};
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
