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
  function ensureLoadoutChipStyles(){
    if(document.getElementById('loadoutChipStyle'))return;
    const st=document.createElement('style');
    st.id='loadoutChipStyle';
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
  function resetDetailsPin(){
    document.querySelectorAll('.detailHero.heroFixed').forEach(clearHeroPin);
  }
  function syncDetailsPin(){
    const panel=document.getElementById('unitDetails');
    const hero=panel&&panel.querySelector('.detailHero');
    if(!panel||!hero)return;
    if(window.innerWidth<=1120||document.body.classList.contains('uiHidden')){resetDetailsPin();return;}
    const top=153;
    const pad=12;
    const wasFixed=hero.classList.contains('heroFixed');
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
    const run=()=>{ticking=false;syncDetailsPin();};
    const queue=()=>{if(!ticking){ticking=true;requestAnimationFrame(run);}};
    window.addEventListener('scroll',queue,{passive:true});
    window.addEventListener('resize',queue);
    new MutationObserver(queue).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
    queue();
  }
  ensureExportModalGlobals();
  ensureLoadoutChipStyles();
  watchLoadoutTitles();
  watchDetailsPin();
  class SortableGrid{
    constructor(el,opts={}){
      this.el=el;
      this.opts=Object.assign({draggable:'.card',ghostClass:'sortableGhost',chosenClass:'sortableChosen',dragClass:'sortableDrag',fallbackTolerance:5,swapThreshold:.15,swapCooldown:45,animation:125,onEnd:null},opts);
      this.down=this.down.bind(this);
      this.move=this.move.bind(this);
      this.up=this.up.bind(this);
      this.el.addEventListener('pointerdown',this.down);
      this.disableNativeDrag();
    }
    destroy(){
      this.el.removeEventListener('pointerdown',this.down);
      document.removeEventListener('pointermove',this.move);
      document.removeEventListener('pointerup',this.up);
      this.cleanup();
    }
    disableNativeDrag(){
      this.el.querySelectorAll('img').forEach(img=>{
        img.draggable=false;
        img.addEventListener('dragstart',e=>e.preventDefault());
      });
    }
    cards(){return Array.from(this.el.querySelectorAll(this.opts.draggable));}
    down(e){
      if(e.button!==undefined&&e.button!==0)return;
      const item=e.target.closest(this.opts.draggable);
      if(!item||!this.el.contains(item))return;
      e.preventDefault();
      this.disableNativeDrag();
      this.state={item,oldIndex:this.cards().indexOf(item),startX:e.clientX,startY:e.clientY,lastX:e.clientX,lastY:e.clientY,lastSwapAt:0,dragging:false,ghost:null,rect:item.getBoundingClientRect(),pointerId:e.pointerId};
      item.setPointerCapture?.(e.pointerId);
      document.addEventListener('pointermove',this.move,{passive:false});
      document.addEventListener('pointerup',this.up,{once:true});
    }
    makeGhost(){
      const s=this.state;
      if(!s||s.ghost)return;
      const g=s.item.cloneNode(true);
      g.classList.add(this.opts.dragClass);
      g.style.position='fixed';
      g.style.left=s.rect.left+'px';
      g.style.top=s.rect.top+'px';
      g.style.width=s.rect.width+'px';
      g.style.height=s.rect.height+'px';
      g.style.zIndex='9999';
      g.style.pointerEvents='none';
      g.style.margin='0';
      g.style.transform='scale(1.04)';
      document.body.appendChild(g);
      s.ghost=g;
      s.item.classList.add(this.opts.ghostClass);
      s.item.classList.add(this.opts.chosenClass);
      window.__armySortClickBlock=true;
    }
    getInsertAction(e,over){
      const s=this.state;
      const cards=this.cards();
      const itemIndex=cards.indexOf(s.item);
      const overIndex=cards.indexOf(over);
      if(itemIndex<0||overIndex<0)return null;
      const r=over.getBoundingClientRect();
      const dx=e.clientX-s.lastX;
      const dy=e.clientY-s.lastY;
      const totalX=e.clientX-s.startX;
      const totalY=e.clientY-s.startY;
      const rowBand=Math.abs(e.clientY-(r.top+r.height/2))<r.height*.48;
      const t=this.opts.swapThreshold;
      if(rowBand){
        const movingLeft=dx<-0.5 || (Math.abs(dx)<=0.5 && totalX<0);
        const movingRight=dx>0.5 || (Math.abs(dx)<=0.5 && totalX>0);
        if(movingLeft && itemIndex>overIndex && e.clientX<r.left+r.width*(1-t))return 'before';
        if(movingRight && itemIndex<overIndex && e.clientX>r.left+r.width*t)return 'after';
        return null;
      }
      const movingUp=dy<-0.5 || (Math.abs(dy)<=0.5 && totalY<0);
      const movingDown=dy>0.5 || (Math.abs(dy)<=0.5 && totalY>0);
      if(movingUp && itemIndex>overIndex && e.clientY<r.top+r.height*(1-t))return 'before';
      if(movingDown && itemIndex<overIndex && e.clientY>r.top+r.height*t)return 'after';
      return null;
    }
    animateReorder(mutator){
      const before=new Map();
      for(const el of this.cards())if(el!==this.state.item)before.set(el,el.getBoundingClientRect());
      mutator();
      const duration=this.opts.animation||0;
      if(!duration||!('animate' in Element.prototype))return;
      for(const [el,oldRect] of before){
        const newRect=el.getBoundingClientRect();
        const dx=oldRect.left-newRect.left;
        const dy=oldRect.top-newRect.top;
        if(Math.abs(dx)<1&&Math.abs(dy)<1)continue;
        el.getAnimations().forEach(a=>a.cancel());
        el.animate([{transform:`translate(${dx}px,${dy}px)`},{transform:'translate(0,0)'}],{duration,easing:'cubic-bezier(.16,1,.3,1)'});
      }
    }
    move(e){
      const s=this.state;if(!s)return;
      e.preventDefault();
      const dx=e.clientX-s.startX,dy=e.clientY-s.startY;
      if(!s.dragging&&Math.hypot(dx,dy)>this.opts.fallbackTolerance){s.dragging=true;this.makeGhost();}
      if(!s.dragging){s.lastX=e.clientX;s.lastY=e.clientY;return;}
      const g=s.ghost;
      if(g){g.style.left=(e.clientX-s.rect.width/2)+'px';g.style.top=(e.clientY-s.rect.height/2)+'px';}
      s.item.style.visibility='hidden';
      const under=document.elementFromPoint(e.clientX,e.clientY);
      s.item.style.visibility='';
      if(!under){s.lastX=e.clientX;s.lastY=e.clientY;return;}
      const holder=under.closest&&under.closest('.unitSlots');
      if(holder!==this.el){s.lastX=e.clientX;s.lastY=e.clientY;return;}
      const over=under.closest&&under.closest(this.opts.draggable);
      if(!over||over===s.item||!this.el.contains(over)){s.lastX=e.clientX;s.lastY=e.clientY;return;}
      const now=performance.now();
      const action=now-s.lastSwapAt<this.opts.swapCooldown?null:this.getInsertAction(e,over);
      if(action){
        this.animateReorder(()=>{
          if(action==='before')this.el.insertBefore(s.item,over);
          else this.el.insertBefore(s.item,over.nextSibling);
        });
        s.lastSwapAt=now;
      }
      s.lastX=e.clientX;
      s.lastY=e.clientY;
    }
    up(){
      const s=this.state;
      document.removeEventListener('pointermove',this.move);
      if(!s)return;
      const wasDragging=s.dragging;
      const oldIndex=s.oldIndex;
      const newIndex=this.cards().indexOf(s.item);
      this.cleanup();
      if(wasDragging){
        window.__armySortClickBlock=true;
        setTimeout(()=>{window.__armySortClickBlock=false;},120);
        if(newIndex>=0&&newIndex!==oldIndex&&typeof this.opts.onEnd==='function')this.opts.onEnd({oldIndex,newIndex,item:s.item});
      }
    }
    cleanup(){
      const s=this.state;
      if(s){
        s.ghost&&s.ghost.remove();
        s.item&&s.item.classList.remove(this.opts.ghostClass,this.opts.chosenClass);
        s.item&&(s.item.style.visibility='');
      }
      this.state=null;
    }
  }
  window.SortableGrid=SortableGrid;
})();
