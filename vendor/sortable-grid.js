(function(){
  function ensureExportModalGlobals(){
    let modal=document.getElementById('exportModal');
    if(!modal){
      modal=document.createElement('div');
      modal.id='exportModal';
      modal.className='modal';
      modal.innerHTML='<div class="modalCard"><div class="modalHead"><h2>Export Army JSON</h2><button id="exportClose" class="closeX">×</button></div><textarea id="modalText"></textarea><div class="row"><button id="exportClose2" class="modalPrimary">Close</button></div></div>';
      document.body.appendChild(modal);
    }
    window.exportModal=modal;
    window.modalText=document.getElementById('modalText');
    window.exportClose=document.getElementById('exportClose');
    window.exportClose2=document.getElementById('exportClose2');
  }
  function ensureUiStyles(){
    if(document.getElementById('armyBuilderInjectedStyle'))return;
    const st=document.createElement('style');
    st.id='armyBuilderInjectedStyle';
    st.textContent=`
      .loadout{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:6px;margin-top:0}
      .loadTitle{grid-column:1/-1;font:900 12px var(--title);letter-spacing:.35px;color:#ffe3a3;text-transform:uppercase;margin:0 0 1px}
      .loadCheck{display:block;cursor:pointer;min-width:0}
      .loadCheck input{position:absolute;opacity:0;pointer-events:none}
      .loadCheck span{display:grid;place-items:center;min-height:28px;padding:5px 8px;border:1px solid #5e6670;background:#0b0d10;color:#d5b06d;font-size:12px;font-weight:900;text-align:center;line-height:1.1;box-shadow:inset 0 0 10px #000}
      .loadCheck span b{font-weight:900}
      .loadCheck:hover span{border-color:#d6a64c;color:#ffe3a3}
      .loadCheck input:checked+span{display:flex;align-items:center;justify-content:center;border-color:#d6a64c;background:linear-gradient(180deg,#3a1908,#0d0f11);color:#fff1c9;box-shadow:inset 0 0 0 1px #d6a64c,0 0 10px #d6a64c33}
      .loadCheck input:checked+span:before{content:'✓';margin-right:4px;color:#86e56a}
      .charLimitToggle{width:100%;border:1px solid #5e6670;background:#0b0d10;color:#d5b06d;font:900 12px var(--ui);padding:6px 8px;cursor:pointer;text-transform:uppercase;letter-spacing:.25px}
      .charLimitToggle.on{border-color:#d6a64c;color:#fff1c9;box-shadow:inset 0 0 0 1px #d6a64c,0 0 10px #d6a64c33}
      .groupTitle{position:relative}
      .charMiniToggle{float:right;min-width:28px;height:20px;margin:-2px 0 -2px 8px;border:1px solid #d6a64c;background:#120303;color:#d6a64c;font:900 12px var(--ui);cursor:pointer;line-height:16px}
      .charMiniToggle.on{background:#3a1908;color:#fff1c9;box-shadow:inset 0 0 0 1px #d6a64c}
      @media(min-width:1121px){
        .wrap{align-items:start}
        .detailHero.heroFixed{position:fixed;z-index:20;overflow:auto;scrollbar-width:thin;scrollbar-color:#b66b25 #130302}
        .detailHero.heroFixed::-webkit-scrollbar{width:10px}
        .detailHero.heroFixed::-webkit-scrollbar-track{background:#130302;border-left:1px solid #45100b}
        .detailHero.heroFixed::-webkit-scrollbar-thumb{background:linear-gradient(#d6a64c,#6b2812);border:1px solid #220604;border-radius:8px}
      }
      @media(max-width:1120px){.detailHero{position:relative!important;left:auto!important;top:auto!important;width:auto!important;max-height:none!important;overflow:visible!important}.detailHero.heroFixed{position:relative!important}}
    `;
    document.head.appendChild(st);
  }
  function normalizeLoadoutTitles(){
    document.querySelectorAll('.loadTitle').forEach(el=>{
      const t=el.textContent.trim().toLowerCase();
      if(t==='lore')el.textContent='Spell School';
      else if(t==='loadout / mount')el.textContent='Mount';
      else if(t==='loadout / abilities')el.textContent='Abilities';
    });
  }
  function watchLoadoutTitles(){
    normalizeLoadoutTitles();
    new MutationObserver(normalizeLoadoutTitles).observe(document.body,{childList:true,subtree:true});
  }
  function clearHeroPin(hero){
    if(!hero)return;
    hero.classList.remove('heroFixed');
    hero.style.left='';
    hero.style.top='';
    hero.style.width='';
    hero.style.maxHeight='';
  }
  function resetDetailsPin(){document.querySelectorAll('.detailHero.heroFixed').forEach(clearHeroPin)}
  function syncDetailsPin(){
    const panel=document.getElementById('unitDetails'),hero=panel&&panel.querySelector('.detailHero');
    if(!panel||!hero)return;
    if(window.innerWidth<=1120||document.body.classList.contains('uiHidden')){resetDetailsPin();return}
    const top=136,pad=10,wasFixed=hero.classList.contains('heroFixed');
    if(wasFixed)clearHeroPin(hero);
    const hr=hero.getBoundingClientRect();
    if(hr.top<=top){
      hero.classList.add('heroFixed');
      hero.style.left=hr.left+'px';
      hero.style.top=top+'px';
      hero.style.width=hr.width+'px';
      hero.style.maxHeight=`calc(100vh - ${top+pad}px)`;
    }else clearHeroPin(hero);
  }
  function watchDetailsPin(){
    let ticking=false;
    const run=()=>{ticking=false;syncDetailsPin()};
    const queue=()=>{if(!ticking){ticking=true;requestAnimationFrame(run)}};
    window.addEventListener('scroll',queue,{passive:true});
    window.addEventListener('resize',queue);
    new MutationObserver(queue).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
    queue();
  }
  function installKhorneLoadoutPatch(){
    let tries=0;
    const wait=()=>{
      tries++;
      if(typeof render!=='function'||typeof roster==='undefined'||typeof state==='undefined'||typeof currentFaction==='undefined'||typeof esc!=='function'){
        if(tries<200)setTimeout(wait,25);
        return;
      }
      const oldFindRoster=findRoster,oldDisplayName=displayName,oldRosterVisible=rosterVisible,oldRosterCard=rosterCard,oldRenderDetails=renderDetails,oldRenderRoster=renderRoster,oldAdd=add,oldLoadFaction=loadFaction,oldImageFile=imageFile,oldFallbackFile=fallbackFile,oldValidate=validate;
      window.__khoLoadouts={entries:[]};
      fetch('/factions/khorne/lords_heroes.json').then(r=>r.ok?r.json():{entries:[]}).then(j=>{window.__khoLoadouts=j||{entries:[]};patchLegacyKhorneCosts();normalizeKhorneArmyState();render()}).catch(()=>{});
      function entries(){return window.__khoLoadouts&&Array.isArray(window.__khoLoadouts.entries)?window.__khoLoadouts.entries:[]}
      function entryById(id){if(currentFaction.id!=='khorne'||!id)return null;return entries().find(e=>e.id===id||(e.variants||[]).some(v=>v.id===id))||null}
      function entryFor(u){return entryById((u&&u.rid)||u&&u.id)}
      function variantFor(e,u){let id=(u&&u.rid)||u&&u.id;return e&&(e.variants||[]).find(v=>v.id===id)||e&&(e.variants||[]).find(v=>v.mount==='On Foot')||e&&(e.variants||[])[0]||null}
      function baseVariant(e){return variantFor(e,{rid:e&&e.id})}
      function unitName(e,v){if(e&&e.id==='wh3_dlc26_kho_cha_arbaal')return e.name;let m=v&&v.mount;return m&&m!=='On Foot'?`${e.name} (${m})`:e.name}
      function abilityMap(e){let out={};(e&&e.abilities||[]).forEach(a=>out[a.key]=a);return out}
      function manifestHit(id){let m=imageManifest;if(Array.isArray(m))return m.find(x=>x.unit===id)||null;return m&&m.by_unit_id&&m.by_unit_id[id]||null}
      function fileFromManifest(hit){return hit&&(hit.image_file||hit.filename)||''}
      function allAbilityKeys(e){return (e&&e.abilities||[]).map(a=>a.key)}
      function abilityCost(e,keys){let map=abilityMap(e);return [...(keys||[])].reduce((n,k)=>n+(+((map[k]||{}).cost)||0),0)}
      function totalCost(e,v,keys){return (+((v||{}).cost)||+((e||{}).baseCost)||0)+abilityCost(e,keys)}
      const CHAR_MULTI_KEY='armyBuilder:allowMultipleCharacters';
      function allowMulti(){return localStorage.getItem(CHAR_MULTI_KEY)==='1'}
      function setAllowMulti(v){localStorage.setItem(CHAR_MULTI_KEY,v?'1':'0')}
      function charTogglePanel(u){return currentFaction.id==='khorne'&&isCharacter(u)?`<div class="divider"></div><button id="charMultiToggle" class="charLimitToggle ${allowMulti()?'on':''}" type="button">${allowMulti()?'Unlimited Lords/Heroes: ON':'Unlimited Lords/Heroes: OFF'}</button>`:''}
      function syntheticRoster(id){let e=entryById(id);if(!e)return null;let v=variantFor(e,{rid:id}),base=roster.find(r=>r.id===e.id)||{};return{id:v&&v.id||e.id,n:unitName(e,v),c:v&&v.cost||e.baseCost||base.c||0,g:e.group||base.g,t:[e.caste||'',e.category||''].filter(Boolean),s:v&&v.s||e.baseStats||base.s||'',image_code:base.image_code,loadout:e}}
      function unitCost(u){let loc=findArmyUnit(u&&u.id);if(loc)return loc.u.c||0;let e=entryFor(u);if(e){let v=baseVariant(e);return totalCost(e,v,allAbilityKeys(e))}let r=findRoster(u)||u;return u&&u.c||r&&r.c||0}
      function patchLegacyKhorneCosts(){
        try{if(LOADOUT_DB.arb_fh)LOADOUT_DB.arb_fh.c=1600;if(LOADOUT_DB.kar_no_fs){LOADOUT_DB.kar_no_fs.c=1100;LOADOUT_DB.kar_no_fs.n='Karanak'}if(REF.arb_fh)REF.arb_fh[1]=1600;if(REF.kar_no_fs){REF.kar_no_fs[0]='Karanak';REF.kar_no_fs[1]=1100}}catch{}
      }
      function normalizeKhorneArmyState(){
        if(currentFaction.id!=='khorne'||!entries().length||!Array.isArray(state))return;
        for(const army of state)for(const slot of ['main','reinf'])for(const u of army[slot]||[]){
          if(u.rid==='arb_fh'){let e=entryById('wh3_dlc26_kho_cha_arbaal'),v=e&&(e.variants||[]).find(x=>x.mount==='Flesh Hound');if(v){u.rid=v.id;u.n=unitName(e,v);u.c=v.cost;u.abilities=Array.isArray(u.abilities)?u.abilities:allAbilityKeys(e)}}
          if(u.rid==='kar_no_fs'){let e=entryById('wh3_pro12_kho_cha_karanak'),v=baseVariant(e);if(v){u.rid=v.id;u.n=unitName(e,v);u.c=v.cost;u.abilities=Array.isArray(u.abilities)?u.abilities:allAbilityKeys(e)}}
          let e=entryFor(u);if(e){let v=variantFor(e,u);if(v){u.n=unitName(e,v);u.c=v.cost;u.abilities=Array.isArray(u.abilities)?u.abilities:allAbilityKeys(e)}}
        }
      }
      findRoster=function(u){let id=u&&u.rid||u&&u.id;return oldFindRoster(u)||syntheticRoster(id)}
      displayName=function(u){let e=entryFor(u);if(e)return e.id==='wh3_dlc26_kho_cha_arbaal'?e.name:((u&&u.n)||e.name);return oldDisplayName(u)}
      rosterVisible=function(u){let e=entryFor(u);if(e&&u.id!==e.id)return false;return oldRosterVisible(u)}
      rosterCard=function(u){let dn=displayName(u);return `<div class="rosterCard ${isRor(u)?'ror':''}" data-id="${esc(u.id)}" data-sel="${esc(u.id)}" title="${esc(dn)} · double-click add">${imgHtml(u)}<div class="cardCost">${coin(unitCost(u))}</div></div>`}
      function addCharacterToggles(){
        if(currentFaction.id!=='khorne')return;
        document.querySelectorAll('.groupTitle').forEach(gt=>{
          const txt=gt.childNodes[0]&&gt.childNodes[0].textContent.trim();
          if(txt!=='Lords'&&txt!=='Heroes')return;
          if(gt.querySelector('.charMiniToggle'))return;
          const b=document.createElement('button');
          b.type='button';
          b.className='charMiniToggle '+(allowMulti()?'on':'');
          b.title='Allow unlimited Lords/Heroes';
          b.textContent=allowMulti()?'∞':'1';
          b.onclick=e=>{e.preventDefault();e.stopPropagation();setAllowMulti(!allowMulti());render();};
          gt.appendChild(b);
        });
      }
      renderRoster=function(){oldRenderRoster();addCharacterToggles();}
      imageFile=function(u){let id=u&&u.rid||u&&u.id,e=entryFor(u);if(e){let hit=manifestHit(e.id)||manifestHit(id),f=fileFromManifest(hit);if(f)return f;let base=roster.find(r=>r.id===e.id)||{};if(e.id==='wh3_dlc26_kho_cha_arbaal')return 'arbaal_the_undefeated.webp';if(base.image_code)return `${base.image_code}.webp`;return oldImageFile({id:e.id,rid:e.id,n:e.name})}let hit=manifestHit(id),f=fileFromManifest(hit);return f||oldImageFile(u)}
      fallbackFile=function(u){let id=u&&u.rid||u&&u.id,e=entryFor(u);if(e){let hit=manifestHit(e.id)||manifestHit(id),f=fileFromManifest(hit);if(f)return f.replace(/\.webp$/i,'.png');let base=roster.find(r=>r.id===e.id)||{};if(e.id==='wh3_dlc26_kho_cha_arbaal')return 'arbaal_the_undefeated.png';if(base.image_code)return `${base.image_code}.png`;return `${e.id}.png`}let hit=manifestHit(id),f=fileFromManifest(hit);return f?f.replace(/\.webp$/i,'.png'):oldFallbackFile(u)}
      validate=function(a){let out=oldValidate(a);return allowMulti()?out.filter(x=>!/Lord required|Only one Lord|Lord placed/.test(x.t)):out}
      loadoutPanel=function(u){
        let loc=findArmyUnit(u&&u.id),rid=(u&&u.rid)||findRoster(u)?.id||u&&u.id;
        if(!isCharacter(u))return '';
        if(currentFaction.id==='khorne'){
          let e=entryFor(u);
          if(e){
            let v=variantFor(e,u),keys=new Set(loc?(u.abilities||[]):allAbilityKeys(e));
            let mounts=(e.variants||[]).length>1?`<div class="divider"></div><div class="loadout"><div class="loadTitle">Mount / Variant</div>${(e.variants||[]).map(x=>`<label class="loadCheck" title="${esc(unitName(e,x))}"><input type="radio" name="khoVariant" data-kho-variant-id="${esc(x.id)}" ${v&&x.id===v.id?'checked':''} ${loc?'':'disabled'}><span><b>${esc(x.mount||'On Foot')}</b> ${coin(x.cost)}</span></label>`).join('')}</div>`:'';
            let abils=(e.abilities||[]).length?`<div class="divider"></div><div class="loadout"><div class="loadTitle">Abilities</div>${e.abilities.map(a=>`<label class="loadCheck" title="${esc(a.tooltip||a.name)}"><input type="checkbox" data-kho-ability-key="${esc(a.key)}" ${keys.has(a.key)?'checked':''} ${loc?'':'disabled'}><span><b>${esc(a.name)}</b> ${coin('+'+(+a.cost||0))}</span></label>`).join('')}</div>`:'';
            return mounts+abils;
          }
        }
        let lores=wefLoreVariants(u);if(lores.length>1)return `<div class="divider"></div><div class="loadout"><div class="loadTitle">Lore</div>${lores.map(v=>`<label class="loadCheck"><input type="radio" name="wefLore" data-lore-id="${esc(v.id)}" ${v.id===rid?'checked':''}><span><b>${esc(wefLoreName(v.n))}</b></span></label>`).join('')}</div>`;return '';
      }
      function setKhorneVariant(variantId){
        let loc=findArmyUnit(selected&&selected.id);if(!loc)return;
        let e=entryFor(loc.u),v=e&&(e.variants||[]).find(x=>x.id===variantId);if(!v)return;
        {let keys=loc.u.abilities||allAbilityKeys(e);state[active][loc.slot][loc.i]={...loc.u,rid:v.id,n:unitName(e,v),c:totalCost(e,v,keys),abilities:keys};}
        selected=state[active][loc.slot][loc.i];markDirty();render();selectUnit(selected);
      }
      function toggleKhorneAbility(key,on){
        let loc=findArmyUnit(selected&&selected.id);if(!loc)return;
        let set=new Set(loc.u.abilities||[]);on?set.add(key):set.delete(key);
        let e=entryFor(loc.u),v=variantFor(e,loc.u);state[active][loc.slot][loc.i]={...loc.u,c:totalCost(e,v,set),abilities:[...set]};
        selected=state[active][loc.slot][loc.i];markDirty();render();selectUnit(selected);
      }
      function selectedAbilityTags(u){let e=entryFor(u);if(!e||!u||!u.abilities)return'';let map=abilityMap(e);return u.abilities.map(k=>map[k]&&map[k].name).filter(Boolean).map(n=>`<span class="tag">✓ ${esc(n)}</span>`).join('')}
      bindLoadoutControls=function(){
        document.querySelectorAll('[data-kho-variant-id]').forEach(x=>x.onchange=e=>{if(e.target.checked)setKhorneVariant(e.target.dataset.khoVariantId)});
        document.querySelectorAll('[data-kho-ability-key]').forEach(x=>x.onchange=e=>toggleKhorneAbility(e.target.dataset.khoAbilityKey,e.target.checked));
        document.querySelectorAll('[data-lore-id]').forEach(x=>x.onchange=e=>{if(e.target.checked)setSelectedLoadout(roster.find(r=>r.id===e.target.dataset.loreId))});
        let mt=document.getElementById('charMultiToggle');if(mt)mt.onclick=()=>{setAllowMulti(!allowMulti());render();};
      }
      renderDetails=function(){
        const u=preview||selected;if(!u){unitDetails.innerHTML='<p class="hint">Hover or click a unit.</p>';return}
        const r=findRoster(u)||u;
        unitDetails.innerHTML=`<div class="detailHero"><div class="detailNameBar"><div class="unitName">${esc(displayName(u))}</div></div><div class="detailBody"><div class="detailTop">${imgHtml(u)}<div><div class="metaRow"><span>${coin(unitCost(u))}</span><span>·</span><span>${esc(groupOf(u))}</span></div><div class="tags">${(r.t||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${selectedAbilityTags(u)}${isRor(u)?'<span class="tag">RoR / Unique</span>':''}</div></div></div>${charTogglePanel(u)}${loadoutPanel(u)}<div class="divider"></div>${detailsStats(r)}</div></div>`;
        bindLoadoutControls();
      }
      add=function(u){
        let a=state[active],arr=a[dest],g=groupOf(u);if(arr.length>=MAX_UNITS){msg(`${dest} already has 20 units`,'bad');return}
        if(!allowMulti()&&dest==='reinf'&&g==='Lords'){msg('Lord should stay in Main Army','bad');return}
        if(!allowMulti()&&dest==='main'&&g==='Lords'&&a.main.some(isLord)){msg('Main Army already has a Lord','bad');return}
        if(isRor(u)&&[...a.main,...a.reinf].some(x=>(findRoster(x)?.id||x.rid||x.n)===u.id||x.n===u.n)){msg('RoR / unique already used in this army','bad');return}
        let e=entryFor(u);if(e){let v=baseVariant(e),keys=allAbilityKeys(e);arr.push({id:uuid(),rid:v.id,n:unitName(e,v),c:totalCost(e,v,keys),abilities:keys})}else arr.push({id:uuid(),rid:u.id,n:u.n,c:u.c});
        markDirty();render();selectUnit(arr[arr.length-1]);msg(`Added ${arr[arr.length-1].n} — Save to keep`,'ok');
      }
      loadFaction=function(f){let out=oldLoadFaction(f);setTimeout(()=>fetch('/factions/khorne/lords_heroes.json').then(r=>r.ok?r.json():{entries:[]}).then(j=>{window.__khoLoadouts=j||{entries:[]};patchLegacyKhorneCosts();normalizeKhorneArmyState();render()}).catch(()=>{}),150);return out}
    };
    wait();
  }
  ensureExportModalGlobals();
  ensureUiStyles();
  watchLoadoutTitles();
  watchDetailsPin();
  installKhorneLoadoutPatch();
  class SortableGrid{
    constructor(el,opts={}){
      this.el=el;
      this.opts=Object.assign({draggable:'.card',ghostClass:'sortableGhost',chosenClass:'sortableChosen',dragClass:'sortableDrag',fallbackTolerance:5,swapThreshold:.15,swapCooldown:45,animation:125,onEnd:null},opts);
      this.down=this.down.bind(this);this.move=this.move.bind(this);this.up=this.up.bind(this);
      this.el.addEventListener('pointerdown',this.down);this.disableNativeDrag();
    }
    destroy(){this.el.removeEventListener('pointerdown',this.down);document.removeEventListener('pointermove',this.move);document.removeEventListener('pointerup',this.up);this.cleanup()}
    disableNativeDrag(){this.el.querySelectorAll('img').forEach(img=>{img.draggable=false;img.addEventListener('dragstart',e=>e.preventDefault())})}
    cards(){return Array.from(this.el.querySelectorAll(this.opts.draggable))}
    down(e){
      if(e.button!==undefined&&e.button!==0)return;
      const item=e.target.closest(this.opts.draggable);if(!item||!this.el.contains(item))return;
      e.preventDefault();this.disableNativeDrag();
      this.state={item,oldIndex:this.cards().indexOf(item),startX:e.clientX,startY:e.clientY,lastX:e.clientX,lastY:e.clientY,lastSwapAt:0,dragging:false,ghost:null,rect:item.getBoundingClientRect(),pointerId:e.pointerId};
      item.setPointerCapture?.(e.pointerId);document.addEventListener('pointermove',this.move,{passive:false});document.addEventListener('pointerup',this.up,{once:true});
    }
    makeGhost(){
      const s=this.state;if(!s||s.ghost)return;
      const g=s.item.cloneNode(true);g.classList.add(this.opts.dragClass);
      Object.assign(g.style,{position:'fixed',left:s.rect.left+'px',top:s.rect.top+'px',width:s.rect.width+'px',height:s.rect.height+'px',zIndex:'9999',pointerEvents:'none',margin:'0',transform:'scale(1.04)'});
      document.body.appendChild(g);s.ghost=g;s.item.classList.add(this.opts.ghostClass,this.opts.chosenClass);window.__armySortClickBlock=true;
    }
    getInsertAction(e,over){
      const s=this.state,cards=this.cards(),itemIndex=cards.indexOf(s.item),overIndex=cards.indexOf(over);if(itemIndex<0||overIndex<0)return null;
      const r=over.getBoundingClientRect(),dx=e.clientX-s.lastX,dy=e.clientY-s.lastY,totalX=e.clientX-s.startX,totalY=e.clientY-s.startY,rowBand=Math.abs(e.clientY-(r.top+r.height/2))<r.height*.48,t=this.opts.swapThreshold;
      if(rowBand){const movingLeft=dx<-0.5||(Math.abs(dx)<=0.5&&totalX<0),movingRight=dx>0.5||(Math.abs(dx)<=0.5&&totalX>0);if(movingLeft&&itemIndex>overIndex&&e.clientX<r.left+r.width*(1-t))return'before';if(movingRight&&itemIndex<overIndex&&e.clientX>r.left+r.width*t)return'after';return null}
      const movingUp=dy<-0.5||(Math.abs(dy)<=0.5&&totalY<0),movingDown=dy>0.5||(Math.abs(dy)<=0.5&&totalY>0);
      if(movingUp&&itemIndex>overIndex&&e.clientY<r.top+r.height*(1-t))return'before';
      if(movingDown&&itemIndex<overIndex&&e.clientY>r.top+r.height*t)return'after';
      return null;
    }
    animateReorder(mutator){
      const before=new Map();for(const el of this.cards())if(el!==this.state.item)before.set(el,el.getBoundingClientRect());
      mutator();const duration=this.opts.animation||0;if(!duration||!('animate' in Element.prototype))return;
      for(const [el,oldRect] of before){const newRect=el.getBoundingClientRect(),dx=oldRect.left-newRect.left,dy=oldRect.top-newRect.top;if(Math.abs(dx)<1&&Math.abs(dy)<1)continue;el.getAnimations().forEach(a=>a.cancel());el.animate([{transform:`translate(${dx}px,${dy}px)`},{transform:'translate(0,0)'}],{duration,easing:'cubic-bezier(.16,1,.3,1)'})}
    }
    move(e){
      const s=this.state;if(!s)return;e.preventDefault();
      const dx=e.clientX-s.startX,dy=e.clientY-s.startY;if(!s.dragging&&Math.hypot(dx,dy)>this.opts.fallbackTolerance){s.dragging=true;this.makeGhost()}
      if(!s.dragging){s.lastX=e.clientX;s.lastY=e.clientY;return}
      const g=s.ghost;if(g){g.style.left=(e.clientX-s.rect.width/2)+'px';g.style.top=(e.clientY-s.rect.height/2)+'px'}
      s.item.style.visibility='hidden';const under=document.elementFromPoint(e.clientX,e.clientY);s.item.style.visibility='';
      if(!under){s.lastX=e.clientX;s.lastY=e.clientY;return}
      const holder=under.closest&&under.closest('.unitSlots');if(holder!==this.el){s.lastX=e.clientX;s.lastY=e.clientY;return}
      const over=under.closest&&under.closest(this.opts.draggable);if(!over||over===s.item||!this.el.contains(over)){s.lastX=e.clientX;s.lastY=e.clientY;return}
      const now=performance.now(),action=now-s.lastSwapAt<this.opts.swapCooldown?null:this.getInsertAction(e,over);
      if(action){this.animateReorder(()=>{if(action==='before')this.el.insertBefore(s.item,over);else this.el.insertBefore(s.item,over.nextSibling)});s.lastSwapAt=now}
      s.lastX=e.clientX;s.lastY=e.clientY;
    }
    up(){
      const s=this.state;document.removeEventListener('pointermove',this.move);if(!s)return;
      const wasDragging=s.dragging,oldIndex=s.oldIndex,newIndex=this.cards().indexOf(s.item);this.cleanup();
      if(wasDragging){window.__armySortClickBlock=true;setTimeout(()=>{window.__armySortClickBlock=false},120);if(newIndex>=0&&newIndex!==oldIndex&&typeof this.opts.onEnd==='function')this.opts.onEnd({oldIndex,newIndex,item:s.item})}
    }
    cleanup(){const s=this.state;if(s){s.ghost&&s.ghost.remove();s.item&&s.item.classList.remove(this.opts.ghostClass,this.opts.chosenClass);s.item&&(s.item.style.visibility='')}this.state=null}
  }
  window.SortableGrid=SortableGrid;
})();