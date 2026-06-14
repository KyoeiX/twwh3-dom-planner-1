(function(){
  class SortableGrid{
    constructor(el,opts={}){
      this.el=el;
      this.opts=Object.assign({draggable:'.card',ghostClass:'sortableGhost',chosenClass:'sortableChosen',dragClass:'sortableDrag',fallbackTolerance:5,onEnd:null},opts);
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
      this.state={item,oldIndex:this.cards().indexOf(item),startX:e.clientX,startY:e.clientY,dragging:false,ghost:null,rect:item.getBoundingClientRect(),pointerId:e.pointerId};
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
    move(e){
      const s=this.state;if(!s)return;
      e.preventDefault();
      const dx=e.clientX-s.startX,dy=e.clientY-s.startY;
      if(!s.dragging&&Math.hypot(dx,dy)>this.opts.fallbackTolerance){s.dragging=true;this.makeGhost();}
      if(!s.dragging)return;
      const g=s.ghost;
      if(g){g.style.left=(e.clientX-s.rect.width/2)+'px';g.style.top=(e.clientY-s.rect.height/2)+'px';}
      s.item.style.visibility='hidden';
      const under=document.elementFromPoint(e.clientX,e.clientY);
      s.item.style.visibility='';
      if(!under)return;
      const holder=under.closest&&under.closest('.unitSlots');
      if(holder!==this.el)return;
      const over=under.closest&&under.closest(this.opts.draggable);
      if(!over||over===s.item||!this.el.contains(over))return;
      const r=over.getBoundingClientRect();
      const before=e.clientY<r.top+r.height/2 || (Math.abs(e.clientY-(r.top+r.height/2))<r.height*.25 && e.clientX<r.left+r.width/2);
      if(before)this.el.insertBefore(s.item,over);
      else this.el.insertBefore(s.item,over.nextSibling);
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
