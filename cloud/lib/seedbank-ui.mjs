/**
 * 씨앗 은행 탭 — 클라우드에서만, 관리자에게만 얹는 화면.
 *
 * 왜 여기서 얹는가: `web/index.html` 은 사무실 PC 로컬 화면과 **같은 파일**이다.
 * 로컬 API(api.py)엔 `/api/seedbank` 가 없으므로 거기에 탭을 박으면 로컬에선 늘
 * 깨진 탭이 하나 는다. 그리고 이 화면은 실존 환자 얼굴이라 직급 판정이 붙는데,
 * 그 판정은 서버(app.js)만 안다. → 프로필 메뉴와 같은 방식(주입)으로 얹는다.
 *
 * ⚠ 화면에서 숨기는 건 방어가 아니다 — 실제 차단은 `/api/seedbank`·`/seedfiles/`
 *   의 관리자 판정이다(app.js 정본). 여기 숨김은 '안 보이게'까지다.
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
nav.innerHTML='<svg><use href="#i-folder"/></svg><span class="lbl">씨앗 은행</span>';
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
var LOADED=false;
var num=function(v){return v==null?'—':v.toFixed(3);};

function derCard(d,ctrl){
  var over=d.over_max?'bad':(d.over_p90?'warn':'ok');
  var word=d.over_max?'원본이 새어 나옴':(d.over_p90?'조금 닮음':'남남');
  var name=d.strength==='kin'?'닮은꼴':'새 얼굴';
  return '<figure><img src="/seedfiles/'+encodeURIComponent(d.img)+'" loading="lazy" alt=""'
    +' data-full="/seedfiles/'+encodeURIComponent(d.img)+'" data-cap="'+esc(d.img)+'">'
    +'<figcaption><b>'+name+'</b> <span class="sb-tag '+over+'">'+word+'</span><br>'
    +'원본과 '+num(d.sim_own)+' · 남과 '+num(d.sim_other_max)+'</figcaption></figure>';
}

function draw(D){
  var c=D.counts, ex=D.exif||{}, ctrl=D.control||{};
  var dupN=D.seeds.filter(function(s){return s.dup.length;}).length;
  var head=
   '<div class="card" style="padding:14px 16px;margin-bottom:14px">'
  +'<div style="font-size:15px;font-weight:700;margin-bottom:6px">씨앗 은행 — '+esc(D.round)+'</div>'
  +'<div style="font-size:13px;color:var(--ui-md);line-height:1.65">'
  +'실제 환자 사진 <b>'+c.raw+'장</b>을 받아 얼굴 없는 '+c.no_face+'장을 빼고 <b>씨앗 '+c.seeds+'장</b>을 만들었습니다. '
  +'그중 6장으로 <b>파생 얼굴 '+c.derived+'장</b>을 시험 생성했습니다.<br>'
  +'위치정보(GPS)는 원본 '+(ex['위치(GPS)']||0)+'장에 있었고 <b>씨앗에는 '+(ex['씨앗잔존']===0?'0장':'남아 있음')+'</b>입니다. '
  +'같은 사람으로 보이는 씨앗이 <b>'+dupN+'장</b> 섞여 있습니다(빨간 딱지).'
  +'</div>'
  +'<div style="margin-top:10px;font-size:12px;color:var(--ui-md);background:var(--ui-surface);'
  +'border-radius:8px;padding:9px 11px;line-height:1.6">'
  +'<b>숫자 읽는 법</b> — 0에 가까울수록 남남입니다. 서로 다른 실제 환자끼리도 평균 '
  +num(ctrl['평균'])+', 최대 '+num(ctrl['최대'])+'까지 나옵니다(그게 자[尺]입니다). '
  +'파생이 그 최대를 넘으면 원본이 새어 나온 것이라 버립니다 — 이번 회차는 0장입니다.'
  +'</div>'
  +'<div style="margin-top:8px;font-size:12px;color:var(--bad,#D92D20)">'
  +'⚠ 이 탭의 씨앗은 <b>실제 환자 얼굴</b>입니다. 관리자에게만 보이며, 내려받거나 밖으로 옮기지 마세요. '
  +'(생성된 파생 얼굴은 실존 인물이 아닙니다.)</div>'
  +'</div>';

  var cards=D.seeds.map(function(s){
    var dup=s.dup.length
      ? '<span class="sb-tag bad" title="'+esc(s.dup.map(function(d){return d.with+' '+d.sim;}).join(', '))+'">중복 인물</span>'
      : '';
    var der=s.derived.length
      ? '<div class="sb-der">'+s.derived.map(function(d){return derCard(d,ctrl);}).join('')+'</div>'
      : '<div class="sb-none">파생 시험 대상 아님(파일럿은 6장만)</div>';
    return '<div class="sb-card">'
      +'<img class="sb-seed" loading="lazy" src="/seedfiles/'+encodeURIComponent(s.img)+'" alt=""'
      +' data-full="/seedfiles/'+encodeURIComponent(s.img)+'" data-cap="'+esc(s.id)+' · '+esc(s.size)+'">'
      +'<div class="sb-h">'+esc(s.id)+dup+'<span class="m">'+esc(s.size)+'</span></div>'
      +der+'</div>';
  }).join('');

  $('#sb-body').outerHTML=head+'<div class="sb-grid" id="sb-body">'+cards+'</div>';
}

function load(){
  if(LOADED) return; LOADED=true;
  fetch('/api/seedbank').then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
   .then(function(x){
     if(!x.ok){ LOADED=false; $('#sb-body').textContent=x.j.error||'불러오지 못했습니다.'; return; }
     draw(x.j);
   }).catch(function(e){ LOADED=false; $('#sb-body').textContent='불러오지 못했습니다 — '+e.message; });
}

// ── 탭 전환에 물린다 ────────────────────────────────────────────────────────
// show() 는 화면 스크립트의 전역 함수다. 내 버튼은 그쪽 onclick 바인딩이 끝난 뒤에
// 생겼으므로 직접 건다. TITLES 에 이름을 넣지 않으면 제목이 'seedbank' 로 나온다.
try { TITLES.seedbank='씨앗 은행'; } catch(e){}
nav.onclick=function(){ try{ show('seedbank'); }catch(e){} load(); };
if(location.hash.slice(1)==='seedbank'){ try{ show('seedbank'); }catch(e){} load(); }
})();</script>`;
}
