/**
 * 실사진 탭(코드명 seedbank) — 클라우드에서만, 관리자에게만 얹는 화면. 실제 환자 사진(씨앗·파생·강남언니 게시분).
 *
 * 왜 여기서 얹는가: `web/index.html` 은 사무실 PC 로컬 화면과 **같은 파일**이다.
 * 로컬 API(api.py)엔 `/api/seedbank` 가 없으므로 거기에 탭을 박으면 로컬에선 늘
 * 깨진 탭이 하나 는다. 그리고 이 화면은 실존 환자 얼굴이라 직급 판정이 붙는데,
 * 그 판정은 서버(app.js)만 안다. → 프로필 메뉴와 같은 방식(주입)으로 얹는다.
 *
 * ⚠ 화면에서 숨기는 건 방어가 아니다 — 실제 차단은 `/api/seedbank`·`/seedfiles/`
 *   의 관리자 판정이다(app.js 정본). 여기 숨김은 '안 보이게'까지다.
 *
 * 시술별 은행(2026-09-16 연서님): index.json 의 `banks[]` 를 칩으로 두고 하나씩 그린다.
 *   status 'ready' = 씨앗·파생·판정이 있음 / 'raw' = 사진은 받았는데 정제 전(장수·명수만) /
 *   'empty' = 아직 아무것도 없음. 옛 index(banks 없이 seeds 만)는 pilot 하나로 감싼다 —
 *   push-seedbank 를 새로 돌리기 전 배포가 깨지지 않게.
 * 업로드본(index.uploads, 강남언니에 실제 게시된 전후 쌍): 시술 칩 밑에 '강남언니 업로드본'으로 붙는다
 *   (product_map 으로 이어진 상품만). 우리 시술에 안 이어진 상품은 '강남언니 · 기타' 칩에서 상품을 골라 본다.
 */

