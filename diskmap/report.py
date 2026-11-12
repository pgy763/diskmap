"""Single-file HTML report: the treemap plus the three action views.

The page is fully offline. All layout happens in the browser on a canvas, so a
5 MB JSON tree still opens instantly and panning costs nothing.

The drawing rules are deliberately identical to render.py: title-band treemap,
depth shading, diagonal hatch for folded folders. A screenshot of the page and
an exported poster should be indistinguishable.
"""

from __future__ import annotations

import datetime
import json
import os

from .scan import to_json


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(root_node, extra, title="DiskMap", tree_depth=80):
    stats = extra["stats"]
    tree = to_json(root_node, depth=tree_depth)
    payload = {
        "tree": tree,
        "largest": extra["largest"][:100],
        "duplicates": extra["duplicates"][:120],
        "stale": extra["stale"][:120],
        "junk": extra.get("junk", [])[:40],
        "stats": {
            "files": stats["files"],
            "dirs": stats["dirs"],
            "bytes": stats["bytes"],
            "errors": stats["errors"],
            "elapsed": stats["elapsed"],
            "root": stats["root"],
        },
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return HTML_TEMPLATE.replace("__TITLE__", _esc(title)).replace("__DATA__", data)


def write_report(root_node, extra, out_path, title="DiskMap"):
    html = build(root_node, extra, title)
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.getsize(out_path)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#0b0d12; --panel:#12151d; --panel2:#171b25; --line:#232936;
  --text:#e6e9ef; --dim:#8b93a7; --accent:#5eead4; --warn:#fbbf24; --bad:#f87171;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);
  font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;overflow:hidden}
#app{display:flex;height:100%}
#map{flex:1;position:relative;min-width:0}
canvas{display:block;width:100%;height:100%;cursor:pointer}
#side{width:352px;flex:0 0 352px;background:var(--panel);border-left:1px solid var(--line);
  display:flex;flex-direction:column;min-height:0}
header{padding:15px 16px 13px;border-bottom:1px solid var(--line)}
h1{margin:0 0 8px;font-size:15px;font-weight:600;letter-spacing:.02em}
.sub{font-size:11.5px;color:var(--dim);line-height:1.65}
.big{font-size:27px;font-weight:700;color:var(--accent);letter-spacing:-.01em;line-height:1.15}
.tabs{display:flex;gap:2px;padding:8px 10px 0;border-bottom:1px solid var(--line)}
.tab{flex:1;padding:8px 4px;font-size:12px;color:var(--dim);background:none;border:0;
  border-bottom:2px solid transparent;cursor:pointer;font-family:inherit}
.tab:hover{color:var(--text)}
.tab.on{color:var(--accent);border-bottom-color:var(--accent)}
.list{flex:1;overflow-y:auto;padding:6px 0 20px}
.list::-webkit-scrollbar{width:8px}
.list::-webkit-scrollbar-thumb{background:#2a3140;border-radius:4px}
.list::-webkit-scrollbar-track{background:transparent}
.row{padding:7px 14px;font-size:12px;border-left:2px solid transparent}
.row:hover{background:var(--panel2)}
.row .p{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .m{color:var(--dim);font-size:11px;margin-top:3px;display:flex;gap:9px}
.row .sz{color:var(--accent);font-variant-numeric:tabular-nums}
.row .path{color:#5f6779;font-size:10.5px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;direction:rtl;text-align:left;margin-top:2px}
.empty{padding:26px 16px;color:var(--dim);font-size:12px;text-align:center;line-height:1.8}
.summary{padding:12px 14px 6px;border-bottom:1px solid #1b2130}
.summary b{font-size:21px;display:block;line-height:1.2}
.summary small{color:var(--dim);font-size:11px}
.lab{font-size:10.5px;color:#5f6779;letter-spacing:.06em;margin-bottom:2px}
#crumb{position:absolute;top:0;left:0;right:0;padding:11px 15px 22px;font-size:12px;
  background:linear-gradient(180deg,rgba(11,13,18,.97),rgba(11,13,18,0));z-index:5;
  white-space:nowrap;overflow:hidden;pointer-events:none}
#crumb span{pointer-events:auto;cursor:pointer;color:var(--dim)}
#crumb span:hover{color:var(--accent)}
#crumb b{color:var(--text);font-weight:500}
#tip{position:fixed;pointer-events:none;background:#1b2130;border:1px solid #2c3444;
  border-radius:7px;padding:8px 11px;font-size:12px;z-index:20;display:none;
  max-width:440px;box-shadow:0 10px 30px rgba(0,0,0,.55)}
#tip .t{color:var(--text);margin-bottom:4px;word-break:break-all;font-weight:600}
#tip .d{color:var(--dim);font-size:11px;line-height:1.6}
#legend{position:absolute;bottom:0;left:0;right:0;padding:10px 15px 12px;display:flex;
  flex-wrap:wrap;gap:13px;font-size:11px;color:var(--dim);z-index:5;
  background:linear-gradient(0deg,rgba(11,13,18,.97),rgba(11,13,18,0));pointer-events:none}
#mode{position:absolute;top:44px;right:14px;display:flex;gap:0;z-index:6;
  background:#12151d;border:1px solid var(--line);border-radius:7px;overflow:hidden}
#mode button{background:none;border:0;color:var(--dim);font-family:inherit;
  font-size:11.5px;padding:6px 11px;cursor:pointer}
#mode button.on{background:#1e2430;color:var(--accent)}
#legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;
  vertical-align:-1px}
