"use strict";
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const initialMonth = Number(params.get("month"));
const state = {month: initialMonth >= 1 && initialMonth <= 12 ? initialMonth : (new Date().getMonth() + 1) % 12 + 1,
  preview: params.get("preview") === "1", category: "전체", data: null, cache: new Map(), request: 0, controller: null,
  catalog: null, editing: null, cursor: null, listRequest: 0, snapshot: null};
const API = (window.SITE_CONFIG?.apiBase || "").replace(/\/$/, "");
const emoji = {배추:"🥬",상추:"🥬",시금치:"🌿",생강:"🫚",토마토:"🍅",감귤:"🍊",방울토마토:"🍅",깻잎:"🌿",파프리카:"🫑",무:"🥬",감자:"🥔",고구마:"🍠",당근:"🥕",양파:"🧅",파:"🌱",오이:"🥒",호박:"🎃",사과:"🍎",배:"🍐",바나나:"🍌",딸기:"🍓",수박:"🍉",포도:"🍇",복숭아:"🍑",단감:"🍊",망고:"🥭",레몬:"🍋",오렌지:"🍊",참다래:"🥝",파인애플:"🍍",아보카도:"🥑",체리:"🍒",멜론:"🍈",쌀:"🌾",콩:"🫘",팥:"🫘",땅콩:"🥜",호두:"🌰",브로콜리:"🥦",풋고추:"🌶️",건고추:"🌶️",고춧가루:"🌶️","깐마늘(국산)":"🧄",피마늘:"🧄"};
const colors = ["#edf2e6","#f1f3e8","#eaf0e5","#f5efe3","#f7eee6","#f6f0df"];
const groups = {"전체":null,"채소":"채소·뿌리","과일":"과일·과채","버섯":"버섯","곡물·기타":["곡물·콩류","견과·종실","건조·분쇄 농산물"]};
function node(tag, className, text) { const n=document.createElement(tag); if(className)n.className=className;if(text!==undefined)n.textContent=text;return n; }
function setConnection(text) { $("connection").replaceChildren(node("i"),document.createTextNode(text)); }
function formatError(data, status) { if(status===401)return "관리자 키를 확인해 주세요.";if(status===503&&typeof data?.detail!=="string")return "서버 또는 Firestore 연결을 확인해 주세요. 잠시 후 다시 시도할 수 있어요.";if(Array.isArray(data?.detail))return data.detail.map(x=>x.msg).join(" · ").slice(0,400);return typeof data?.detail==="string"?data.detail:"요청을 완료하지 못했어요. 다시 시도해 주세요."; }
async function api(path, options={}) {
  const headers={...options.headers};if(options.body)headers["Content-Type"]="application/json";
  let response;try{response=await fetch(API+path,{...options,headers,signal:options.signal||AbortSignal.timeout(90000)});}catch(error){if(error.name==="AbortError")throw error;throw new Error("서버에 연결할 수 없어요. 서버 실행 상태와 연결 주소를 확인해 주세요.");}
  if(response.status===204)return null;
  const data=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(formatError(data,response.status));return data;
}
function selectMonth(month){state.month=month;const url=new URL(location.href);url.searchParams.set("month",month);history.replaceState(null,"",url);loadSummary();}
function buildControls(){
  for(let month=1;month<=12;month++){const b=node("button","",`${month}월`);b.onclick=()=>selectMonth(month);b.dataset.month=month;$("months").append(b);}
  for(const name of Object.keys(groups)){const b=node("button",name==="전체"?"active":"",name);b.setAttribute("aria-pressed",String(name==="전체"));b.onclick=()=>{state.category=name;for(const child of $("filters").children){child.classList.toggle("active",child===b);child.setAttribute("aria-pressed",String(child===b));}renderList();};$("filters").append(b);}
}
function statusMessage(title,message,actions=[]){$("status").replaceChildren(node("strong","",title),node("p","",message));for(const [label,action] of actions){const b=node("button","",label);b.onclick=action;$("status").append(b);}}
async function loadSummary(force=false){
  const request=++state.request;state.controller?.abort();state.controller=new AbortController();const controller=state.controller;const month=state.month;
  state.data=null;$("ranking-list").replaceChildren();$("status").replaceChildren();$("visible-count").textContent="";
  $("month-heading").textContent=`${month}월`;$("candidate-label").textContent=`${month}월 기준`;
  for(const b of $("months").children){b.classList.toggle("active",Number(b.dataset.month)===month);b.setAttribute("aria-pressed",String(Number(b.dataset.month)===month));}
  $("sample-banner").hidden=!state.preview;for(const id of ["record-count","candidate-count","period"])$(id).textContent="—";
  const key=`${state.preview}:${month}`;let cached=state.cache.get(key);if(force)cached=null;
  if(cached && Date.now()-cached.time<300000){applySummary(cached.data);return;}
  setConnection(state.preview?"저장된 분석 불러오는 중":"분석 데이터 불러오는 중");
  for(let i=0;i<6;i++)$("ranking-list").append(node("div","skeleton"));$("ranking-list").setAttribute("aria-busy","true");
  const slow=setTimeout(()=>{if(request===state.request)statusMessage("분석 데이터를 준비하고 있어요","처음 접속하면 서버가 깨어나거나 가격 자료를 읽는 데 시간이 걸릴 수 있어요.");},4500);
  const timeout=setTimeout(()=>controller.abort(),90000);
  try {
    let data;
    if(state.preview){
      if(!state.snapshot){const r=await fetch("/sample/seasonal_rankings.json",{signal:controller.signal});if(!r.ok)throw new Error("저장된 분석 파일을 찾을 수 없어요.");state.snapshot=await r.json();}
      const candidates=state.snapshot.rankings[String(month)];data={metadata:state.snapshot.metadata,candidates,candidate_count:candidates.length,target_month:month,previous_month:month===1?12:month-1};
    }else data=await api(`/api/data/summary?month=${month}&limit=100`,{signal:controller.signal});
    if(request!==state.request)return;
    if(!data?.metadata||!Array.isArray(data.candidates))throw new Error("분석 응답 형식이 올바르지 않아요.");
    state.cache.set(key,{time:Date.now(),data});applySummary(data);
  }catch(error){if(request!==state.request)return;$("ranking-list").replaceChildren();setConnection("연결 확인 필요");const actions=[["다시 시도",()=>loadSummary(true)]];if(!state.preview)actions.push(["저장된 분석 미리보기",()=>switchPreview(true)]);statusMessage("자료를 불러오지 못했어요",error.name==="AbortError"?"응답이 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.":error.message,actions);
  }finally{clearTimeout(slow);clearTimeout(timeout);if(request===state.request)$("ranking-list").setAttribute("aria-busy","false");}
}
function applySummary(data){state.data=data;$("status").replaceChildren();$("ranking-list").setAttribute("aria-busy","false");$("record-count").textContent=Number(data.metadata.selected_record_count).toLocaleString("ko-KR")+"건";$("candidate-count").textContent=`${data.candidate_count}가지`;$("period").textContent=`${data.metadata.start_year}–${data.metadata.end_year}`;setConnection(state.preview?"저장된 분석 미리보기":"Firestore 분석 연결됨");renderList();}
function renderList(){
  if(!state.data)return;$("ranking-list").replaceChildren();$("status").replaceChildren();const search=$("search").value.trim();const group=groups[state.category];
  const rows=state.data.candidates.filter(r=>(!group||(Array.isArray(group)?group.includes(r.category):r.category===group))&&r.item_name.includes(search));
  const sort=$("sort").value;rows.sort(sort==="frequency"?(a,b)=>b.drop_frequency_pct-a.drop_frequency_pct||a.rank-b.rank:sort==="name"?(a,b)=>a.item_name.localeCompare(b.item_name,"ko"):(a,b)=>a.rank-b.rank);
  $("visible-count").textContent=rows.length;
  if(!rows.length){statusMessage("조건에 맞는 재료가 없어요",state.data.candidate_count?"검색어나 분류를 바꿔보세요.":"비교 가능한 연도 수와 하락 경향 기준을 충족하는 재료가 없습니다.");return;}
  for(const r of rows){
    const item=node("button","rank-row");item.setAttribute("aria-label",`${r.rank}위 ${r.item_name}, 과거 중앙값 ${Math.abs(r.median_change_pct).toFixed(1)}% 하락, 근거 보기`);item.onclick=()=>showDetail(r);
    const rank=node("span",`row-rank ${r.rank<=3?"top":""}`,String(r.rank));const picture=node("span","row-icon",emoji[r.item_name]||(r.category==="버섯"?"🍄":"🌱"));picture.setAttribute("aria-hidden","true");picture.style.setProperty("--row-bg",colors[(r.rank-1)%colors.length]);
    const content=node("div","row-main"),title=node("div","row-title");title.append(node("strong","",r.item_name),node("span","row-category",r.category));content.append(title,node("div","row-subtitle",`${r.previous_month}월 → ${r.month}월 · ${r.sample_year_count}개 연도 비교`));
    const evidence=node("div","row-evidence"),track=node("span","row-frequency"),bar=node("i");bar.style.width=`${Math.min(100,Math.max(0,r.drop_frequency_pct))}%`;track.append(bar);evidence.append(track,node("span","row-years",`${r.drop_year_count}/${r.sample_year_count}년 하락`));
    const change=node("div","row-change");change.append(node("strong","",`↘ ${Math.abs(r.median_change_pct).toFixed(1)}%`),node("small","","과거 중앙값 · 근거 보기 ›"));item.append(rank,picture,content,evidence,change);$("ranking-list").append(item);
  }
}

