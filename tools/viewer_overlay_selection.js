async function selectEvent(id,groupId=null){
  requestIdentity($('model').value,id,groupId);
  if(!data)return;
  const chosenData=data,chosenModel=activeModel,category=$('category').value;
  $('event').value='';$('group').replaceChildren();$('group').disabled=true;
  await gate.run(async()=>{
    const event=events.get(id),proof=evidence.get(id);
    if(!event||!proof)throw Error(`${chosenModel} primary ${id} is outside the saved Ge-positive population (zero-Ge or otherwise not represented).`);
    const matches=proof.groups.filter(g=>category==='all'||g.categories.includes(category));
    const group=groupId===null?matches[0]:matches.find(g=>g.group_id===groupId);
    if(!group)throw Error(`${chosenModel} primary ${id}${groupId===null?'':', group '+groupId} is not represented by the current candidate filter / saved groups.`);
    return {event,group,matches};
  },value=>{
    if(chosenData!==data||chosenModel!==activeModel)return;
    selected=value.event;selectedGroup=value.group;$('event').value=String(id);
    $('group').replaceChildren(...value.matches.map(g=>option(g.group_id,`${g.group_id} · ${g.ge_energy_keV.toPrecision(6)} keV`)));
    $('group').disabled=false;$('group').value=String(value.group.group_id);
    successfulIdentity(chosenModel,id,value.group.group_id);describe();
  },error=>unavailableSelection(error.message));
}
function filterCategory(preferred=null){
  if(!data)return;
  gate.invalidate();$('event').replaceChildren();$('group').replaceChildren();$('group').disabled=true;
  const category=$('category').value,members=category==='all'?data.event_ids:data.categories[category].map(m=>m.event_id),ids=[...new Set(members)];
  const empty=option('','Choose a represented primary');empty.disabled=true;
  $('event').replaceChildren(empty,...ids.map(id=>option(id,String(id))));$('event').value='';$('event').disabled=!ids.length;
  if(navigation.invalid){unavailableSelection(navigation.invalid);return;}
  const id=preferred?.event_id??navigation.event??ids[0],group=preferred?.group_id??navigation.group;
  if(id===undefined){unavailableSelection('No saved groups in this category.');return;}
  selectEvent(id,group);
}
