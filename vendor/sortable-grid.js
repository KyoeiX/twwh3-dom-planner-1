(function(){
  class SortableGrid{
    constructor(el,opts={}){
      this.el=el;
      this.opts=Object.assign({draggable:'.card',ghostClass:'sortableGhost',chosenClass:'sortableChosen',dragClass:'sortableDrag',fallbackTolerance:5,swapThreshold:.15,swapCooldown:45,animation:120,onEnd:null},opts);
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
        el.animate([{transform:`translate(${dx}px,${dy}px)`},{transform:'translate(0,0)'}],{duration,easing:'cubic-bezier(.2,0,.2,1)'});
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
