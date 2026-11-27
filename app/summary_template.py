"""汇总分析网页模板：单文件、离线可打开，数据以 JSON 嵌入。"""
import json

_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>扣款汇总分析</title>
<style>
:root{color-scheme:light;
 --bg:#f6f5f2;--surface:#fdfdfc;--sunken:#f1f0ec;--border:#e4e2dc;--grid:#ecebe7;
 --ink:#1d1d1b;--ink2:#55534e;--muted:#625e56;
 --brand:#24694a;--brand-ink:#1c5a3e;--brand-tint:#e6f0ea;--warn:#a87814;--warn-tint:#fbf2dc;--crit:#c2412f;--crit-tint:#fbe9e5;
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--other:#aaa79f;--soft:#d9d7d0;
 --good:#0ca30c;--critical:#d03b3b}
@media screen and (prefers-color-scheme:dark){:root{color-scheme:dark;
 --bg:#121211;--surface:#1a1a19;--sunken:#161615;--border:#2e2e2c;--grid:#262624;
 --ink:#f0efec;--ink2:#c3c2b7;--muted:#a2a096;
 --brand:#4fae7f;--brand-ink:#7cc9a0;--brand-tint:#1d2b23;--warn:#d9a640;--warn-tint:#2b2416;--crit:#e5735f;--crit-tint:#2e1c19;
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--other:#76746d;--soft:#3a3936;
 --good:#0ca30c;--critical:#e05a5a}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:30px 24px 64px}
header.top{display:flex;align-items:flex-start;gap:16px;padding-bottom:18px;border-bottom:2px solid var(--brand);margin-bottom:14px}
.mark{flex:none;width:46px;height:46px;border-radius:10px;background:var(--brand);color:#fff;display:grid;place-items:center;font-size:22px;font-weight:700}
.titles{flex:1;min-width:0}
h1{font-size:25px;line-height:1.25;margin:0 0 4px;letter-spacing:.5px}
.sub{color:var(--ink2);margin:0}
.meta{color:var(--muted);font-size:12px;margin-top:2px}
.actions{display:flex;gap:8px;flex:none}
button,.btn{font:inherit;font-size:13px;border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:7px;padding:6px 14px;cursor:pointer}
button:hover{border-color:var(--brand);color:var(--brand-ink)}
button.primary{background:var(--brand);border-color:var(--brand);color:#fff}
button.primary:hover{filter:brightness(1.08);color:#fff}
nav.toc{position:sticky;top:0;z-index:5;display:flex;gap:4px;flex-wrap:wrap;padding:8px 0;margin-bottom:14px;background:var(--bg)}
nav.toc a{color:var(--ink2);text-decoration:none;font-size:13px;padding:3px 10px;border-radius:999px;border:1px solid transparent}
nav.toc a:hover{border-color:var(--border);background:var(--surface);color:var(--ink)}
.banner{display:flex;border:1px solid;border-radius:10px;overflow:hidden;margin:0 0 16px}
.banner .tag{flex:none;display:grid;place-items:center;padding:10px 18px;color:#fff;font-weight:600;font-size:14px;min-width:116px;text-align:center}
.banner .body{padding:10px 16px;font-size:13.5px}
.banner.warn{border-color:#e3c77f;background:var(--warn-tint)} .banner.warn .tag{background:var(--warn)}
.banner.brand{border-color:#b9d3c3;background:var(--brand-tint)} .banner.brand .tag{background:var(--brand)}
.banner ul{margin:0;padding-left:18px} .banner li{margin:2px 0}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
@media(max-width:920px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:13px 15px 12px;position:relative}
.kpi .l{color:var(--ink2);font-size:12.5px;font-weight:600}
.kpi .l b{color:var(--brand-ink);margin-right:4px}
.kpi .v{font-size:27px;font-weight:700;letter-spacing:-.5px;font-variant-numeric:tabular-nums;line-height:1.3;margin-top:2px}
.kpi .v small{font-size:14px;font-weight:600;color:var(--ink2);margin-left:2px}
.kpi .n{color:var(--muted);font-size:12px;line-height:1.5}
.kpi.alert{border-color:#e3c77f;background:linear-gradient(var(--warn-tint),var(--surface) 70%)}
section{scroll-margin-top:52px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px 20px;margin-bottom:16px}
.card>h2{display:flex;align-items:baseline;gap:10px;font-size:17px;margin:0 0 2px}
.card>h2:before{content:"";width:4px;height:16px;border-radius:2px;background:var(--brand);align-self:center}
.card>h2 .hint{font-size:12px;font-weight:400;color:var(--muted)}
.desc{color:var(--ink2);margin:0 0 14px;font-size:13px}
h3{font-size:14px;margin:4px 0 6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.grid32{display:grid;grid-template-columns:3fr 2fr;gap:24px}
@media(max-width:920px){.grid2,.grid32{grid-template-columns:1fr}}
.find{border-left:3px solid var(--brand);padding:3px 0 3px 12px;margin:8px 0;font-size:13.5px}
.find b{font-weight:650}
.note{color:var(--muted);font-size:12px;margin:8px 0 0}
.empty{color:var(--muted);font-size:13px;padding:18px;text-align:center;background:var(--sunken);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:middle}
th{color:var(--ink2);font-weight:600;font-size:12.5px;position:sticky;top:0;background:var(--surface);z-index:1;white-space:nowrap}
td.r,th.r{text-align:right;white-space:nowrap} td.nw{white-space:nowrap} td.c,th.c{text-align:center}
tr.key td{background:var(--warn-tint)}
td.id{font-size:11.5px;color:var(--muted);word-break:break-all;min-width:7em}
td.st{min-width:9em}
a{color:var(--brand-ink)}
.scroll{max-height:430px;overflow:auto;border-top:1px solid var(--grid)}
.chip{display:inline-flex;align-items:center;gap:4px;padding:0 7px;border-radius:999px;font-size:12px;line-height:20px;border:1px solid var(--border);color:var(--ink2);white-space:nowrap;background:var(--surface)}
.chip.ok{border-color:#b9d3c3;color:var(--brand-ink);background:var(--brand-tint)}
.chip.warn{border-color:#e3c77f;color:var(--warn);background:var(--warn-tint)}
.chip.crit{border-color:#efb7ac;color:var(--crit);background:var(--crit-tint)}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.filters button{border-radius:999px;padding:3px 12px;font-size:12.5px}
.filters button.on{background:var(--brand);border-color:var(--brand);color:#fff}
.ib{display:flex;align-items:center;gap:8px;min-width:140px}
.ib i{display:block;height:9px;border-radius:0 3px 3px 0;flex:none}
.ib span{min-width:46px;text-align:right}
.age{display:flex;align-items:center;gap:8px;justify-content:flex-end}
.age i{display:block;width:64px;height:6px;border-radius:3px;background:var(--grid);position:relative;overflow:hidden}
.age i:after{content:"";position:absolute;left:0;top:0;bottom:0;width:var(--p);background:var(--s2);border-radius:3px}
.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin:6px 0 14px}
.flow>div{position:relative;padding:10px 14px 10px 12px;background:var(--sunken);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.flow>div:first-child{border-left:1px solid var(--border);border-radius:8px 0 0 8px}
.flow>div:last-child{border-right:1px solid var(--border);border-radius:0 8px 8px 0;background:var(--brand-tint)}
.flow>div:not(:last-child):after{content:"";position:absolute;right:-7px;top:50%;width:12px;height:12px;background:inherit;border-top:1px solid var(--border);border-right:1px solid var(--border);transform:translateY(-50%) rotate(45deg);z-index:1}
.flow .k{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.3}
.flow .t{font-size:12px;color:var(--ink2);line-height:1.45}
svg{display:block;overflow:visible}
svg text{fill:var(--ink2);font-size:11px}
svg .ax{stroke:var(--border)} svg .gl{stroke:var(--grid)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--ink2);margin:2px 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
#tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:7px 10px;font-size:12px;box-shadow:0 6px 18px rgba(0,0,0,.12);display:none;z-index:20;max-width:320px;line-height:1.55}
#tip .t{color:var(--ink2);margin-bottom:2px}
ul.method{margin:0;padding-left:18px;color:var(--ink2);font-size:13px} ul.method li{margin:3px 0}
footer{color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:12px;margin-top:26px;padding-top:12px;border-top:1px solid var(--border)}
@media print{
 @page{size:A4;margin:12mm}
 body{background:#fff;font-size:12px} .wrap{max-width:none;padding:0}
 nav.toc,.actions,.filters{display:none!important}
 .card,.kpi,.banner{break-inside:avoid;box-shadow:none}
 .scroll{max-height:none;overflow:visible}
 th{position:static}
}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
 <div class="mark">汇</div>
 <div class="titles"><h1>扣款汇总分析</h1><p class="sub" id="sub"></p><div class="meta" id="meta"></div></div>
 <div class="actions"><button onclick="window.print()">打印 / 存为 PDF</button></div>
</header>
<nav class="toc">
 <a href="#overview">概览</a><a href="#comp">构成</a><a href="#trend">趋势</a><a href="#chain">质检单→罚款</a>
 <a href="#confirm">确认环节</a><a href="#stores">门店与地区</a><a href="#unload">卸货费</a><a href="#method">口径</a>
</nav>
<div id="alerts"></div>
<section id="overview">
 <div class="kpis" id="kpis"></div>
 <div class="banner brand"><div class="tag">先看这几件</div><div class="body"><ul id="todo"></ul></div></div>
</section>
<section id="comp" class="card"><h2>扣款构成 <span class="hint">按扣款类型</span></h2>
 <p class="desc">单数和金额是两回事：张数多的类型不一定钱多。灰条是单数占比，彩条是金额占比。</p>
 <div id="compTable"></div><div id="compFind"></div></section>
<section id="trend" class="card"><h2>趋势 <span class="hint" id="trendHint"></span></h2>
 <div class="toolbar"><div class="legend" id="trendLegend"></div>
  <div class="filters" id="trendMode"><button data-m="amt" class="on">金额</button><button data-m="cnt">单数</button></div></div>
 <div id="trendChart"></div></section>
<section id="chain" class="card"><h2>质检单 → 罚款 <span class="hint">按门店和发现日期关联异物罚款与质检单</span></h2>
 <div class="flow" id="flow"></div>
 <div class="grid32">
  <div><h3>观察清单：观察期内还没升级的 110～130 元质检单</h3><div id="watch"></div></div>
  <div><h3>各金额档质检单后来升级成罚款的比例</h3><div class="legend" id="histLegend"></div><div id="hist"></div><div id="chainFind"></div></div>
 </div>
 <h3 style="margin-top:18px">罚款明细 <span class="hint" style="font-weight:400;color:var(--muted);font-size:12px">最近的在前</span></h3>
 <div class="filters" id="penFilter"></div>
 <div class="scroll" id="penalties"></div></section>
<section id="confirm" class="card"><h2>确认环节 <span class="hint">超过确认期限没人处理，系统会自动确认</span></h2>
 <div class="grid32">
  <div><h3>待供应商确认</h3><div class="filters" id="pendFilter"></div><div class="scroll" id="pending"></div></div>
  <div><h3>人工确认率（按类型）</h3><div id="manual"></div><div id="confirmFind"></div></div>
 </div></section>
<section id="stores" class="card"><h2>门店与地区 <span class="hint">门店类单据按门店名，卸货费按仓库，罚款按说明里的门店</span></h2>
 <div class="grid32">
  <div><div class="toolbar"><h3>扣款最多的门店</h3><div class="filters" id="storeMode"><button data-m="amt" class="on">按金额</button><button data-m="n">按张数</button></div></div><div class="scroll" id="storeTable"></div></div>
  <div><h3>各省扣款金额</h3><div id="prov"></div><p class="note" id="provNote"></p></div>
 </div>
 <h3 style="margin-top:16px">品牌对比 <span class="hint" style="font-weight:400;color:var(--muted);font-size:12px">每 100 家有单据的门店</span></h3>
 <div id="brands"></div></section>
<section id="unload" class="card"><h2>卸货费与出货量 <span class="hint" id="unloadHint"></span></h2>
 <div class="grid2"><div><h3>各仓卸货费</h3><div id="wh"></div></div>
 <div><h3>每万件出货开出的单据</h3><div class="legend" id="rateLegend"></div><div id="rate"></div><p class="note" id="rateNote"></p></div></div></section>
<section id="method" class="card"><h2>口径与数据来源</h2>
 <ul class="method" id="methodList"></ul>
 <h3 style="margin-top:14px">数据来源</h3><div id="sources"></div></section>
<footer><span>由「扣款与客诉导出」生成 · <span id="gen"></span></span><span>只在本机生成，按公司要求保管</span></footer>
</div>
<div id="tip"></div>
<script>
const D=/*__DATA__*/null;
const $=s=>document.querySelector(s);
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(n,d=0)=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:d,minimumFractionDigits:d});
const yuan=n=>fmt(n,2);
const wan=n=>Math.abs(n)>=10000?fmt(n/10000,Math.abs(n)>=1e6?1:2)+' 万':fmt(n,Math.abs(n)<100&&n%1?2:0);
const pct=(x,d=0)=>{if(x==null||!isFinite(x))return '—';const v=x*100;if(v===0)return '0%';if(Math.abs(v)<0.01)return v<0?'≈0%':'<0.01%';return fmt(v,Math.abs(v)<0.1?2:d)+'%'};
const axisWan=v=>Math.abs(v)>=10000?fmt(v/10000,(v/10000)%1?1:0)+' 万':fmt(v);
const NS='http://www.w3.org/2000/svg';
function el(t,a,p){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
const tip=$('#tip');
function showTip(ev,html){tip.innerHTML=html;tip.style.display='block';const x=ev.clientX+14,y=ev.clientY+14;tip.style.left=Math.min(x,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(y,innerHeight-tip.offsetHeight-8)+'px'}
function hideTip(){tip.style.display='none'}
function hover(node,fn){node.addEventListener('mousemove',e=>showTip(e,fn()));node.addEventListener('mouseleave',hideTip)}
function niceStep(m){if(m<=0)return 1;const p=Math.pow(10,Math.floor(Math.log10(m)));const f=m/p;return (f<=1?1:f<=2?2:f<=2.5?2.5:f<=5?5:10)*p}
function nice(m){return niceStep(m/4)*4}
function topPath(x,y,w,h,r){r=Math.min(r,w/2,h);if(h<=0)return'';return `M${x},${y+h}V${y+r}Q${x},${y} ${x+r},${y}H${x+w-r}Q${x+w},${y} ${x+w},${y+r}V${y+h}Z`}
function endPath(x,y,w,h,r){r=Math.min(r,h/2,w);if(w<=0)return'';return `M${x},${y}H${x+w-r}Q${x+w},${y} ${x+w},${y+r}V${y+h-r}Q${x+w},${y+h} ${x+w-r},${y+h}H${x}Z`}
const swatch=c=>`<i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${css(c)};margin-right:5px"></i>`;
const COLOR={'卸货费':'--s1','违规罚款':'--s2','门店报损':'--s3','消费者客诉':'--s4','质检单':'--s5','其他':'--other'};
const groupOf=c=>COLOR[c]?c:'其他';
const legend=(names)=>names.map(n=>`<span>${swatch(COLOR[n])}${n}</span>`).join('');
const ib=(v,max,color,txt)=>`<div class="ib"><i style="width:${Math.max(2,90*Math.max(v,0)/(max||1))}px;background:var(${color})"></i><span>${txt}</span></div>`;
function table(target,cols,rows,{rowClass=null,empty='没有记录'}={}){
 if(!rows.length){target.innerHTML=`<div class="empty">${empty}</div>`;return}
 target.innerHTML='<table><thead><tr>'+cols.map(c=>`<th class="${c.cls||''}">${c.h}</th>`).join('')+'</tr></thead><tbody>'+
  rows.map(r=>`<tr class="${rowClass?rowClass(r):''}">`+cols.map(c=>`<td class="${c.cls||''}">${c.v(r)}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
}
function filters(target,opts,onPick){
 target.innerHTML=opts.map((o,i)=>`<button data-i="${i}" class="${i?'':'on'}">${o.label}</button>`).join('');
 target.querySelectorAll('button').forEach(b=>b.onclick=()=>{target.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));onPick(opts[+b.dataset.i])});
 onPick(opts[0]);
}

function stacked(target,labels,series,{h=250,fmtv=v=>fmt(v),axis=fmtv,unitLabel=''}={}){
 const W=Math.max(target.clientWidth,320),H=h,L=58,R=8,T=12,B=28;
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});target.innerHTML='';target.appendChild(svg);
 const n=labels.length,tot=labels.map((_,i)=>series.reduce((s,x)=>s+Math.max(x.vals[i],0),0));
 const mx=nice(Math.max(...tot,1)),iw=W-L-R,ih=H-T-B,bw=iw/n,gap=Math.min(6,bw*.28),w=Math.max(bw-gap,1);
 for(let i=0;i<=4;i++){const y=T+ih-ih*i/4;el('line',{x1:L,x2:W-R,y1:y,y2:y,class:i?'gl':'ax'},svg);el('text',{x:L-8,y:y+4,'text-anchor':'end'},svg).textContent=axis(mx*i/4)}
 const every=Math.max(1,Math.ceil(n/Math.floor(iw/62)));
 labels.forEach((lb,i)=>{
  let y=T+ih;const x=L+i*bw+gap/2;const live=series.filter(s=>s.vals[i]>0);
  live.forEach((s,k)=>{const bh=ih*s.vals[i]/mx;y-=bh;const top=k===live.length-1;
   el('path',{d:top?topPath(x,y,w,bh,Math.min(4,w/2)):`M${x},${y}h${w}v${bh}h${-w}Z`,fill:css(s.color),stroke:css('--surface'),'stroke-width':bh>3?1:0},svg)});
  if(i%every===0)el('text',{x:x+w/2,y:H-B+16,'text-anchor':'middle'},svg).textContent=lb;
  const hit=el('rect',{x:L+i*bw,y:T,width:bw,height:ih,fill:'transparent'},svg);
  hover(hit,()=>`<div class="t">${esc(lb)}</div>`+series.slice().reverse().filter(s=>s.vals[i]).map(s=>`${swatch(s.color)}${s.name}：<b>${fmtv(s.vals[i])}</b>`).join('<br>')+`<br>合计 <b>${fmtv(tot[i])}</b> ${unitLabel}`)});
}
function columns(target,labels,vals,colors,{h=190,fmtv=v=>fmt(v),axis=fmtv,top=null,tipf=null}={}){
 const W=Math.max(target.clientWidth,280),H=h,L=44,R=4,T=16,B=30;
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});target.innerHTML='';target.appendChild(svg);
 const mx=top??nice(Math.max(...vals,1e-9)),iw=W-L-R,ih=H-T-B,bw=iw/labels.length;
 for(let i=0;i<=4;i++){const y=T+ih-ih*i/4;el('line',{x1:L,x2:W-R,y1:y,y2:y,class:i?'gl':'ax'},svg);el('text',{x:L-6,y:y+4,'text-anchor':'end'},svg).textContent=axis(mx*i/4)}
 labels.forEach((lb,i)=>{const v=vals[i],bh=ih*v/mx,x=L+i*bw+bw*.14,w=bw*.72;
  el('path',{d:topPath(x,T+ih-bh,w,bh,Math.min(4,w/2)),fill:css(colors[i])},svg);
  el('text',{x:x+w/2,y:T+ih-bh-5,'text-anchor':'middle',style:'fill:var(--ink)'},svg).textContent=fmtv(v);
  el('text',{x:x+w/2,y:H-B+15,'text-anchor':'middle'},svg).textContent=lb;
  const hit=el('rect',{x:L+i*bw,y:T,width:bw,height:ih,fill:'transparent'},svg);
  hover(hit,()=>tipf?tipf(i):`<div class="t">${esc(lb)}</div><b>${fmtv(v)}</b>`)});
}
function hbars(target,rows,{val,label,color,right=null,fmtv=v=>fmt(v),w0=96,tipf=null}){
 if(!rows.length){target.innerHTML='<div class="empty">没有数据</div>';return}
 const W=Math.max(target.clientWidth,280),rh=25,H=rows.length*rh+4,L=w0,R=right?92:60;
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});target.innerHTML='';target.appendChild(svg);
 const mx=Math.max(...rows.map(val),1e-9),iw=W-L-R-60;
 rows.forEach((r,i)=>{const y=i*rh,w=Math.max(iw*Math.max(val(r),0)/mx,0),full=String(label(r)),lb=full.length>9?full.slice(0,9)+'…':full;
  el('text',{x:L-8,y:y+16,'text-anchor':'end'},svg).textContent=lb;
  el('path',{d:endPath(L,y+5,w,rh-10,4),fill:css(color(r))},svg);
  el('text',{x:L+w+6,y:y+16,style:'fill:var(--ink)'},svg).textContent=fmtv(val(r));
  if(right)el('text',{x:W-2,y:y+16,'text-anchor':'end'},svg).textContent=right(r);
  const hit=el('rect',{x:0,y,width:W,height:rh,fill:'transparent'},svg);
  hover(hit,()=>tipf?tipf(r):`<div class="t">${esc(full)}</div><b>${fmtv(val(r))}</b>`)});
}
function multiples(target,labels,series){
 target.innerHTML='';
 series.forEach((s,k)=>{
  const last=k===series.length-1,W=Math.max(target.clientWidth,280),L=40,R=70,T=20,B=last?24:6,ih=58,H=T+ih+B;
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});target.appendChild(svg);
  const f=v=>fmt(v,v>=100||v%1===0?0:1),mx=nice(Math.max(...s.vals,1e-9)),iw=W-L-R,n=labels.length;
  const X=i=>L+(n===1?iw/2:i*iw/(n-1)),Y=v=>T+ih-ih*v/mx;
  el('text',{x:L,y:12,style:'fill:var(--ink);font-weight:600;font-size:12px'},svg).textContent=s.name;
  [0,.5,1].forEach(j=>{const y=T+ih-ih*j;el('line',{x1:L,x2:W-R,y1:y,y2:y,class:j?'gl':'ax'},svg);el('text',{x:L-6,y:y+4,'text-anchor':'end'},svg).textContent=f(mx*j)});
  if(last){const every=Math.max(1,Math.ceil(n/Math.floor(iw/52)));labels.forEach((lb,i)=>{if(i%every===0)el('text',{x:X(i),y:H-6,'text-anchor':'middle'},svg).textContent=lb})}
  el('path',{d:s.vals.map((v,i)=>(i?'L':'M')+X(i)+','+Y(v)).join(''),stroke:css(s.color),'stroke-width':2,fill:'none','stroke-linejoin':'round'},svg);
  s.vals.forEach((v,i)=>el('circle',{cx:X(i),cy:Y(v),r:i===n-1?3.5:2.5,fill:css(s.color),stroke:css('--surface'),'stroke-width':1.2},svg));
  el('text',{x:X(n-1)+9,y:Y(s.vals[n-1])+4,style:'fill:var(--ink);font-weight:600'},svg).textContent=f(s.vals[n-1]);
  const step=n>1?iw/(n-1):iw,cross=el('line',{x1:0,x2:0,y1:T,y2:T+ih,stroke:css('--muted'),'stroke-dasharray':'3 3',visibility:'hidden'},svg);
  labels.forEach((lb,i)=>{const hit=el('rect',{x:X(i)-step/2,y:T,width:step,height:ih,fill:'transparent'},svg);
   hit.addEventListener('mousemove',e=>{cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));cross.setAttribute('visibility','visible');showTip(e,`<div class="t">20${lb}</div>${swatch(s.color)}${s.name}：<b>${f(s.vals[i])}</b> 张/万件`)});
   hit.addEventListener('mouseleave',()=>{cross.setAttribute('visibility','hidden');hideTip()})});
 });
}
function lines(target,labels,series,{h=200,fmtv=v=>fmt(v,1)}={}){
 const W=Math.max(target.clientWidth,280),H=h,L=40,R=58,T=12,B=28;
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%'});target.innerHTML='';target.appendChild(svg);
 const all=series.flatMap(s=>s.vals),mx=nice(Math.max(...all,1)),iw=W-L-R,ih=H-T-B,n=labels.length;
 const X=i=>L+(n===1?iw/2:i*iw/(n-1)),Y=v=>T+ih-ih*v/mx;
 for(let i=0;i<=4;i++){const y=T+ih-ih*i/4;el('line',{x1:L,x2:W-R,y1:y,y2:y,class:i?'gl':'ax'},svg);el('text',{x:L-6,y:y+4,'text-anchor':'end'},svg).textContent=fmtv(mx*i/4)}
 const every=Math.max(1,Math.ceil(n/Math.floor(iw/58)));
 labels.forEach((lb,i)=>{if(i%every===0||i===n-1)el('text',{x:X(i),y:H-B+16,'text-anchor':'middle'},svg).textContent=lb});
 const cross=el('line',{x1:0,x2:0,y1:T,y2:T+ih,stroke:css('--muted'),'stroke-dasharray':'3 3',visibility:'hidden'},svg);
 const ends=[];
 series.forEach(s=>{el('path',{d:s.vals.map((v,i)=>(i?'L':'M')+X(i)+','+Y(v)).join(''),stroke:css(s.color),'stroke-width':2,fill:'none','stroke-linejoin':'round'},svg);
  s.vals.forEach((v,i)=>el('circle',{cx:X(i),cy:Y(v),r:3,fill:css(s.color),stroke:css('--surface'),'stroke-width':1.5},svg));
  ends.push({s,y:Y(s.vals[n-1])})});
 ends.sort((a,b)=>a.y-b.y);for(let i=1;i<ends.length;i++)if(ends[i].y-ends[i-1].y<13)ends[i].y=ends[i-1].y+13;
 ends.forEach(e=>el('text',{x:X(n-1)+8,y:e.y+4,style:'fill:var(--ink)'},svg).textContent=e.s.short+' '+fmtv(e.s.vals[n-1]));
 const step=n>1?iw/(n-1):iw;
 labels.forEach((lb,i)=>{const hit=el('rect',{x:X(i)-step/2,y:T,width:step,height:ih,fill:'transparent'},svg);
  hit.addEventListener('mousemove',e=>{cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));cross.setAttribute('visibility','visible');
   showTip(e,`<div class="t">${lb}</div>`+series.map(s=>`${swatch(s.color)}${s.name}：<b>${fmtv(s.vals[i])}</b>`).join('<br>'))});
  hit.addEventListener('mouseleave',()=>{cross.setAttribute('visibility','hidden');hideTip()})});
}

// ---------------- 头部与提醒
const T=D.totals,C=Object.fromEntries(D.comp.map(r=>[r.cat,r])),CH=D.chain,P=D.params;
const cnt=c=>(C[c]||{n:0}).n,amt=c=>(C[c]||{amt:0}).amt;
$('#sub').textContent=`${D.first} 至 ${D.last} · ${fmt(T.n)} 张有效扣款单 · 合计 ${wan(T.amt)} 元`;
$('#meta').textContent=`数据截至 ${D.as_of} · 来自 ${D.sources.length} 份扣款明细（${fmt(T.rows)} 行，去重后 ${fmt(T.unique)} 张，作废 ${fmt(T.void_n)} 张未计）`;
$('#gen').textContent='生成于 '+D.generated;
(function(){
 const items=[];
 const stale=Math.round((new Date(D.today)-new Date(D.as_of))/864e5);
 if(stale>3)items.push(`数据截至 ${D.as_of}，距今已 ${stale} 天。待确认状态和观察清单以那天为准，建议先导出最近的扣款明细再汇总。`);
 if(D.gap_days>0)items.push(`导出区间之间缺了 ${D.gap_days} 天：`+D.gaps.slice(0,6).map(g=>g[0]===g[1]?g[0]:`${g[0]} 至 ${g[1]}`).join('、')+(D.gaps.length>6?' 等':'')+'。这些天的单据没有算进来。');
 (D.warnings||[]).forEach(w=>items.push(esc(w)));
 if(items.length)$('#alerts').innerHTML=`<div class="banner warn"><div class="tag">请留意</div><div class="body"><ul>${items.map(t=>`<li>${t}</li>`).join('')}</ul></div></div>`;
})();

// ---------------- 概览
(function(){
 const B=CH.band,pend=D.confirm,today=pend.due_today??0,overdue=pend.overdue??0,manual=pend.auto==null?null:1-pend.auto;
 const k3=D.volume?D.volume.months.slice(-3):[];
 const avg=a=>a.slice(-3).reduce((s,v)=>s+v,0)/Math.max(a.slice(-3).length,1);
 const tiles=[
  ['有效扣款',wan(T.amt)+'<small>元</small>',`${fmt(T.n)} 张 · 金额最大的 1% 单据占 ${pct(D.pareto.top1)}`],
  ['<b>K1</b>罚款升级率',B.n>=20?pct(B.escalated/B.n):'—',B.n>=20?`${fmt(B.low,0)}～${fmt(B.high,0)} 元质检单 ${B.n} 张，后来同店开罚款 ${B.escalated} 张`:`样本太少：这个区间的质检单只有 ${B.n} 张，满 20 张再看比例`],
  ['观察清单',fmt(D.watch.length)+'<small>张</small>',`${P.watch_days} 天观察期内、还没升级的 ${fmt(B.low,0)}～${fmt(B.high,0)} 元质检单`,D.watch.length>0],
  ['<b>K2</b>人工确认率',manual==null||pend.covered<30?'—':pct(manual),manual==null?'缺少修改人字段':pend.covered<30?`已确认单据只有 ${pend.covered} 张，满 30 张再看比例`:`其余 ${pct(pend.auto)} 到期后由系统自动确认`],
  ['待供应商确认',fmt(pend.pending_n)+'<small>张</small>',`${wan(pend.pending_amt)} 元 · 今天到期 ${fmt(today)} 张`+(overdue?` · 已过期 ${fmt(overdue)} 张`:''),today>0],
 ];
 if(D.volume)tiles.push(['<b>K3</b>每万件单据',`${fmt(avg(D.volume.rate.ls),0)} · ${fmt(avg(D.volume.rate.qc),0)} · ${fmt(avg(D.volume.rate.kc),1)}`,`报损 · 质检 · 客诉，${k3[0]}～${k3[k3.length-1].slice(5)} 月平均`]);
 $('#kpis').innerHTML=tiles.map(k=>`<div class="kpi${k[3]?' alert':''}"><div class="l">${k[0]}</div><div class="v">${k[1]}</div><div class="n">${k[2]}</div></div>`).join('');
 const todo=[];
 if(D.watch.length){const old=D.watch.reduce((m,w)=>Math.max(m,w.age),0);
  const gap=CH.gap_min==null?'':`本次匹配的单据开单间隔为 ${CH.gap_min}～${CH.gap_max} 天。`;
  todo.push(`<b>观察清单 ${D.watch.length} 张</b>：同店核对批次、留样和门店照片，最久的已过 ${old} 天。${gap}<a href="#chain">看清单</a>`)}
 const keyN=pend.key_n??D.pending.filter(p=>p.key).length;
 if(keyN)todo.push(`<b>待确认的关键单据 ${keyN} 张</b>（罚款、${fmt(B.low,0)}～${fmt(B.high,0)} 元质检单、100 元以上客诉）：到期前人工确认或申诉，别等系统自动确认。<a href="#confirm">看单据</a>`);
 else if(pend.pending_n)todo.push(`待确认 ${fmt(pend.pending_n)} 张里没有关键单据，${fmt(today)} 张今天到期。<a href="#confirm">看单据</a>`);
 const recent=D.penalties.filter(p=>(new Date(D.as_of)-new Date(p.created))/864e5<=30);
 if(recent.length)todo.push(`<b>近 30 天新开罚款 ${recent.length} 张，${wan(recent.reduce((s,p)=>s+p.amt,0))} 元</b>：`+[...new Set(recent.map(p=>p.kind))].join('、')+'。<a href="#chain">看罚款</a>');
 const top=D.comp.slice().sort((a,b)=>b.amt-a.amt)[0];
 if(top)todo.push(`金额最多的是<b>${top.cat}</b>（${wan(top.amt)} 元，占 ${pct(top.amt/T.amt)}）；张数最多的是<b>${D.comp.slice().sort((a,b)=>b.n-a.n)[0].cat}</b>。<a href="#comp">看构成</a>`);
 $('#todo').innerHTML=todo.map(t=>`<li>${t}</li>`).join('')||'<li>本期没有需要特别处理的单据。</li>';
})();

// ---------------- 构成
(function(){
 const rows=D.comp,mxn=Math.max(...rows.map(r=>r.n/T.n)),mxa=Math.max(...rows.map(r=>Math.max(r.amt,0)/T.amt));
 table($('#compTable'),[
  {h:'类型',v:r=>`${swatch(COLOR[groupOf(r.cat)])}${r.cat}`,cls:'nw'},
  {h:'单数',v:r=>fmt(r.n),cls:'r'},{h:'单数占比',v:r=>ib(r.n/T.n,mxn,'--soft',pct(r.n/T.n,1))},
  {h:'金额（元）',v:r=>yuan(r.amt),cls:'r'},{h:'金额占比',v:r=>ib(r.amt/T.amt,mxa,COLOR[groupOf(r.cat)],pct(r.amt/T.amt,1))},
  {h:'中位单价',v:r=>yuan(r.med),cls:'r'},{h:'最大单笔',v:r=>yuan(r.max),cls:'r'}],rows);
 const byN=rows.slice().sort((a,b)=>b.n-a.n)[0],byA=rows.slice().sort((a,b)=>b.amt-a.amt)[0];
 let html=`<div class="find"><b>${byN.cat}</b>占了 ${pct(byN.n/T.n)} 的单，中位只有 ${yuan(byN.med)} 元；金额最多的是<b>${byA.cat}</b>，${fmt(byA.n)} 张占 ${pct(byA.amt/T.amt)}。</div>`;
 if(C['违规罚款'])html+=`<div class="find"><b>违规罚款</b>只有 ${fmt(cnt('违规罚款'))} 张，却占金额的 ${pct(amt('违规罚款')/T.amt)}，中位 ${yuan(C['违规罚款'].med)} 元/张。控制总额要先盯罚款和大单。</div>`;
 $('#compFind').innerHTML=html;
})();

// ---------------- 趋势
(function(){
 const unit={month:'按月',week:'按周（周一开始）',day:'按天'}[D.trend.unit];
 $('#trendHint').textContent=`${unit} · 按创建时间`;
 $('#trendLegend').innerHTML=legend(D.groups.filter(g=>D.trend.cnt[g].some(v=>v)));
 const labels=D.trend.periods.map(p=>D.trend.unit==='month'?p:p.slice(5));
 const draw=m=>stacked($('#trendChart'),labels,D.groups.filter(g=>D.trend.cnt[g].some(v=>v)).map(g=>({name:g,color:COLOR[g],vals:D.trend[m][g]})),
  m==='amt'?{fmtv:v=>wan(v),axis:axisWan,unitLabel:'元'}:{fmtv:v=>fmt(v),unitLabel:'张'});
 let mode='amt';draw(mode);
 $('#trendMode').querySelectorAll('button').forEach(b=>b.onclick=()=>{mode=b.dataset.m;$('#trendMode').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));draw(mode)});
 addEventListener('resize',()=>draw(mode));
})();

// ---------------- 质检单 → 罚款
(function(){
 const B=CH.band;
 $('#flow').innerHTML=[
  [fmt(CH.foreign),'张异物罚款',`共 ${wan(CH.foreign_amt)} 元`],
  [fmt(CH.eligible),'张写明门店',CH.start?`${CH.start} 起，能和质检单对照`:'暂无可对照的质检日期'],
  [fmt(CH.hit),`张同店前后 ${P.match_days} 天有质检单`,CH.eligible?`占 ${pct(CH.hit/CH.eligible)}，其中同一天 ${CH.same_day} 张`:''],
  [CH.ratio_med?CH.ratio_med+' 倍':'—','罚款是质检单的',CH.hit?`质检单中位 ${yuan(CH.qc_med)} 元，${CH.gap_min}～${CH.gap_max} 天后开罚款`:'暂时没有对上的记录'],
 ].map(x=>`<div><div class="k">${x[0]}</div><div class="t">${x[1]}<br>${x[2]}</div></div>`).join('');
 table($('#watch'),[
  {h:'开单日期',v:r=>r.day,cls:'nw'},{h:'门店',v:r=>esc(r.store)},{h:'省份',v:r=>esc(r.prov||'—'),cls:'nw'},
  {h:'金额（元）',v:r=>yuan(r.amt),cls:'r'},
  {h:'已过天数',v:r=>`<div class="age"><i style="--p:${Math.min(100,100*r.age/P.watch_days)}%"></i>${r.age}</div>`,cls:'r'},
  {h:'状态',v:r=>r.status==='已确认'?'<span class="chip">已确认</span>':`<span class="chip warn">${esc(r.status)}</span>`,cls:'nw'}],
  D.watch,{empty:`${P.watch_days} 天观察期内没有还没升级的 ${fmt(B.low,0)}～${fmt(B.high,0)} 元质检单`});
 const R=CH.rates||[];
 $('#histLegend').innerHTML=`<span>${swatch('--s2')}${fmt(B.low,0)}～${fmt(B.high,0)} 元（预警区间）</span><span>${swatch('--soft')}其他金额</span>`;
 if(!R.some(r=>r.esc))$('#hist').innerHTML=`<div class="empty">本次数据中没有匹配到同店关联的质检单与罚款。</div>`;
 else columns($('#hist'),R.map(r=>r.label),R.map(r=>r.n?r.esc/r.n:0),R.map(r=>r.band?'--s2':'--soft'),{fmtv:v=>pct(v),axis:v=>fmt(v*100,0)+'%',
  tipf:i=>`<div class="t">${R[i].label} 元的质检单</div>${fmt(R[i].n)} 张，后来同店开罚款 <b>${R[i].esc}</b> 张（${pct(R[i].n?R[i].esc/R[i].n:0,1)}）`});
 $('#chainFind').innerHTML=B.n>=20&&B.escalated?`<div class="find">${fmt(B.low,0)}～${fmt(B.high,0)} 元的质检单共 ${B.n} 张，<b>${B.escalated} 张（${pct(B.escalated/B.n)}）后来同店开了罚款</b>；已过观察期的 ${B.settled_n} 张里升级 ${B.settled_escalated} 张。各金额档的结果可在上方对照。</div>`:'';
 const kinds=['全部',...new Set(D.penalties.map(p=>p.kind))];
 filters($('#penFilter'),kinds.map(k=>({label:k==='全部'?`全部 ${D.penalties.length}`:`${k} ${D.penalties.filter(p=>p.kind===k).length}`,k})),o=>{
  const rows=o.k==='全部'?D.penalties:D.penalties.filter(p=>p.kind===o.k);
  table($('#penalties'),[
   {h:'创建',v:r=>r.created,cls:'nw'},{h:'发现',v:r=>r.found||'—',cls:'nw'},{h:'类型',v:r=>esc(r.kind),cls:'nw'},
   {h:'门店',v:r=>esc(r.store)||'<span style="color:var(--muted)">说明里没写</span>'},{h:'省份',v:r=>esc(r.prov||'—'),cls:'nw'},
   {h:'物料 / 异物',v:r=>esc([r.material,r.foreign&&('异物：'+r.foreign)].filter(Boolean).join(' · ')||'—')},
   {h:'金额（元）',v:r=>yuan(r.amt),cls:'r'},
   {h:'同店质检单',v:r=>r.qc?`<span class="chip ok">${r.qc.d===0?'同一天':'差 '+r.qc.d+' 天'} · ${yuan(r.qc.amt)} 元</span>`:'—',cls:'nw'},
   {h:'间隔',v:r=>r.qc?r.qc.gap+' 天':'—',cls:'r'}],rows,{empty:'这段时间没有罚款'});
 });
})();

// ---------------- 确认环节
(function(){
 const all=D.pending,cf=D.confirm;
 const opts=[{label:`全部 ${fmt(cf.pending_n)}`,f:()=>true},{label:`关键单据 ${fmt(cf.key_n??all.filter(p=>p.key).length)}`,f:p=>p.key},
  {label:`今天到期 ${fmt(cf.due_today??0)}`,f:p=>p.left===0}];
 if(cf.overdue)opts.push({label:`已过期 ${fmt(cf.overdue)}`,f:p=>p.left!=null&&p.left<0});
 const due=r=>r.left==null?'—':r.left<0?`<span class="chip crit">已过 ${-r.left} 天</span>`:r.left===0?'<span class="chip crit">今天到期</span>':r.left<=1?'<span class="chip warn">明天到期</span>':`<span class="chip">${r.left} 天后</span>`;
 filters($('#pendFilter'),opts,o=>table($('#pending'),[
  {h:'要求确认',v:r=>r.due||'—',cls:'nw'},{h:'剩余',v:due,cls:'nw'},{h:'类型',v:r=>`${swatch(COLOR[groupOf(r.cat)])}${esc(r.cat)}`,cls:'nw'},
  {h:'门店',v:r=>esc(r.store||'—'),cls:'st'},{h:'金额（元）',v:r=>yuan(r.amt),cls:'r'},{h:'扣款单号',v:r=>esc(r.id),cls:'id'}],
  all.filter(o.f),{rowClass:r=>r.key?'key':'',empty:'没有待确认的单据'}));
 const notes=[];
 if(cf.pending_n>all.length)notes.push(`共 ${fmt(cf.pending_n)} 张，这里列出全部关键单据和要求确认日期最早的单据，共 ${fmt(all.length)} 张。`);
 if(D.as_of<D.today)notes.push(`状态是 ${D.as_of} 导出时的；已过确认期限的单据，系统可能已经自动确认，以 SRM 为准。`);
 if(notes.length)$('#pending').insertAdjacentHTML('afterend',`<p class="note">${notes.join('')}</p>`);
 const rows=cf.by_cat.filter(r=>r.n>=5).map(r=>({...r,manual:1-r.auto})).sort((a,b)=>b.manual-a.manual);
 hbars($('#manual'),rows,{val:r=>r.manual*100,label:r=>r.cat,color:r=>COLOR[groupOf(r.cat)],fmtv:v=>fmt(v,0)+'%',right:r=>`${fmt(r.n)} 张`,w0:76,
  tipf:r=>`<div class="t">${r.cat}</div>人工确认 <b>${pct(r.manual)}</b><br>系统自动确认 ${pct(r.auto)}<br>已确认 ${fmt(r.n)} 张，确认期限中位 ${r.window??'—'} 天`});
 $('#confirmFind').innerHTML=cf.auto==null?'<p class="note">扣款明细里缺少「最后修改用户」，无法区分人工和系统确认。</p>':
  `<div class="find">已确认的单据里 <b>${pct(cf.auto)} 是到期后系统自动确认</b>的。关键单据应按各自的要求确认日期处理。</div>`;
})();

// ---------------- 门店与地区
(function(){
 const S=D.stores,cols=[
  {h:'门店',v:r=>esc(r.store)},{h:'品牌',v:r=>esc(r.brand||'—'),cls:'nw'},{h:'省份',v:r=>esc(r.prov||'—'),cls:'nw'},
  {h:'报损',v:r=>fmt(r.ls),cls:'r'},{h:'质检',v:r=>fmt(r.qc),cls:'r'},{h:'客诉',v:r=>fmt(r.kc),cls:'r'},{h:'罚款',v:r=>r.pen?fmt(r.pen):'—',cls:'r'},
  {h:'金额（元）',v:r=>yuan(r.amt+r.pen_amt),cls:'r'}];
 const draw=m=>table($('#storeTable'),cols,m==='amt'?S.top_amt:S.top_n);
 draw('amt');
 $('#storeMode').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('#storeMode').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));draw(b.dataset.m)});
 const prov=D.provinces.filter(r=>r.prov!=='未识别').slice(0,15);
 hbars($('#prov'),prov,{val:r=>r.amt,label:r=>r.prov,color:()=>'--s1',fmtv:v=>wan(v),right:r=>pct(r.amt/T.amt,1),w0:52,
  tipf:r=>`<div class="t">${r.prov} · ${wan(r.amt)} 元</div>`+D.groups.filter(g=>r[g]).map(g=>`${swatch(COLOR[g])}${g}：<b>${wan(r[g])}</b>`).join('<br>')});
 const un=D.provinces.find(r=>r.prov==='未识别');
 $('#provNote').textContent=`能归到省份的金额占 ${pct(D.located_share)}`+(un?`；未识别 ${wan(un.amt)} 元（门店名里没有地名，或少称、退货、调整等不带门店的单据）`:'')+'。';
 table($('#brands'),[
  {h:'品牌',v:r=>esc(r.brand)},{h:'有单据的门店',v:r=>fmt(r.stores),cls:'r'},
  {h:'报损 / 百店',v:r=>fmt(r.ls,1),cls:'r'},{h:'质检单 / 百店',v:r=>fmt(r.qc,1),cls:'r'},{h:'客诉 / 百店',v:r=>fmt(r.kc,1),cls:'r'},
  {h:'有质检单的门店',v:r=>pct(r.has_qc),cls:'r'},{h:'有客诉的门店',v:r=>pct(r.has_kc),cls:'r'}],D.brands,{empty:'门店数太少，不做品牌对比'});
})();

// ---------------- 卸货费
(function(){
 const W=D.warehouses,hasRate=P.yuan_per_piece!=null;
 $('#unloadHint').textContent=`共 ${D.warehouse_n} 个仓`+(hasRate?` · 按约 ${P.yuan_per_piece} 元/件折算出货件数`:'');
 hbars($('#wh'),W.slice(0,12),{val:r=>r.amt,label:r=>r.wh,color:()=>'--s1',fmtv:v=>wan(v),right:hasRate?r=>`≈ ${wan(r.pcs)} 件`:null,w0:84,
  tipf:r=>`<div class="t">${esc(r.wh)}（${esc(r.prov||'未识别')}）</div>卸货费 <b>${yuan(r.amt)}</b> 元，${r.n} 张`+(hasRate?`<br>折算约 ${fmt(r.pcs)} 件`:'')});
 if(!hasRate){$('#rate').innerHTML='<div class="empty">填写本机卸货费折算费率后，可查看每万件单据数。</div>';return}
 const V=D.volume;
 if(!V){$('#rate').innerHTML='<div class="empty">至少需要 3 个月的卸货费才能折算</div>';return}
 const S=[{name:'门店报损',short:'报损',color:'--s3',vals:V.rate.ls},{name:'质检单',short:'质检',color:'--s5',vals:V.rate.qc},{name:'消费者客诉',short:'客诉',color:'--s4',vals:V.rate.kc}];
 const last=V.months.slice(-18),cut=V.months.length-last.length;
 $('#rateLegend').innerHTML='三条线量级差很多，各用各的刻度。';
 multiples($('#rate'),last.map(m=>m.slice(2)),S.map(s=>({...s,vals:s.vals.slice(cut)})));
 $('#rateNote').textContent='件数按卸货费备注里的服务月份归属；某月卸货费还没开出来时，那个月不画。用来剔除出货量的波动，看单据是不是真的变多了。';
})();

// ---------------- 口径
(function(){
 $('#methodList').innerHTML=[
  `同一扣款单号出现多次时，优先保留「已确认」的版本，其次保留最后修改时间最晚的版本；作废单据不计入金额和张数。`,
  `趋势按创建时间归期；导出文件本身按「要求扣款日期，缺失时按创建日期」筛选。`,
  `类型：「非消费者索赔」模板按索赔类型拆成门店报损、质检单、少称和违规罚款；「供应商违规处理」也算违规罚款。`,
  `质检单 → 罚款：罚款的门店从扣款说明里提取，按门店名后 6 个字对应；罚款发现日期前后 ${P.match_days} 天内同店有质检单即算对上。${CH.start?`从 ${CH.start} 起统计发现的异物罚款。`:'暂无可对照的质检日期。'}`,
  `观察清单：${fmt(P.band_low,0)}～${fmt(P.band_high,0)} 元、开单不超过 ${P.watch_days} 天、还没对上罚款的质检单，天数算到数据截至日 ${D.as_of}。`,
  `人工确认率：已确认单据中，排除「system_系统」在确认期限后一天自动确认的部分。`,
  P.yuan_per_piece==null?'每万件单据：填写本机卸货费折算费率后计算。':`每万件单据：按本机配置的 ${P.yuan_per_piece} 元/件将卸货费折算成出货件数。`,
 ].map(t=>`<li>${t}</li>`).join('');
 table($('#sources'),[{h:'文件',v:r=>esc(r.name)},{h:'日期区间',v:r=>esc(r.range||'—'),cls:'nw'},{h:'导出时间',v:r=>esc(r.fetched||'—'),cls:'nw'},{h:'行数',v:r=>fmt(r.rows),cls:'r'}],D.sources);
})();
</script>
</body>
</html>
"""


def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return _TEMPLATE.replace("/*__DATA__*/null", payload, 1)
