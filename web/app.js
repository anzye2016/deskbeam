
var _gBtns=[],_gHoldUp=[];
var _BASE=new URL('.',location.href).pathname.replace(/\/+$/,'');
var _isTouch=('ontouchstart' in window);
var _isLan=true,_mqx=0,_mqy=0,_mqT=null;
function _mqAcc(dx,dy){
  _mqx+=dx;_mqy+=dy;
  if(!_mqT){_mqT=setTimeout(function(){_mqT=null;if(_mqx||_mqy){sendCmd({type:'mouse_move',dx:_mqx,dy:_mqy});_mqx=0;_mqy=0;}},8);}
}
function _mkShiftBtn(sh){
  var shT=null;
  var rel=function(){
    if(_gShSt||shT){_gShSt=false;if(shT){clearTimeout(shT);shT=null;}sh.classList.remove('sh-on');sendCmd({type:'key_up',key:'shift'});}
  };
  var d=function(){
    if(_gShSt){rel();return;}
    sendCmd({type:'key_down',key:'shift'});
    shT=setTimeout(function(){shT=null;_gShSt=true;sh.classList.add('sh-on');},500);
  };
  var u=function(){
    if(shT){clearTimeout(shT);shT=null;sendCmd({type:'key_up',key:'shift'});return;}

  };
  sh.addEventListener('mousedown',d);sh.addEventListener('mouseup',u);sh.addEventListener('mouseleave',u);
  sh.addEventListener('touchstart',function(e){e.preventDefault();d();});
  sh.addEventListener('touchend',function(e){e.preventDefault();u();});
  return rel;
}
var ks=document.getElementById('ks');
function _mkBtn(spec){
  var b=document.createElement('button');b.className='k';b.textContent=spec.t;
  if(spec.m==='hold'){_bindHoldEl(b,spec.d,spec.u,spec.nc||false,spec.nr);}
  else if(spec.fn){_tapEl(b,spec.fn);}
  else{_tapEl(b,function(){sendCmd({type:spec.c});});}
  return b;
}
var _MOUSE=[
  {t:'L',m:'hold',d:{type:'mouse_down'},u:{type:'mouse_up'},nr:true,nc:true},
  {t:'R',m:'hold',d:{type:'mouse_right_down'},u:{type:'mouse_right_up'},nr:true,nc:true},
  {t:'▲',m:'hold',d:{type:'scroll_up'},u:null,nc:true},
  {t:'▼',m:'hold',d:{type:'scroll_down'},u:null,nc:true},
  {t:'⌫',m:'hold',d:{type:'key_press',key:'backspace'},u:null,nc:true,nr:false},{t:'Enter',c:'enter'},
];
var _KEYS=[
  {t:'Ctrl+C',c:'ctrl_c'},{t:'Esc',c:'esc'},{t:'Ctrl+V',c:'ctrl_v'},
  {t:'Drag',fn:function(){_dm=!_dm;var b=this;b.style.color=_dm?'var(--green)':'';b.style.borderColor=_dm?'var(--green)':'';if(_dm)sendCmd({type:'mouse_down'});else sendCmd({type:'mouse_up'});}},
  {t:'Space',m:'hold',d:{type:'key_press',key:'space'},u:null,nr:false},
  {t:'Win',c:'win'},{t:'F5',c:'f5'},{t:'Ctrl+F5',c:'ctrl_f5'},{t:'Ctrl+J',c:'ctrl_j'},
  {t:'Shift+Enter',c:'shift_enter'},{t:'F12',c:'f12'},
  {t:'UAC',fn:_espUac},{t:'JS',fn:_espJs},{t:'ESP ESC',fn:_espEsc},{t:'Lock',fn:_espLock},
  {t:'ESP Win',fn:_espWin},{t:'ESP L',fn:_espL},
  {t:'↑',m:'hold',d:{type:'key_down',key:'up'},u:{type:'key_up',key:'up'},nr:true,nc:true},
  {t:'↓',m:'hold',d:{type:'key_down',key:'down'},u:{type:'key_up',key:'down'},nr:true,nc:true},
  {t:'←',m:'hold',d:{type:'key_down',key:'left'},u:{type:'key_up',key:'left'},nr:true,nc:true},
  {t:'→',m:'hold',d:{type:'key_down',key:'right'},u:{type:'key_up',key:'right'},nr:true,nc:true},
];
var _mc=document.getElementById('mc');_MOUSE.forEach(function(s){_mc.appendChild(_mkBtn(s));});
_KEYS.forEach(function(s){ks.appendChild(_mkBtn(s));});
var cv=document.getElementById('cv'),sw=document.getElementById('sw'),ta=document.getElementById('ta'),ti=document.getElementById('ti');
var st=document.getElementById('st');

/* ── 证书指纹校验（防局域网 MITM）────────────────────────────
   登录成功后把 /fingerprint 的指纹存 localStorage；此后每次加载页面
   都重新拉取并比对。若指纹与记录的不同，说明连接被中间人劫持
   （ARP 欺骗 + 伪证书），全屏告警并阻断。 */