function switchPreview(value){state.preview=value;const url=new URL(location.href);value?url.searchParams.set("preview","1"):url.searchParams.delete("preview");history.replaceState(null,"",url);state.cache.clear();loadSummary();if(!$("chat-dialog").hidden)openChat();}

async function showDetail(r){
  const request=state.detailRequest=(state.detailRequest||0)+1;
  $("detail-title").textContent=`${emoji[r.item_name]||'🌱'} ${r.item_name} 가격 흐름`;
  const chart=node('div','trend-container'),explanation=node('p','',`과거 ${r.sample_year_count}년 중 ${r.drop_year_count}년에 ${r.previous_month}월보다 ${r.month}월 가격이 내려갔어요. 변화율 중앙값은 ${r.median_change_pct.toFixed(1)}%입니다.`);
  chart.append(node('p','','월별 가격 기록을 불러오고 있어요…'));chart.setAttribute('aria-busy','true');
  $('detail-body').replaceChildren(chart,explanation,node('p','footnote','순위는 여러 해·품종의 변화율을 요약한 결과이고, 그래프는 선택한 조건의 한 해 실제 가격입니다. 현재 가격이나 미래 예측이 아닙니다.'));
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
  try{
    let data;
    if(state.preview){if(!state.previewTrends){const response=await fetch('/sample/price_trends.json');if(!response.ok)throw new Error('저장된 가격 흐름을 찾을 수 없어요.');state.previewTrends=await response.json();}data={series:state.previewTrends[r.item_name]||[]};}
    else data=await api('/api/data/trend?'+new URLSearchParams({item_name:r.item_name}));
    if(request!==state.detailRequest)return;chart.replaceChildren();
    if(!data.series.length){chart.append(node('p','','그래프로 표시할 가격 기록이 없어요.'));return;}
    const label=node('label','trend-label','비교 조건 '),select=node('select'),plot=node('div');select.setAttribute('aria-label','가격 그래프 품종·등급·단위 선택');
    data.series.forEach((s,i)=>{const o=node('option','',`${s.year}년 · ${s.variety_name} · ${s.grade_name} · ${s.quantity}${s.unit}`);o.value=i;select.append(o);});label.append(select);chart.append(label,plot);
    const tabs=node('div','trend-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','가격 비교 방식');
    const monthly=node('section','trend-panel'),annual=node('section','trend-panel');monthly.id='monthly-price-panel';annual.id='annual-price-panel';
    monthly.setAttribute('role','tabpanel');annual.setAttribute('role','tabpanel');monthly.tabIndex=0;annual.tabIndex=0;
    const buttons=['월별 가격 비교','연도별 가격 비교'].map((text,i)=>{const button=node('button','',text);button.type='button';button.id=`price-tab-${i}`;button.setAttribute('role','tab');button.setAttribute('aria-controls',i?annual.id:monthly.id);tabs.append(button);return button;});
    monthly.setAttribute('aria-labelledby',buttons[0].id);annual.setAttribute('aria-labelledby',buttons[1].id);
    function activate(index,focus=false){buttons.forEach((button,i)=>{button.setAttribute('aria-selected',String(i===index));button.tabIndex=i===index?0:-1;});monthly.hidden=index!==0;annual.hidden=index!==1;if(focus)buttons[index].focus();}
    buttons.forEach((button,i)=>{button.onclick=()=>activate(i);button.onkeydown=e=>{let next;if(e.key==='ArrowRight'||e.key==='ArrowLeft')next=1-i;else if(e.key==='Home')next=0;else if(e.key==='End')next=1;else return;e.preventDefault();activate(next,true);};});
    plot.append(tabs,monthly,annual);
    select.onchange=()=>{const series=data.series[Number(select.value)];const graph=node('div');monthly.replaceChildren(node('h3','',`${series.year}년 월별 가격 비교`),graph);drawPriceTrend(graph,series,r.month);drawAnnualTrend(annual,series,r.month);};select.onchange();activate(0);
    if(state.preview)chart.append(node('p','footnote','CSV에서 생성한 저장된 가격 흐름입니다. 현재 Firestore 조회 결과가 아닙니다.'));
  }catch(error){if(request===state.detailRequest)chart.replaceChildren(node('p','',error.message));}finally{chart.setAttribute('aria-busy','false');}
}
function drawAnnualTrend(container,series,targetMonth){
  container.replaceChildren(node('h3','',`연도별 가격 비교 · 같은 ${targetMonth}월`));
  const points=(series.history||[]).filter(p=>p.month===targetMonth&&p.price!==null).sort((a,b)=>a.year-b.year);
  if(!points.length){container.append(node('p','','이 조건의 선택한 달에는 연도별 비교 자료가 없어요.'));return;}
  const min=points[0].year,maxYear=points.at(-1).year,count=maxYear-min+1,maxPrice=Math.max(...points.map(p=>p.price))*1.15;
  const ns='http://www.w3.org/2000/svg';function shape(tag,attrs,text){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
  const svg=shape('svg',{viewBox:'0 0 640 280',class:'price-chart',role:'group','aria-label':`각 연도 ${targetMonth}월 실제 소매가격. 아래 표에서 같은 값을 확인할 수 있습니다.`});
  const x=year=>65+(year-min+.5)*540/count,y=price=>220-price/maxPrice*180;
  for(let i=0;i<=4;i++){const value=maxPrice*i/4;svg.append(shape('line',{x1:65,x2:605,y1:y(value),y2:y(value),stroke:'#e3e7dd'}),shape('text',{x:56,y:y(value)+4,'text-anchor':'end','font-size':11,fill:'#778477'},Math.round(value).toLocaleString('ko-KR')));}
  const readout=node('p','chart-readout',`${series.variety_name} · ${series.grade_name} · 원 / ${series.quantity}${series.unit}`),table=node('table','price-table'),head=node('thead'),body=node('tbody'),hrow=node('tr');hrow.append(node('th','','연월'),node('th','',`가격 (원 / ${series.quantity}${series.unit})`));head.append(hrow);
  for(let year=min;year<=maxYear;year++){
    const p=points.find(p=>p.year===year);const row=node('tr');row.append(node('td','',`${year}년 ${targetMonth}월`),node('td','',p?p.price.toLocaleString('ko-KR')+'원':'자료 없음'));body.append(row);
    if(count<=12||(year-min)%2===0||year===maxYear)svg.append(shape('text',{x:x(year),y:244,'text-anchor':'end',transform:`rotate(-35 ${x(year)} 244)`,'font-size':11,fill:'#778477'},String(year)));
    if(!p)continue;const label=`${year}년 ${targetMonth}월 · ${p.price.toLocaleString('ko-KR')}원 / ${series.quantity}${series.unit}`;
    const bar=shape('rect',{x:x(year)-Math.min(15,180/count),y:y(p.price),width:Math.min(30,360/count),height:220-y(p.price),rx:3,fill:year===maxYear?'#254e3b':'#98b287',tabindex:0,role:'button','aria-label':label});const select=()=>readout.textContent=label;bar.onclick=select;bar.onfocus=select;bar.onmouseenter=select;bar.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};bar.append(shape('title',{},label));svg.append(bar);
  }
  table.append(head,body);const details=node('details');details.append(node('summary','','연도별 가격 표 보기'),table);
  const latest=points.at(-1),previous=points.find(p=>p.year===latest.year-1);let explanation=`같은 조건의 ${targetMonth}월 가격을 연도별로 비교했어요. `;
  if(previous){const change=latest.price-previous.price;explanation+=`${latest.year}년은 ${previous.year}년보다 ${change===0?'가격이 같아요.':Math.abs(change).toLocaleString('ko-KR')+'원 '+(change<0?'낮아요.':'높아요.')}`;}else explanation+='바로 전년도 자료가 없어 전년 대비 차이는 계산하지 않았어요.';
  container.append(svg,readout,node('p','',explanation),node('p','footnote','연평균이 아니라 선택한 같은 달의 가격입니다. 물가 상승률을 보정하지 않은 당시 금액이며, 없는 연도는 비워 둡니다.'),details);
}
function drawPriceTrend(container,series,targetMonth){
  container.replaceChildren();const available=series.points.filter(p=>p.price!==null);if(!available.length){container.append(node('p','','가격 기록이 없어요.'));return;}
  const ns='http://www.w3.org/2000/svg';function shape(tag,attrs,text){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
  const svg=shape('svg',{viewBox:'0 0 640 270',class:'price-chart',role:'group','aria-label':`${series.year}년 월별 소매가격. 같은 값은 아래 표에서 확인할 수 있습니다.`});
  const max=Math.max(...available.map(p=>p.price))*1.15,x=m=>65+(m-1)*49,y=p=>220-p/max*180;
  for(let i=0;i<=4;i++){const value=max*i/4;svg.append(shape('line',{x1:65,x2:604,y1:y(value),y2:y(value),stroke:'#e3e7dd'}),shape('text',{x:56,y:y(value)+4,'text-anchor':'end','font-size':11,fill:'#778477'},Math.round(value).toLocaleString('ko-KR')));}
  svg.append(shape('rect',{x:x(targetMonth)-17,y:24,width:34,height:196,fill:'#e9eedf',opacity:.6}));
  let path='',connected=false;for(const p of series.points){if(p.price===null){connected=false;continue;}path+=`${connected?'L':'M'}${x(p.month)},${y(p.price)} `;connected=true;}
  svg.append(shape('path',{d:path,fill:'none',stroke:'#527d45','stroke-width':3}));
  const readout=node('p','chart-readout'),table=node('table','price-table'),head=node('thead'),body=node('tbody'),hrow=node('tr');hrow.append(node('th','','월'),node('th','',`소매가격 (원 / ${series.quantity}${series.unit})`));head.append(hrow);
  for(const p of series.points){svg.append(shape('text',{x:x(p.month),y:246,'text-anchor':'middle','font-size':12,fill:'#778477'},`${p.month}월`));const row=node('tr');row.append(node('td','',`${series.year}-${String(p.month).padStart(2,'0')}`),node('td','',p.price===null?'자료 없음':p.price.toLocaleString('ko-KR')+'원'));body.append(row);if(p.price===null)continue;
    const text=`${series.year}년 ${p.month}월 · ${p.price.toLocaleString('ko-KR')}원 / ${series.quantity}${series.unit}`,dot=shape('circle',{cx:x(p.month),cy:y(p.price),r:6,fill:p.month===targetMonth?'#254e3b':'white',stroke:'#527d45','stroke-width':2,tabindex:0,role:'button','aria-label':text});const show=()=>readout.textContent=text;dot.onclick=show;dot.onfocus=show;dot.onmouseenter=show;dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show();}};dot.append(shape('title',{},text));svg.append(dot);}
  const current=series.points.find(p=>p.month===targetMonth),prior=series.points.find(p=>p.month===targetMonth-1);
  readout.textContent=current?.price!=null?`${series.year}년 ${targetMonth}월: ${current.price.toLocaleString('ko-KR')}원 / ${series.quantity}${series.unit}`:'선택한 월의 자료가 없어요. 다른 달의 점을 선택해 보세요.';
  if(current?.price!=null&&prior?.price!=null){const difference=current.price-prior.price;readout.textContent+=difference===0?' · 전월과 같아요.':` · 전월보다 ${Math.abs(difference).toLocaleString('ko-KR')}원 ${difference<0?'내렸어요':'올랐어요'}.`;}
  table.append(head,body);const details=node('details');details.append(node('summary','','월별 가격 표 보기'),table);container.append(svg,readout,node('p','footnote','점에 마우스를 올리거나 터치하면 가격이 표시됩니다. 빠진 달은 추정하지 않고 선을 끊어 표시합니다.'),details);
}
function changeView(view){$("workspace").hidden=view!=="explore";$("explore-view").hidden=view!=="explore";$("manage-view").hidden=view!=="manage";$("page-label").textContent=view==="explore"?"재료 탐색 / 월별 하락 경향":"데이터 관리 / 월별 소매가격";document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===view));if(view==="manage")loadRecords();else if(!state.data)loadSummary();window.scrollTo({top:0,behavior:"smooth"});}
async function loadRecords(append=false){
  const token=++state.listRequest;$("load-more").hidden=true;if(!append){$("records").replaceChildren();state.cursor=null;}
  if(state.preview){$("manage-status").textContent="저장된 분석 미리보기에서는 데이터를 변경할 수 없어요. 재료 탐색에서 실제 API 연결을 선택해 주세요.";return;}
  $("manage-status").textContent="가격 기록을 불러오고 있어요…";const query=new URLSearchParams({limit:30});if(append&&state.cursor)query.set("cursor",state.cursor);if($("manage-search").value.trim())query.set("item_name",$("manage-search").value.trim());
  try{const data=await api("/api/data?"+query);if(token!==state.listRequest)return;
    for(const r of data.items){const record=node("article","record"),info=node("div");info.append(node("strong","",r.item_name),node("small","",`${r.year_month} · ${r.variety_name} · ${r.grade_name} · ${r.quantity}${r.unit}`));const actions=node("div","record-actions");actions.append(node("span","record-price",Number(r.average_price).toLocaleString("ko-KR")+"원"));const edit=node("button","","수정");edit.onclick=()=>openPriceForm(r);const del=node("button","delete","삭제");del.onclick=()=>deletePrice(r,del);actions.append(edit,del);record.append(info,actions);$("records").append(record);}
    state.cursor=data.next_cursor;$("load-more").hidden=!data.has_more;$("manage-status").textContent=$("records").children.length?`${$("records").children.length}건 표시 중` : "등록된 가격이 없어요.";
  }catch(error){if(token===state.listRequest)$("manage-status").textContent=error.message;}
}
function authHeaders(){const key=$("admin-key").value.trim();if(!key)throw new Error("데이터 관리 상단에 관리자 키를 먼저 입력해 주세요.");return {"X-Admin-Key":key};}
async function openPriceForm(record=null){
  try{if(state.preview)throw new Error("실제 API 연결 모드에서 사용할 수 있어요.");authHeaders();if(!state.catalog)state.catalog=await api("/api/data/catalog");
    $("item-select").replaceChildren(...state.catalog.map(r=>{const o=node("option","",r.item_name);o.value=r.item_name;return o;}));
    state.editing=record;const form=$("price-form");form.reset();$("identity-fields").disabled=!!record;$("form-title").textContent=record?`${record.item_name} 가격 수정`:"월별 가격 추가";$("form-error").textContent="";
    const today=new Date(),max=new Date(today.getFullYear(),today.getMonth()-1,1);form.elements.year_month.max=`${max.getFullYear()}-${String(max.getMonth()+1).padStart(2,"0")}`;form.elements.year_month.min="1996-01";
    if(record)for(const key of ["year_month","item_name","variety_name","grade_name","quantity","unit","average_price","note"])form.elements[key].value=record[key]??"";
    $("price-dialog").showModal();
  }catch(error){$("manage-status").textContent=error.message;$("admin-key").focus();}
}
function invalidateAnalysis(){state.controller?.abort();state.request++;state.cache.clear();state.data=null;}
async function savePrice(event){event.preventDefault();const form=$("price-form"),button=$("save-price");button.disabled=true;$("form-error").textContent="";
  try{const body={average_price:form.elements.average_price.value,note:form.elements.note.value};if(!state.editing)for(const key of ["year_month","item_name","variety_name","grade_name","quantity","unit"])body[key]=form.elements[key].value;
    await api(state.editing?`/api/data/${state.editing.id}`:"/api/data",{method:state.editing?"PATCH":"POST",headers:authHeaders(),body:JSON.stringify(body)});
    $("price-dialog").close();invalidateAnalysis();await loadRecords();$("manage-status").textContent+=" · 저장 완료. 분석 기간 내 자료는 다음 분석 조회에 반영됩니다.";
  }catch(error){$("form-error").textContent=error.message;}finally{button.disabled=false;}}