export function seedbankUi() {
  return `<script>(function(){
var $=function(s,r){return (r||document).querySelector(s);};
var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
 return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
var side=$('.side'), main=$('.main'); if(!side||!main) return;

// ── 사이드바 버튼 (라이브러리 아래) ─────────────────────────────────────────
var nav=document.createElement('button');
nav.className='nav-item'; nav.setAttribute('data-tab','seedbank');
nav.innerHTML='<svg><use href="#i-folder"/></svg><span class="lbl">실사진</span>';
var foot=$('#side-foot');
if(foot) side.insertBefore(nav,foot); else side.appendChild(nav);

// ── 페이지 ──────────────────────────────────────────────────────────────────
var page=document.createElement('section');
page.className='page'; page.id='tab-seedbank';
page.innerHTML='<div id="sb-body" class="card" style="padding:16px">불러오는 중…</div>';
var host=$('#tab-home')?$('#tab-home').parentNode:main;
host.appendChild(page);

var css=document.createElement('style');
css.textContent=
 '#tab-seedbank .sb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}'
+'#tab-seedbank .sb-card{border:1px solid var(--ui-border);border-radius:var(--r-md,10px);overflow:hidden;background:#fff}'
+'#tab-seedbank .sb-seed{width:100%;aspect-ratio:3/4;object-fit:cover;display:block;background:var(--ui-surface);cursor:zoom-in}'
+'#tab-seedbank .sb-h{display:flex;align-items:center;gap:6px;padding:8px 10px 6px;font-size:13px;font-weight:600}'
+'#tab-seedbank .sb-h .m{margin-left:auto;font-weight:400;font-size:11px;color:var(--ui-md)}'
+'#tab-seedbank .sb-der{display:flex;gap:6px;padding:0 10px 10px}'
+'#tab-seedbank .sb-der figure{flex:1;margin:0}'
+'#tab-seedbank .sb-der img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:6px;display:block;cursor:zoom-in}'
+'#tab-seedbank .sb-der figcaption{font-size:11px;color:var(--ui-md);padding-top:3px;line-height:1.35}'
+'#tab-seedbank .sb-none{padding:0 10px 10px;font-size:11px;color:var(--ui-lo,#98A2B3)}'
+'#tab-seedbank .sb-tag{display:inline-block;padding:1px 6px;border-radius:999px;font-size:10px;font-weight:600}'
+'#tab-seedbank .sb-tag.ok{background:var(--ok-weak,#E3F5EA);color:var(--ok,#1F8F55)}'
+'#tab-seedbank .sb-tag.warn{background:var(--warn-weak,#FFF3D6);color:var(--warn,#B87A00)}'
+'#tab-seedbank .sb-tag.bad{background:var(--bad-weak,#FBE5E5);color:var(--bad,#D64545)}'
+'#tab-seedbank .sb-tag.eye{background:var(--ui-surface,#F2F4F7);color:var(--ui-md);border:1px solid var(--ui-border)}'
+'#tab-seedbank .sb-chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}'
+'#tab-seedbank .sb-chip{border:1px solid var(--ui-border);background:#fff;border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:6px}'
+'#tab-seedbank .sb-chip .n{font-size:11px;color:var(--ui-md)}'
+'#tab-seedbank .sb-chip.on{background:var(--primary,#1F3A5F);color:#fff;border-color:transparent}'
+'#tab-seedbank .sb-chip.on .n{color:rgba(255,255,255,.75)}'
+'#tab-seedbank .sb-who{font-size:11px;color:var(--ui-md);padding:0 10px 8px;line-height:1.4}'
+'#tab-seedbank .sb-sec{display:flex;align-items:baseline;gap:8px;margin:18px 0 10px;font-size:14px;font-weight:700}'
+'#tab-seedbank .sb-sec .m{font-weight:400;font-size:12px;color:var(--ui-md)}'
+'#tab-seedbank .sb-pairs{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}'
+'#tab-seedbank .sb-pair{border:1px solid var(--ui-border);border-radius:var(--r-md,10px);overflow:hidden;background:#fff}'
+'#tab-seedbank .sb-pair .im{display:grid;grid-template-columns:1fr 1fr;gap:2px;background:var(--ui-border)}'
+'#tab-seedbank .sb-pair .im img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:var(--ui-surface);cursor:zoom-in}'
+'#tab-seedbank .sb-pair .im .no{aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--ui-lo,#98A2B3);background:var(--ui-surface)}'
+'#tab-seedbank .sb-pair .cap{padding:8px 10px;font-size:12px;line-height:1.45}'
+'#tab-seedbank .sb-pair .cap b{font-size:13px}'
+'#tab-seedbank .sb-pair .cap .t{color:var(--ui-md);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
+'#tab-seedbank .sb-tag.off{background:var(--ui-surface,#F2F4F7);color:var(--ui-lo,#98A2B3)}'
+'#tab-seedbank .sb-sel{font:inherit;font-size:13px;padding:6px 10px;border:1px solid var(--ui-border);border-radius:8px;background:#fff;margin-bottom:12px}'
+'#sb-lb{position:fixed;inset:0;z-index:9998;background:rgba(15,20,28,.86);display:flex;'
+'align-items:center;justify-content:center;cursor:zoom-out}'
+'#sb-lb img{max-width:92vw;max-height:88vh;border-radius:8px}';
document.head.appendChild(css);

// ── 확대 ────────────────────────────────────────────────────────────────────
function lightbox(src,cap){
  var b=document.createElement('div'); b.id='sb-lb';
  b.innerHTML='<div style="text-align:center"><img src="'+src+'" alt=""><div style="color:#fff;'
    +'font-size:12px;padding-top:8px">'+esc(cap)+'</div></div>';
  b.onclick=function(){b.remove();};
  document.body.appendChild(b);
}
page.addEventListener('click',function(e){
  var im=e.target.closest('img[data-full]'); if(!im) return;
  lightbox(im.dataset.full, im.dataset.cap||'');
});

// ── 그리기 ──────────────────────────────────────────────────────────────────
// 2026-09-16 연서님: 탭 이름은 '실사진', 칩은 **정식 시술 이름만**(treatments.yaml name_ko, 그 순서), 설명 글은 전부 뺀다.
//   → 시술이 아닌 묶음(0909 KOS 파일럿, 강남언니 미대응 상품)은 칩을 만들지 않는다. 데이터는 index 에 그대로 있다.
var LOADED=false;
var BANKS=[], UPS={}, CUR=null;

function seedUrl(bank,name){ return '/seedfiles/'+encodeURIComponent(bank)+'/'+encodeURIComponent(name); }
function treatments(){                                    // [{key,name}] — 화면 설정(CFG.treatments) 순서
  var out=[];
  try{ Object.keys(CFG.treatments).forEach(function(k){ out.push({key:k,name:CFG.treatments[k].name_ko||k}); }); }catch(e){}
  if(!out.length) BANKS.forEach(function(b){ if(b.key!=='pilot') out.push({key:b.key,name:b.name_ko}); });
  return out;
}
function bankOf(k){ return BANKS.filter(function(b){return b.key===k;})[0]||null; }
function upProducts(treat){
  var out=[];
  Object.keys(UPS).forEach(function(k){ var u=UPS[k]; if(u.status!=='ready') return;
    (u.products||[]).forEach(function(p){ if(p.treatment===treat) out.push({src:u,p:p}); }); });
  return out;
}

function chips(){
  return '<div class="sb-chips">'+treatments().map(function(t){
    return '<button type="button" class="sb-chip'+(t.key===CUR?' on':'')+'" data-bank="'+esc(t.key)+'">'+esc(t.name)+'</button>';
  }).join('')+'</div>';
}

function derCard(bank,d){
  var over=d.over_max?'bad':(d.over_p90?'warn':'ok');
  var word=d.over_max?'원본이 새어 나옴':(d.over_p90?'조금 닮음':'남남');
  var name=d.strength==='kin'?'닮은꼴':'새 얼굴';
  return '<figure><img src="'+seedUrl(bank,d.img)+'" loading="lazy" alt="" data-full="'+seedUrl(bank,d.img)+'" data-cap="'+esc(d.img)+'">'
    +'<figcaption><b>'+name+'</b> <span class="sb-tag '+over+'">'+word+'</span></figcaption></figure>';
}
function whoLine(w){
  if(!w) return '';
  var t=(w.used||'')+(w.batch&&w.batch!=='-'?' · '+w.batch:'')+(w.shot==='selfie'?' · 셀카':(w.shot==='medical'?' · 메디컬포토':''))
    +(w.side?' · '+w.side+(w.angle!=null?'('+w.angle+')':''):'');
  return '<div class="sb-who">'+esc(t)+(w.partial?' <span class="sb-tag eye">눈 가리고 사용</span>':'')+'</div>';
}
function seedCards(D){
  return '<div class="sb-grid">'+D.seeds.map(function(s){
    var dup=s.dup.length?'<span class="sb-tag bad">중복 인물</span>':'';
    var der=s.derived.length?'<div class="sb-der">'+s.derived.map(function(d){return derCard(D.key,d);}).join('')+'</div>':'';
    return '<div class="sb-card">'
      +'<img class="sb-seed" loading="lazy" src="'+seedUrl(D.key,s.img)+'" alt="" data-full="'+seedUrl(D.key,s.img)+'" data-cap="'+esc(s.id)+'">'
      +'<div class="sb-h">'+esc(s.id)+dup+'<span class="m">'+esc(s.size||'')+'</span></div>'
      +whoLine(s.who)+der+'</div>';
  }).join('')+'</div>';
}
function pairCard(c){
  var img=function(name,side){ return name
    ? '<img src="'+seedUrl('uploads',name)+'" loading="lazy" alt="" data-full="'+seedUrl('uploads',name)+'" data-cap="'+esc('#'+c.no+' '+side+(c.days!=null&&side==='후'?' D+'+c.days:''))+'">'
    : '<div class="no">'+side+' 없음</div>'; };
  var who=[c.gender,c.age].filter(Boolean).join(' ');
  return '<div class="sb-pair"><div class="im">'+img(c.before,'전')+img(c.after,'후')+'</div>'
    +'<div class="cap"><b>#'+esc(c.no)+'</b> '+(c.days!=null?'<b>D+'+c.days+'</b>':'')
    +' <span class="sb-tag '+(c.status==='게시중'?'ok':'off')+'">'+esc(c.status||'?')+'</span>'
    +(who?' <span class="sb-tag eye">'+esc(who)+'</span>':'')
    +'<span class="t" title="'+esc(c.tags.join(', '))+'">'+esc(c.title||'')+'</span></div></div>';
}
function uploadsSection(treat){
  return upProducts(treat).map(function(x){
    return '<div class="sb-sec">'+esc(x.src.name_ko)+' · '+esc(x.p.product)+'<span class="m">'+x.p.cases.length+'건</span></div>'
      +'<div class="sb-pairs">'+x.p.cases.map(pairCard).join('')+'</div>';
  }).join('');
}

function draw(){
  var t=treatments().filter(function(x){return x.key===CUR;})[0];
  var D=bankOf(CUR), html='';
  if(D&&D.status==='ready'&&D.seeds.length){
    html+='<div class="sb-sec">씨앗<span class="m">'+D.seeds.length+'장</span></div>'+seedCards(D);
  }
  html+=uploadsSection(CUR);
  if(!html) html='<div class="card" style="padding:16px;color:var(--ui-md);font-size:13px">'+esc(t?t.name:'')+' 사진이 아직 없습니다.</div>';
  $('#sb-body').outerHTML='<div id="sb-body">'+chips()+html+'</div>';
}
page.addEventListener('click',function(e){
  var ch=e.target.closest('.sb-chip'); if(!ch) return;
  CUR=ch.dataset.bank; try{ localStorage.setItem('sb-bank',CUR); }catch(x){}
  draw();
});

function load(){
  if(LOADED) return; LOADED=true;
  fetch('/api/seedbank').then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
   .then(function(x){
     if(!x.ok){ LOADED=false; $('#sb-body').textContent=x.j.error||'불러오지 못했습니다.'; return; }
     var J=x.j;
     // 옛 모양(banks 없음) → pilot 하나로 감싼다. 사진 주소는 /seedfiles/pilot/<파일> 이고 서버가 옛 자리로도 찾는다.
     BANKS=Array.isArray(J.banks)?J.banks:[{key:'pilot',name_ko:'1차 파일럿',source:'KOS 실사진 (시술 미구분)',round:J.round||'',status:'ready',
       counts:J.counts,exif:J.exif,control:J.control,strength:J.strength,face_found:J.face_found,seeds:J.seeds||[],raw:null}];
     UPS=(J.uploads&&typeof J.uploads==='object')?J.uploads:{};
     var want=null; try{ want=localStorage.getItem('sb-bank'); }catch(e){}   // 마지막에 보던 시술
     var ts=treatments(), has=function(k){ var b=bankOf(k); return (b&&b.status==='ready'&&b.seeds.length)||upProducts(k).length; };
     CUR=(ts.filter(function(x){return x.key===want;})[0]||ts.filter(function(x){return has(x.key);})[0]||ts[0]||{}).key||null;
     draw();
   }).catch(function(e){ LOADED=false; $('#sb-body').textContent='불러오지 못했습니다 — '+e.message; });
}

// ── 탭 전환에 물린다 ────────────────────────────────────────────────────────
// show() 는 화면 스크립트의 전역 함수다. 내 버튼은 그쪽 onclick 바인딩이 끝난 뒤에
// 생겼으므로 직접 건다. TITLES 에 이름을 넣지 않으면 제목이 'seedbank' 로 나온다.
try { TITLES.seedbank='실사진'; } catch(e){}
nav.onclick=function(){ try{ show('seedbank'); }catch(e){} load(); };
if(location.hash.slice(1)==='seedbank'){ try{ show('seedbank'); }catch(e){} load(); }
})();</script>`;
}