(function () {
  var KEY = 'deskbeam_cert_fp3';
  function blockMitm() {
    var d = document.createElement('div');
    d.id = 'mitm-block';
    d.style.cssText = 'position:fixed;inset:0;background:rgba(120,10,10,.97);color:#fff;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;text-align:center;padding:24px;font-family:inherit';
    d.innerHTML = '<div style="font-size:18px;font-weight:600;letter-spacing:.08em">⚠ 安全警告：证书指纹不一致</div>' +
      '<div style="font-size:13px;max-width:420px;line-height:1.6">连接到的服务器证书与之前记录的不同，' +
      '可能是中间人攻击（ARP 欺骗 + 伪造证书）。若你确实更换了服务器或重新生成了证书，' +
      '可点下方“信任此证书”重新记录。</div>' +
      '<div style="display:flex;gap:12px">' +
      '<button onclick="location.reload()" style="padding:8px 20px;cursor:pointer">刷新重试</button>' +
      '<button id="mitm-trust" style="padding:8px 20px;cursor:pointer;background:#fff;color:#780a0a;border:none;border-radius:4px;font-weight:600">信任此证书</button>' +
      '</div>';
    document.body.appendChild(d);
    document.getElementById('mitm-trust').addEventListener('click', function () {
      try { localStorage.removeItem(KEY); } catch (e) {}
      location.reload();
    });
  }
  function start() {
    if (location.protocol !== 'https:') return;
    fetch('fingerprint', { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (fp) {
      fp = (fp || '').trim();
      if (!fp) return;
      var stored = localStorage.getItem(KEY);
      if (stored && stored !== fp) { blockMitm(); return; }
      if (!stored) localStorage.setItem(KEY, fp);
    }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

document.addEventListener('mousedown',function(e){if(e.target.closest('.k,.send,.rec,.rec-mini,.ctl'))e.preventDefault();});
let ws=null,wsV=null,_so=false,_dm=false;
var _px=0,_py=0,_mv=false,_ts=0,_vfps=30,_fts=[],_qmtx=0,_qmty=0,_qmp=false;
var _mdP=false,_mdX=0,_mdY=0;
var decoder=null;
var _pc=null,_rtcDc=null;
var _rw=0,_rh=0,_rwr=0,_rhr=0,_pinching=false,_pinchEnded=false,_ps=0;
var _wantKey=false,_wantKeyAt=0,_keyReqAt=0;
var _iceServers=[];
var _encName='';
var RTPPref=false;
var _prefManual=false;
/* 传输方式选择:手动切换过则以手动为准;否则**默认一律 UDP(RTP)**,局域网也一样
   —— 局域网过去走 TCP(端到端延迟遥测 + 自愈),现在统一走 UDP,少一套路径差异、
   也省掉局域网切到 UDP 时那次 RTP 冷启动。
   仍然强制 TCP 的只剩两种情况:SSH 隧道(只通 TCP)、浏览器没有 RTCPeerConnection。
   _isLan 仍保留,但只用于输入等其它判断,不再影响传输选择。 */
var _tunnel=false,_wantRtp=false;
function _useUdp(){
  if(_prefManual)return RTPPref;
  if(_tunnel)return false;
  if(typeof RTCPeerConnection==='undefined')return false;
  return true;
}
var mb=document.getElementById('mb');
/* Render queue: 解码后的帧在此等待绘制。有界突发摊平(旧"低延迟/顺滑"二选一
   已移除,该策略为唯一行为):稳态帧均匀到达 → 来了就画,零额外延迟;网络突发
   (Wi-Fi/TCP 成批投递) → 按帧间隔摊平出帧,显示窗上限 _BUF_RENDER_MS,超出丢
   最旧的已解码帧(已解码帧可安全丢,不破坏参考链)。窗口有界 = 尾帧额外延迟
   有界(3 帧窗最坏 +2 帧 ≈ 60ms),突发内容取"最新几帧"跳剪而非完整回放。 */
var _rq=[],_arrQ=[],_rqMax=3,_stLast=0;
/* 客户端缓冲预算(毫秒)。写死帧数是错的:同样的 16 帧在 55fps 是 290ms,
   在 25fps 就是 640ms —— 那部分延迟完全白送。这里显式钉死"容忍多少毫秒
   积压",两个预算分别对应解码积压与解码后未渲染的积压。
   渲染预算 = 摊平显示窗:90ms(33fps 约 3 帧)。比旧"顺滑"的 150ms/5 帧
   少一截尾帧延迟;2 帧突发(Wi-Fi 最常见批量)完整摊平无跳剪,更大突发
   丢中间帧保尾帧延迟有界。 */
var _BUF_DECODE_MS=250,_BUF_RENDER_MS=90,_dskipMax=16;
var _rqTimer=null,_rqNext=0,_rqFirst=false,_rqIv=1000/33;
function _rqStop(){
  if(_rqTimer){clearTimeout(_rqTimer);_rqTimer=null;}
  _rqFirst=false;_rqNext=0;
  for(var i=0;i<_rq.length;i++){try{_rq[i].f.close();}catch(_){}}
  _rq=[];_arrQ=[];
  _latReset();
}
/* 绘制一张并结算统计(到达->上屏)。 */
function _rqDrawOne(){
  if(!_rq.length)return false;
  var _it=_rq.shift(),f=_it.f;
  try{
    var tg=_gm?document.getElementById('gc'):cv;
    /* 不加 desynchronized:个别驱动上反而造成主线程停顿,解码输出
       回调被拖慢(fps 掉半)。缓存 context 本身仍是免每帧查找的开销。 */
    var ctx=tg._dctx;
    if(!ctx){ctx=tg.getContext('2d');tg._dctx=ctx;}
    var _dt0=performance.now();
    ctx.drawImage(f,0,0);
    _aDrawS+=performance.now()-_dt0;_aDrawN++;
    _aAdS+=performance.now()-_it.t;_aAdN++;
  }catch(_){}
  try{f.close();}catch(_){}
  return true;
}
/* 摊平节拍器:每次只出一帧,按 _rqIv 排下一个 tick;队列空了就停表,
   等下一帧到达时由 output 回调重新启动(所以稳态下不额外加延迟)。 */
function _rqTick(){
  _rqTimer=null;
  var now=performance.now();
  if(!_rqFirst){ if(!_rq.length)return; _rqFirst=true; _rqNext=now; }
  if(now<_rqNext){_rqTimer=setTimeout(_rqTick,Math.max(1,_rqNext-now));return;}
  _rqDrawOne();
  _rqNext+=_rqIv;
  if(_rqNext<now)_rqNext=now;      /* 落后就重置,不追帧 */
  if(!_rq.length)return;           /* 队列空:停表,等下一帧 */
  _rqTimer=setTimeout(_rqTick,Math.max(1,_rqNext-now));
}
function _rqStart(){
  if(_rqTimer)return;
  _rqTimer=setTimeout(_rqTick,0);
}
/* 解码失败要看得见:以前 configure 抛错被丢掉、error 回调只进 console,手机
   上没有控制台,表现就是黑屏却查不出原因。 */
function _decoderFail(msg){
  try{st.textContent=msg;st.style.color='var(--accent)';}catch(_){}
  console.error('Decoder:',msg);
}
function _setupDecoder(m){
  if(typeof VideoDecoder==='undefined'){_decoderFail('浏览器不支持 WebCodecs');return false;}
  _rqStop();_rw=m.width;_rh=m.height;_rwr=m.raw_width||_rw;_rhr=m.raw_height||_rh;_ts=0;_vfps=m.fps||30;_latIv=1000/_vfps;_rqIv=1000/_vfps;_latArrPrev=0;
  _dskipMax=Math.max(3,Math.round(_vfps*_BUF_DECODE_MS/1000));
  _rqMax=Math.max(2,Math.round(_vfps*_BUF_RENDER_MS/1000));
  /* 这次要走 RTP:上面的状态(坐标映射/帧率等)照常设好,但**不建 WebCodecs
     解码器** —— RTP 一帧都不会经过它。那个"建了就扔"的空转正是最容易冒出一个
     虚假解码器错误的地方,而 _decoderFail 会把状态栏永久涂红。 */
  if(_wantRtp){
    if(decoder){try{decoder.close();}catch(ex){}decoder=null;}
    return false;
  }
  if(decoder){try{decoder.close();}catch(ex){}decoder=null;}
  var vd=document.getElementById('vd');if(vd)vd.style.display='none';
  var tg=_gm?document.getElementById('gc'):cv;
  tg.style.display='';tg.width=_rw;tg.height=_rh;_zReset();
  decoder=new VideoDecoder({
    output:function(f){
      var n=performance.now();_fts.push(n);_fts.length>10&&_fts.shift();
      var _nw=performance.now();
      if(_nw-_stLast>500){
        _stLast=_nw;
        var fps=_fts.length<3?0:Math.min(120,Math.round((_fts.length-1)*1000/(_fts[_fts.length-1]-_fts[0])));
        st.textContent='LIVE '+String(fps).padStart(3,'0')+'fps';st.style.color='';
      }
      /* 到达时刻从 WS 收帧处随解码链路一路带到绘制:VideoDecoder 一进一出
         与输入 1:1(H.264 无 B 帧,不重排),FIFO 空说明失配,退化为当前时刻。
         这里先结算"到达->解码输出"(排队+解码),差值即"解码->上屏"
         (渲染队列+主线程调度+绘制),后者才是 Worker 化能改善的部分。 */
      var _at=_arrQ.length?_arrQ.shift():performance.now();
      _aDecS+=performance.now()-_at;_aDecN++;
      _rq.push({f:f,t:_at});
      if(_rq.length>_rqMax){try{_rq.shift().f.close();}catch(_){}_aDr++;}
      _rqStart();
    },
    error:function(e){_decoderFail('解码错误');_arrQ=[];}
  });
  /* 不加 optimizeForLatency:实测会强制低吞吐解码路径,1440p@55
     掉到 ~30fps(编码侧已 -bf 0 无重排,不需要它)。 */
  /* 服务端按实际分辨率/编码器算 codec(旧值写死 Baseline 3.1,而 1440p 实为
     Main 5.0):先问浏览器是否接受,不接受就说清楚,别黑屏。 */
  if(VideoDecoder.isConfigSupported){
    VideoDecoder.isConfigSupported({codec:m.codec}).then(function(s){
      if(!s.supported)_decoderFail('解码器不支持 '+m.codec);
    }).catch(function(){_decoderFail('解码器检查失败 '+m.codec);});
  }
  try{decoder.configure({codec:m.codec});}catch(e){_decoderFail('配置失败 '+m.codec);return false;}
  _fts=[];
  return true;
}
/* ── 播放启动 / 世代守卫 ──────────────────────────────────────────────
   play() 会因三类原因失败,症状都表现为"连上了但黑屏",必须分开处理:
     AbortError      —— 被新的 load()/换源打断,不是故障,忽略;
     NotAllowedError —— 浏览器自动播放策略拦截,需要用户手势;
     其它            —— 真正的播放失败,写状态栏。
   <video> 已带 muted+autoplay,所以正常路径不会走到 NotAllowedError,但
   手机浏览器省电模式/iOS 低电量模式会违反这个前提,必须能自己恢复。

   同时用 _vidGen 给每次换源编号:play() 是异步的,换源后回来的旧结果必须
   作废,否则一次失败的旧 Promise 会把新流的正常状态覆盖掉。 */
var _vidGen=0;
function _playVid(el){
  if(!el)return;
  var gen=_vidGen,p;
  try{p=el.play();}catch(e){_playVidFailed(e,gen);return;}
  if(p&&p.then)p.then(function(){if(gen===_vidGen)_hideTapPlay();},
                      function(e){_playVidFailed(e,gen);});
}
function _playVidFailed(e,gen){
  if(gen!==_vidGen)return;                    /* 已换源:旧结果作废 */
  var n=(e&&(e.name||e.code))||'';
  if(n==='AbortError')return;                 /* 换源/暂停打断,不是故障 */
  if(n==='NotAllowedError'){_showTapPlay();return;}
  _decoderFail('视频播放失败 '+(n||'unknown'));
}
function _tapPlayEl(){
  var el=document.getElementById('tpmsg');
  if(!el){
    var ta=document.getElementById('ta');
    if(!ta)return null;
    el=document.createElement('div');
    el.id='tpmsg';
    el.style.cssText='position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);'
      +'background:rgba(0,0,0,.82);color:#fff;border:1px solid var(--accent,#4cf);'
      +'padding:10px 18px;border-radius:4px;font-size:13px;z-index:1500;cursor:pointer;'
      +'display:none;white-space:nowrap;font-family:inherit';
    el.textContent='点击开始播放';
    el.addEventListener('click',function(ev){
      ev.stopPropagation();ev.preventDefault();
      el.style.display='none';
      var v=_vidEl();if(v)_playVid(v);
    });
    ta.appendChild(el);
  }
  return el;
}
function _showTapPlay(){var el=_tapPlayEl();if(el)el.style.display='block';}
function _hideTapPlay(){var el=document.getElementById('tpmsg');if(el)el.style.display='none';}

/* ── 声音开关 ─────────────────────────────────────────────────────────
   音频只在 RTP/UDP 路径存在(服务端 screen_config 的 audio 字段),TCP 路径
   没有音频通道 —— 所以按钮**只在 UDP 模式出现**,并且放在设置卡片里"传输"
   和"详细统计"之间:标题栏在手机窄屏上已经很挤,空间留给状态和模式。

   默认静音是必须的:<video> 带 muted+autoplay 才能自动起播,一旦解除静音,
   浏览器自动播放策略就会拦下 —— 所以解开静音这个动作本身就是用户手势,
   正好满足策略要求,不需要额外弹窗。 */
var _audioOn=false,_audioFound=false,_audioDev='';
/* 收到但**未并在听**时的音频轨(见 _applyMute)。它留在 PC 里,所以
   `_audioFound` 仍为真、声音按钮语义不变、也不需要重协商。 */
var _audioTrack=null;
function _paintSnd(b){
  if(!b)return;
  /* 按钮文字只留最短的状态词(手机窄屏空间紧张):"TCP"/"UDP"、"声音"/"静音"、
     "统计开"/"统计关"。完整说明放在 title 提示里,不占版面。 */
  b.textContent=_audioFound?(_audioOn?'声音':'静音'):'无音轨';
  b.disabled=!_audioFound;
  b.style.opacity=_audioFound?'':'0.5';
  b.title=_audioFound
    ?((_audioOn?'关闭电脑声音':'播放电脑声音')+(_audioDev?('（'+_audioDev+'）'):''))
    :'当前没有音轨:需要服务端 audio_enabled=true,且能采到系统声音';
  b.classList.toggle('on',_audioOn&&_audioFound);
}
function _sndBtn(){
  /* 只更新已存在的按钮。设置卡片是临时创建的,没打开时这里是 no-op。 */
  var b=document.getElementById('snd');
  _paintSnd(b);
  return b;
}
function _audioRow(container){
  if(!_useUdp())return null;      /* 只有 UDP(RTP) 模式提供电脑声音 */
  var b=document.createElement('button');
  b.id='snd';b.type='button';
  b.style.cssText='flex:1;height:36px;border:1px solid var(--border);'
    +'background:var(--surface);color:var(--dim);font-family:inherit;'
    +'font-size:12px;cursor:pointer';
  b.addEventListener('click',function(ev){
    ev.stopPropagation();ev.preventDefault();
    if(!_audioFound)return;
    _audioOn=!_audioOn;_applyMute();_paintSnd(b);
  });
  container.appendChild(b);
  /* 直接绘制手上这个元素,不要走 getElementById:_openPanel 是先把整棵
     DOM 建好再 appendChild 到 body 的,此刻按钮还不在文档里,查不到。 */
  _paintSnd(b);
  return b;
}
/* 更新设置卡片里的"声音来源"那一行。卡片没打开时是 no-op。
   el 可选:_openPanel 内部调它时必须把元素**直接传进来**,因为那时整棵 DOM 还没
   appendChild 到 body,getElementById 查不到(踩过两次的同一个坑)。 */
function _paintSrc(el){
  var v=el||document.getElementById('asrcV');
  if(!v)return;
  v.style.color=_audioFound?'var(--text)':'var(--dim)';
  v.style.fontWeight=_audioFound?'700':'';
  v.textContent=_audioFound?(_audioDev||'未知设备'):'未启用';
}
function _applyMute(){
  ['vd','gv'].forEach(function(id){
    var v=document.getElementById(id);
    if(v)v.muted=!_audioOn;
  });
  /* 静音时把音频轨从 <video> 的流里摘掉、解除静音时并回去 —— 只有在流里
     的轨道才会被播放/解码,也才让 Chrome 产生 A/V 对齐的约束。 */
  if(_audioTrack){
    var s=document.getElementById('vd'),g=document.getElementById('gv');
    var ms=(g&&g.srcObject)||(s&&s.srcObject);
    if(ms&&ms.addTrack){
      try{
        if(_audioOn)ms.addTrack(_audioTrack);
        else if(ms.getTracks&&ms.getTracks().indexOf(_audioTrack)>=0)ms.removeTrack(_audioTrack);
      }catch(_){}
    }
  }
  /* 解除静音后如果播放被策略中断,这里用同一手势重试一次。 */
  if(_audioOn){var v=_vidEl();if(v)_playVid(v);}
}

/* 离开 RTP 时清理:RTP 用独立的 <video>+PeerConnection,不清理会让 _rtpMode
   残留(缩放/点击命中仍指向已隐藏的 <video>)、旧 PC 继续收流。 */
function _teardownRtp(){
  if(_rtpTimer){clearTimeout(_rtpTimer);_rtpTimer=null;}
  if(_rtpStatTimer){clearInterval(_rtpStatTimer);_rtpStatTimer=null;}
  _jbRecv=null;_jbRecvA=null;_audioTrack=null;_avStream=null;
  if(_rtpMode){
    _rtpMode=false;
    _vidGen++;                     /* 换源:让在途的 play() 结果作废 */
    _hideTapPlay();
    _audioFound=false;_sndBtn();   /* 音轨随 PC 一起消失;下次 screen_config 再定 */
    var vd=document.getElementById('vd');
    if(vd){try{vd.srcObject=null;}catch(_){}vd.style.display='none';}
    /* gv 也要清:GYRO 模式下画面在 gv 上,只清 vd 会留下一个挂着旧 MediaStream
       的隐藏元素,下次进 GYRO 时先闪旧流再被覆盖。 */
    var gv=document.getElementById('gv');
    if(gv){try{gv.srcObject=null;}catch(_){}gv.style.display='none';}
  }
  if(_pc){try{_pc.close();}catch(_){}_pc=null;}
}
/* RTP 模式没有自建帧序号,延迟/丢帧只能看浏览器自己的接收统计。每 2s 采一次
   pc.getStats(),取 inbound-rtp(video) 的累计量换算成:丢包率、抖动缓冲平均延迟、
   解码丢帧、卡顿次数、NACK 次数。 */
function _startRtpStats(pc){
  if(_rtpStatTimer){clearInterval(_rtpStatTimer);_rtpStatTimer=null;}
  _rtp={loss:0,jb:0,dropped:0,freeze:0,nack:0,rx:0};
  var _brPrev=null;
  var tick=function(){
    if(!_rtpMode||_pc!==pc)return;
    pc.getStats().then(function(rep){
      if(!_rtpMode||_pc!==pc)return;
      var s=null,sa=null;
      rep.forEach(function(r){
        if(r.type!=='inbound-rtp')return;
        var k=r.kind||r.mediaType;
        if(k==='video')s=r;
        else if(k==='audio')sa=r;
      });
      if(!s)return;
      /* 音频侧的抖动缓冲驻留。**这是"RTT 很低、局域网却出现一两秒延迟"最可能的
         来源**:Chrome 的 NetEq 缓冲能涨到秒级,而 <video> 同时承载音视频时,播放器
         会把视频**拖到与音频对齐**。以前只取视频的 inbound-rtp,从没测过它。 */
      var abd=-1,arx=-1,aem=-1;
      if(sa&&sa.jitterBufferDelay!=null&&sa.jitterBufferEmittedCount>0)
        abd=(sa.jitterBufferDelay/sa.jitterBufferEmittedCount)*1000;
      if(sa){
        /* 收/出两个**速率**。只有"驻留时间"分不出下面这两种完全不同的故障:
             音出≈50/s 而驻留在涨 -> 接收端在放,但播放速率慢于 RTP 时钟(漂移)
             音出远小于 50/s       -> 接收端根本没在消费音频(没播/被挂起)
           两者修法毫无共同点,所以必须把速率也显示出来。 */
        var _an=performance.now()/1000;
        if(_aPrev.t&&_an>_aPrev.t){
          var _dt=_an-_aPrev.t;
          if(sa.packetsReceived!=null&&_aPrev.rx!=null)
            arx=Math.round((sa.packetsReceived-_aPrev.rx)/_dt);
          if(sa.jitterBufferEmittedCount!=null&&_aPrev.em!=null)
            aem=Math.round((sa.jitterBufferEmittedCount-_aPrev.em)/_dt);
        }
        _aPrev={t:_an,rx:sa.packetsReceived,em:sa.jitterBufferEmittedCount};
      }
      var lost=s.packetsLost||0,recv=s.packetsReceived||0,tot=lost+recv;
      var jbd=s.jitterBufferDelay,jbe=s.jitterBufferEmittedCount;
      var rx=0;
      if(s.bytesReceived!=null){
        if(_brPrev!=null&&s.bytesReceived>=_brPrev)rx=(s.bytesReceived-_brPrev)/2/1024;
        _brPrev=s.bytesReceived;
      }
      _rtp={
        loss:tot>0?lost*100/tot:0,
        jb:(jbd!=null&&jbe>0)?(jbd/jbe)*1000:0,
        dropped:s.framesDropped||0,
        freeze:s.freezeCount||0,
        nack:s.nackCount||0,
        rx:rx,
        ab:abd,
        arx:arx,
        aem:aem,
        jit:(s.jitter||0)*1000,  /* Chrome 报的 RTP 到达间隔抖动(≠缓冲驻留) */
        jbt:_jbTarget            /* 我们给浏览器设的 jitterBufferTarget */
      };
      _jbAuto(s);
    }).catch(function(){});
  };
  tick();
  _rtpStatTimer=setInterval(tick,2000);
}
function _sendScreenMode(){
  if(!(wsV&&wsV.readyState===WebSocket.OPEN))return '';
  var fmt;
  if(typeof RTCPeerConnection!=='undefined'&&typeof VideoDecoder==='undefined')fmt='webrtc';
  else if(_useUdp())fmt='rtp';
  else fmt='tcp';
  /* 记住这次要用哪条传输:_setupDecoder 据此决定要不要建 WebCodecs 解码器。
     RTP 的画面由 <video> 渲染,建出来的解码器一帧都收不到、随即被 _rtpRecv 关掉。 */
  _wantRtp=(fmt==='rtp');
  if(fmt!=='rtp')_teardownRtp();
  /* 协商宽限期:这期间无帧是正常的,不能触发帧停滞看门狗。
     RTP 冷启动最坏 ~5.5s(服务端切流让位 ≤2s + 编码器探测 0.5s +
     first_frame ≤2s + offer),而看门狗阈值是 5s —— 不给宽限期就会在会话
     即将成功的瞬间把它拆掉重来,表现成"切 UDP 进画面特别慢甚至进不去"。 */
  _mediaDeadline=performance.now()+_NEGO_MS;
  if(fmt==='webrtc')wsV.send(JSON.stringify({type:'set_mode',screen:true,format:'webrtc'}));
  else if(fmt==='rtp')wsV.send(JSON.stringify({type:'set_mode',screen:true,format:'rtp'}));
  else wsV.send(JSON.stringify({type:'set_mode',screen:true}));
  return fmt;
}
function _startScreenVideo(){
  _sendScreenMode();
}
function sm(on){
  _so=on;mb.textContent=on?'SCREEN':'REMOTE';mb.className='mode-btn'+(on?' on':'');document.body.classList.toggle('screen',on);
  if(on){
    sw.style.overflow='hidden';document.getElementById('ph').style.display='none';
    document.getElementById('pz').style.display='';document.getElementById('ph').innerHTML='';_fts=[];
    if(wsV&&wsV.readyState===WebSocket.OPEN){
      var fmt=_sendScreenMode();
      if(fmt==='webrtc'){
        var td=document.createElement('div');
        td.style.cssText='position:fixed;left:50%;top:12px;transform:translateX(-50%);background:rgba(0,0,0,.85);color:#ffd166;border:1px solid #ffd166;padding:6px 14px;font-size:11px;letter-spacing:.05em;z-index:2000;border-radius:3px;font-family:inherit;pointer-events:none;white-space:nowrap';
        td.textContent='当前浏览器无 VideoDecoder,使用 WebRTC 兜底(30fps+高延迟)。建议 Chrome/Edge';
        document.body.appendChild(td);
        setTimeout(function(){try{td.remove()}catch(_){}},5000);
      }else if(fmt==='rtp'){
        // UDP 协商超时兜底:服务端冷启动 RTP(切流让位 ≤2s + 编码器探测 0.5s +
        // first_frame ≤2s + offer)最坏 ~5s,给 8s 余量;超时才回退 TCP。
        if(_rtpTimer){clearTimeout(_rtpTimer);}
        _rtpTimer=setTimeout(function(){_rtpTimer=null;if(!_rtpMode)_rtpFail();},_NEGO_MS);
      }
    }
  }else{
    _setPaused(false);_fts=[];st.textContent='LIVE';_rqStop();
    if(decoder){try{decoder.close();}catch(e){}decoder=null;}
    _teardownRtp();_rtcDc=null;
    var vd=document.getElementById('vd');if(vd){vd.style.display='none';}
    cv.style.display='none';document.getElementById('ph').style.display='';
    document.getElementById('ph').innerHTML='<div class=ph>REMOTE MODE</div>';
    document.getElementById('pz').style.display='none';
    if(document.body.classList.contains('full'))zs(Z.length-2);
    if(wsV&&wsV.readyState===WebSocket.OPEN)wsV.send(JSON.stringify({type:'set_mode',screen:false}));
  }
}
mb.addEventListener('click',function(){sm(!_so);});
var _ENC_LABELS={h264_nvenc:'NVENC (NVIDIA)',h264_amf:'AMF (AMD)',h264_qsv:'QSV (Intel)',h264_vaapi:'VAAPI (Linux HW)',libx264:'x264 软编 (CPU)'};
function _openPanel(){
  var d=document.createElement('div');
  /* padding 让卡片不贴屏幕边(窄屏上也是安全的:可用宽度会先于 max-width 生效)。 */
  d.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:1001;padding:16px;box-sizing:border-box';
  var b=document.createElement('div');
  /* 必须给 max-width:这是 flex 项,宽度是 fit-content = min(max-content, 可用宽度)。
     卡片一旦装进任意长度的文本(最典型的是 WASAPI 设备名),max-content 被抬高,
     卡片就会一路撑满整个视口 —— 之前的 "声音来源" 那一行正是这样把设置页拉宽的。
     注意 overflow-wrap 只影响 min-content,管不住 max-content,所以封顶只能靠这里。
     封顶后长设备名会换行,完整内容仍然看得到。 */
  b.style.cssText='background:var(--surface);border:1px solid var(--border);padding:16px;display:flex;flex-direction:column;gap:8px;min-width:240px;max-width:320px;box-sizing:border-box';
  var t=document.createElement('div');t.textContent='DeskBeam';
  t.style.cssText='color:var(--dim);font-size:10px;letter-spacing:.1em;text-transform:uppercase;text-align:center;margin-bottom:4px';
  b.appendChild(t);
  /* 串流状态：编码为服务端实际选中的编码器（NVENC/AMF/QSV/软编），
     分辨率为编码输出尺寸；与原生捕获不一致即为降级（WAN/软编降规格）。 */
  var st=document.createElement('div');
  st.style.cssText='border:1px solid var(--border);border-radius:2px;padding:6px 8px;display:flex;flex-direction:column;gap:3px;font-size:11px;letter-spacing:.02em;color:var(--text)';
  /* 只在真的在串流且已知编码器时显示:remote 模式没有视频、不会下发 config,
     未连接时的默认文案会落到"软 · 未连接",纯属误导。 */
  if(_encName&&(_so||_gm)){
    var encLbl=_ENC_LABELS[_encName]||_encName;
    var encHw=_encName!=='libx264';
    var en=document.createElement('div');
    en.innerHTML='<span style="color:var(--dim)">编码 </span><span style="color:'+(encHw?'var(--green)':'var(--accent)')+';font-weight:700">'+(encHw?'硬':'软')+' · '+encLbl+'</span>';
    st.appendChild(en);
  }
  var deg=(_rwr&&_rwr!==_rw)||(_rhr&&_rhr!==_rh);
  var rn=document.createElement('div');
  if(!_rw)rn.innerHTML='<span style="color:var(--dim)">分辨率 </span><span style="color:var(--dim)">未连接</span>';
  else rn.innerHTML='<span style="color:var(--dim)">分辨率 </span><span style="color:'+(deg?'var(--accent)':'var(--text)')+';font-weight:700">'+
    (deg?(_rwr+'×'+_rhr+' → '):'')+_rw+'×'+_rh+' @ '+Math.round(_vfps)+'fps'+
    (deg?' <span style="color:var(--accent)">降级</span>':'')+'</span>';
  st.appendChild(rn);
  /* 声音来源:回环采的是 Windows 的哪个输出设备。**必须直接写出来**——
     "没声音"最常见的原因就是采到的不是你正在用的那个设备,而手机上没法悬停
     看 title(触摸屏没有 hover)。只在 UDP 模式显示,因为音频本身就是 UDP 专属。
     设备名来自服务端,可能含 ()& 等字符,所以用 textContent 而不是 innerHTML。 */
  if(_useUdp()){
    var an=document.createElement('div');
    an.id='asrc';
    /* overflow-wrap:设备名是任意的 WASAPI 名字,可能很长且没有空格;
       不设的话会横向撑破设置卡片。 */
    an.style.cssText='overflow-wrap:anywhere';
    var a1=document.createElement('span');
    a1.style.color='var(--dim)';a1.textContent='声音来源 ';
    var a2=document.createElement('span');
    a2.id='asrcV';
    an.appendChild(a1);an.appendChild(a2);
    st.appendChild(an);
    _paintSrc(a2);
  }
  b.appendChild(st);
  var row=document.createElement('div');row.style.cssText='display:flex;gap:8px';
  b.appendChild(row);
  var l=document.createElement('button');l.textContent='Logout';
  l.style.cssText='flex:1;height:36px;border:1px solid var(--blue);background:var(--surface);color:var(--blue);font-family:inherit;font-size:12px;cursor:pointer';
  l.onclick=function(){d.remove();location.href=_BASE+'/logout'};
  row.appendChild(l);
  var s=document.createElement('button');s.textContent='Shutdown';
  s.style.cssText='flex:1;height:36px;border:1px solid var(--accent);background:var(--surface);color:var(--accent);font-family:inherit;font-size:12px;cursor:pointer';
  s.onclick=function(){d.remove();location.href=_BASE+'/shutdown'};
  row.appendChild(s);
  var rowG=document.createElement('div');rowG.style.cssText='display:flex;gap:8px';
  b.appendChild(rowG);
  var g=document.createElement('button');g.textContent='GYRO';
  g.style.cssText='flex:1;height:36px;border:1px solid var(--border);background:var(--surface);color:'+(_gm?'var(--green)':'var(--dim)')+';font-family:inherit;font-size:12px;cursor:pointer';
  g.onclick=function(){d.remove();_gyToggle();};
  rowG.appendChild(g);
  var th=document.createElement('button');
  th.textContent=document.documentElement.classList.contains('dark')?'LIGHT':'DARK';
  th.style.cssText='flex:1;height:36px;border:1px solid var(--border);background:var(--surface);color:var(--dim);font-family:inherit;font-size:12px;cursor:pointer';
  th.onclick=function(){d.remove();_toggleTheme()};
  rowG.appendChild(th);
  /* LAN 访问开关：改的是服务端运行期开关（并写回 config.json，重启后保持）。
     关闭后来自 RFC1918 的连接一律 403，已连着的局域网会话会被立刻断开——若
     本机正在走局域网，关它会连自己一起断。 */
  var la=document.createElement('button');
  la.style.cssText='height:36px;border:1px solid var(--border);background:var(--surface);color:var(--dim);font-family:inherit;font-size:12px;cursor:pointer';
  la.textContent='LAN ACCESS: ...';la.disabled=true;
  var _laOn=null;
  function _laPaint(t){
    _laOn=(t==='on');
    la.textContent='LAN ACCESS: '+(_laOn?'ON':'OFF');
    la.style.borderColor=_laOn?'var(--green)':'var(--accent)';
    la.style.color=_laOn?'var(--green)':'var(--accent)';
    la.disabled=false;
  }
  fetch(_BASE+'/lan_access',{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.text():null;})
    .then(function(t){if(t===null){la.textContent='LAN ACCESS: --';return;}_laPaint(t.trim().split(':')[0]);})
    .catch(function(){la.textContent='LAN ACCESS: --';});
  la.onclick=function(){
    if(_laOn===null)return;
    var want=!_laOn;la.disabled=true;
    fetch(_BASE+'/lan_access?on='+(want?'1':'0'),{credentials:'include',cache:'no-store'})
      .then(function(r){return r.ok?r.text():null;})
      .then(function(t){
        if(t===null){la.textContent='LAN ACCESS: --';return;}
        var p=t.trim().split(':');
        _laPaint(p[0]);
        if(p[1]==='unsaved')la.textContent+=' (未写入 config)';
        else if(!_laOn&&_isLan)la.textContent+=' (本机已断开)';
      })
      .catch(function(){la.disabled=false;});
  };
  /* 传输方式 + 详细统计开关:同一行,放在 LAN ACCESS 之上。
     - 传输:手动切换后不再受隧道/能力探测的自动选择影响。
     - 详细统计:关=日常只显示 R(延迟);开=按传输显示 TCP/UDP 各自统计(含丢包)。
       状态存 localStorage,下次打开保持。 */
  var rowT=document.createElement('div');rowT.style.cssText='display:flex;gap:8px';
  b.appendChild(rowT);
  var u=document.createElement('button');
  u.textContent=(_useUdp()?'UDP':'TCP');
  u.title='传输方式:UDP(RTP) / TCP。手动选过之后不再自动切换';
  u.style.cssText='flex:1;height:36px;border:1px solid var(--border);background:var(--surface);color:var(--dim);font-family:inherit;font-size:12px;cursor:pointer';
  u.onclick=function(){
    d.remove();
    /* 首次手动切换:先把"当前自动选择的结果"固化成手动偏好,再翻转。否则
       RTPPref 初值 false 在"自动=UDP"(WAN/Tailscale)时会 !false=true,第一次
       点击仍选 UDP,要再点一次才会切成 TCP。 */
    if(!_prefManual){RTPPref=_useUdp();_prefManual=true;}
    RTPPref=!RTPPref;
    /* 用户明确表达意图,解除 _rtpFail 的失败退避锁。否则一次 RTP 失败会让 TCP
       兜底被禁用 30 秒(_rtpRetry 只随时间/刷新复位),期间怎么切都不推流 ——
       现象就是"必须刷新浏览器才能恢复"。 */
    _rtpRetry=0;
    if(_so)sm(true);
  };
  rowT.appendChild(u);
  /* 声音开关(仅 UDP 模式出现):夹在"传输"和"详细统计"之间 */
  _audioRow(rowT);
  var dg=document.createElement('button');
  dg.textContent='统计'+(_DIAG?'开':'关');
  dg.title='标题栏显示当前传输的详细统计(含丢包/丢帧);关=只显示 R 延迟';
  dg.style.cssText='flex:1;height:36px;border:1px solid var(--border);background:var(--surface);color:var(--dim);font-family:inherit;font-size:12px;cursor:pointer';
  dg.onclick=function(){d.remove();_diagToggle();};
  rowT.appendChild(dg);
  b.appendChild(la);
  var c=document.createElement('button');c.textContent='Cancel';
  c.style.cssText='height:36px;border:1px solid var(--border);background:var(--surface);color:var(--dim);font-family:inherit;font-size:12px;cursor:pointer';
  c.onclick=function(){d.remove()};
  b.appendChild(c);
  d.appendChild(b);
  document.body.appendChild(d);
}
var _zi=0,Z=['Fit','Full'],ZF=[0,-1];
function zs(i){
  _zi=Math.max(0,Math.min(Z.length-1,i));var z=ZF[_zi];
  document.body.classList.toggle('full',z<0);
  _zReset();
  var vd=document.getElementById('vd');
  if(z<0){
    cv.style.width='100%';cv.style.height='100%';cv.style.maxWidth='none';cv.style.maxHeight='none';
    if(vd){vd.style.width='100%';vd.style.height='100%';vd.style.maxWidth='none';vd.style.maxHeight='none';}
  }else if(z===0){
    cv.style.width='';cv.style.height='';cv.style.maxWidth='100%';cv.style.maxHeight='100%';
    if(vd){vd.style.width='';vd.style.height='';vd.style.maxWidth='100%';vd.style.maxHeight='';}
  }else{
    cv.style.maxWidth='none';cv.style.maxHeight='none';cv.style.width=(z*100)+'%';cv.style.height='';
    if(vd){vd.style.maxWidth='none';vd.style.maxHeight='none';vd.style.width=(z*100)+'%';vd.style.height='';}
  }
  document.getElementById('zl').textContent=Z[_zi];
}
document.getElementById('zi').addEventListener('click',function(){zs(_zi+1);});document.getElementById('zo').addEventListener('click',function(){zs(_zi-1);});zs(0);
/* ── 后台标签页治理:隐藏时不自动重连(避免僵尸标签页循环重连拖垮
   服务端),并暂停视频流省 GPU/带宽;回到前台恢复。 ── */
var _recon={cmd:false,vid:false};
function _reconLater(which,fn){
  _recon[which]=true;
  if(document.hidden)return;
  setTimeout(function(){
    if(document.hidden)return;  // 挂起等 visibilitychange 再恢复
    _recon[which]=false;fn();
  },2000);
}
/* WS 重连前先探测认证:session 过期则跳登录页,避免无限重连刷 403
   把自己 IP 送进 fail2ban 封禁。 */
function _reconOrLogin(which,fn){
  if(document.hidden){_reconLater(which,fn);return;}
  fetch(_BASE+'/',{redirect:'follow',credentials:'include',cache:'no-store'}).then(function(r){
    if(r.redirected&&r.url.indexOf('/login')>=0)location.href=_BASE+'/login';
    else _reconLater(which,fn);
  }).catch(function(){_reconLater(which,fn);});
}
document.addEventListener('visibilitychange',function(){
  if(document.hidden){
    if(_so){
      if(wsV&&wsV.readyState===WebSocket.OPEN)
        wsV.send(JSON.stringify({type:'set_mode',screen:false}));
    }
    return;
  }
  if(_recon.cmd){_recon.cmd=false;cn();}
  if(_recon.vid){_recon.vid=false;cnV();}
  else if(_so)_startScreenVideo();
});
function cn(){
  var p=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(p+'://'+location.host+_BASE+'/ws_cmd');
  ws.onopen=function(){
    st.textContent='LIVE';
    var gx=document.getElementById('gex');if(gx)gx.textContent='LIVE';
  };
  ws.onclose=function(){
    _qmtx=0;_qmty=0;_qmp=false;st.textContent='RETRY';
    var gx=document.getElementById('gex');if(gx)gx.textContent='RETRY';
    _reconOrLogin('cmd',cn);
  };
  ws.onerror=function(){st.textContent='ERROR';};
  ws.onmessage=function(e){
    if(typeof e.data!=='string')return;
    try{
      var m=JSON.parse(e.data);
      if(m.type==='hello'){
        var wasTun=_tunnel,wasLan=_isLan;
        _iceServers=m.iceServers||[];_isLan=m.lan!==false;_tunnel=m.tunnel===true;
        // hello 可能晚于 wsV onopen 到达。隧道/LAN 判定变化时重新选择传输
        // (隧道或局域网 → TCP;WAN/Tailscale → UDP)。手动切换过则不干预。
        if(wasTun!==_tunnel&&!_prefManual&&(_so||_gm))sm(true);
        if(!m.streaming){document.getElementById('mb').style.display='none';}
        if(m.espConfig){
          _espRelay=m.espConfig.relayUrl;_espToken=m.espConfig.token;_espDev=m.espConfig.device;_espLockPw=m.espConfig.lockPassword||'';_espLockEnter=m.espConfig.lockEnter===true;
        }
      }else if(m.type==='pong'){
        if(typeof m.t==='number'){
          var _s=performance.now()-m.t;
          _aRttS+=_s;_aRttN++;
          /* 拥塞判据用近期值(短 EMA),不用 30s 均值:均值会把 5s 的突发抹平 */
          _rttNow=_rttNow?_rttNow*0.6+_s*0.4:_s;
        }
      }
    }catch(_){}
  };
}
function cnV(){
  _bitrateTier=0;_tierSince=0;
  var p=location.protocol==='https:'?'wss':'ws';
  wsV=new WebSocket(p+'://'+location.host+_BASE+'/ws');
  wsV.binaryType='arraybuffer';
  wsV.onopen=function(){_setPaused(false);if(_so||_gm)sm(true);};
  wsV.onclose=function(){_reconOrLogin('vid',cnV);};
  wsV.onerror=function(){};
  wsV.onmessage=function(e){
    if(typeof e.data==='string'){
      try{
        var m=JSON.parse(e.data);
        if(m.type==='screen_config'){
          _encName=m.enc||'';
          _setupDecoder(m);
          /* 服务端只在 RTP 路径建音轨;TCP/WebRTC 兜底一律 audio:false。
             按钮只在真有音轨时出现,避免用户点了没反应。 */
          _audioFound=m.audio===true;
          _audioDev=m.audio_device||'';
          /* **不要**在这里把 _audioOn 清成 false。它表达的是"用户想不想听",
             不是"当前通道有没有音频"。清掉之后:UDP(开声音)→ TCP(没有音频通道)
             → 切回 UDP,声音会默认是关的,用户每切一次传输就得重新点一遍。
             元素是否静音交给 _applyMute 处理,音轨回来后 _rtpRecv 会按 _audioOn
             自动恢复。 */
          _applyMute();
          _sndBtn();
        }else if(m.type==='audio_device'){
          /* 服务端切换了采集设备(Windows 默认播放设备被改):更新设置卡片里的
             "声音来源"那一行。卡片是临时创建的,没打开时 _paintSrc 是 no-op,
             下次打开会读到新的 _audioDev。 */
          _audioDev=m.device||'';
          _paintSrc();
        }else if(m.type==='screen_paused'){
          _setPaused(true);
        }else if(m.type==='screen_resumed'){
          _setPaused(false);
        }else if(m.type==='webrtc_offer'){
          var pc=new RTCPeerConnection({iceServers:_iceServers});_pc=pc;_rtcDc=null;
          pc.ontrack=function(e){
            if(e.track&&e.track.kind!=='video')return;   /* 该路径无音轨,防御性跳过 */
            var tv=_gm?document.getElementById('gv'):document.getElementById('vd');
            if(_gm){document.getElementById('gc').style.display='none';}
            else{cv.style.display='none';}
            tv.style.display='block';_vidGen++;tv.srcObject=e.streams[0];_playVid(tv);
          };
          pc.ondatachannel=function(e){_rtcDc=e.channel;};
          pc.setRemoteDescription(new RTCSessionDescription({sdp:m.sdp,type:m.sdp_type})).then(function(){return pc.createAnswer()}).then(function(a){
            pc.setLocalDescription(a);wsV.send(JSON.stringify({type:'webrtc_answer',sdp:a.sdp,sdp_type:a.type}));
          });
          pc.onicecandidate=function(e){
            if(e.candidate&&wsV)wsV.send(JSON.stringify({type:'webrtc_ice',candidate:{candidate:e.candidate.candidate,sdpMid:e.candidate.sdpMid||'0',sdpMLineIndex:e.candidate.sdpMLineIndex||0}}));
          };
        }else if(m.type==='webrtc_ice'){
          if(_pc){try{_pc.addIceCandidate(new RTCIceCandidate(m.candidate))}catch(ex){}}
        }else if(m.type==='rtp_offer'){
          _rtpRecv(m);
        }else if(m.type==='rtp_ice'){
          if(_pc){try{_pc.addIceCandidate(new RTCIceCandidate(m.candidate))}catch(ex){}}
        }else if(m.type==='rtp_failed'){
          if(_rtpTimer){clearTimeout(_rtpTimer);_rtpTimer=null;}
          console.error('RTP failed:',m.reason);_rtpFail();
        }
      }catch(_){}
    }else if(e.data instanceof ArrayBuffer){
      var v=new Uint8Array(e.data);
      if(v.length<5)return;
      var isKey=v[0]===1,h264=v.subarray(5);
      var seq=0;
      for(var i=0;i<4;i++)seq=seq*256+v[1+i];
      var _na=performance.now();
      if(_latArrPrev){var _d=_na-_latArrPrev;if(_d>5&&_d<250)_latIv=_latIv*0.92+_d*0.08;}
      _latArrPrev=_na;
      _lastFrameAt=_na;
      _aFrame++;
      _rxNow+=v.length;
      _aBufS+=(decoder?decoder.decodeQueueSize:0)+_rq.length;_aBufN++;
      _latMeasure(seq);_bitrateAdapt();
      if(decoder&&decoder.state==='configured'){
        /* 仅解码器真饱和(decodeQueueSize 深积压)时跳 delta 等 key。
           渲染队列 _rq 存的是已解码帧,丢了不破坏参考链——由解码回调里
           原有的"丢最旧"处理,这里绝不能按 _rq 跳帧,否则渲染稍慢就
           循环进入 GOP 级冻结。 */
        if(isKey){_wantKey=false;_keyReqAt=0;}
        if(!isKey&&decoder.decodeQueueSize>_dskipMax){
          /* 积压丢 delta 等 key:长 GOP 下(如 WAN 3s)等待太久会长时间
             冻结,主动向服务器请求关键帧(服务端重启编码器强制 IDR)。
             但仅在"链路突发"时请求:若本端本来就在持续丢帧(手机跟不上),
             请求只会让服务端反复重启 ffmpeg,越帮越忙。 */
          var _nk=performance.now();
          if(!_wantKey){_wantKey=true;_wantKeyAt=_nk;}
          if(_nk-_wantKeyAt>600&&_nk-_keyReqAt>3000&&_pDrop<5&&wsV&&wsV.readyState===WebSocket.OPEN){
            _keyReqAt=_nk;
            wsV.send(JSON.stringify({type:'request_keyframe'}));
          }
          _aDd++;
          return;
        }
        var c=new EncodedVideoChunk({type:isKey?'key':'delta',timestamp:_ts,data:h264});_ts+=Math.round(1000000/_vfps);
        try{decoder.decode(c);_arrQ.push(_na);}catch(_){}
      }
    }
  };
}

/* ── RTP (WebRTC video track over UDP) ──
   服务端把已 NVENC 编码的 H.264 通过标准 RTP 视频轨发来,浏览器用
   RTCRtpReceiver 接收,由浏览器原生 <video> 解码播放。丢包由浏览器原生
   NACK/PLI 处理,无需自建协议。信令(offer/answer/ICE)复用 /ws。 */
var _rtpMode=false,_rtpRetry=0,_rtpTimer=null;
/* 当前 RTP 会话的合成流(音视频轨并进同一条,见 pc.ontrack)。
   进出 GYRO 靠 _attachStream 把它改挂到另一个 <video>,而不是重新协商。 */
var _avStream=null;
/* RTP 模式的接收统计(每 2s 采一次 pc.getStats()):丢包% / 抖动缓冲ms / 解码丢帧 /
   卡顿次数 / NACK。只在标题栏"详细统计"开启且处于 RTP 模式时显示。 */
var _rtp={loss:0,jb:0,dropped:0,freeze:0,nack:0,rx:0},_rtpStatTimer=null;
function _rtpRecv(m){
  /* 过期 offer 守卫:服务端处理 set_mode{format:'rtp'} 时有一段"等 TCP sender
     让位"(最长 2s)再冷启动,期间用户完全可能已经切回 TCP/退出 SCREEN。那条
     offer 这时是**没人要的** —— 照单全收会把画面切到一条服务端随后就关掉的
     RTP 通道上:PC 停在 new/checking,oniceconnectionstatechange 不会触发
     failed,而下面又会清掉 _rtpTimer,于是没有任何东西会把它救回来,表现为
     永久黑屏、只有刷新页面才行。所以只在自己确实还要 RTP 时才接受。 */
  if(!_so||!_useUdp()){
    if(wsV&&wsV.readyState===WebSocket.OPEN){
      wsV.send(JSON.stringify({type:'set_mode',screen:!!_so}));
    }
    return;
  }
  if(_rtpTimer){clearTimeout(_rtpTimer);_rtpTimer=null;}
  try{if(_pc){_pc.close();}}catch(_){}
  // RTP 画面由 <video> 渲染,screen_config 触发的 WebCodecs 解码器用不上,
  // 关掉省资源(不影响 _rw/_rh 坐标映射,它们已在 _setupDecoder 里设好)。
  if(decoder){try{decoder.close();}catch(_){}decoder=null;}
  var pc=new RTCPeerConnection({iceServers:_iceServers});_pc=pc;
  /* aiortc 给每条 track 分配各自的 msid,所以视频与音频是两个独立的
     MediaStream。这里自己合成一条再挂到 <video> 上:解除静音后有声音,而且
     音视频同属一个播放器,由它自己做 A/V 对齐。 */
  _avStream=new MediaStream();
  pc.ontrack=function(e){
    if(!e.track)return;
    if(e.track.kind==='video'){try{_avStream.addTrack(e.track);}catch(_){}}
    if(e.track.kind!=='video'){
      /* 音频轨只并进 MediaStream,绝不重设 srcObject —— 那会把视频轨挤掉。 */
      /* **静音时先不并进去**:同一个 <video> 同时承载音视频时,Chrome 会为
         A/V 对齐多缓冲视频(实测 ~200ms)并在手机上多占 CPU —— 而客户端
         默认就是静音,等于一直在白付这笔开销。轨道留在 PC 里(不动按钮
         语义、不重协商),解除静音时再并回去,立即生效。 */
      _audioTrack=e.track;
      if(_audioOn){try{_avStream.addTrack(e.track);}catch(_){}}
      /* 音频接收端也要设缓冲目标(以前这里直接 return,音频侧从没设过,
         于是按 Chrome 默认自由生长并拖住视频,见 _JB_AUDIO_MS 处的实测)。 */
      var _ra=pc.getReceivers().find(function(r){
        return r.track&&r.track.kind==='audio';});
      if(_ra){
        _jbRecvA=_ra;
        try{if('jitterBufferTarget' in _ra)_ra.jitterBufferTarget=_JB_AUDIO_MS;}catch(_){}
        try{if('playoutDelayHint' in _ra)_ra.playoutDelayHint=_JB_AUDIO_MS/1000;}catch(_){}
      }
      _audioFound=true;_sndBtn();
      return;
    }
    var tv=_gm?document.getElementById('gv'):document.getElementById('vd');
    if(_gm){document.getElementById('gc').style.display='none';}
    else{cv.style.display='none';}
    tv.style.display='block';
    // 抖动缓冲由 _jbAuto 自动调参(0~80ms,见下),初始压到 0 换最低延迟。
    var _recv=pc.getReceivers().find(function(r){return r.track&&r.track.kind==='video';});
    _jbRecv=_recv||null;_jbTarget=0;_jbClean=0;_jbPrev={freeze:0,nack:0};
    _jbApply();
    _vidGen++;                     /* 新流:让在途的 play() 结果作废 */
    tv.muted=!_audioOn;            /* 保持用户已选的静音状态 */
    tv.srcObject=_avStream;
    _playVid(tv);
    _rtpMode=true;
    _startRtpStats(pc);
    // RTP 模式画面由 <video> 直接渲染,不经过 VideoDecoder,帧率/延迟
    // 显示逻辑(decoder.output)不触发。用 requestVideoFrameCallback 统计
    // 实际渲染帧率填充标题栏;延迟无帧序号可测,只显示帧率。
    if(tv.requestVideoFrameCallback){
      var _rfStart=0,_rfCount=0,_rfLast=0;
      var _rfTick=function(now){
        if(!_rtpMode)return;
        _lastFrameAt=now;  // 帧停滞看门狗也覆盖 RTP 模式(否则误判无帧频繁重连)
        if(!_rfStart){_rfStart=now;}
        _rfCount++;
        if(now-_rfLast>500){
          _rfLast=now;
          var fps=_rfCount*1000/(now-_rfStart);
          _rfStart=now;_rfCount=0;
          st.textContent='LIVE '+String(Math.min(120,Math.round(fps))).padStart(3,'0')+'fps';st.style.color='';
        }
        tv.requestVideoFrameCallback(_rfTick);
      };
      tv.requestVideoFrameCallback(_rfTick);
    }
    // RTP 模式若未收到 screen_config(兜底),从视频实际尺寸初始化坐标映射
    // (_rw/_rh 客户端显示尺寸,_rwr/_rhr 远程桌面原生分辨率)。
    tv.addEventListener('loadedmetadata',function(){
      if(!_rw&&!_rh){_rw=tv.videoWidth;_rh=tv.videoHeight;}
      if(!_rwr&&!_rhr){_rwr=tv.videoWidth;_rhr=tv.videoHeight;}
    });
  };
  pc.onicecandidate=function(e){
    if(e.candidate&&wsV&&wsV.readyState===WebSocket.OPEN){
      wsV.send(JSON.stringify({type:'rtp_ice',candidate:{candidate:e.candidate.candidate,sdpMid:e.candidate.sdpMid||'0',sdpMLineIndex:e.candidate.sdpMLineIndex||0}}));
    }
  };
  // 手机后台挂起时 WebRTC UDP 连接会进入 disconnected/failed,恢复前台后
  // 不会自动恢复(需重新协商)。检测到就关掉视频通道让 cnV 重连。
  // disconnected 在短时网络抖动也会出现,延时确认持续失联再重连。
  pc.oniceconnectionstatechange=function(){
    var s=pc.iceConnectionState;
    if(s==='failed'||s==='closed'){
      if(!_rtpMode)return;
      if(wsV&&wsV.readyState===WebSocket.OPEN)wsV.close();
    }else if(s==='disconnected'){
      if(!_rtpMode)return;
      if(_rtpTimer){clearTimeout(_rtpTimer);}
      _rtpTimer=setTimeout(function(){_rtpTimer=null;if(_rtpMode&&wsV&&wsV.readyState===WebSocket.OPEN)wsV.close();},3000);
    }else if(s==='connected'||s==='completed'){
      if(_rtpTimer){clearTimeout(_rtpTimer);_rtpTimer=null;}
    }
  };
  pc.setRemoteDescription(new RTCSessionDescription({sdp:m.sdp,type:m.sdp_type})).then(function(){
    return pc.createAnswer();
  }).then(function(a){
    // 候选已通过 onicecandidate→rtp_ice 逐条推给服务端(trickle ICE),
    // 这里立即发 answer 即可,不必等 gathering 完成(那会白等数秒)。
    return pc.setLocalDescription(a);
  }).then(function(){
    if(wsV&&wsV.readyState===WebSocket.OPEN){
      wsV.send(JSON.stringify({type:'rtp_answer',sdp:pc.localDescription.sdp,sdp_type:pc.localDescription.type}));
    }
  }).catch(function(ex){console.error('RTP answer:',ex);_rtpFail();});
}
function _rtpFail(){
  _teardownRtp();
  _rtpMode=false;
  /* 只回退不粘死:不再改 _prefManual/RTPPref——一次失败就锁死 TCP 会让
     本会话怎么点都回不到 UDP,只有刷新页面(内存偏好重置)才行。现在失败
     后自动选择、下次点击或重连都仍可重试 UDP。 */
  if(_rtpRetry++<1){
    // 兜底切回 TCP 串流
    if(wsV&&wsV.readyState===WebSocket.OPEN){
      wsV.send(JSON.stringify({type:'set_mode',screen:true}));
    }
  }
  setTimeout(function(){_rtpRetry=0;},30000);
}

/* 端到端延迟:服务端每帧带一个单调帧序号。客户端只用本地时钟
   performance.now()——不比较两端时钟。期望帧间隔用实测到达间隔的
   EMA 自适应(不用配置 fps),这样实际帧率低于配置时不会积累出
   虚假延迟;真正的停顿(丢包/卡顿/渲染积压)仍会让延迟冲高触发重连。 */
var _latS0=-1,_latA0=0,_latLast=-1;
var _latIv=1000/30;
var _latArrPrev=0;
var _lat=0,_latOver=null,_latLastRefresh=0;
/* _lat 的重锚定次数(序号空洞造成的重新对表 + 负向漂移保护)。这是判断"看到的延迟
   是真实排队、还是估算器自己漂了"的关键:重锚频繁就说明这个数不可信。
   _lat 原来只喂给重连/码率分档、从不显示,所以这一点一直没法判断。 */
var _latReanchor=0;
/* 自本会话首帧以来,播放层累积落后了多少 ms(由 rVFC 的 mediaTime 推出)。
   绝对值无意义(媒体时间轴起点未知),**变化量才是"画面落后了多少"** ——
   这正是"刷新后正常、随后逐步变大"那个量的直接读数。见 _rfTick。
   负值 = 尚未量到(浏览器没给 mediaTime)。 */
var _plNow=-1,_plBase=null,_plDrop=0;
/* 采样"当前播放位置"并换算成播放滞后。
   最初用的是 rVFC 的 metadata.mediaTime,但实测(2026-10-10)Chrome 对这条
   live MediaStream **两分钟里一次都没给过**,读数恒为 '-'。改用
   video.currentTime —— 它同样是媒体时间轴上的"当前播放点",所以
       lag = performance.now()/1000 - currentTime
   的绝对值仍然无意义(起点未知),但**自本会话首个采样以来的变化量**就是
   "画面又落后了多少"。每 tick(500ms)采一次即可,不需要逐帧。
   同时记 droppedVideoFrames:它可以分辨两种机制 ——
       Chrome 靠丢帧追上(丢帧数增长) vs 靠延后显示(丢帧 0 而滞后增长)。 */
function _plSample(){
  if(!_rtpMode)return;
  var el=_gm?document.getElementById('gv'):document.getElementById('vd');
  if(!el)return;
  try{var q=el.getVideoPlaybackQuality&&el.getVideoPlaybackQuality();
      if(q)_plDrop=q.droppedVideoFrames||0;}catch(_){}
  var ct=el.currentTime;
  if(!(ct>0))return;                      /* 还没开始播 */
  var v=performance.now()/1000-ct;
  if(_plBase===null){_plBase=v;return;}
  _plNow=Math.round((v-_plBase)*1000);
}
/* 音频 inbound-rtp 上一次的累计值+时刻,用来算"每秒收/出"速率。 */
var _aPrev={t:0,rx:null,em:null};
var _LAT_LIMIT=1500;      // 触发阈值 ms
var _LAT_COOLDOWN=60000;  // 一次刷新后的冷却 ms
var _latReconCnt=0;       // 连续快速触发计数(风暴抑制)
function _latReset(){
  _latS0=-1;_latA0=0;_latLast=-1;
  _lat=0;_latOver=null;_lastFrameAt=performance.now();
}
function _latMeasure(seq){
  var now=performance.now();
  if(_latS0<0){_latS0=seq;_latA0=now;_latLast=seq;_lat=0;_latOver=null;return;}
  if(seq!==_latLast+1){_latReanchor++;_latS0=seq;_latA0=now;_latLast=seq;_lat=0;_latOver=null;return;}
  _latLast=seq;
  _lat=now-(_latA0+(seq-_latS0)*_latIv);
  /* _lat = 实际到达 - 按 _latIv 外推的预期,而 _latIv 是到达间隔的 EMA:
     一旦它偏大(经历过低帧率/突发期),_lat 会单向漂成负数且永不自愈(实测到过
     负几万),让依赖它的重连与分档形同虚设。离谱值直接重新锚定,截住漂移。 */
  if(_lat<-1000){_latReanchor++;_latS0=seq;_latA0=now;_latLast=seq;_lat=0;_latOver=null;return;}
  if(_lat>_LAT_LIMIT){
    if(_latOver===null)_latOver=now;
    else if(now-_latOver>500&&now-_latLastRefresh>_LAT_COOLDOWN){
      /* 风暴抑制:接收端/CPU 瞬时停顿会让延迟冲高,重连治不了它,反而
         每次冷却到期就再断一次(用户看到"卡到自动刷新")。连续触发时
         指数退避:第 2 次 3 分钟冷却,第 3 次 10 分钟,>=4 次不再自动
         重连(画面最多延迟累积,不再打断)。正常网络不足 1.5s 时计数
         每 10 分钟自然衰减归零。 */
      _latReconCnt++;
      if(_latReconCnt>=4){
        _latOver=null;
        return;
      }
      var cd=_latReconCnt===1?_LAT_COOLDOWN:(_latReconCnt===2?180000:600000);
      _latLastRefresh=now+_LAT_COOLDOWN-cd; /* 借用冷却比较,等效延长 */
      _latCooldownUntil=now+cd;
      _latOver=null;_latReset();
      if(wsV)wsV.close();
    }
  }else{
    _latOver=null;
    if(_lat<200&&now-(_latCooldownUntil||0)>600000)_latReconCnt=0;
  }
}
var _latCooldownUntil=0;
/* ── 网络/播放质量显示:RTT(cmd 通道 ping/pong)+ 丢帧率(本端没播出来的帧)。
   WebSocket 跑在 TCP 上,链路丢包会被重传消化成"晚到"而不是"缺帧",
   所以按帧序号空洞统计的丢包率恒为 0,没有信息量。这里改为统计真正
   未播出的帧:解码器积压时跳过的 delta + 渲染队列满时丢掉的旧帧。
   该数值取代原先 LIVE 状态栏的延迟值;延迟测量本身保留,仍用于重连与码率分档。
   所有显示值都按 30 秒窗口取平均(速率类 = 窗口内总和 / 窗口帧数),进度显示为
   [n/30s],读满 30 秒即为完整的 30 秒平均。 ── */
var _WIN=30,_winT0=performance.now(),_winSec=0;
/* 标题栏"详细统计"开关(可持久化,默认关):
   关 = 日常,只显示 R(最近一次 ping 的 RTT),与传输方式无关;
   开 = 按传输方式显示各自的统计,口径为 30 秒窗口平均(带 [n/30s] 进度):
        TCP → 解码/上屏/缓冲/丢帧(解·渲)/绘制;
        UDP(RTP) → 丢包%/抖动缓冲/解码丢帧/卡顿次数/NACK(来自 pc.getStats())。
   切换:设置卡片里的"详细统计"按钮,或直接点标题栏上的那串数字。 */
var _DIAG=false;
/* 键名带 _v2:做一次性重置 —— 早前版本 _DIAG 曾写死 true,旧键可能残留 '1',
   换键后默认回到"关";之后的开/关照常持久化。 */
try{_DIAG=localStorage.getItem('deskbeam_diag_v2')==='1';}catch(_){}
function _diagToggle(){
  _DIAG=!_DIAG;
  try{localStorage.setItem('deskbeam_diag_v2',_DIAG?'1':'0');}catch(_){}
  _netText();
}
/* RTP 抖动缓冲自动调参(旧"最小/自适应"手动开关已移除):jitterBufferTarget 在
   0~80ms 间按卡顿信号自动升降 —— 出现卡顿/NACK 就按实测抖动抬缓冲(2×jitter,
   保底 30ms),连续 12s 干净则逐档降回 0(稳态零额外延迟)。运行期直接改
   jitterBufferTarget 即生效(标准允许),不需要重新协商。 */
/* 注意:这个目标值**对 Chrome 的视频抖动缓冲没有杠杆作用**(2026-10-10 实测,
   见 AGENTS.md):同一个会话里把下限从 0 调到 40~55ms,`视缓` 反而 158->197ms。
   保留它是因为网络真有抖动时"按 NACK/卡顿抬缓冲"仍然有意义,但**不要**把
   "降低视频延迟"寄托在它身上 —— 平峰期的实际驻留由 Chrome 自己决定。 */
var _jbTarget=0,_jbClean=0,_jbRecv=null,_jbPrev={freeze:0,nack:0};
/* 音频接收端的缓冲目标:**固定值,不参与 _jbAuto** —— 那个调节器是按视频的
   NACK/卡顿信号设计的。实测音频 RTP 到达抖动只有 8ms、一包 20ms,60ms 有
   3 倍余量。实测数据(2026-10-10):音缓 251ms > 视缓 153ms,而播放器要让
   音视频对齐 —— 音频缓冲高了会把视频一起拖住(表现是"操作不跟手")。
   声音若出现断续就把这个值调大;若还嫌延迟大可以试 40。 */
/* 实测:设 60ms 时 `音缓` 仍在 173-213ms(高出 110-150ms)。压到 0 是判别实验:
     音缓 明显下降且 视缓 跟着降 -> 超出的部分由我们的目标决定,0 就是最优,皆大欢喜
     音缓 仍 ~200ms             -> 那是**手机音频输出设备**的缓冲,我们控制不了;
                                    唯一的杠杆是"干脆不发这条音轨"(见 AGENTS.md 实测)
   历史上 Tailscale 一直是 UDP,而加音轨之前画面跟手、之后滞后 ~200ms,所以
   音轨(Chrome 的 A/V 对齐)就是这段延迟的来源。若声音出现断续就把值调回 60/100。 */
var _jbRecvA=null,_JB_AUDIO_MS=0;
function _jbApply(){
  if(!_jbRecv)return;
  try{if('jitterBufferTarget' in _jbRecv)_jbRecv.jitterBufferTarget=_jbTarget;}catch(_){}
  try{if('playoutDelayHint' in _jbRecv)_jbRecv.playoutDelayHint=_jbTarget/1000;}catch(_){}
}
function _jbAuto(s){
  var jitMs=(s.jitter||0)*1000;
  var f=s.freezeCount||0,n=s.nackCount||0;
  var dF=f-_jbPrev.freeze,dN=n-_jbPrev.nack;
  _jbPrev={freeze:f,nack:n};
  var t=_jbTarget;
  if(dF>0||dN>0){
    _jbClean=0;
    t=Math.min(80,Math.max(t+30,Math.round(jitMs*2),30));
  }else if(t>0&&++_jbClean>=6){   /* 每 tick 2s → 12s 干净降一档 */
    _jbClean=3;                   /* 再过 6s 继续降,直到 0 */
    t=Math.max(0,t-25);
  }
  if(t!==_jbTarget){_jbTarget=t;_jbApply();}
}
var _rtt=0,_rttNow=0,_bufMs=0,_adMs=0,_decMs=0,_drawMs=0,_pDrop=0,_pDd=0,_pDr=0;
var _rxNow=0,_rxK=0;   /* 下行速率:TCP 每秒统计收到的视频帧字节 → _rxK(KB/s) */
/* _rtt = 30 秒窗口平均 RTT(详细统计用,与其它窗口值口径一致);
   _rttNow = 最近一次 ping 的 RTT 短 EMA(日常模式用)。 */
var _aRttS=0,_aRttN=0,_aFrame=0,_aDd=0,_aDr=0,_aBufS=0,_aBufN=0,_aDrawS=0,_aDrawN=0,_aAdS=0,_aAdN=0,_aDecS=0,_aDecN=0;
var _stEl=document.getElementById('st'),_netSpan=null;
if(_stEl&&_stEl.parentNode){
  _netSpan=document.createElement('span');
  _netSpan.style.cssText='margin-left:6px;color:var(--dim);font-size:10px';
  _netSpan.style.cursor='pointer';
  _netSpan.title='点击切换详细统计';
  _netSpan.addEventListener('click',_diagToggle);
  _stEl.parentNode.insertBefore(_netSpan,_stEl.nextSibling);
}
function _netText(){
  if(!_netSpan)return;
  if(_aRttN)_rtt=_aRttS/_aRttN;
  if(_aBufN)_bufMs=(_aBufS/_aBufN)*_latIv;
  if(_aAdN)_adMs=_aAdS/_aAdN;
  if(_aDecN)_decMs=_aDecS/_aDecN;
  if(_aDrawN)_drawMs=_aDrawS/_aDrawN;
  if(_aFrame){_pDrop=(_aDd+_aDr)*100/_aFrame;_pDd=_aDd*100/_aFrame;_pDr=_aDr*100/_aFrame;}
  var _rt=_DIAG
    ?(_rtt>0?Math.round(_rtt)+'ms':'-')
    :(_rttNow>0?Math.round(_rttNow)+'ms':'-');
  if(!_DIAG){
    /* 日常:只显示 R(最近一次 ping 的 RTT)。关闭时连丢包/丢帧一并隐藏 */
    _netSpan.textContent='R'+_rt;
    return;
  }
  var _w='['+Math.floor(Math.min(_WIN,_winSec))+'/'+_WIN+'s] ';
  if(_rtpMode){
    /* UDP(RTP):浏览器原生接收统计(pc.getStats(),每 2s 采样)。
       标签务必名副其实 —— 原来那个数标成"抖动"其实是**视频抖动缓冲的驻留时间**
       (jitterBufferDelay/EmittedCount),和网络抖动相差甚远,曾直接导致误判
       (以为局域网抖动 200ms,其实是我们自己的缓冲加了 200ms 延迟),所以改叫"视缓"。 */
    _netSpan.textContent=_w+'R'+_rt+
      ' 延迟'+Math.round(_lat)+'ms'+          /* 端到端视频延迟估计(以前只做重连判据) */
      ' 播放滞后'+(_plNow<0?'-':_plNow)+'ms'+  /* 自首帧以来播放层累积落后(本会话) */
      ' 丢帧'+_plDrop+                          /* getVideoPlaybackQuality().droppedVideoFrames */
      ' 重锚'+_latReanchor+                    /* 本窗口内延迟估计被重置的次数 */
      ' 视缓'+Math.round(_rtp.jb)+'ms'+        /* 视频抖动缓冲驻留 */
      ' 网抖'+Math.round(_rtp.jit||0)+'ms'+    /* Chrome 报的到达间隔抖动 */
      ' 缓目标'+(_rtp.jbt!=null?_rtp.jbt:'-')+'ms'+  /* 我们的 jitterBufferTarget */
      ' 音缓'+(_rtp.ab>=0?Math.round(_rtp.ab)+'ms':'-')+  /* 音频抖动缓冲驻留 */
      ' 音收'+(_rtp.arx>=0?_rtp.arx:'-')+'/s'+             /* 音频包到达速率(健康 50/s) */
      ' 音出'+(_rtp.aem>=0?_rtp.aem:'-')+'/s'+             /* 音频包播出版速率(健康 50/s) */
      ' 丢包'+_rtp.loss.toFixed(1)+'%'+
      ' 解丢'+_rtp.dropped+
      ' 卡顿'+_rtp.freeze+
      ' NACK'+_rtp.nack+
      ' ↓'+Math.round(_rtp.rx||0)+'K/s';
    return;
  }
  /* TCP:WebCodecs 解码 + canvas 绘制链表 */
  _netSpan.textContent=_w+'R'+_rt+
    ' 解码'+Math.round(_decMs)+'ms'+
    ' 上屏'+Math.round(_adMs)+'ms'+
    ' 缓冲'+Math.round(_bufMs)+'ms'+
    ' 丢帧'+_pDrop.toFixed(1)+'%(解'+_pDd.toFixed(1)+' 渲'+_pDr.toFixed(1)+')'+
    ' 绘制'+_drawMs.toFixed(1)+'ms'+
    ' ↓'+Math.round(_rxK)+'K/s';
}
setInterval(function(){
  _winSec=(performance.now()-_winT0)/1000;
  _rxK=_rxNow/1024;_rxNow=0;
  _plSample();
  _netText();
  if(_winSec>=_WIN){
    _winT0=performance.now();_winSec=0;
    _aRttS=0;_aRttN=0;_aFrame=0;_aDd=0;_aDr=0;
    _latReanchor=0;  /* 与 [n/30s] 前缀口径一致:本窗口内的重锚次数 */
    _aBufS=0;_aBufN=0;_aDrawS=0;_aDrawN=0;_aAdS=0;_aAdN=0;_aDecS=0;_aDecN=0;
  }
},1000);
setInterval(function(){
  if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'ping',t:performance.now()}));
},2000);
/* 帧停滞看门狗:捕获源(如 UAC 安全桌面、锁屏)短暂失效时帧会完全停止,
   延迟测量因无新帧到达而永远无法触发重连。这里每秒检查:屏幕模式下视频
   连接正常但已 5 秒无帧,就重连一次(每 10 秒最多一次,无永久抑制——
   捕获源失效是瞬时故障,重连才能恢复)。 */
var _lastFrameAt=0,_stallCooldownUntil=0,_stallStage=0,_mediaDeadline=0;
/* 协商/重建的耐心必须**大于服务端最坏启动预算**,否则服务端还在冷启动、客户端已经
   放弃,现象就是"进不去画面,必须切 REMOTE 再切 SCREEN 才有一轮干净协商"。
   服务端账(RTP 路径,server.py):等非 RTP sender 让出 ≤2.0s + _rtp_start_streamer
   2 次尝试 ×(first_frame 2.0s + 间隔 1.5s)=7.0s + 建 transport/create_offer ~1.0s
   ≈ **10s**(息屏或静止桌面时第一次 first_frame 必然超时,所以就是走这条最坏路径)。
   原来是 8000ms —— 比服务端预算短 2s,天生对不上。 */
var _NEGO_MS=13000;
/* 安全桌面(UAC / 锁屏)提示:服务端看到输入桌面切成 Winlogon 就下发
   screen_paused——此时采集根本不可能成功,重连也是白连,所以暂停期间直接
   禁用下面的停滞看门狗,画面停在最后一帧并叠一行文字说明"不是真卡"。 */
var _paused=false;
function _setPaused(on){
  if(_paused===on)return;
  _paused=on;
  var el=document.getElementById('pmsg');
  if(!el){
    /* 页面可能是改动前的缓存(没有这个节点):按需创建,别让提示静默消失。 */
    var ta=document.getElementById('ta');
    if(ta){el=document.createElement('div');el.id='pmsg';el.className='screen-msg';ta.appendChild(el);}
  }
  if(el)el.className='screen-msg'+(on?' on':'');
  if(on)_lastFrameAt=performance.now();
}
/* 媒体路径重建:连接与输入通道全部保留,只把视频管线重来一遍。
   画面停了但 socket 还活着时,重连整个会话代价过大(重新协商 + 重新认证 +
   重选传输),还会打断用户正在进行的输入。 */
function _recoverMedia(){
  try{
    if(_rtpMode){
      _teardownRtp();                    /* 关掉旧 PeerConnection,ws 不动 */
      _rtpMode=false;
    }else if(decoder){
      try{decoder.close();}catch(_){}
      decoder=null;_arrQ=[];
    }
    var fmt=_sendScreenMode();           /* 让服务端重出 offer / 重推流 */
    if(fmt==='rtp'){
      if(_rtpTimer){clearTimeout(_rtpTimer);}
      _rtpTimer=setTimeout(function(){_rtpTimer=null;if(!_rtpMode)_rtpFail();},_NEGO_MS);
    }
  }catch(e){console.error('recoverMedia:',e);}
}
function _frameStall(){
  if(_paused)return;
  if(!_so||!(wsV&&wsV.readyState===WebSocket.OPEN)||!_lastFrameAt)return;
  var now=performance.now();
  if(now-_lastFrameAt<=5000){_stallStage=0;return;}   /* 有帧:阶段复位 */
  if(now<_mediaDeadline)return;   /* 正在协商/重建媒体:这期间无帧是正常的 */
  if(now<=_stallCooldownUntil)return;
  _stallCooldownUntil=now+10000;
  _lastFrameAt=now;  /* re-arm: 若仍无帧,10s 后再进下一阶段 */
  if(_stallStage===0){
    /* 第一阶段:只重建媒体管线。5s 无帧而 socket 健康,绝大多数是解码/渲染
       或单条媒体通道的问题,不是会话故障——直接 ws.close() 要白白付一次
       完整重连的代价。 */
    _stallStage=1;
    console.warn('frame stall: rebuilding media pipeline (session kept)');
    _recoverMedia();
    return;
  }
  /* 第二阶段:媒体重建也没救回来,才判定为会话级故障,重连。 */
  _stallStage=2;
  console.warn('frame stall: media rebuild failed, reconnecting session');
  if(wsV)wsV.close();
}
setInterval(_frameStall,1000);
/* ── 码率分档:判据用 RTT,不再用 _lat。_lat 靠帧间隔外推、会漂移,拿它当
   拥塞信号不可靠;RTT 由 ping/pong 直接测量,而"比历史最小 RTT 高出多少"
   是标准的排队拥塞指标,并能随链路自动标定(_rttBase 取历史最小值)。
   三档:0 全速 / 1 中度 / 2 严重。升档需持续 5s(排除一次性抖动),降档每档
   20s(避免来回切)。阈值可按标题栏实测的 RTT 再调。 ── */
var _bitrateTier=0,_tierSince=0,_tierHighAt=0,_rttBase=0;
function _bitrateAdapt(){
  if(!_rttNow)return;
  var now=performance.now();
  if(!_rttBase||_rttNow<_rttBase)_rttBase=_rttNow;
  var over=_rttNow-_rttBase;          /* 相对最优链路的额外排队(ms) */
  if(over>80){
    if(!_tierHighAt)_tierHighAt=now;
    if(_bitrateTier<2&&over>200&&now-_tierHighAt>5000){
      _bitrateTier=2;_tierHighAt=0;_tierSince=now;
      if(wsV&&wsV.readyState===WebSocket.OPEN)wsV.send(JSON.stringify({type:'bitrate_adapt',tier:_bitrateTier}));
    }else if(_bitrateTier<1&&now-_tierHighAt>5000){
      _bitrateTier=1;_tierHighAt=0;_tierSince=now;
      if(wsV&&wsV.readyState===WebSocket.OPEN)wsV.send(JSON.stringify({type:'bitrate_adapt',tier:_bitrateTier}));
    }
  }else{
    _tierHighAt=0;
    if(over<30&&_bitrateTier>0&&now-_tierSince>20000){
      _bitrateTier--;_tierSince=now;
      if(wsV&&wsV.readyState===WebSocket.OPEN)wsV.send(JSON.stringify({type:'bitrate_adapt',tier:_bitrateTier}));
    }
  }
}

/* ── 画面缩放/平移：只用 transform，不再切换排版 ──
   以前捏合靠加/去 body.full 上的 .pinching 类，在「flex 居中 + object-fit:contain
   留黑边」与「block 左上 + height:auto 铺满」两套布局间硬切，再改 canvas 的
   width%。那是两次「排版」跳变，而且基线用 cv.style.width 反推倍率——Fit 档它是
   空串、Full 档元素宽≠画面实际宽（有黑边），所以第一次捏合必然突跳。
   现在布局恒定，缩放=translate+scale（transform-origin 固定 0 0），锚点就是双指
   中点，数学上不可能跳变；顺带每次 touchmove 不再触发 layout（transform 走合成器）。
   平移不做任何夹取（用户要求两档都能把画面推到屏外，方便让开键盘）；推丢后
   双指反向拖回来即可，缩放下限仍是 Fit 0.5 / Full 1。 */
var _k=1,_tx=0,_ty=0,_k0=1,_tx0=0,_ty0=0,_ox=0,_oy=0,_cx0=0,_cy0=0,_aP=0,_bP=0;
function _zMinK(){return document.body.classList.contains('full')?1:0.5;}
/* 当前实际显示画面的元素:RTP(UDP)模式是 <video id=vd>(canvas 已隐藏),
   GYRO 模式是 gv,TCP 模式是 canvas。缩放/命中必须以它为准,否则 RTP 模式下
   双指缩放与点击坐标映射会作用到隐藏的 canvas 上而失效。 */
function _vidEl(){
  if(_rtpMode||cv.style.display==='none')return document.getElementById(_gm?'gv':'vd');
  if(_gm)return document.getElementById('gv');
  return cv;
}
function _zApply(){
  var el=_vidEl();
  el.style.transformOrigin='0 0';
  el.style.transform=(_k===1&&!_tx&&!_ty)?'':'translate('+_tx+'px,'+_ty+'px) scale('+_k+')';
}
function _zReset(){_k=1;_tx=0;_ty=0;_zApply();}
var _tt=null,_lt=0;
/* 双指判定必须看 e.touches（屏幕上所有触点），不能用 e.targetTouches——后者只统计
   与事件 target 同一元素的触点：一根手指落在 canvas 上、另一根落在 #ta 的空白处时
   两次 touchstart 各只看到 1 个，于是被当成单指拖动鼠标。改为"屏幕上有两个触点，
   且都落在触控区内（canvas 或它的空白边）"，手指在其它控件（快捷键/输入框）上则不参与。 */
function _twoInTa(e){
  if(e.touches.length!==2)return false;
  for(var i=0;i<2;i++){
    var tg=e.touches[i].target;
    if(!tg||!ta.contains(tg))return false;
  }
  return true;
}
ta.addEventListener('touchstart',function(e){
  if(_tt){clearTimeout(_tt);_tt=null;}
  _pinchEnded=false;
  if(_pinching)return;                       /* 手势进行中：忽略新增触点，避免重算锚点 */
  if(_twoInTa(e)&&_so){
    _pinching=true;
    var a=e.touches[0],b=e.touches[1];
    _ps=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
    _cx0=(a.clientX+b.clientX)/2;_cy0=(a.clientY+b.clientY)/2;
    _k0=_k;_tx0=_tx;_ty0=_ty;
    var r=_vidEl().getBoundingClientRect();
    _ox=r.left-_tx;_oy=r.top-_ty;              /* 本次手势内不变 */
    _aP=(_cx0-_ox-_tx0)/_k0;_bP=(_cy0-_oy-_ty0)/_k0;  /* 起始时压在手指下的内容点 */
    return;
  }
  var t=e.touches[0];_px=t.clientX;_py=t.clientY;_mv=false;if(_dm)sendCmd({type:'mouse_down'});
},{passive:false});
ta.addEventListener('touchmove',function(e){
  e.preventDefault();
  if(_pinching&&e.touches.length===2){
    var a=e.touches[0],b=e.touches[1];
    var ds=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
    var cx=(a.clientX+b.clientX)/2,cy=(a.clientY+b.clientY)/2;
    var nk=Math.max(_zMinK(),Math.min(10,_k0*ds/_ps));
    _k=nk;
    /* 让 _aP/_bP 那个内容点始终待在手指中点下：缩放与拖动由这一个式子同时给出。
       不夹取：画面可以推到屏外（用户要求），推丢后反向拖回来。 */
    _tx=(cx-_ox)-_aP*nk;
    _ty=(cy-_oy)-_bP*nk;
    _zApply();
    return;
  }
  var t=e.touches[0],dx=Math.round((t.clientX-_px)*4),dy=Math.round((t.clientY-_py)*4);
  if(Math.abs(dx)<2&&Math.abs(dy)<2)return;_px=t.clientX;_py=t.clientY;_mv=true;
  _mqAcc(dx,dy);
},{passive:false});
ta.addEventListener('touchend',function(e){
  if(_pinching){
    if(e.touches.length<2){
      _pinching=false;_pinchEnded=true;
      if(e.touches.length===1){var _t=e.touches[0];_px=_t.clientX;_py=_t.clientY;}
      if(Math.abs(_k-1)<0.005&&Math.abs(_tx)<0.5&&Math.abs(_ty)<0.5)_zReset();
    }
    return;
  }
  if(_pinchEnded){_pinchEnded=false;return;}
  _te=Date.now();
  if(_dm)sendCmd({type:'mouse_up'});
  else if(!_mv){
    _tt=setTimeout(function(){
      _tt=null;
      if(Date.now()-_lt<500){sendCmd({type:'mouse_double_click'});_lt=0;return;}
      if(document.body.classList.contains('full')){sendCmd({type:'mouse_click'});}
      else if(_rw&&_rh&&_vidEl().style.display!=='none'&&_vidEl().getBoundingClientRect){
        var _ve=_vidEl(),t=e.changedTouches[0],rect=_ve.getBoundingClientRect(),ix=rect.left,iy=rect.top,iw=rect.width,ih=rect.height;
        if(t.clientX>=ix&&t.clientX<=ix+iw&&t.clientY>=iy&&t.clientY<=iy+ih)
          sendCmd({type:'mouse_click_at',x:Math.round((t.clientX-ix)/iw*_rwr),y:Math.round((t.clientY-iy)/ih*_rhr)});
        else sendCmd({type:'mouse_click'});
      }else sendCmd({type:'mouse_click'});
      _lt=Date.now();
    },20);
  }
},{passive:false});
ta.addEventListener('mousemove',function(e){var dx=e.movementX||0,dy=e.movementY||0;if(_gy)return;if(_mdP&&(Math.abs(e.clientX-_mdX)>5||Math.abs(e.clientY-_mdY)>5))_mdP=false;if(!(e.buttons&1))return;if(!dx&&!dy)return;_mqAcc(dx*4,dy*4);});
ta.addEventListener('mousedown',function(e){if(e.button!==0)return;ta.focus();_mdP=true;_mdX=e.clientX;_mdY=e.clientY;});
ta.addEventListener('mouseup',function(e){var wasClick=_mdP&&e.button===0;_mdP=false;if(wasClick&&Date.now()-_te>300){sendCmd({type:'mouse_down'});sendCmd({type:'mouse_up'});}});
function sendCmd(obj){
  var s=JSON.stringify(obj);
  if(_rtcDc&&_rtcDc.readyState==='open')_rtcDc.send(s);
  else if(ws&&ws.readyState===WebSocket.OPEN)ws.send(s);
  if(_rtcDc&&(_rtcDc.readyState==='closing'||_rtcDc.readyState==='closed'))_rtcDc=null;
}
var _gy=false,_gsX=20,_gsY=15,_gyLast=0,_gm=false,_gPrevSo=false,_gAcc=true;
var _gShSt=false,_gShRel=null;
function _gSetAcc(on){
  _gAcc=on;
  var b=document.getElementById('ggb');
  if(b){if(on)b.classList.add('on');else b.classList.remove('on');}
  if(_gm)sendCmd({type:'set_gyro',on:!on});
}
function _gyStart(){
  _gy=true;
  sendCmd({type:'set_gyro',on:!_gAcc});
  var s=document.getElementById('gyroStatus');if(s){s.textContent='GYRO';s.classList.remove('off');}
}
function _gyStop(){
  _gy=false;
  sendCmd({type:'set_gyro',on:false});
  var s=document.getElementById('gyroStatus');if(s){s.textContent='GYRO';s.classList.add('off');}
}
function _gyToggleSensor(){
  if(_gy){_gyStop();}else{_gyStart();}
}
function _gyRequest(cb){
  var req=window.DeviceMotionEvent&&window.DeviceMotionEvent.requestPermission;
  if(req){req().then(function(r){if(r==='granted')cb();else{alert('陀螺仪权限被拒绝');}}).catch(function(){});}
  else if(window.DeviceMotionEvent){cb();}
  else{alert('此设备不支持陀螺仪');}
}
/* 把当前 RTP 的合成流搬到指定的 <video> 上,并隐藏另一个。返回是否搬成功。

   **进出 GYRO 靠这个搬画面,不要靠重新协商。** `pc.ontrack` 是按当时的 `_gm` 决定
   把 `_avStream` 挂到 `vd` 还是 `gv` 的,所以原先进出 GYRO 各调一次 `sm()`
   (= 发 `set_mode{format:'rtp'}` -> 服务端关掉现有 RTP 传输并重跑冷启动 ~5-10s)。
   两次协商会撞在一起:先到的 offer 可能挂在一条服务端随后就关掉的通道上,PC 停在
   new/checking(**不会触发 failed**,没有任何东西能救它)——表现就是"从 GYRO 退回
   SCREEN 大约率没画面,必须刷新浏览器"。同一条 MediaStream 可以直接改挂到另一个
   <video>,所以搬流即可,零协商、零冷启动、零竞态。 */
function _attachStream(which){
  if(!_rtpMode||!_avStream)return false;
  var vd=document.getElementById('vd'),gv=document.getElementById('gv');
  var tgt=(which==='gv')?gv:vd, other=(which==='gv')?vd:gv;
  if(!tgt)return false;
  try{
    if(other&&other.srcObject===_avStream)other.srcObject=null;
    tgt.srcObject=_avStream;
    tgt.style.display='block';
    if(other)other.style.display='none';
    _vidGen++;                 /* 换源:让在途的 play() 结果作废 */
    tgt.muted=!_audioOn;       /* 保持用户已选的静音状态 */
    _playVid(tgt);
    return true;
  }catch(_){return false;}
}
function _gyEnter(){
  _gyRequest(function(){
    _gm=true;_gPrevSo=_so;
    if(document.body.classList.contains('full'))zs(Z.length-2);
    if(_dm){_dm=false;sendCmd({type:'mouse_up'});}
    document.getElementById('gyroPage').classList.add('on');
    var ggb=document.getElementById('ggb');
    if(ggb){if(_gAcc)ggb.classList.add('on');else ggb.classList.remove('on');}
    _gyStart();
    var cb=document.getElementById('gcb');
    /* 画面搬到 GYRO 的 <video>。屏幕本来就是开的、流也在 -> 只搬流,
       不要协商(那会各触发一次 RTP 冷启动并互相撞车,见 _attachStream)。 */
    if(!_so)sm(true);
    else if(!_attachStream('gv'))sm(true);
    if(_so){cb.classList.add('on');}else{cb.classList.remove('on');}
    _gyShowCam(_so);
    _gySetView(_so);
  });
}
function _gyExit(){
  _gm=false;
  if(_gtt===1){sendCmd({type:'mouse_up'});_gtt=0;}
  if(_gShRel)_gShRel();
  /* 这里原来还有一行 `if(_gShRel2)_gShRel2();` —— 但 `_gShRel2` 从未被赋值过(死钩子),
     清理时只删了它的「声明」而留下了这处「读」,于是变成 ReferenceError:
     `_gyExit()` 在中间抛异常,后面移除 gyroPage 的 'on'、_gyStop()、sm(_gPrevSo)
     全都执行不到 —— 表现就是"进了 GYRO 就退不出来"。只删声明不删使用,
     会把死代码变成运行时崩溃。 */
  _gHoldUp.forEach(function(h){
    if(h.el.classList.contains('pressed')){h.el.classList.remove('pressed');sendCmd(h.up);}
  });
  _gyStop();
  document.getElementById('gyroPage').classList.remove('on');
  document.getElementById('gcb').classList.remove('on');
  _gySetView(true);
  /* 屏幕状态确实要变(例如本来就是 REMOTE)-> 按老路协商;
     状态没变 -> 只把流搬回普通 <video>,搬不成才退化为协商。 */
  if(_gPrevSo!==_so)sm(_gPrevSo);
  else if(!_attachStream('vd'))sm(_gPrevSo);
}
function _gyToggle(){
  if(_gm){_gyExit();return;}
  _gyEnter();
}
function _gyShowCam(on){
  var msg=document.getElementById('gmsg');
  var gv=document.getElementById('gv'),gc=document.getElementById('gc');
  if(on){
    msg.style.display='none';
    if(gv&&gv.style.display!=='none'){gc.style.display='none';gv.style.display='';}
    else{
      if(_rw&&gc.width!==_rw){gc.width=_rw;gc.height=_rh;}
      gc.style.display='';
    }
  }else{
    msg.style.display='';
    if(gv){gv.style.display='none';}
    if(gc){gc.style.display='none';}
  }
}

function _gyCalib(){
  sendCmd({type:'gyro_calib'});
}
var _gLand=false,_gAxSwap=false,_gyOrientT=null;
function _gAxBtn(){
  var b=document.getElementById('gax');
  if(!b)return;
  b.textContent=((_gLand^_gAxSwap)?'L':'P')+(_gAxSwap?'*':'');
  b.classList.toggle('on',_gAxSwap);
}
function _gySetLand(land){
  _gLand=land;_gAxSwap=false;_gAxBtn();
}
function _gyOrient(){_gySetLand(window.matchMedia&&window.matchMedia('(orientation:landscape)').matches);_gLayout();
  clearTimeout(_gyOrientT);
  _gyOrientT=setTimeout(function(){if(_gm)_gyCalib();},300);}
_gyOrient();
if(window.matchMedia)window.matchMedia('(orientation:landscape)').addListener(function(m){_gySetLand(m.matches);});
window.addEventListener('orientationchange',function(){setTimeout(_gyOrient,200);});
window.addEventListener('devicemotion',function(e){
  if(!_gy)return;
  var rr=e.rotationRate;
  if(!rr||rr.gamma==null)return;
  var now=Date.now();
  var dt=Math.min(0.05,(now-_gyLast)/1000);
  _gyLast=now;
  if(dt<=0)return;
  var ga=rr.alpha!=null?rr.alpha:0;
  var gy=rr.gamma;
  var gb=rr.beta!=null?rr.beta:0;
  var dead=1.0;
  var dx=0,dy=0;
  if(_gLand^_gAxSwap){
    if(Math.abs(gy)>dead)dx=Math.round(-gy*dt*(_gsX)*2);
    if(Math.abs(gb)>dead)dy=Math.round(gb*dt*(_gsY)*2);
  }else{
    if(Math.abs(gy)>dead)dx=Math.round(-gy*dt*(_gsX)*2);
    if(Math.abs(ga)>dead)dy=Math.round(-ga*dt*(_gsY)*2);
  }
  if(dx||dy){
    if(_isLan)sendCmd({type:'mouse_move',dx:dx,dy:dy});
    else _mqAcc(dx,dy);
  }
});
var _espRelay='',_espToken='',_espDev='',_espLockPw='',_espLockEnter=false;
function _espSend(m){
  if(!_espRelay)return;
  var r=new WebSocket(_espRelay);
  r.onopen=function(){
    r.send(JSON.stringify({type:'register',token:_espToken}));
    r.send(JSON.stringify(m));
    setTimeout(function(){try{r.close()}catch(_){}},500);
  };
}
function _espHid(k){_espSend({type:'hid_key',device:_espDev,key:k});}
function _espUac(){_espHid('left');setTimeout(function(){_espHid('enter')},200);}
function _espJs(){var pw=_espLockPw;function n(i){if(i>=pw.length){if(_espLockEnter)_espHid('enter');return;}_espHid(pw[i]);setTimeout(function(){n(i+1)},150);}_espHid('backspace');if(!pw){if(_espLockEnter)setTimeout(function(){_espHid('enter')},5000);return;}setTimeout(function(){n(0)},5000);}
function _espEsc(){_espHid('esc');}
function _espLock(){_espHid('win+l');}
function _espWin(){_espHid('win');}
function _espMouse(o){
  var m={type:'hid_mouse',device:_espDev};
  if(o.btn)m.btn=o.btn;
  if(o.x)m.x=o.x;
  if(o.y)m.y=o.y;
  if(o.w)m.w=o.w;
  if(o.hold)m.hold=o.hold;
  _espSend(m);
}
function _espL(){_espMouse({btn:1});}
document.addEventListener('touchmove',function(e){if(!e.target.closest('#ks')&&!e.target.closest('input'))e.preventDefault();},{passive:false});
function _bindHoldEl(el,dcmd,ucmd,nocancel,norepeat){
  if(!el)return;
  var iv=null,to=null,pr=false,sx=0,sy=0,sl=false,sTid=-1;
  var add=function(){el.classList.add('pressed');};
  var rem=function(){el.classList.remove('pressed');};
  var sd=function(){if(Array.isArray(dcmd))dcmd.forEach(function(c){sendCmd(c);});else sendCmd(dcmd);};
  var su=function(){if(!ucmd)return;if(Array.isArray(ucmd))ucmd.forEach(function(c){sendCmd(c);});else sendCmd(ucmd);};
  var _tid=function(ts){var t;for(var i=0;i<ts.length;i++)if(ts[i].identifier===sTid){t=ts[i];break;}return t||ts[0];};
  var down=function(e){
    if(e.type==='touchstart'){
      var t=e.changedTouches[0];sx=t.clientX;sy=t.clientY;sTid=t.identifier;sl=false;
      if(pr)return;pr=true;add();sd();
      if(!norepeat)to=setTimeout(function(){to=null;iv=setInterval(sd,50);},350);
    }else{
      e.preventDefault();
      if(pr)return;pr=true;add();sd();
      if(!norepeat)to=setTimeout(function(){to=null;iv=setInterval(sd,50);},350);
    }
  };
  var mv=function(e){
    if(sl)return;
    if(nocancel)return;
    var t=_tid(e.touches);
    if(t.identifier!==sTid)return;
    if(Math.abs(t.clientX-sx)>10||Math.abs(t.clientY-sy)>10){
      sl=true;
      if(pr){pr=false;rem();if(to){clearTimeout(to);to=null;}if(iv){clearInterval(iv);iv=null;}su();}
    }
  };
  var up=function(e){
    if(e.type==='touchend'&&sl)return;
    e.preventDefault();sTid=-1;rem();
    if(!pr)return;pr=false;
    if(to){clearTimeout(to);to=null;}
    if(iv){clearInterval(iv);iv=null;}
    su();
  };
  _gHoldUp.push({el:el,up:su});
  if(!_isTouch){el.addEventListener('mousedown',down);el.addEventListener('mouseup',up);el.addEventListener('mouseleave',up);}
  el.addEventListener('touchstart',down,{passive:true});
  el.addEventListener('touchmove',mv,{passive:true});
  el.addEventListener('touchend',up,{passive:false});
  el.addEventListener('touchcancel',up);
}
function _bindHoldCombo(el,keys){if(!el)return;_bindHoldEl(el,keys.map(function(k){return {type:'key_down',key:k};}),keys.map(function(k){return {type:'key_up',key:k};}),true,true);}
function _tapEl(el,fn,nocancel){if(!el)return;
  var sx=0,sy=0,sl=false,sTid=-1;
  var add=function(){el.classList.add('pressed');};
  var rem=function(){el.classList.remove('pressed');};
  var _tid=function(ts){var t;for(var i=0;i<ts.length;i++)if(ts[i].identifier===sTid){t=ts[i];break;}return t||ts[0];};
  var f=function(e){
    if(e.type==='touchstart'){
      var t=e.changedTouches[0];sx=t.clientX;sy=t.clientY;sTid=t.identifier;sl=false;add();return;
    }
    if(sl){rem();return;}
    e.preventDefault();rem();fn.call(el);
  };
  var mv=function(e){
    if(sl)return;
    if(nocancel)return;
    var t=_tid(e.touches);
    if(t.identifier!==sTid)return;
    if(Math.abs(t.clientX-sx)>10||Math.abs(t.clientY-sy)>10)sl=true;
  };
  if(!_isTouch)el.addEventListener('mousedown',f);
  el.addEventListener('touchstart',f,{passive:true});
  el.addEventListener('touchmove',mv,{passive:true});
  el.addEventListener('touchend',f,{passive:false});
}
var sn=document.getElementById('sn'),rc=document.getElementById('rc'),rr=document.getElementById('rr');
sn.addEventListener('click',function(){var t=ti.value;if(!t)return;sendCmd({type:'type_text',text:t.replace(/\n/g,' ')});ti.value='';ta.focus();});
var _rr=false,_ac=null,_st=null,_ch=[];var _te=0,_ci=null;
var _pxc=null,_pxb=false;
var _awUrl=URL.createObjectURL(new Blob(
  ["class P extends AudioWorkletProcessor{process(i,o){const c=i[0][0];for(let n=0;n<c.length;n++)o[0][0][n]=c[n];this.port.postMessage(new Float32Array(c));return true}}registerProcessor('r',P);"],
  {type:'application/javascript'}
));
function _warmCtx(){
  if(_pxc||_pxb)return;
  _pxb=true;
  var ac=new(window.AudioContext||window.webkitAudioContext)({sampleRate:16000});
  ac.audioWorklet.addModule(_awUrl).then(function(){_pxc=ac;_pxb=false;}).catch(function(){_pxb=false;});
}
document.addEventListener('touchstart',_warmCtx,{once:true});document.addEventListener('mousedown',_warmCtx,{once:true});
function wv(s,sr){
  var b=new ArrayBuffer(44+s.length*2),v=new DataView(b);
  var w=function(p,s){for(var i=0;i<s.length;i++)v.setUint8(p+i,s.charCodeAt(i));};
  w(0,'RIFF');v.setUint32(4,36+s.length*2,true);w(8,'WAVE');w(12,'fmt ');
  v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
  v.setUint32(24,sr,true);v.setUint32(28,sr*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);
  w(36,'data');v.setUint32(40,s.length*2,true);
  for(var i=0;i<s.length;i++)v.setInt16(44+i*2,Math.round(Math.max(-1,Math.min(1,s[i]))*32767),true);
  return new Blob([b],{type:'audio/wav'});
}
function _fc(){
  var l=_ch.reduce(function(s,c){return s+c.length;},0);
  if(!l)return;
  var sa=new Float32Array(l),off=0;
  _ch.forEach(function(c){sa.set(c,off);off+=c.length;});
  if(ws&&ws.readyState===WebSocket.OPEN){_ch=[];ws.send(wv(sa,16000));}
}
function rs(){
  if(_rr)return;
  _rr=true;_ch=[];_ci=setInterval(_fc,2000);
  _recBtn.textContent=_recBtn.classList.contains('rec-mini')?'S':'\u25a0 Stop';
  _recBtn.parentElement.classList.add('recording');
  navigator.mediaDevices.getUserMedia({audio:true}).then(function(s){
    if(!_rr){s.getTracks().forEach(function(t){t.stop();});return}
    _st=s;
    if(_pxc&&_pxc.state==='suspended')_pxc.resume();
    _ac=_pxc||new(window.AudioContext||window.webkitAudioContext)({sampleRate:16000});
    var src=_ac.createMediaStreamSource(_st);
    var load=_pxc?Promise.resolve():_ac.audioWorklet.addModule(_awUrl);
    load.then(function(){
      var nd=new AudioWorkletNode(_ac,'r',{channelCount:1});
      nd.port.onmessage=function(e){if(_rr)_ch.push(e.data);};
      src.connect(nd);
    }).catch(function(){re(true);});
  }).catch(function(){re(true);});
}
function re(si){
  if(!_rr)return;
  _rr=false;
  if(_ci){clearInterval(_ci);_ci=null;}
  _fc();
  if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'voice_end'}));
  _recBtn.textContent=_recBtn.classList.contains('rec-mini')?'R':'REC';
  _recBtn.parentElement.classList.remove('recording');
  if(_st){_st.getTracks().forEach(function(t){t.stop();});_st=null;}
  if(_ac)_ac.close();
  _ac=null;_pxc=null;_pxb=false;
  setTimeout(_warmCtx,0);
}
var _pt=0,_wr=false;
function _rcD(){_pt=Date.now();_wr=_rr;rs();}
function _rcU(){if(!_rr||_pt===0)return;if(_wr||Date.now()-_pt>=300)re();}
function _bindRec(b){
  b.addEventListener('mousedown',function(){_recBtn=b;_rcD();});
  b.addEventListener('mouseup',_rcU);
  b.addEventListener('mouseleave',function(){if(_rr)re();});
  b.addEventListener('touchstart',function(e){e.preventDefault();_recBtn=b;_rcD();});
  b.addEventListener('touchend',function(e){e.preventDefault();_rcU();});
  b.addEventListener('touchcancel',function(e){e.preventDefault();if(_rr)re();});
}
var _recBtn=rc;_bindRec(rc);
var bs=document.getElementById('bs');_bindHoldEl(bs,{type:'scroll_up'},null,true);
var be=document.getElementById('be');_bindHoldEl(be,{type:'mouse_right_down'},{type:'mouse_right_up'},true,true);
_bindHoldEl(rr,{type:'scroll_down'},null,true);
ti.addEventListener('focus',function(){
  if(!document.getElementById('sw-spacer')){
    var s=document.createElement('div');s.id='sw-spacer';s.style.cssText='height:400px;flex:0 0 auto;';sw.appendChild(s);
  }
});
ti.addEventListener('blur',function(){var s=document.getElementById('sw-spacer');if(s)s.remove();});
function _toggleTheme(){var h=document.documentElement;h.classList.toggle('dark');localStorage.setItem('deskbeam_theme',h.classList.contains('dark')?'dark':'light');}
if(localStorage.getItem('deskbeam_theme')==='dark')document.documentElement.classList.add('dark');
/* ── GYRO page ── */
document.getElementById('st').addEventListener('click',_openPanel);
function _gkey(t,cls){var b=document.createElement('button');b.className='gk'+(cls?' '+cls:'');b.textContent=t;return b;}
function _gTap(b,key){_tapEl(b,function(){sendCmd({type:'key_press',key:key});},true);}
(function(){
  var gl=document.getElementById('gcl'),gr=document.getElementById('gcr');
  function reg(el,side){_gBtns.push({el:el,side:side});}
  var wasd=document.createElement('div');wasd.className='gyro-dpad';
  var wsB=_gkey('WA','hl');_bindHoldCombo(wsB,['w','a']);wsB.className+=' dp-ul';wasd.appendChild(wsB);
  var wB=_gkey('W','hl');_bindHoldEl(wB,{type:'key_down',key:'w'},{type:'key_up',key:'w'},true,true);wB.className+=' dp-up';wasd.appendChild(wB);
  var wdB=_gkey('WD','hl');_bindHoldCombo(wdB,['w','d']);wdB.className+=' dp-ur';wasd.appendChild(wdB);
  var aB=_gkey('A','hl');_bindHoldEl(aB,{type:'key_down',key:'a'},{type:'key_up',key:'a'},true,true);aB.className+=' dp-left';wasd.appendChild(aB);
  var sB=_gkey('S','hl');_bindHoldEl(sB,{type:'key_down',key:'s'},{type:'key_up',key:'s'},true,true);sB.className+=' dp-down';wasd.appendChild(sB);
  var dB=_gkey('D','hl');_bindHoldEl(dB,{type:'key_down',key:'d'},{type:'key_up',key:'d'},true,true);dB.className+=' dp-right';wasd.appendChild(dB);
  reg(wasd,'L');
  var dirs=document.createElement('div');dirs.className='gyro-dpad';
  var ul=_gkey('\u2196','hl');_bindHoldCombo(ul,['up','left']);ul.className+=' dp-ul';dirs.appendChild(ul);
  var upB=_gkey('\u2191','hl');_bindHoldEl(upB,{type:'key_down',key:'up'},{type:'key_up',key:'up'},true,true);upB.className+=' dp-up';dirs.appendChild(upB);
  var ur=_gkey('\u2197','hl');_bindHoldCombo(ur,['up','right']);ur.className+=' dp-ur';dirs.appendChild(ur);
  var lfB=_gkey('\u2190','hl');_bindHoldEl(lfB,{type:'key_down',key:'left'},{type:'key_up',key:'left'},true,true);lfB.className+=' dp-left';dirs.appendChild(lfB);
  var dnB=_gkey('\u2193','hl');_bindHoldEl(dnB,{type:'key_down',key:'down'},{type:'key_up',key:'down'},true,true);dnB.className+=' dp-down';dirs.appendChild(dnB);
  var rtB=_gkey('\u2192','hl');_bindHoldEl(rtB,{type:'key_down',key:'right'},{type:'key_up',key:'right'},true,true);rtB.className+=' dp-right';dirs.appendChild(rtB);
  reg(dirs,'R');
  [['H','h',''],['END','end','']].forEach(function(k){var b=_gkey(k[0],k[2]);_gTap(b,k[1]);reg(b,'L');});
  var fR=_gkey('R','hr');_bindHoldEl(fR,{type:'mouse_right_down'},{type:'mouse_right_up'},true,true);reg(fR,'L');
  var mB=_gkey('M','blk');_bindHoldEl(mB,{type:'mouse_middle_down'},{type:'mouse_middle_up'},true,true);reg(mB,'L');
  var pu=_gkey('\u25B2');_bindHoldEl(pu,{type:'scroll_up'},null,true);reg(pu,'L');
  var pd=_gkey('\u25BC');_bindHoldEl(pd,{type:'scroll_down'},null,true);reg(pd,'L');
  [['ESC','esc',''],['Z','z','']].forEach(function(k){var b=_gkey(k[0],k[2]);_gTap(b,k[1]);reg(b,'L');});
  [['L','l',''],['M','m',''],['Q','q',''],['B','b','']].forEach(function(k){var b=_gkey(k[0],k[2]);_gTap(b,k[1]);reg(b,'L');});
  [['R','r',''],['E','e',''],['F','f','']].forEach(function(k){var b=_gkey(k[0],k[2]);_gTap(b,k[1]);reg(b,'R');});
  var sp=_gkey('SPACE','hl');_gTap(sp,'space');reg(sp,'R');
  var l=_gkey('CTRL','hl');_bindHoldEl(l,{type:'key_down',key:'ctrl'},{type:'key_up',key:'ctrl'},true,true);reg(l,'R');
  var sh=_gkey('SHIFT');reg(sh,'R');
  _gShRel=_mkShiftBtn(sh);
  [['C','c',''],['X','x','']].forEach(function(k){var b=_gkey(k[0],k[2]);_gTap(b,k[1]);reg(b,'R');});
  var tapB=_gkey('TAP');_bindHoldEl(tapB,{type:'key_down',key:'tab'},{type:'key_up',key:'tab'},true,true);reg(tapB,'R');
  [['V','v',''],['ENTER','enter','enter-key']].forEach(function(k){var b=_gkey(k[0],k[2]);_gTap(b,k[1]);reg(b,'R');});
  var bsp=_gkey('\u232b','');_bindHoldEl(bsp,{type:'key_press',key:'backspace'},null,true,false);reg(bsp,'R');
  _gLayout();
})();
function _gLayout(){
  if(_gtt===1){sendCmd({type:'mouse_up'});_gtt=0;}
  _gHoldUp.forEach(function(h){
    if(h.el.classList.contains('pressed')){h.el.classList.remove('pressed');sendCmd(h.up);}
  });
  var mc=document.getElementById('gmc'),gl=document.getElementById('gcl'),gr=document.getElementById('gcr');
  if(!mc||!gl||!gr)return;
  var ls=window.matchMedia&&window.matchMedia('(orientation:landscape)').matches;
  _gBtns.forEach(function(b){
    if(ls){if(b.side==='L')gl.appendChild(b.el);else gr.appendChild(b.el);}
    else mc.appendChild(b.el);
  });
}
function _gySetView(on){
  document.getElementById('gyroPage').classList.toggle('novid',!on);
}
document.getElementById('gcb').addEventListener('click',function(){
  var b=this;b.classList.toggle('on');
  if(b.classList.contains('on')){if(!_so)sm(true);}
  else{if(_so)sm(false);}
  _gyShowCam(b.classList.contains('on'));
  _gySetView(b.classList.contains('on'));
});
document.getElementById('gex').addEventListener('click',_openPanel);
document.getElementById('gyroStatus').addEventListener('click',_gyToggleSensor);
document.getElementById('ggb').addEventListener('click',function(){_gSetAcc(!_gAcc);});
document.getElementById('gcal').addEventListener('click',_gyCalib);
document.getElementById('gax').addEventListener('click',function(){_gAxSwap=!_gAxSwap;_gAxBtn();});
(function(){
  var sx=document.getElementById('gsx'),sy=document.getElementById('gsy');
  var vx=document.getElementById('gsxv'),vy=document.getElementById('gsyv');
  sx.value=_gsX;sy.value=_gsY;
  if(vx)vx.textContent=_gsX;if(vy)vy.textContent=_gsY;
  sx.addEventListener('input',function(){_gsX=parseInt(this.value)||20;if(vx)vx.textContent=_gsX;});
  sy.addEventListener('input',function(){_gsY=parseInt(this.value)||20;if(vy)vy.textContent=_gsY;});
})();
/* ── GYRO touch canvas: 1-finger left-hold + virtual joystick move ── */
var _gtt=0; /* 0=none 1=left-down */
(function(){
  var ta=document.getElementById('gta');
  if(!ta)return;
  var stick=document.getElementById('gstick');
  var stickKnob=document.getElementById('gstickKnob');
  var sCX=0,sCY=0,sLx=0,sLy=0,sActive=false,sTouchId=-1;
  function _stickArea(x,y){
    if(!stick)return false;
    var r=stick.getBoundingClientRect();
    var pad=24;
    return x>=r.left-pad&&x<=r.right+pad&&y>=r.top-pad&&y<=r.bottom+pad;
  }
  ta.addEventListener('touchstart',function(e){
    var ct=e.changedTouches;
    for(var i=0;i<ct.length;i++){
      if(_stickArea(ct[i].clientX,ct[i].clientY)){
        sActive=true;sTouchId=ct[i].identifier;
        sCX=ct[i].clientX;sCY=ct[i].clientY;
        sLx=ct[i].clientX;sLy=ct[i].clientY;
        if(stick)stick.classList.add('active');
        return;
      }
    }
    var n=e.targetTouches.length-(sActive?1:0);
    if(n===1&&_gtt===0){sendCmd({type:'mouse_down'});_gtt=1;}
    else if(n>1&&_gtt===1){sendCmd({type:'mouse_up'});_gtt=0;}
  },{passive:true});
  ta.addEventListener('touchmove',function(e){
    if(sActive){
      var t;for(var i=0;i<e.touches.length;i++){if(e.touches[i].identifier===sTouchId){t=e.touches[i];break;}}
      if(t){
        var ox=t.clientX-sCX,oy=t.clientY-sCY;
        var d=Math.hypot(ox,oy);
        if(d>20){ox=ox/d*20;oy=oy/d*20;}
        var dx=Math.round((t.clientX-sLx)*3);
        var dy=Math.round((t.clientY-sLy)*3);
        if(dx>40)dx=40;if(dx<-40)dx=-40;
        if(dy>40)dy=40;if(dy<-40)dy=-40;
        sLx=t.clientX;sLy=t.clientY;
        if(stickKnob)stickKnob.style.transform='translate('+ox+'px,'+oy+'px)';
        if(dx||dy)sendCmd({type:'mouse_move',dx:dx,dy:dy});
        return;
      }
    }
    e.preventDefault();
  },{passive:false});
  ta.addEventListener('touchend',function(e){
    for(var i=0;i<e.changedTouches.length;i++){
      if(e.changedTouches[i].identifier===sTouchId){
        sActive=false;sTouchId=-1;
        if(stick)stick.classList.remove('active');
        if(stickKnob)stickKnob.style.transform='translate(-50%,-50%)';
        return;
      }
    }
    if(!sActive&&e.targetTouches.length===0){if(_gtt===1)sendCmd({type:'mouse_up'});_gtt=0;}
  },{passive:true});
  ta.addEventListener('touchcancel',function(e){
    for(var i=0;i<e.changedTouches.length;i++){
      if(e.changedTouches[i].identifier===sTouchId){
        sActive=false;sTouchId=-1;
        if(stick)stick.classList.remove('active');
        if(stickKnob)stickKnob.style.transform='translate(-50%,-50%)';
        return;
      }
    }
    if(!sActive&&e.targetTouches.length===0){if(_gtt===1)sendCmd({type:'mouse_up'});_gtt=0;}
  },{passive:true});
})();
/* ── GYRO input row (text + voice, like main page) ── */
var gti=document.getElementById('gti'),gsn=document.getElementById('gsn'),grc=document.getElementById('grc');
if(gsn){
  gsn.addEventListener('click',function(){var t=gti.value;if(!t)return;sendCmd({type:'type_text',text:t.replace(/\n/g,' ')});gti.value='';document.getElementById('gta').focus();});
}
if(grc){
  _bindRec(grc);
}

cn();cnV();