async function deletePrice(record,button){try{const headers=authHeaders();if(!confirm(`${record.year_month} ${record.item_name} (${record.variety_name} · ${record.grade_name}) 가격을 삭제할까요?`))return;button.disabled=true;await api(`/api/data/${record.id}`,{method:"DELETE",headers});invalidateAnalysis();await loadRecords();}catch(error){$("manage-status").textContent=error.message;button.disabled=false;}}
function getOwnerId(){if(state.ownerId)return state.ownerId;try{state.ownerId=localStorage.getItem("seasonal-food-chat-owner-v1");if(!state.ownerId){state.ownerId=crypto.randomUUID();localStorage.setItem("seasonal-food-chat-owner-v1",state.ownerId);}}catch{state.ownerId=state.ownerId||crypto.randomUUID();}return state.ownerId;}
function appendMessage(role,content,createdAt=new Date().toISOString()){const bubble=node("article",`chat-bubble ${role}`,content);bubble.append(node("div","chat-time",new Date(createdAt).toLocaleString("ko-KR",{month:"numeric",day:"numeric",hour:"numeric",minute:"2-digit"})));$("chat-messages").append(bubble);$("chat-messages").scrollTop=$("chat-messages").scrollHeight;return bubble;}
function welcomeMessage(){
  if(state.chatSending)return;$("conversation-list").hidden=true;
  $("chat-messages").replaceChildren();$("chat-notice").textContent="";state.conversation=null;
  appendMessage("assistant",`${state.month}월의 과거 가격 흐름을 참고해 요리를 함께 찾아볼게요. 어떤 재료나 한 끼가 궁금하세요?`);
  $("chat-suggestions").hidden=false;$("chat-suggestions").querySelector("button").textContent=`${state.month}월 재료로 따뜻한 국 추천해줘`;
}
async function openChat(){if($("workspace").hidden)changeView("explore");$("chat-dialog").hidden=false;$("workspace").classList.remove("chat-collapsed");$("open-chat").setAttribute("aria-expanded","true");if(!$("chat-messages").children.length)welcomeMessage();state.chatReady=false;$("chat-state").textContent="AI 설정 확인 중";$("chat-notice").textContent="";$("chat-input").focus();
  try{const info=await api("/api/chat/status",{cache:"no-store"});state.chatReady=info.configured===true;$("chat-state").textContent=state.chatReady?"재료와 레시피를 같이 찾아봐요":"AI 연결 설정 필요";$("chat-state").classList.toggle("chat-status-pill",!state.chatReady);$("chat-state").classList.toggle("required",!state.chatReady);
    if(state.preview){state.chatReady=false;$("chat-state").textContent="미리보기 모드";$("chat-notice").textContent="저장된 분석 미리보기에서는 챗봇 질문을 보낼 수 없습니다.";}
    else if(!info.configured)$("chat-notice").textContent="대화형 AI를 켜려면 서버에 OPENAI_API_KEY 설정이 필요해요. 질문과 가격 요약은 답변을 위해 OpenAI API로 전송됩니다.";
  }catch(error){$("chat-state").textContent="서버 연결 필요";$("chat-notice").textContent=error.message;}
  $("conversation-list").hidden=true;
}
async function loadConversationList(){
  if(state.chatSending||state.preview)return;
  const box=$("conversations");box.replaceChildren();$("conversation-list").hidden=false;box.append(node("p","chat-no-history","저장된 대화를 불러오는 중…"));
  try{const result=await api(`/api/conversations?owner_id=${encodeURIComponent(getOwnerId())}`);box.replaceChildren();const rows=result.items.slice().sort((a,b)=>Date.parse(b.updated_at)-Date.parse(a.updated_at));
    if(!rows.length){box.append(node("p","chat-no-history","저장된 대화가 아직 없어요."));return;}
    for(const row of rows){const button=node("button","conversation-item");button.append(node("strong","",row.title||"새 대화"),node("small","",`${row.message_count}개 메시지 · ${new Date(row.updated_at).toLocaleDateString("ko-KR")}`));button.onclick=()=>loadConversation(row.id);box.append(button);}
  }catch(error){box.replaceChildren(node("p","chat-no-history",error.message));}
}
async function loadConversation(id){if(state.chatSending)return;try{const url=`/api/conversations/${encodeURIComponent(id)}?owner_id=${encodeURIComponent(getOwnerId())}`;const item=await api(url);state.conversation=item.id;$("chat-messages").replaceChildren();for(const message of item.messages)appendMessage(message.role,message.content,message.created_at);$("conversation-list").hidden=true;$("chat-notice").textContent="";}
  catch(error){$("chat-notice").textContent=error.message;}}