.search{padding:9px 12px;border-bottom:1px solid var(--line)}
.search input{width:100%;background:var(--panel2);border:1px solid var(--line);
  color:var(--text);border-radius:6px;padding:7px 10px;font-size:12px;
  font-family:inherit;outline:none}
.search input:focus{border-color:#3a4558}
</style>
</head>
<body>
<div id="app">
  <div id="map">
    <canvas id="cv"></canvas>
    <div id="crumb"></div>
    <div id="legend"></div>
    <div id="mode"><button id="m-size" class="on">按体积</button><button id="m-count">按文件数</button></div>
  </div>
  <aside id="side">
    <header>
      <h1 id="ttl">__TITLE__</h1>
      <div class="lab" id="totalunit">总体积</div>
      <div class="big" id="total">—</div>
      <div class="sub" id="meta"></div>
    </header>
    <div class="tabs">
      <button class="tab on" data-tab="largest">最大文件</button>
      <button class="tab" data-tab="duplicates">重复文件</button>
      <button class="tab" data-tab="stale">一年没动</button>
      <button class="tab" data-tab="junk">依赖缓存</button>
    </div>
    <div class="search"><input id="q" placeholder="搜索文件名 / 扩展名…" autocomplete="off"></div>
    <div class="list" id="list"></div>
  </aside>
</div>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const tipEl = document.getElementById('tip');

/* ---- colour by extension family: the map should read at a glance ---- */
const PALETTE = {
  video:['mp4','mkv','avi','mov','wmv','flv','webm','m4v','ts','mpg'],
  image:['png','jpg','jpeg','gif','bmp','webp','svg','ico','psd','raw','heic','tif','tiff'],
  audio:['mp3','wav','flac','aac','ogg','m4a','wma'],
  archive:['zip','rar','7z','tar','gz','bz2','xz','iso','cab'],
  code:['js','ts','jsx','tsx','py','java','go','rs','c','cpp','h','cs','rb','php','kt','swift','sh','sql'],
  doc:['pdf','doc','docx','xls','xlsx','ppt','pptx','txt','md','csv','json','xml','yaml','yml','log','epub'],
  app:['exe','dll','msi','so','dylib','bin','jar','apk','app','sys','lib','o','obj','pdb'],
};
const CAT_COLOR = {
  video:'#f472b6', image:'#a78bfa', audio:'#fbbf24', archive:'#fb923c',
  code:'#5eead4', doc:'#60a5fa', app:'#f87171', other:'#64748b',
};
const CAT_NAME = {video:'视频',image:'图片',audio:'音频',archive:'压缩包',
  code:'代码',doc:'文档',app:'程序',other:'其他'};
const EXT2CAT = {};
for(const [cat, exts] of Object.entries(PALETTE)) for(const e of exts) EXT2CAT[e]=cat;

/* ---- precompute each folder's dominant category (same rule as render.py) ---- */
const DEPTH_K = [1.00,0.93,0.86,0.80,0.76,0.73,0.71];
function decorate(n){
  if(!n.c || !n.c.length){ n._cat = EXT2CAT[n.e||''] || 'other'; return n; }
  const tally={};
  for(const c of n.c){ decorate(c); tally[c._cat]=(tally[c._cat]||0)+(c.s||0); }
  if(n.h) tally.other=(tally.other||0)+n.h.s;
  let dom='other', val=0, tot=0;
  for(const k in tally){ tot+=tally[k]; if(tally[k]>val){val=tally[k];dom=k;} }
  n._cat = (tot && val/tot>=0.30) ? dom : 'other';
  return n;
}
decorate(DATA.tree);

/* ---- helpers ---- */
function fmt(n){
  if(n<1024) return Math.round(n)+' B';
  const u=['KB','MB','GB','TB']; let i=-1;
  do{ n/=1024; i++; }while(n>=1024&&i<3);
  return n.toFixed(n<10?2:1)+' '+u[i];
}
function fmtDate(ts){
  if(!ts) return '';
  const d=new Date(ts*1000), p=x=>String(x).padStart(2,'0');
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

/* ---- squarified treemap (verified: 100% fill, no overlap) ---- */
function squarify(items, x, y, w, h){
  const total = items.reduce((a,b)=>a+b.size,0);
  const out=[];
  if(total<=0||w<=0||h<=0) return out;
  const scale=(w*h)/total;
  const areas=items.map(it=>({it,a:it.size*scale})).filter(r=>r.a>0);
  let cx=x, cy=y, cw=w, ch=h, i=0;
  while(i<areas.length && cw>0.5 && ch>0.5){
    const side=Math.min(cw,ch);
    const row=[]; let rowSum=0, best=Infinity, j=i;
    while(j<areas.length){
      const sum=rowSum+areas[j].a;
      const vals=row.map(r=>r.a).concat([areas[j].a]);
      const worst=worstRatio(sum, vals, side);
      if(row.length===0 || worst<=best){ row.push(areas[j]); rowSum=sum; best=worst; j++; }
      else break;
    }
    if(cw>=ch){
      const sw=rowSum/ch; let py=cy;
      for(const r of row){ const ih=r.a/sw; out.push({x:cx,y:py,w:sw,h:ih,item:r.it}); py+=ih; }
      cx+=sw; cw-=sw;
    } else {
      const sh=rowSum/cw; let px=cx;
      for(const r of row){ const iw=r.a/sh; out.push({x:px,y:cy,w:iw,h:sh,item:r.it}); px+=iw; }
      cy+=sh; ch-=sh;
    }
    i=j;
  }
  return out;
}
function worstRatio(sum, arr, side){
  if(!(sum>0)) return Infinity;
  const mx=Math.max(...arr), mn=Math.max(Math.min(...arr),1e-9);
  const s2=sum*sum, w2=side*side;
  return Math.max((w2*mx)/s2, s2/(w2*mn));
}
function shade(hex,k){
  const m=hex.match(/\w\w/g).map(x=>parseInt(x,16));
  return '#'+m.map(v=>Math.min(255,Math.round(v*k)).toString(16).padStart(2,'0')).join('');
}

/* ---- hatch pattern for folded folders ---- */
const hatch = (()=>{
  const c=document.createElement('canvas'); c.width=c.height=8;
  const h=c.getContext('2d');
  h.strokeStyle='rgba(255,255,255,.17)'; h.lineWidth=1.5;
  h.beginPath(); h.moveTo(-2,10); h.lineTo(10,-2); h.stroke();
  h.beginPath(); h.moveTo(3,10); h.lineTo(15,-2); h.stroke();
  return ctx.createPattern(c,'repeat');
})();

/* ---- state ---- */
let cur = DATA.tree;
let crumbs = [DATA.tree];
let boxes = [], hovered = -1, W = 0, H = 0, DPR = 1;

function resize(){
  const r = document.getElementById('map').getBoundingClientRect();
  DPR = window.devicePixelRatio || 1;
  W = r.width; H = r.height;
  cv.width = Math.max(1, Math.round(W*DPR));
  cv.height = Math.max(1, Math.round(H*DPR));
  ctx.setTransform(DPR,0,0,DPR,0,0);
  draw();
}
window.addEventListener('resize', resize);

/* ---- recursive draw: title band, then children ---- */
/* Two weights for the same tree. Bytes answer "what can I delete", file counts
   answer "where is the mess" - and they point at completely different folders,
   which is the whole reason both exist. */
let mode = 'size';
function wt(n){ return mode==='size' ? (n.s||0) : (n.k||0); }
function wfmt(n){
  if(mode==='size') return fmt(n.s||0);
  return (n.k||0).toLocaleString()+' 个';
}

function drawBox(node, x, y, w, h, depth, total){
  const kids = (node.c||[]).filter(c=>wt(c)>0);
  const hidden = node.h;
  if(!kids.length && !hidden) return;

  const items = kids.slice().sort((a,b)=>wt(b)-wt(a));
  const list = items.map(c=>({size:wt(c), n:c}));
  if(hidden) list.push({size:wt({s:hidden.s,k:hidden.k}), n:{n:'… '+hidden.count+' 个小项',
    s:hidden.s, k:hidden.k, _agg:true}});

  const trivial = kids.length===1 && wt(kids[0]) >= wt(node)*0.995;
  let bx=x, by=y, bw=w, bh=h;
  if(!trivial && w>74 && h>32){
    const band = Math.max(13, Math.min(21, Math.round(h*0.22)));
    ctx.fillStyle='#141821';
    ctx.fillRect(x, y, w, band);
    ctx.fillStyle='rgba(45,52,68,.9)';
    ctx.fillRect(x, y+band-1, w, 1);
    const fs = Math.max(9, Math.min(Math.round(band*0.72), 15));
    ctx.font = '600 '+fs+'px "Microsoft YaHei",sans-serif';
    ctx.textAlign='left'; ctx.textBaseline='top';
    ctx.fillStyle='#e8ecf4';
    ctx.fillText(clip(node.n, fs, w-14), x+7, y+(band-fs)*0.45);
    by = y+band; bh = h-band;
  }
  if(bw<=0||bh<=0) return;

  const gap = depth<=2 ? 1 : 0;
  const sum = list.reduce((a,b)=>a+b.size,0)||1;
  for(const r of squarify(list, bx, by, bw, bh)){
    const n = r.item.n;
    if(r.w<1.2||r.h<1.2) continue;
    const g = (r.w>2*gap+1 && r.h>2*gap+1) ? gap : 0;
    const cat = n._agg ? 'other' : (n._cat||'other');
    const base = CAT_COLOR[cat];
    const k = DEPTH_K[Math.min(depth, DEPTH_K.length-1)] * (n._agg?0.75:1);
    ctx.fillStyle = shade(base, k*(n===hoverNode?1.5:1));
    ctx.fillRect(r.x+g, r.y+g, r.w-g*2, r.h-g*2);
    // Push the parent before recursing: hitTest scans from the end, so whatever
    // is pushed last wins, and we want the deepest box under the cursor.
    boxes.push({x:r.x, y:r.y, w:r.w, h:r.h, n});

    if(n.c && n.c.length && depth<6 && r.w>64 && r.h>46){
      drawBox(n, r.x+g, r.y+g, r.w-g*2, r.h-g*2, depth+1, sum);
    } else {
      if((n.c && n.c.length || n._agg) && hatch){
        ctx.save();
        ctx.beginPath();
        ctx.rect(r.x+g, r.y+g, r.w-g*2, r.h-g*2);
        ctx.clip();
        ctx.fillStyle = hatch;
        ctx.fillRect(r.x+g, r.y+g, r.w-g*2, r.h-g*2);
        ctx.restore();
      }
      if(r.w>=52 && r.h>=20 && !(n._agg && r.h<26)){
        const fs = Math.max(9, Math.min(13, Math.round(r.w/6), Math.round(r.h/2.6)));
        ctx.font = '600 '+fs+'px "Microsoft YaHei",sans-serif';
        ctx.textAlign='left'; ctx.textBaseline='top';
        ctx.fillStyle='#e8ecf4';
        ctx.fillText(clip(n.n, fs, r.w-10), r.x+g+5, r.y+g+4);
        if(r.h>fs*2.9 && r.w>62){
          ctx.font = (fs-2)+'px "Segoe UI",sans-serif';
          ctx.fillStyle='#8b93a7';
          ctx.fillText(wfmt(n), r.x+g+5, r.y+g+5+fs);
        }
      }
    }
    if(n===hoverNode){
      ctx.strokeStyle='#fff'; ctx.lineWidth=1.5;
      ctx.strokeRect(r.x+0.5, r.y+0.5, r.w-1, r.h-1);
    }
  }
}
function clip(text, fs, maxw){
  ctx.font = '600 '+fs+'px "Microsoft YaHei",sans-serif';
  if(ctx.measureText(text).width <= maxw) return text;
  let t = text;
  while(t.length>1 && ctx.measureText(t+'…').width > maxw) t = t.slice(0,-1);
  return t+'…';
}
let hoverNode = null, hoverBox = null;

function draw(){
  ctx.clearRect(0,0,W,H);
  document.getElementById('total').textContent = mode==='size' ? fmt(st.bytes) : st.files.toLocaleString();
  document.getElementById('totalunit').textContent = mode==='size' ? '总体积' : '总文件数';
  boxes = [];
  if(!cur.c || !cur.c.length){
    ctx.fillStyle='#2a3140'; ctx.font='13px "Microsoft YaHei",sans-serif';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText(cur.h ? '这里只有 '+cur.h.count+' 个小文件（'+fmt(cur.h.s)+'）' : '空目录', W/2, H/2);
    renderCrumb(); return;
  }
  drawBox(cur, 0, 40, W, H-40-34, 1, cur.s||1);
  renderCrumb();
  renderLegend();
}

function renderCrumb(){
  const el=document.getElementById('crumb');
  const parts = crumbs.map((c,i)=>{
    const label = i===0 ? (c.n.split(/[\\/]/).filter(Boolean).pop()||c.n) : c.n;
    return i===crumbs.length-1 ? '<b>'+esc(label)+'</b>' : '<span data-i="'+i+'">'+esc(label)+'</span>';
  });
  el.innerHTML = parts.join(' <span style="pointer-events:none;opacity:.4">/</span> ');
  el.querySelectorAll('span[data-i]').forEach(s=>{
    s.onclick=()=>{ const i=+s.dataset.i; crumbs=crumbs.slice(0,i+1); cur=crumbs[i]; hovered=-1; hoverNode=null; draw(); };
  });
}
function renderLegend(){
  const el=document.getElementById('legend');
  if(mode==='count'){
    el.innerHTML='<span style="color:#5eead4">面积 = 文件数量</span>'
      +'<span>斜纹 = 一坨小文件</span><span>点方块下钻</span>';
    return;
  }
  const order = ['video','image','audio','archive','code','doc','app','other'];
  el.innerHTML = order.map(c=>'<span><i style="background:'+CAT_COLOR[c]+'"></i>'+CAT_NAME[c]+'</span>').join('');
}

/* ---- interaction: hover, click to drill, right-click to go up ---- */
function hitTest(mx,my){
  for(let i=boxes.length-1;i>=0;i--){
    const b=boxes[i];
    if(mx>=b.x&&mx<=b.x+b.w&&my>=b.y&&my<=b.y+b.h) return b;
  }
  return null;
}
cv.addEventListener('mousemove', e=>{
  const r=cv.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  const b=hitTest(mx,my);
  const n = b ? b.n : null;
  if(n!==hoverNode){ hoverNode=n; hoverBox=b; draw(); }
  if(b){
    tipEl.style.display='block';
    tipEl.innerHTML = '<div class="t">'+esc(n.n||'')+'</div><div class="d">'+fmt(n.s||0)
      +(n.m?'<br>'+fmtDate(n.m):'')
      +(n.c?'<br>'+(n.c.length+(n.h?n.h.count:0))+' 项':'')+'</div>';
    let tx=e.clientX+16, ty=e.clientY+16;
    if(tx+300>window.innerWidth) tx=e.clientX-310;
    if(ty+90>window.innerHeight) ty=e.clientY-100;
    tipEl.style.left=tx+'px'; tipEl.style.top=ty+'px';
  } else tipEl.style.display='none';
});
cv.addEventListener('mouseleave', ()=>{ hoverNode=null; hoverBox=null; tipEl.style.display='none'; draw(); });
cv.addEventListener('click', ()=>{
  if(!hoverNode) return;
  if(hoverNode.c && hoverNode.c.length){
    crumbs.push(hoverNode); cur=hoverNode; hoverNode=null; hoverBox=null; draw();
  }
});
cv.addEventListener('contextmenu', e=>{
  e.preventDefault();
  if(crumbs.length>1){ crumbs.pop(); cur=crumbs[crumbs.length-1]; hoverNode=null; draw(); }
});

/* ---- side panels ---- */
let tab='largest', filter='';
document.querySelectorAll('.tab').forEach(t=>{
  t.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
    t.classList.add('on'); tab=t.dataset.tab; renderList();
  };
});
document.getElementById('q').addEventListener('input', e=>{
  filter=e.target.value.trim().toLowerCase(); renderList();
});

function row(p,s,meta,color){
  const base = String(p).split(/[\\/]/).pop();
  return '<div class="row" style="border-left-color:'+(color||'transparent')+'"><div class="p">'+esc(base)+'</div>'
    +'<div class="m"><span class="sz">'+fmt(s)+'</span><span>'+esc(meta)+'</span></div>'
    +'<div class="path">'+esc(p)+'</div></div>';
}
function renderList(){
  const el=document.getElementById('list');
  el.scrollTop=0;
  const f = s => !filter || String(s).toLowerCase().includes(filter);
  let html='';

  if(tab==='largest'){
    const rows = DATA.largest.filter(x=>f(x.path)).slice(0,300);
    html = rows.length ? rows.map(x=>row(x.path,x.size,
      (x.ext?x.ext+' · ':'')+fmtDate(x.mtime))).join('')
      : '<div class="empty">没有匹配的文件</div>';
  }
  else if(tab==='duplicates'){
    const groups = DATA.duplicates.filter(g=>g.files.some(x=>f(x.path)));
    const wasted = DATA.duplicates.reduce((a,g)=>a+g.wasted,0);
    html = groups.length
      ? '<div class="summary"><b style="color:#fbbf24">'+fmt(wasted)+'</b>'
        +'<small>可以凭空释放 · '+DATA.duplicates.length+' 组重复</small></div>'
        + groups.map(g=>'<div class="row" style="border-left-color:#fbbf24">'
          +'<div class="p">'+g.count+' × '+esc(g.files[0].name)+'</div>'
          +'<div class="m"><span class="sz">'+fmt(g.size)+'</span><span>可省 '+fmt(g.wasted)+'</span></div>'
          +'<div class="path">'+esc(g.files[0].path)+'</div></div>').join('')
      : '<div class="empty">没有发现重复文件<br><span style="font-size:11px">只比对 ≥1MB 的文件</span></div>';
  }
  else if(tab==='junk'){
    const groups = (DATA.junk||[]).filter(g=>f(g.path));
    const total = (DATA.junk||[]).reduce((a,g)=>a+g.size,0);
    const files = (DATA.junk||[]).reduce((a,g)=>a+g.count,0);
    const KIND = {deps:'依赖',build:'构建产物',cache:'缓存',venv:'虚拟环境'};
    html = groups.length
      ? '<div class="summary"><b style="color:#5eead4">'+fmt(total)+'</b>'
        +'<small>删了能自动重建 · '+files.toLocaleString()+' 个文件 · '+groups.length+' 个目录</small></div>'
        + groups.map(g=>'<div class="row" style="border-left-color:#5eead4">'
          +'<div class="p">'+esc(g.name)+'</div>'
          +'<div class="m"><span class="sz">'+fmt(g.size)+'</span><span>'
          +esc(KIND[g.kind]||g.kind)+' · '+g.count.toLocaleString()+' 个文件</span></div>'
          +'<div class="path">'+esc(g.path)+'</div></div>').join('')
      : '<div class="empty">没有发现可重建的依赖目录</div>';
  }
  else {
    const rows = DATA.stale.filter(x=>f(x.path)).slice(0,300);
    const sum = rows.reduce((a,x)=>a+x.size,0);
    html = rows.length
      ? '<div class="summary"><b style="color:#f87171">'+fmt(sum)+'</b>'
        +'<small>超过一年没打开过 · '+rows.length+' 个文件</small></div>'
        + rows.map(x=>row(x.path,x.size,x.days+' 天没动','#f87171')).join('')
      : '<div class="empty">没有僵尸大文件</div>';
  }
  el.innerHTML=html;
}

/* ---- weight mode ---- */
for(const [id,m] of [['m-size','size'],['m-count','count']]){
  document.getElementById(id).onclick=()=>{
    if(mode===m) return;
    mode=m; hoverNode=null; hoverBox=null;
    document.getElementById('m-size').classList.toggle('on', m==='size');
    document.getElementById('m-count').classList.toggle('on', m==='count');
    draw();
  };
}

/* ---- boot ---- */
const st=DATA.stats;
document.getElementById('meta').innerHTML =
  st.files.toLocaleString()+' 个文件 · '+st.dirs.toLocaleString()+' 个目录<br>'
  +'扫描耗时 '+st.elapsed+'s · '+DATA.generated;
renderList();
resize();
</script>
</body>
</html>
"""