async function sendChat(event){event?.preventDefault();const input=$("chat-input"),message=input.value.trim();if(!message||state.chatSending||state.chatChecking)return;
  if(state.preview){$("chat-notice").textContent="\uBBF8\uB9AC\uBCF4\uAE30 \uBAA8\uB4DC\uC5D0\uC11C\uB294 \uCC57\uBD07\uC744 \uC0AC\uC6A9\uD560 \uC218 \uC5C6\uC5B4\uC694. \uCC3D\uC744 \uB2EB\uACE0 \uC0C1\uB2E8\uC758 '\uC2E4\uC81C API \uC5F0\uACB0'\uC744 \uB20C\uB7EC \uC8FC\uC138\uC694.";return;}
  if(!state.chatReady){state.chatChecking=true;try{await openChat();}finally{state.chatChecking=false;}if(!state.chatReady)return;}

  state.chatSending=true;$("new-chat").disabled=true;$("show-conversations").disabled=true;$("chat-input").disabled=true;$("conversation-list").hidden=true;
  $("chat-suggestions").hidden=true;const sent=appendMessage("user",message);input.value="";input.style.height="auto";const pending=node("article","chat-bubble assistant chat-pending","제철 재료를 살펴보고 있어요…");$("chat-messages").append(pending);$("chat-messages").scrollTop=$("chat-messages").scrollHeight;$("chat-send").disabled=true;
  try{const result=await api("/api/chat",{method:"POST",body:JSON.stringify({message,month:state.month,owner_id:getOwnerId(),conversation_id:state.conversation})});state.conversation=result.conversation_id;pending.remove();appendMessage(result.message.role,result.message.content,result.message.created_at);$("chat-notice").textContent="대화가 Firestore에 저장됐어요. ☰에서 다시 불러올 수 있어요.";}
  catch(error){sent.remove();input.value=message;pending.remove();appendMessage("assistant",`요청을 완료하지 못했어요.\n${error.message}\n\n질문은 입력창에 남겨 두었어요.`);$("chat-notice").textContent=error.message;}
  finally{state.chatSending=false;$("new-chat").disabled=false;$("show-conversations").disabled=false;input.disabled=false;$("chat-send").disabled=false;if(!$("chat-dialog").hidden)input.focus();}}

function closeChat(){const focused=$('chat-dialog').contains(document.activeElement);$('chat-dialog').hidden=true;$('workspace').classList.add('chat-collapsed');$('open-chat').setAttribute('aria-expanded','false');if(focused)$('open-chat').focus({preventScroll:true});}
document.querySelectorAll('dialog').forEach(dialog=>{let backdrop=false;const outside=e=>{const r=dialog.getBoundingClientRect();return e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom;};dialog.addEventListener('pointerdown',e=>{backdrop=e.target===dialog&&outside(e);});dialog.addEventListener('click',e=>{if(backdrop&&e.target===dialog&&outside(e))dialog.close();backdrop=false;});});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.isComposing&&!document.querySelector('dialog[open]')&&!$('chat-dialog').hidden){e.preventDefault();closeChat();}});
document.addEventListener('click',e=>{if($('chat-dialog').hidden||$('workspace').hidden||document.querySelector('dialog[open]'))return;if(e.target.closest('#chat-dialog,#open-chat,dialog'))return;closeChat();});
$('open-chat').setAttribute('aria-controls','chat-dialog');$('open-chat').setAttribute('aria-expanded','false');
buildControls();document.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>changeView(b.dataset.view));document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>b.dataset.close==="chat-dialog"?closeChat():$(b.dataset.close).close());
$("method-link").onclick=()=>{changeView("explore");$("method").scrollIntoView({behavior:"smooth"});};$("open-chat").onclick=openChat;$("search").oninput=renderList;$("sort").onchange=renderList;$("refresh").onclick=()=>loadSummary(true);$("switch-live").onclick=()=>switchPreview(false);$("manage-load").onclick=()=>loadRecords();$("manage-search").onkeydown=e=>{if(e.key==="Enter")loadRecords();};$("load-more").onclick=()=>loadRecords(true);$("add-price").onclick=()=>openPriceForm();$("price-form").onsubmit=savePrice;
$("new-chat").onclick=welcomeMessage;$("show-conversations").onclick=loadConversationList;$("close-conversations").onclick=()=>$("conversation-list").hidden=true;$("chat-form").onsubmit=sendChat;$("chat-suggestions").onclick=e=>{const button=e.target.closest("button");if(button){$("chat-input").value=button.textContent;sendChat();}};$("chat-input").onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendChat();}};$("chat-input").oninput=e=>{e.target.style.height="auto";e.target.style.height=Math.min(e.target.scrollHeight,110)+"px";};loadSummary();

openChat();
