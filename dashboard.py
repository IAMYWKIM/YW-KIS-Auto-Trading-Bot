# ==========================================================
# [dashboard.py]  Snowball TS  V23.10
# 실행: streamlit run dashboard.py
# V23.10 업데이트: VWAP+스나이퍼 공수분담, 총초토화 재장전, 5MA락온,
#   스나이퍼 단순화, TrueSync 단가소급, VWAP매도락다운, 동적스펙트럼게이지
# ==========================================================
import streamlit as st
import json, os, math, datetime, pytz, time

from dotenv import load_dotenv
load_dotenv()

st.set_page_config(page_title="Snowball TS", page_icon="☃️",
                   layout="wide", initial_sidebar_state="collapsed")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# ── yfinance 가용성 체크 (설치 안 돼도 크래시 방지) ──────────
try:
    import yfinance as _yf_test
    YFINANCE_OK = True
except (ImportError, ModuleNotFoundError):
    YFINANCE_OK = False

# ════════════════════════════════════════════════════════════════
# 공통 CSS
# ════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=Space+Mono:wght@400;700&display=swap');
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{
  background:#0d0d0f!important;color:#e8e8e8!important;
  font-family:'Noto Sans KR',sans-serif!important;}
[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stStatusWidget"],section[data-testid="stSidebar"],
.stDeployButton{display:none!important;}
#MainMenu,footer,header{visibility:hidden!important;}
.block-container{padding:1rem 1rem 2rem!important;max-width:660px!important;margin:0 auto!important;}
::-webkit-scrollbar{width:4px;}
::-webkit-scrollbar-thumb{background:#3a3a55;border-radius:4px;}
.stTabs [data-baseweb="tab-list"]{background:#111120!important;border-radius:12px!important;padding:4px!important;}
.stTabs [data-baseweb="tab"]{color:#888!important;font-weight:600!important;border-radius:8px!important;font-size:.92rem!important;}
.stTabs [aria-selected="true"]{background:#1e1e35!important;color:#fff!important;border-bottom:2px solid #4488ff!important;}
.stButton>button{background:#1e1e2e!important;color:#ccc!important;border:1px solid #2a2a45!important;
  border-radius:10px!important;font-family:'Noto Sans KR',sans-serif!important;
  font-size:.92rem!important;font-weight:600!important;min-height:44px!important;}
.stButton>button:hover{background:#252540!important;border-color:#4444aa!important;color:#eee!important;}
.stTextInput>div>div>input{background:#1c1c28!important;border:1px solid #2a2a45!important;
  border-radius:10px!important;color:#e8e8e8!important;font-size:1rem!important;
  padding:.7rem 1rem!important;min-height:44px!important;}
.stTextInput>div>div>input:focus{border-color:#3b6ff5!important;
  box-shadow:0 0 0 3px rgba(59,111,245,.2)!important;}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# 데이터 헬퍼
# ════════════════════════════════════════════════════════════════
DATA = "data"

def _j(fname, d=None):
    p = os.path.join(DATA, fname)
    if os.path.exists(p):
        try:
            with open(p,'r',encoding='utf-8') as f: return json.load(f)
        except: pass
    return d if d is not None else {}

def get_tickers():   return _j("active_tickers.json", ["SOXL","TQQQ"])
def get_ledger():    return _j("manual_ledger.json", [])
def get_history():   return _j("manual_history.json", [])
def get_seed(t):     return float(_j("seed_config.json",{"SOXL":6720,"TQQQ":6720}).get(t,6720))
def get_split(t):    return float(_j("split_config.json",{"SOXL":40,"TQQQ":40}).get(t,40))
def get_target(t):   return float(_j("profit_config.json",{"SOXL":12,"TQQQ":10}).get(t,12))
def get_version(t):  return _j("version_config.json",{"SOXL":"V14","TQQQ":"V14"}).get(t,"V14")
def get_sniper(t):
    d={"SOXL":0.9,"TQQQ":0.8}
    return float(_j("sniper_multiplier.json",d).get(t,d.get(t,0.9)))
def get_reverse(t):  return _j("reverse_config.json",{}).get(t,{"is_active":False,"day_count":0,"exit_target":0.0})
def get_escrow(t):   return float(_j("trade_locks.json",{}).get("ESCROW_"+t, 0.0))
def get_upward():    return _j("trade_locks.json",{}).get("UPWARD_SNIPER_MODE", False)
def get_vcache():    return _j("vwap_cache.json", {})
def get_5ma(t):      return float(_j("tracking_cache.json",{}).get(t+"_5ma", 0.0))
def get_vwap_sell_locked(t): return bool(_j("vwap_cache.json",{}).get(t+"_sell_locked", False))
def get_regime():    return _j("volatility_cache.json",{})  # weight per ticker

def calc_holdings(ticker, ledger):
    """
    장부 평단가 계산.

    텔레그램 봇 TrueSync(V20.4)의 비파괴 보정 레코드 처리 포함:
    - 일반 BUY/SELL : FIFO 누적 계산
    - CALIB 레코드  : exec_id가 'CALIB_'로 시작하거나 desc가 '비파괴 보정'인 경우
                      → qty 는 델타(±), avg_price 는 KIS API 확인 누적 평단가
                      → BUY/SELL 후 inv = 누적qty × avg_price 로 강제 리셋
    - side='CALIB'  : qty·avg 직접 리셋 (명시적 보정 레코드)
    """
    qty, inv = 0, 0.0
    for r in ledger:
        if r.get('ticker') != ticker:
            continue

        q      = int(float(r.get('qty', 0)))
        p      = float(r.get('price', 0))
        avg_p  = float(r.get('avg_price', 0))   # KIS API 누적 평단가
        side   = r.get('side', '')
        exec_id = str(r.get('exec_id', ''))
        desc   = r.get('desc', '')

        # CALIB 레코드 판별
        is_calib = (
            exec_id.startswith('CALIB_') or
            desc == '비파괴 보정' or
            side == 'CALIB'
        )

        if side == 'BUY':
            qty += q
            if is_calib and avg_p > 0:
                # avg_price = 이 매수 이후 KIS 기준 누적 평단가
                inv = qty * avg_p
            else:
                inv += q * p

        elif side == 'SELL':
            qty = max(0, qty - q)
            if is_calib and avg_p > 0:
                # avg_price = 이 매도 이후 KIS 기준 누적 평단가
                inv = qty * avg_p
            else:
                if qty > 0 and inv > 0:
                    ratio = qty / (qty + q)
                    inv = inv * ratio

        elif side == 'CALIB':
            # 명시적 CALIB: qty·avg 직접 리셋
            qty = q
            inv = q * (avg_p if avg_p > 0 else p)

    qty = max(0, qty)
    avg = (inv / qty) if qty > 0 else 0.0
    return qty, avg

def calc_v14(ticker, ledger):
    seed  = get_seed(ticker)
    split = get_split(ticker)
    base  = seed / split if split > 0 else 1
    qty, avg = calc_holdings(ticker, ledger)
    t_val = (qty * avg) / base if base > 0 else 0.0

    recs = sorted([r for r in ledger if r.get('ticker') == ticker],
                  key=lambda x: x.get('id', 0))
    rem = seed
    for r in recs:
        q = int(r.get('qty', 0))
        p = float(r.get('price', 0))
        side = r.get('side', '')
        if side == 'BUY':
            rem -= q * p
        elif side == 'SELL':
            rem += q * p
        # CALIB: 현금 흐름 없음 — rem 변화 없음

    budget = rem / max(1.0, split - t_val) if qty > 0 else base
    return round(max(0, t_val), 4), max(0, budget), max(0, rem)

@st.cache_data(ttl=60)
def get_price(ticker):
    """
    yfinance 미설치 시 크래시 없이 0 반환.
    1차: history(5d) / 2차: fast_info / 3차: download
    실패 시: avg 폴백은 호출 레이어에서 처리.
    """
    if not YFINANCE_OK:
        return {"p": 0.0, "prev": 0.0, "high": 0.0, "low": 0.0}
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        h = t.history(period="5d", interval="1d")
        if h is not None and len(h) >= 2:
            return {
                "p":    float(h['Close'].iloc[-1]),
                "prev": float(h['Close'].iloc[-2]),
                "high": float(h['High'].iloc[-1]),
                "low":  float(h['Low'].iloc[-1])
            }
    except Exception:
        pass
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        cp = float(fi.get('last_price') or fi.get('regularMarketPrice') or 0)
        if cp > 0:
            prev = float(fi.get('previous_close') or fi.get('regularMarketPreviousClose') or cp)
            dh   = float(fi.get('day_high') or fi.get('regularMarketDayHigh') or cp)
            dl   = float(fi.get('day_low')  or fi.get('regularMarketDayLow')  or cp)
            return {"p": cp, "prev": prev, "high": dh, "low": dl}
    except Exception:
        pass
    try:
        import yfinance as yf, pandas as pd
        df = yf.download(ticker, period="5d", interval="1d", progress=False)
        if df is not None and len(df) >= 2:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            return {
                "p":    float(df['Close'].iloc[-1]),
                "prev": float(df['Close'].iloc[-2]),
                "high": float(df['High'].iloc[-1]),
                "low":  float(df['Low'].iloc[-1])
            }
    except Exception:
        pass
    return {"p": 0.0, "prev": 0.0, "high": 0.0, "low": 0.0}

def get_first_date(ticker, ledger):
    recs = [r for r in ledger if r.get('ticker') == ticker and r.get('side') == 'BUY']
    if recs: return sorted([r.get('date', '') for r in recs])[0]
    return ""

@st.cache_data(ttl=300)
def get_vol():
    if not YFINANCE_OK:
        return {"TQQQ": {}, "SOXL": {}}
    res = {"TQQQ":{}, "SOXL":{}}
    try:
        import yfinance as yf, pandas as pd
        v = yf.download("^VXN",period="1y",interval="1d",progress=False)
        if not v.empty:
            if isinstance(v.columns, pd.MultiIndex): v.columns = v.columns.droplevel(1)
            c = v['Close'].dropna().tail(252)
            cur = float(c.iloc[-1]); mean = float(c.mean()); w = cur/mean if mean>0 else 1.0
            res["TQQQ"] = {"val":cur,"mean":mean,"w":w,"label":"VXN (나스닥 공포지수)"}
    except: pass
    try:
        import yfinance as yf, pandas as pd, numpy as np
        s = yf.download("SOXX",period="1y",interval="1d",progress=False)
        if not s.empty:
            if isinstance(s.columns, pd.MultiIndex): s.columns = s.columns.droplevel(1)
            c = s['Close'].dropna()
            lr = np.log(c/c.shift(1))
            hv = lr.rolling(20).std()*np.sqrt(252)*100
            v1 = hv.dropna().tail(252)
            cur = float(v1.iloc[-1]); mean = float(v1.mean()); w = cur/mean if mean>0 else 1.0
            res["SOXL"] = {"val":cur,"mean":mean,"w":w,"label":"SOXX HV20 (반도체 실현변동성)"}
    except: pass
    return res

def get_vwap_window():
    try:
        est = pytz.timezone('US/Eastern')
        now = datetime.datetime.now(est)
        if now.hour==15 and 30<=now.minute<=59:
            b = now.minute-30
            return {"active":True,"bin":b,"elapsed":b+1,"left":30-(b+1),"pct":round((b+1)/30*100)}
    except: pass
    return {"active":False,"bin":-1,"elapsed":0,"left":30,"pct":0}

def get_market():
    try:
        import pandas_market_calendars as mcal
        est = pytz.timezone('US/Eastern')
        now = datetime.datetime.now(est)
        nyse = mcal.get_calendar('NYSE')
        sch = nyse.schedule(start_date=now.date(),end_date=now.date())
        if sch.empty: return "HOLIDAY"
        mo = sch.iloc[0]['market_open'].astimezone(est)
        mc = sch.iloc[0]['market_close'].astimezone(est)
        if now < mo.replace(hour=4,minute=0): return "PRE_PRE"
        if now < mo: return "PRE"
        if now < mc: return "OPEN"
        if now < mc.replace(hour=20,minute=0): return "AFTER"
        return "CLOSED"
    except: return "UNKNOWN"

# ════════════════════════════════════════════════════════════════
# HTML 빌더 (중첩 f-string 완전 배제, 모두 + 연결)
# ════════════════════════════════════════════════════════════════
def H(tag, style, content, extra=""):
    return '<' + tag + ' style="' + style + '"' + (' ' + extra if extra else '') + '>' + content + '</' + tag + '>'

def card(content, radius="16px", bg="#111120", border="#1e1e35", margin="0 0 .5rem", pad="1.2rem 1.3rem"):
    s = "background:" + bg + ";border:1px solid " + border + ";border-radius:" + radius
    s += ";padding:" + pad + ";margin-bottom:" + margin.split(" ")[-1] + ";"
    return H("div", s, content)

def badge(text, bg, border, color):
    s = "background:" + bg + ";border:1px solid " + border + ";border-radius:8px;"
    s += "padding:.2rem .7rem;font-size:.82rem;font-weight:700;color:" + color + ";"
    s += "display:inline-block;"
    return H("div", s, text)

def row(left, right):
    s_wrap = "display:flex;justify-content:space-between;align-items:center;padding:.85rem 1.1rem;"
    s_l = "font-size:.92rem;color:#aaa;font-weight:500;"
    s_r = "font-family:'Space Mono',monospace;font-size:1rem;font-weight:700;"
    return H("div", s_wrap, H("span",s_l,left) + H("span",s_r,right))

def sep(color="#1a1a2e"):
    return '<div style="height:1px;background:' + color + ';margin:0;"></div>'

def mono(text, color="#ddd", size=".92rem", weight="700"):
    s = "font-family:'Space Mono',monospace;font-size:" + size
    s += ";font-weight:" + weight + ";color:" + color + ";"
    return H("span", s, text)

def sm(text, color="#8899aa", size=".82rem"):
    return H("div","font-size:"+size+";color:"+color+";font-weight:500;margin-bottom:.25rem;",text)

def grid3(items):
    """items = [(label, value, color), ...]"""
    cells = ""
    for label, val, col in items:
        cells += H("div","",
            H("div","font-size:.8rem;color:#8899aa;margin-bottom:.25rem;font-weight:500;",label) +
            H("div","font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:"+col+";",val)
        )
    return H("div","display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;",cells)

def sub_card(content, bg="#0d0d1c", border="#1a1a30", radius="11px", pad=".9rem 1rem", mb=".7rem"):
    s = "background:"+bg+";border:1px solid "+border+";border-radius:"+radius
    s += ";padding:"+pad+";margin-bottom:"+mb+";"
    return H("div",s,content)

def section_title(text):
    s = "font-size:.88rem;font-weight:700;color:#aaa;margin-bottom:.7rem;"
    s += "border-bottom:1px solid #1a1a30;padding-bottom:.4rem;"
    return H("div",s,text)

# ════════════════════════════════════════════════════════════════
# 로그인 화면
# ════════════════════════════════════════════════════════════════
def show_login():
    st.markdown("""
<style>
.block-container{padding:0!important;max-width:100%!important;
  min-height:100vh!important;display:flex!important;
  align-items:center!important;justify-content:center!important;}
</style>""", unsafe_allow_html=True)

    _, col, _ = st.columns([1,1.1,1])
    with col:
        shield_svg = (
            '<svg viewBox="0 0 64 72" width="54" height="62" xmlns="http://www.w3.org/2000/svg">'
            '<defs>'
            '<linearGradient id="lg1" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#ccddf5"/>'
            '<stop offset="100%" stop-color="#4466a8"/>'
            '</linearGradient>'
            '<linearGradient id="lg2" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#e86040"/>'
            '<stop offset="100%" stop-color="#b02818"/>'
            '</linearGradient>'
            '<clipPath id="cp1"><path d="M32 2 L58 12 L58 38 Q58 58 32 70 Q6 58 6 38 L6 12 Z"/></clipPath>'
            '</defs>'
            '<path d="M32 2 L58 12 L58 38 Q58 58 32 70 Q6 58 6 38 L6 12 Z" fill="url(#lg1)" stroke="rgba(200,220,255,.6)" stroke-width="1.2"/>'
            '<rect x="-10" y="18" width="84" height="26" fill="url(#lg2)" transform="rotate(-35,32,36)" clip-path="url(#cp1)" opacity=".9"/>'
            '</svg>'
        )

        shield_wrap = (
            '<div style="width:100px;height:100px;'
            'background:radial-gradient(ellipse at 35% 35%,#1e3a8a 0%,#0d1f5c 50%,#060d2e 100%);'
            'border-radius:50%;display:flex;align-items:center;justify-content:center;'
            'box-shadow:0 0 0 1px rgba(60,100,255,.3),0 0 30px rgba(30,80,220,.4);">'
            + shield_svg + '</div>'
        )

        header_box = (
            '<div style="text-align:center;padding:2.5rem 2rem 2rem;'
            'background:linear-gradient(160deg,#0e0e1a,#13131f,#0a0a14);'
            'border:1px solid #22223a;border-radius:22px;margin-bottom:1.2rem;">'
            '<div style="margin:0 auto 1.4rem;width:100px;">' + shield_wrap + '</div>'
            '<div style="font-family:\'Space Mono\',monospace;font-size:.9rem;font-weight:700;'
            'color:#5599ff;letter-spacing:.28em;margin-bottom:.6rem;">SNIPER COMMAND</div>'
            '<div style="font-size:1.4rem;font-weight:900;color:#fff;margin-bottom:.5rem;">'
            '✨ VWAP 자율주행 엔진 ✨</div>'
            '<div style="display:inline-block;background:rgba(255,255,255,.06);'
            'border:1px solid rgba(255,255,255,.12);border-radius:20px;'
            'padding:.2rem .9rem;font-size:.8rem;color:#8899bb;margin-bottom:.4rem;">'
            'V23.02 멀티코어 하이브리드 아키텍처</div>'
            '<div style="font-size:.85rem;color:#ee5555;margin-top:.3rem;">'
            '인가된 총사령관만 접근을 허가합니다.</div>'
            '</div>'
        )
        st.markdown(header_box, unsafe_allow_html=True)

        st.markdown('<p style="color:#99aacc;font-size:.88rem;font-weight:600;margin-bottom:.2rem;">총사령관 ID</p>', unsafe_allow_html=True)
        st.text_input("id", placeholder="ID를 입력하세요", key="login_id", label_visibility="collapsed")
        st.markdown('<p style="color:#99aacc;font-size:.88rem;font-weight:600;margin:.5rem 0 .2rem;">보안 암호</p>', unsafe_allow_html=True)
        pw = st.text_input("pw", type="password", placeholder="••••••••", key="login_pw", label_visibility="collapsed")

        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
        btn_style = (
            '<style>.login-btn>button{background:linear-gradient(135deg,#1a6fff,#0d4fd4)!important;'
            'color:#fff!important;border:none!important;border-radius:12px!important;'
            'font-weight:700!important;font-size:1rem!important;'
            'box-shadow:0 4px 20px rgba(26,111,255,.4)!important;min-height:48px!important;}'
            '</style><div class="login-btn">'
        )
        st.markdown(btn_style, unsafe_allow_html=True)
        if st.button("🚀  사령부 접속", use_container_width=True, key="do_login"):
            secret = os.getenv("DASHBOARD_PASSWORD","snowball2025")
            if pw == secret:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.markdown('<div style="background:rgba(200,40,40,.18);border:1px solid rgba(240,80,80,.4);'
                    'border-radius:10px;padding:.7rem 1rem;color:#ff8888;text-align:center;font-size:.9rem;margin-top:.5rem;">'
                    '❌ 접근 거부 — 보안 암호가 올바르지 않습니다.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div style="text-align:center;margin-top:.8rem;color:#5566aa;font-size:.8rem;">'
            '기본 암호: <code style="color:#7788cc;background:rgba(80,100,200,.15);'
            'padding:.1rem .4rem;border-radius:4px;">snowball2025</code></div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# 메인 대시보드
# ════════════════════════════════════════════════════════════════
def show_dashboard():
    ledger   = get_ledger()
    history  = get_history()
    tickers  = get_tickers()
    mkt      = get_market()
    vwap_win = get_vwap_window()
    vc       = get_vcache()
    upward   = get_upward()

    MKT_MAP = {
        "OPEN":    ('<span style="background:#0a3a1a;border:1px solid #1a6a3a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#44ee88;font-weight:700;">🟢 정규장</span>'),
        "PRE":     ('<span style="background:#1a1a0a;border:1px solid #4a4a1a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#cccc44;font-weight:700;">🌅 프리마켓</span>'),
        "AFTER":   ('<span style="background:#1a0a1a;border:1px solid #4a2a4a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#cc88ff;font-weight:700;">🌙 애프터</span>'),
        "HOLIDAY": ('<span style="background:#1a0a0a;border:1px solid #4a1a1a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#ee5555;font-weight:700;">⛔ 휴장일</span>'),
        "CLOSED":  ('<span style="background:#111118;border:1px solid #2a2a3a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#778899;font-weight:700;">🌑 장마감</span>'),
        "PRE_PRE": ('<span style="background:#111118;border:1px solid #2a2a3a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#778899;font-weight:700;">🌃 개장 전</span>'),
        "UNKNOWN": ('<span style="background:#111118;border:1px solid #2a2a3a;border-radius:6px;padding:.15rem .55rem;font-size:.78rem;color:#778899;font-weight:700;">⏳ 확인중</span>'),
    }
    mkt_badge = MKT_MAP.get(mkt, MKT_MAP["UNKNOWN"])

    # ── 헤더 ─────────────────────────────────────
    header = (
        '<div style="display:flex;align-items:center;justify-content:space-between;padding:.4rem 0 .2rem;">'
        '<div style="display:flex;align-items:center;gap:.7rem;">'
        '<span style="font-size:1.7rem;">☃️</span>'
        '<div>'
        '<span style="font-size:1.45rem;font-weight:900;color:#fff;">Snowball TS</span>'
        '<span style="display:inline-block;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);'
        'border-radius:12px;padding:.08rem .55rem;font-size:.73rem;color:#6677aa;margin-left:.45rem;'
        'font-family:\'Space Mono\',monospace;">V23.10</span>'
        '</div></div>'
        + mkt_badge + '</div>'
    )
    st.markdown(header, unsafe_allow_html=True)

    st.markdown(
        '<div style="display:inline-block;background:linear-gradient(90deg,#2a2010,#3a2e08);'
        'border:1px solid #5a4a20;border-radius:22px;padding:.35rem 1.2rem;font-size:.88rem;'
        'font-weight:700;color:#e0b830;margin:.2rem 0 .5rem;">'
        '🚀 VWAP+스나이퍼 공수분담 · 총초토화 재장전 · V3.2 ATR</div>',
        unsafe_allow_html=True
    )

    c1, c2, c3 = st.columns([1.2,1.8,.7])
    with c1: auto = st.toggle("🕐 1분 갱신", value=True, key="ar")
    with c2:
        aid = os.getenv("ADMIN_CHAT_ID","")
        bname = "pipiosbot" if aid else "hambot"
        st.markdown(
            '<div style="background:#1a1a2a;border:1px solid #28284a;border-radius:10px;'
            'padding:.4rem .8rem;font-size:.85rem;color:#ccc;display:flex;align-items:center;gap:.4rem;">'
            '<span>🤖</span>'
            '<span style="color:#ddd;font-weight:600;">' + bname + '</span></div>',
            unsafe_allow_html=True
        )
    with c3:
        if st.button("🚪", key="logout", help="로그아웃"):
            st.session_state.logged_in = False
            st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["  📊 현황판  ","  🌊 VWAP  ","  ⚙️ 조종실  ","  🏆 역사관  "])

    # ── yfinance 미설치 전역 경고 ─────────────────────
    if not YFINANCE_OK:
        st.markdown(
            H("div","background:#1a0a00;border:1px solid #662200;border-radius:12px;"
              "padding:.8rem 1.1rem;margin:.4rem 0 .6rem;",
                H("div","font-size:.92rem;font-weight:700;color:#ff8844;margin-bottom:.4rem;",
                    "⚠️ yfinance 모듈이 설치되지 않았습니다") +
                H("div","font-size:.85rem;color:#cc7755;margin-bottom:.5rem;",
                    "현재가·고저가 조회가 불가합니다. 아래 명령어로 설치하세요:") +
                H("div","background:#0d0d0d;border:1px solid #333;border-radius:8px;"
                  "padding:.5rem .8rem;font-family:'Space Mono',monospace;font-size:.85rem;color:#88cc88;",
                    "pip install yfinance --break-system-packages") +
                H("div","font-size:.78rem;color:#886644;margin-top:.4rem;",
                    "설치 후 대시보드를 재시작하세요. 평단가·장부 데이터는 정상 표시됩니다.")
            ),
            unsafe_allow_html=True
        )

    # ════════════════════════════════════════════════════════
    # 탭1: 현황판
    # ════════════════════════════════════════════════════════
    with tab1:
        # ── 계좌 요약 ───────────────────────────────
        total_cash = total_eval = total_escrow = 0.0
        for t in tickers:
            _, _, rem = calc_v14(t, ledger)
            q, avg_ = calc_holdings(t, ledger)
            pd_ = get_price(t)
            cp = pd_["p"] if pd_["p"]>0 else avg_
            total_cash   += rem
            total_eval   += q * cp
            total_escrow += get_escrow(t)

        total_invested = sum(calc_holdings(t,ledger)[0]*calc_holdings(t,ledger)[1] for t in tickers)
        total_account  = total_cash + total_eval
        avail          = max(0, total_cash - total_escrow)

        esc_col  = "#ff6666" if total_escrow>0 else "#666688"
        esc_sign = "−" if total_escrow>0 else ""

        acc_inner = (
            H("div",
              "display:flex;justify-content:space-between;align-items:center;padding:.85rem 1.1rem;border-bottom:1px solid #1a1a2e;",
              H("span","font-size:.9rem;color:#aaa;font-weight:500;","💵 계좌 총액") +
              H("div","text-align:right;",
                H("div","font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:#fff;","$"+f"{total_account:,.2f}") +
                H("div","font-size:.76rem;color:#5566aa;margin-top:.1rem;","예수금 $"+f"{total_cash:,.2f}"+" + 평가 $"+f"{total_eval:,.2f}")
              )
            ) +
            H("div",
              "display:flex;justify-content:space-between;align-items:center;padding:.85rem 1.1rem;border-bottom:1px solid #1a1a2e;",
              H("span","font-size:.9rem;color:#aaa;font-weight:500;","📦 총 매수금액") +
              H("div","text-align:right;",
                H("div","font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:#ddd;","$"+f"{total_invested:,.2f}") +
                H("div","font-size:.76rem;color:#5566aa;margin-top:.1rem;","수량 × 평단가 합계")
              )
            ) +
            H("div",
              "display:flex;justify-content:space-between;align-items:center;padding:.85rem 1.1rem;border-bottom:1px solid #1a1a2e;",
              H("span","font-size:.9rem;color:#aaa;font-weight:500;","🔒 에스크로") +
              H("span","font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:"+esc_col+";",
                esc_sign+"$"+f"{total_escrow:,.2f}")
            ) +
            H("div",
              "display:flex;justify-content:space-between;align-items:center;padding:.85rem 1.1rem;",
              H("div","",
                H("div","font-size:.9rem;color:#aaa;font-weight:500;","✅ 가용 예산") +
                H("div","font-size:.76rem;color:#5566aa;margin-top:.1rem;","예수금 − 에스크로")
              ) +
              H("span","font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:#4ade80;","$"+f"{avail:,.2f}")
            )
        )
        st.markdown(
            H("div","background:#111120;border:1px solid #22223a;border-radius:14px;overflow:hidden;margin:.3rem 0 .9rem;", acc_inner),
            unsafe_allow_html=True
        )

        # ── 종목 카드 루프 ───────────────────────────
        for ticker in tickers:
            qty, avg  = calc_holdings(ticker, ledger)
            pd_       = get_price(ticker)
            curr      = pd_["p"]; prev_c = pd_["prev"]
            high      = pd_["high"]; low = pd_["low"]

            # ── 가격 패치 실패 시 폴백 처리 ──────────────
            price_fetch_failed = (curr <= 0)
            if price_fetch_failed and avg > 0:
                curr = avg   # 평단가로 임시 대체 (표시용)

            chg       = (curr-prev_c)/prev_c*100 if prev_c>0 else 0.0
            high_pct  = (high-prev_c)/prev_c*100  if prev_c>0 else 0.0
            low_pct   = (low-prev_c)/prev_c*100   if prev_c>0 else 0.0
            chg_col   = "#ff6666" if chg>=0 else "#60a5fa"
            chg_sign  = "+" if chg>=0 else ""
            hi_sign   = "+" if high_pct>=0 else ""
            lo_sign   = "+" if low_pct>=0 else ""

            version   = get_version(ticker)
            split     = get_split(ticker)
            target    = get_target(ticker)
            seed      = get_seed(ticker)
            rev       = get_reverse(ticker)
            is_rev    = rev.get("is_active",False)
            escrow    = get_escrow(ticker)
            sniper_m  = get_sniper(ticker)
            is_vwap   = (version=="V_VWAP")

            t_val, budget, _ = calc_v14(ticker, ledger)
            progress  = min(100.0, round(t_val/split*100,1)) if split>0 else 0.0
            dep       = 2.0/split if split>0 else 0.1
            star_r    = (target/100) - (target/100)*dep*t_val
            star_p    = math.ceil(avg*(1+star_r)*100)/100.0 if avg>0 else 0.0
            sniper_drop = round(abs(sniper_m)*10, 2)
            sniper_l  = math.floor(avg*(1-sniper_m*0.10)*100)/100.0 if avg>0 else 0.0
            invest_a  = qty * avg
            start_dt  = get_first_date(ticker, ledger)

            vwap_buy  = vc.get(ticker+"_buy_executed",  0)
            vwap_sell = vc.get(ticker+"_sell_executed", 0)
            esc_col2  = "#ff7777" if escrow>0 else "#666688"
            vwap_sell_locked = get_vwap_sell_locked(ticker)
            ma5 = get_5ma(ticker)

            # 버전 배지
            if is_vwap:
                vbg,vbr,vcol = "#00224a","#004488","#00ccff"
            elif is_rev:
                vbg,vbr,vcol = "#2a0a0a","#661111","#ff6666"
            else:
                vbg,vbr,vcol = "#0a2a1a","#116633","#33cc66"

            prefix = "🌊 " if is_vwap else ""

            # ── 가격 조회 실패 경고 배너 ─────────────────
            if price_fetch_failed:
                st.markdown(
                    H("div","background:#1a1500;border:1px solid #4a3800;border-radius:10px;"
                      "padding:.55rem 1rem;margin-bottom:.4rem;font-size:.83rem;color:#ccaa44;",
                        "⚠️ <b>"+ticker+"</b> 실시간 시세 조회 실패 — 평단가($"+f"{avg:,.2f}"+")로 임시 표시 중. "
                        "yfinance 네트워크 상태를 확인하거나 잠시 후 새로고침해 주세요."),
                    unsafe_allow_html=True
                )

            # ── CARD 1: 헤더 ──────────────────────────
            upward_badge = ""
            if upward:
                upward_badge = (
                    H("div","background:#1a1a0a;border:1px solid #4a4a20;border-radius:8px;"
                      "padding:.2rem .6rem;font-size:.78rem;font-weight:700;color:#ddcc44;",
                      "🔼 상방스나이퍼 ON")
                )

            ver_badge = badge(prefix+"Ver "+version, vbg, vbr, vcol)
            badges_row = H("div","display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;", ver_badge+upward_badge)
            progress_block = (
                H("div","text-align:right;",
                    H("div","font-size:.8rem;color:#999;font-weight:500;","진행도") +
                    H("div","font-family:'Space Mono',monospace;font-size:1.35rem;font-weight:700;color:#fff;line-height:1.1;",str(progress)+"%") +
                    H("div","font-size:.78rem;color:#8888aa;",f"{t_val:.4f}T / {int(split)}")
                )
            )
            top_row = H("div","display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.6rem;",
                badges_row+progress_block)

            ticker_name = H("div","font-size:2.3rem;font-weight:900;color:#fff;line-height:1;margin-bottom:.4rem;",ticker)
            price_block = (
                H("div","font-family:'Space Mono',monospace;font-size:1.85rem;font-weight:700;color:"+chg_col+";line-height:1.1;","$"+f"{curr:,.2f}") +
                H("div","font-size:.9rem;color:"+chg_col+";margin-bottom:.8rem;font-weight:500;","("+chg_sign+f"{chg:.2f}%)")
            )
            # 최고/최저 — 가격 조회 실패 시 "조회 실패" 표시
            if price_fetch_failed or high <= 0:
                hl_block = H("div","display:flex;gap:.55rem;margin-bottom:.7rem;",
                    H("div","flex:1;background:#1c0e0e;border:1px solid #441a1a;border-radius:9px;padding:.5rem .75rem;",
                        H("span","font-size:.82rem;color:#cc8888;","최고 ") +
                        H("span","font-size:.85rem;color:#888;","— 조회 실패")
                    ) +
                    H("div","flex:1;background:#0a0e1e;border:1px solid #1a2855;border-radius:9px;padding:.5rem .75rem;",
                        H("span","font-size:.82rem;color:#8899cc;","최저 ") +
                        H("span","font-size:.85rem;color:#888;","— 조회 실패")
                    )
                )
            else:
                hl_block = H("div","display:flex;gap:.55rem;margin-bottom:.7rem;",
                    H("div","flex:1;background:#1c0e0e;border:1px solid #441a1a;border-radius:9px;padding:.5rem .75rem;",
                        H("span","font-size:.82rem;color:#cc8888;","최고 ") +
                        H("span","font-size:.88rem;color:#ff8888;font-weight:700;","$"+f"{high:,.2f}") +
                        H("span","font-size:.8rem;color:#ff8888;"," ("+hi_sign+f"{high_pct:.2f}%)")
                    ) +
                    H("div","flex:1;background:#0a0e1e;border:1px solid #1a2855;border-radius:9px;padding:.5rem .75rem;",
                        H("span","font-size:.82rem;color:#8899cc;","최저 ") +
                        H("span","font-size:.88rem;color:#60a5fa;font-weight:700;","$"+f"{low:,.2f}") +
                        H("span","font-size:.8rem;color:#60a5fa;"," ("+lo_sign+f"{low_pct:.2f}%)")
                    )
                )
            start_line = ""
            if start_dt:
                start_line = H("div","font-size:.85rem;color:#7788aa;margin-bottom:.7rem;font-weight:500;","📅 "+start_dt+" ~")

            card1_inner = top_row + ticker_name + price_block + hl_block + start_line
            st.markdown(card(card1_inner, margin=".5rem 0 .3rem"), unsafe_allow_html=True)

            # ── CARD 2: 기본·매입 정보 ────────────────
            info_grid = grid3([
                ("총 시드",      "$"+f"{seed:,.0f}",    "#ddd"),
                ("사용 중인 금고","$"+f"{escrow:,.2f}", esc_col2),
                ("오늘 예산",    "$"+f"{budget:,.2f}",  "#4ade80"),
            ])
            hold_grid = grid3([
                ("평단가",   "$"+f"{avg:,.2f}",      "#ddd"),
                ("보유 수량", str(qty)+"주",          "#ddd"),
                ("매입 금액", "$"+f"{invest_a:,.2f}", "#fbbf24"),
            ])
            card2_inner = (
                sub_card(section_title("기본 정보") + info_grid, mb=".6rem") +
                sub_card(section_title("매입 정보") + hold_grid, mb="0")
            )
            st.markdown(card(card2_inner, radius="14px", margin=".3rem 0 .3rem", pad="1rem 1.3rem"), unsafe_allow_html=True)

            # ── CARD 3: VWAP + 스나이퍼 공수분담 현황 (V_VWAP, V23.03~04) ──
            if is_vwap and qty > 0:
                sell_lock_line = ""
                if vwap_sell_locked:
                    sell_lock_line = H("div","background:#2a1500;border:1px solid #5a3000;border-radius:8px;padding:.45rem .8rem;margin-top:.6rem;font-size:.82rem;color:#ff9944;font-weight:600;",
                        "🔒 VWAP 매도 락다운 (V23.08) — 당일 쿼터 익절 완료로 중복 매도 차단 중")

                vwap_exec = (
                    H("div","display:flex;align-items:center;gap:.5rem;margin-bottom:.7rem;",
                        H("div","font-size:.88rem;font-weight:700;color:#44bbff;","🌊 VWAP + 스나이퍼 공수분담 (V23.03)") +
                        H("span","background:#001a3a;border:1px solid #003366;border-radius:6px;padding:.1rem .45rem;font-size:.75rem;color:#4499cc;","15:30 총초토화→재장전")
                    ) +
                    H("div","display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-bottom:.5rem;",
                        sub_card(
                            H("div","font-size:.8rem;color:#5599cc;margin-bottom:.2rem;font-weight:500;","장중 스나이퍼") +
                            H("div","font-size:.78rem;color:#4488aa;","바닥 추적 · Vol>MA20 격발"),
                            bg="#001a3a", border="#002255", mb="0"
                        ) +
                        sub_card(
                            H("div","font-size:.8rem;color:#5599cc;margin-bottom:.2rem;font-weight:500;","15:30 VWAP 엔진") +
                            H("div","font-size:.78rem;color:#4488aa;","U-Curve 1분 분할 타격"),
                            bg="#001a3a", border="#002255", mb="0"
                        )
                    ) +
                    H("div","display:grid;grid-template-columns:1fr 1fr;gap:.5rem;",
                        sub_card(
                            H("div","font-size:.8rem;color:#5599cc;margin-bottom:.2rem;font-weight:500;","오늘 매수 체결") +
                            H("div","font-family:'Space Mono',monospace;font-size:1rem;font-weight:700;color:#44ccff;",str(vwap_buy)+"주"),
                            bg="#001a3a", border="#002255", mb="0"
                        ) +
                        sub_card(
                            H("div","font-size:.8rem;color:#5599cc;margin-bottom:.2rem;font-weight:500;","오늘 매도 체결") +
                            H("div","font-family:'Space Mono',monospace;font-size:1rem;font-weight:700;color:#ff9944;",str(vwap_sell)+"주"),
                            bg="#001a3a", border="#002255", mb="0"
                        )
                    ) +
                    sell_lock_line
                )
                st.markdown(
                    H("div","background:#00112a;border:1px solid #004488;border-radius:14px;padding:1rem 1.2rem;margin-bottom:.3rem;", vwap_exec),
                    unsafe_allow_html=True
                )

            # ── CARD 4: 무매 공식 + 스나이퍼 + 주문계획 (V_VWAP 제외) ──
            if avg > 0 and not is_vwap:
                p_avg  = round(avg-0.01, 2)
                p_star = round(star_p-0.01, 2)
                q_star = math.floor(budget/p_star) if p_star>0 else 0
                q_sell = math.ceil(qty/4) if qty>0 else 0
                N      = math.floor(budget/avg) if avg>0 else 0
                phase  = "전반전" if t_val < split/2 else "후반전"

                # 무매 공식
                formula = sub_card(
                    section_title("📐 무매 공식") +
                    H("div","display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;text-align:center;",
                        H("div","",sm("T") + H("div","font-family:'Space Mono',monospace;font-size:.93rem;font-weight:700;color:#ddd;",f"{t_val:.4f}")) +
                        H("div","",sm("목표 수익률") + H("div","font-family:'Space Mono',monospace;font-size:.93rem;font-weight:700;color:#4ade80;",f"{target:.1f}%")) +
                        H("div","",sm("별%가격") + H("div","font-family:'Space Mono',monospace;font-size:.93rem;font-weight:700;color:#fbbf24;","$"+f"{star_p:,.2f}"))
                    )
                )
                st.markdown(card(formula, radius="14px", margin=".3rem 0 .3rem", pad=".95rem 1.2rem"), unsafe_allow_html=True)

                # 스나이퍼 방어선 (V23.06: Vol>MA20 단일 조건)
                if qty > 0:
                    # V23.05: 리버스 모드는 5MA 절대 락온
                    if is_rev and ma5 > 0:
                        sniper_target_line = H("div","font-size:.88rem;color:#e0c050;font-weight:600;","🎯 리버스 목표: 5MA "+H("span","font-family:'Space Mono',monospace;color:#fbbf24;","$"+f"{ma5:,.2f}")+" 절대 락온")
                        sniper_buy_line = H("div","font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:#ff7777;margin-bottom:.35rem;","$"+f"{sniper_l:,.2f}"+" 이하 지정가 장전 대기 중")
                    else:
                        sniper_buy_line = H("div","font-family:'Space Mono',monospace;font-size:.95rem;font-weight:700;color:#ff7777;margin-bottom:.35rem;","$"+f"{sniper_l:,.2f}"+" 이하 지정가 장전 대기 중")
                        sniper_target_line = H("div","font-size:.88rem;color:#e0c050;font-weight:600;","🦅 쿼터 스나이퍼: $"+f"{star_p:,.2f}"+" 이상 대기")

                    sniper_filter = H("div","font-size:.78rem;color:#664444;margin-top:.35rem;","Vol > MA20 단일 조건 (V23.06) · 10:20 EST 이후 격발")
                    sniper_html = (
                        H("div","font-size:.88rem;color:#cc9999;font-weight:600;margin-bottom:.4rem;",
                            "🎯 스나이퍼 동적 방어선 " +
                            H("span","font-size:.8rem;color:#998888;font-weight:400;","(−"+f"{sniper_drop:.2f}"+"% / ATR×3)")
                        ) +
                        sniper_buy_line +
                        sniper_target_line +
                        sniper_filter
                    )
                    st.markdown(
                        H("div","background:#180a0a;border:1px solid #3a1818;border-radius:14px;padding:.9rem 1.2rem;margin-bottom:.3rem;", sniper_html),
                        unsafe_allow_html=True
                    )

                # 주문 계획
                if not is_rev and qty > 0:
                    ver_span = H("span","background:#182818;border:1px solid rgba(51,170,85,.25);border-radius:6px;padding:.1rem .45rem;font-size:.8rem;font-weight:700;color:#33cc66;","Ver "+version)
                    phase_span = H("span","font-size:.8rem;color:#8899aa;font-weight:500;margin-left:.3rem;","["+phase+"]")
                    plan_title = H("div","display:flex;justify-content:space-between;align-items:center;margin-bottom:.7rem;border-bottom:1px solid #1a1a30;padding-bottom:.4rem;",
                        H("div","font-size:.88rem;font-weight:700;color:#aaa;","📋 주문 계획") +
                        H("div","",ver_span+phase_span)
                    )

                    def order_row(color, emoji, title, detail):
                        return H("div","display:flex;align-items:flex-start;gap:.55rem;margin-bottom:.5rem;",
                            H("span","color:"+color+";font-size:.92rem;",emoji) +
                            H("div","",
                                H("div","font-size:.88rem;font-weight:700;color:#ddd;",title) +
                                H("div","font-size:.83rem;color:#99aacc;margin-top:.1rem;","└ "+detail)
                            )
                        )

                    orders_html = (
                        order_row("#ff6666","🔴","⚓ 평단매수","$"+f"{p_avg:,.2f}"+" × "+str(N)+"주 (LOC)") +
                        order_row("#ff6666","🔴","💫 별값매수","$"+f"{p_star:,.2f}"+" × "+str(q_star)+"주 (LOC)") +
                        order_row("#60a5fa","🔵","⭐ 별값매도","$"+f"{star_p:,.2f}"+" × "+str(q_sell)+"주 (LOC)")
                    )
                    st.markdown(
                        card(sub_card(plan_title+orders_html, mb="0"), radius="14px", margin=".3rem 0 .3rem", pad=".95rem 1.2rem"),
                        unsafe_allow_html=True
                    )

                    # 줍줍
                    base_n = math.floor(budget/avg) if avg>0 else 0
                    jups = []
                    for i in range(1,6):
                        jp = math.floor(budget/(base_n+i)*100)/100.0 if (base_n+i)>0 else 0
                        jp = min(jp, avg-0.01)
                        if jp>0.01: jups.append(jp)
                    if jups and qty>0:
                        jup_range = "$"+f"{max(jups):,.2f}"+" ~ $"+f"{min(jups):,.2f}"
                        jup_html = H("div","display:flex;align-items:flex-start;gap:.55rem;",
                            H("span","color:#aaa;font-size:.92rem;","🧹") +
                            H("div","",
                                H("div","font-size:.88rem;font-weight:700;color:#ddd;","줍줍 ("+str(len(jups))+"개)") +
                                H("div","font-size:.83rem;color:#99aacc;margin-top:.1rem;","└ "+jup_range+" (LOC)")
                            )
                        )
                        st.markdown(card(jup_html, radius="12px", margin=".3rem 0 .3rem", pad=".85rem 1.2rem"), unsafe_allow_html=True)

            recs = sorted([r for r in ledger if r.get('ticker')==ticker], key=lambda x: x.get('id',0), reverse=True)
            if recs:
                buy_t  = sum(r['price']*r['qty'] for r in recs if r.get('side')=='BUY')
                sell_t = sum(r['price']*r['qty'] for r in recs if r.get('side')=='SELL')
                has_calib = any(r.get('price_corrected') for r in recs)

                calib_note = ""
                if has_calib:
                    calib_note = H("div","background:#1a1500;border:1px solid #3a3000;border-radius:6px;padding:.3rem .6rem;font-size:.78rem;color:#ccaa44;margin-bottom:.5rem;",
                        "✏️ V23.07 TrueSync 단가 소급 — 실제 체결가로 자동 교정된 기록 포함")

                th = (H("th","padding:.4rem .5rem;text-align:left;color:#667788;font-size:.78rem;font-weight:600;","#") +
                      H("th","padding:.4rem .5rem;text-align:left;color:#667788;font-size:.78rem;font-weight:600;","구분") +
                      H("th","padding:.4rem .5rem;text-align:left;color:#667788;font-size:.78rem;font-weight:600;","날짜") +
                      H("th","padding:.4rem .5rem;text-align:left;color:#667788;font-size:.78rem;font-weight:600;","가격") +
                      H("th","padding:.4rem .5rem;text-align:left;color:#667788;font-size:.78rem;font-weight:600;","수량"))

                rows_html = ""
                for r in recs[:25]:
                    side = r.get('side','')
                    sc = "#ff7777" if side=="BUY" else "#60a5fa"
                    sl = "매수" if side=="BUY" else "매도"
                    d = r.get('date','')
                    ds = d[-5:].replace('-','.') if len(d)>=5 else d
                    price_str = "$"+f"{r.get('price',0):,.2f}"
                    if r.get('price_corrected'):
                        price_str += H("span","font-size:.7rem;color:#ccaa44;margin-left:.2rem;","✏️","")
                    rows_html += (
                        "<tr>" +
                        H("td","padding:.45rem .5rem;color:#8899aa;font-size:.8rem;border-bottom:1px solid #181828;",str(r.get('id',''))) +
                        H("td","padding:.45rem .5rem;font-weight:700;font-size:.85rem;color:"+sc+";border-bottom:1px solid #181828;",sl) +
                        H("td","padding:.45rem .5rem;color:#aabbcc;font-size:.83rem;border-bottom:1px solid #181828;",ds) +
                        H("td","padding:.45rem .5rem;font-family:'Space Mono',monospace;color:#ddd;font-size:.83rem;border-bottom:1px solid #181828;",price_str) +
                        H("td","padding:.45rem .5rem;font-family:'Space Mono',monospace;color:#ddd;font-size:.83rem;border-bottom:1px solid #181828;",str(r.get('qty',0))+"주") +
                        "</tr>"
                    )

                tbl = (
                    H("div","font-size:.88rem;font-weight:700;color:#bbb;margin-bottom:.3rem;","🗒️ 거래 내역 " + H("span","font-size:.78rem;color:#556677;font-weight:400;","(✏️ = 단가 소급 교정)","")) +
                    H("div","font-size:.82rem;color:#8899aa;margin-bottom:.5rem;",
                        "매수합계: "+H("span","color:#ddd;","$"+f"{buy_t:,.2f}") +
                        " | 매도합계: "+H("span","color:#ddd;","$"+f"{sell_t:,.2f}")) +
                    calib_note +
                    "<table style='width:100%;border-collapse:collapse;'>" +
                    H("thead","","<tr>"+th+"</tr>") +
                    H("tbody","",rows_html) +
                    "</table>"
                )
                st.markdown(card(tbl, radius="14px", margin=".3rem 0 .6rem", pad="1rem 1.2rem"), unsafe_allow_html=True)

            if st.button("🔄 수동 갱신", key="ref_"+ticker, use_container_width=True):
                st.cache_data.clear(); st.rerun()
            st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # 탭2: VWAP 엔진
    # ════════════════════════════════════════════════════════
    with tab2:
        st.markdown(H("div","font-size:1rem;font-weight:700;color:#ddd;margin:.4rem 0 .8rem;","🌊 VWAP 자율주행 엔진"), unsafe_allow_html=True)

        # VWAP 윈도우 상태
        vw = vwap_win
        if vw["active"]:
            bar_n = round(vw["pct"]/100*22)
            bar = "█"*bar_n + "░"*(22-bar_n)
            win_html = (
                H("div","display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem;",
                    H("div","",
                        H("div","font-size:.8rem;color:#4499cc;font-weight:600;margin-bottom:.2rem;","🔴 LIVE · 실행 중") +
                        H("div","font-size:1.2rem;font-weight:900;color:#44ccff;","Bin "+str(vw['bin']+1)+" / 30")
                    ) +
                    H("div","text-align:right;",
                        H("div","font-size:.8rem;color:#4499cc;margin-bottom:.2rem;","잔여") +
                        H("div","font-family:'Space Mono',monospace;font-size:1.5rem;font-weight:700;color:#fff;",str(vw['left'])+"분")
                    )
                ) +
                H("div","font-family:'Space Mono',monospace;font-size:.8rem;color:#3377aa;margin-bottom:.4rem;", bar+" "+str(vw['pct'])+"%") +
                H("div","font-size:.82rem;color:#336688;","15:30 EST 진입 → 16:00 EST 완전 소진")
            )
            st.markdown(H("div","background:#00112a;border:1px solid #0055aa;border-radius:16px;padding:1.1rem 1.2rem;margin-bottom:.7rem;",win_html), unsafe_allow_html=True)
        else:
            est = pytz.timezone('US/Eastern')
            now_e = datetime.datetime.now(est)
            if now_e.hour<15 or (now_e.hour==15 and now_e.minute<30):
                mins = (15*60+30)-(now_e.hour*60+now_e.minute)
                wtxt = "⏳ VWAP 윈도우 대기 중 (약 "+str(mins)+"분 후)"
                wbg,wbrd,wc = "#1a1500","#443a00","#ccaa44"
            else:
                wtxt = "✅ 당일 VWAP 집행 완료"
                wbg,wbrd,wc = "#0a1a10","#114422","#44cc88"
            st.markdown(
                H("div","background:"+wbg+";border:1px solid "+wbrd+";border-radius:16px;padding:1rem 1.2rem;margin-bottom:.7rem;text-align:center;",
                    H("div","font-size:1rem;font-weight:700;color:"+wc+";",wtxt) +
                    H("div","font-size:.82rem;color:#446655;margin-top:.35rem;","VWAP 윈도우: 15:30~16:00 EST")),
                unsafe_allow_html=True
            )

        # U-Curve 프로파일
        soxl_p = [
            0.0308,0.0220,0.0190,0.0228,0.0179,0.0191,0.0199,0.0190,0.0187,0.0213,
            0.0216,0.0234,0.0222,0.0212,0.0211,0.0231,0.0234,0.0226,0.0215,0.0223,
            0.0518,0.0361,0.0369,0.0400,0.0655,0.0661,0.0365,0.0394,0.0503,0.1447
        ]
        tqqq_p = [
            0.0292,0.0249,0.0231,0.0225,0.0237,0.0222,0.0253,0.0242,0.0223,0.0184,
            0.0265,0.0253,0.0218,0.0212,0.0220,0.0273,0.0230,0.0246,0.0240,0.0286,
            0.0628,0.0354,0.0384,0.0373,0.0624,0.0564,0.0321,0.0382,0.0441,0.1129
        ]

        for pname, prof in [("SOXL", soxl_p), ("TQQQ", tqqq_p)]:
            mw = max(prof)
            cur_b = vw["bin"] if vw["active"] else -1
            bars = '<div style="display:flex;align-items:flex-end;gap:2px;height:58px;padding:0 .1rem;">'
            for i,w in enumerate(prof):
                h = max(4, round(w/mw*56))
                if i<cur_b:   bc,bt = "#224422","#114411"
                elif i==cur_b: bc,bt = "#00ccff","#0088bb"
                else:          bc,bt = "#1a3a6a","#0a2a5a"
                bars += '<div style="flex:1;height:'+str(h)+'px;background:'+bc+';border-top:2px solid '+bt+';border-radius:2px 2px 0 0;min-width:4px;" title="Bin '+str(i+1)+': '+f"{w:.4f}"+'"></div>'
            bars += "</div>"
            bars += '<div style="display:flex;justify-content:space-between;font-size:.7rem;color:#445566;margin-top:.25rem;">'
            bars += "<span>15:30</span><span>15:45</span><span>15:52</span><span>15:58</span><span>16:00</span></div>"

            active_label = ""
            if vw["active"]:
                active_label = H("span","font-size:.78rem;color:#44ccff;font-weight:600;"," — Bin "+str(cur_b+1)+" 실행 중","")

            chart_title = H("div","font-size:.88rem;font-weight:700;color:#aaa;margin-bottom:.6rem;", "📊 "+pname+" U-Curve 30구간"+active_label)
            note = H("div","font-size:.78rem;color:#334455;margin-top:.4rem;","마지막 구간에 유동성 집중 (U-Curve 후미 폭발 패턴)")
            st.markdown(card(chart_title+bars+note, radius="14px", margin=".4rem 0 .5rem", pad="1rem 1.2rem"), unsafe_allow_html=True)

        # 변동성 엔진
        st.markdown(H("div","font-size:.95rem;font-weight:700;color:#ccc;margin:.5rem 0 .5rem;","⚡ 변동성 엔진 V3.2 + 동적 스펙트럼 게이지 (V23.09)"), unsafe_allow_html=True)
        with st.spinner("변동성 데이터 로드 중..."):
            vdata = get_vol()

        atr_def = {"TQQQ":1.65*3,"SOXL":2.93*3}
        for ticker in tickers:
            vd = vdata.get(ticker,{})
            if not vd:
                st.markdown(card(H("div","color:#556677;font-size:.88rem;",ticker+" — 데이터 로드 실패 (캐시 사용 중)"), radius="12px"), unsafe_allow_html=True)
                continue

            weight = vd["w"]; val = vd["val"]; mean = vd["mean"]
            lbl = vd["label"]
            drop = atr_def.get(ticker,5.0)

            if weight > 1.3:   wc,ws = "#ff6644","⚠️ 과열"
            elif weight > 1.0: wc,ws = "#ffaa44","↑ 주의"
            else:              wc,ws = "#44cc88","✅ 정상"

            # V22.16 마스터 스위치
            if weight > 1.0:
                dir_txt,dir_col,dir_bg,dir_br = "🛡️ 상방 익절 우선 [ON]","#ff8844","#2a1500","#552200"
            else:
                dir_txt,dir_col,dir_bg,dir_br = "🔫 하방 매수 [ON]","#44ee88","#0a2a1a","#115522"

            dir_badge = H("div","background:"+dir_bg+";border:1px solid "+dir_br+";border-radius:8px;padding:.2rem .65rem;font-size:.8rem;font-weight:700;color:"+dir_col+";",dir_txt)

            title_row = H("div","display:flex;justify-content:space-between;align-items:center;margin-bottom:.7rem;",
                H("span","font-size:1.05rem;font-weight:900;color:#fff;",ticker) + dir_badge)

            sub_lbl = H("div","font-size:.8rem;color:#5577aa;margin-bottom:.6rem;font-weight:500;",lbl)

            nums = (
                sub_card(sm("현재값")+H("div","font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:"+wc+";",f"{val:.1f}"), bg="#0d0d1c",border="#1a1a30",mb="0") +
                sub_card(sm("1년 평균")+H("div","font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:#aabbcc;",f"{mean:.1f}"), bg="#0d0d1c",border="#1a1a30",mb="0") +
                sub_card(sm("공포 가중치")+H("div","font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:"+wc+";",f"{weight:.2f}x"), bg="#0d0d1c",border="#1a1a30",mb="0")
            )
            nums_row = H("div","display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-bottom:.7rem;",nums)

            # V23.09: 동적 스펙트럼 게이지
            # 게이지 범위: 0.5x ~ 2.0x (가중치 1.0이 중앙선)
            gauge_min, gauge_max = 0.5, 2.0
            gauge_range = gauge_max - gauge_min
            # 현재 위치 (0~100%)
            pos_pct = min(100, max(0, round((weight - gauge_min) / gauge_range * 100)))
            # 임계선 위치 (1.0 = 중앙)
            mid_pct = round((1.0 - gauge_min) / gauge_range * 100)
            # 게이지 색상: 좌측(파란=매수), 우측(빨간=매도)
            gauge_left_w  = min(pos_pct, mid_pct)
            gauge_right_w = max(0, pos_pct - mid_pct)
            gauge_empty   = 100 - pos_pct

            gauge_bar_inner = (
                '<div style="height:100%;width:' + str(gauge_left_w) + '%;background:linear-gradient(90deg,#1a4a88,#3399ff);border-radius:4px 0 0 4px;"></div>'
                '<div style="height:100%;width:' + str(gauge_right_w) + '%;background:linear-gradient(90deg,#ff8844,#ff4444);"></div>'
                '<div style="height:100%;width:' + str(gauge_empty) + '%;background:#1a1a2a;border-radius:0 4px 4px 0;"></div>'
            )
            # 현재 위치 마커
            marker_html = (
                '<div style="position:relative;height:10px;margin-top:2px;">'
                '<div style="position:absolute;left:' + str(pos_pct) + '%;transform:translateX(-50%);'
                'width:3px;height:10px;background:' + wc + ';border-radius:2px;"></div>'
                '</div>'
            )
            # 레이블
            gauge_labels = (
                H("div","display:flex;justify-content:space-between;font-size:.72rem;color:#445566;margin-top:.25rem;",
                    H("span","","0.5x 매수장") +
                    H("span","color:#fff;font-weight:600;","1.0x ← 임계점") +
                    H("span","","2.0x 패닉장")
                )
            )

            spectrum_gauge = (
                H("div","margin-bottom:.7rem;",
                    H("div","display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem;",
                        H("span","font-size:.8rem;color:#667788;font-weight:500;","📊 공수 스펙트럼 게이지") +
                        H("span","font-size:.8rem;color:"+wc+";font-weight:700;", ws + " · " + f"{weight:.2f}x")
                    ) +
                    '<div style="height:12px;background:#1a1a2a;border-radius:4px;overflow:hidden;'
                    'display:flex;position:relative;">' +
                    gauge_bar_inner + '</div>' +
                    marker_html +
                    gauge_labels
                )
            )

            wbar = min(100,round(weight*50))
            sniper_box = H("div","background:#1a0a0a;border:1px solid #3a1818;border-radius:9px;padding:.7rem .9rem;margin-top:.7rem;",
                H("div","font-size:.8rem;color:#cc8888;font-weight:600;margin-bottom:.3rem;","🎯 동적 타격선 (1년 ATR × 3배, V3.2)") +
                H("div","font-family:'Space Mono',monospace;font-size:1rem;font-weight:700;color:#ff7777;","−"+f"{drop:.2f}"+"% 이하 하락 시 스나이퍼 발동") +
                H("div","font-size:.76rem;color:#664444;margin-top:.25rem;","기초지수 1년 ATR 기반 · 공포 가중치는 공수 방향만 제어")
            )

            st.markdown(card(title_row+sub_lbl+nums_row+spectrum_gauge+sniper_box, radius="14px", margin=".4rem 0 .5rem", pad="1.1rem 1.2rem"), unsafe_allow_html=True)

        # V23.04: 15:30 총초토화 재장전 아키텍처
        nuke_html = (
            H("div","font-size:.9rem;font-weight:700;color:#ff8844;margin-bottom:.7rem;","💥 V23.04 — 15:30 총초토화(Nuclear Wipe) + 재장전 아키텍처") +
            H("div","display:flex;flex-direction:column;gap:.4rem;",
                H("div","display:flex;align-items:center;gap:.6rem;",
                    H("div","background:#ff6600;color:#fff;border-radius:6px;padding:.2rem .6rem;font-size:.78rem;font-weight:700;","STEP 1") +
                    H("div","font-size:.82rem;color:#cc9966;","15:30 EST 정각 — 호가창 미체결 전량 강제 소각(Nuke)")
                ) +
                H("div","display:flex;align-items:center;gap:.6rem;",
                    H("div","background:#4488ff;color:#fff;border-radius:6px;padding:.2rem .6rem;font-size:.78rem;font-weight:700;","STEP 2") +
                    H("div","font-size:.82rem;color:#7799cc;","12% 잭팟 LOC 매도 + 줍줍 재장전 (예수금·주식 해방)")
                ) +
                H("div","display:flex;align-items:center;gap:.6rem;",
                    H("div","background:#44cc88;color:#fff;border-radius:6px;padding:.2rem .6rem;font-size:.78rem;font-weight:700;","STEP 3") +
                    H("div","font-size:.82rem;color:#55aa77;","VWAP 엔진 가동 — U-Curve 1분 단위 Marketable Limit 타격")
                )
            ) +
            H("div","font-size:.77rem;color:#445566;margin-top:.5rem;","이중 매수 방지 · 예산/주식 완전 해방 후 무결점 집행 보장")
        )
        st.markdown(card(nuke_html, radius="14px", margin=".4rem 0 .5rem", pad="1rem 1.2rem",
                         bg="#0d0d1c", border="#2a1800"), unsafe_allow_html=True)

        # 멀티코어 아키텍처 (V23 전체 반영)
        arch = (
            H("div","font-size:.88rem;font-weight:700;color:#aaa;margin-bottom:.7rem;","🏗️ V23 멀티코어 스케줄러 아키텍처") +
            H("div","background:#0a1a0a;border:1px solid #1a3a1a;border-radius:9px;padding:.7rem .9rem;margin-bottom:.4rem;",
                H("div","font-size:.85rem;font-weight:700;color:#44cc77;","⚙️ 시스템 코어 (scheduler_core)") +
                H("div","font-size:.78rem;color:#5577aa;margin-top:.25rem;","토큰 갱신(4회/일) · TrueSync V23.07 단가소급 동기화 · 리버스 점검 · 자정 청소")
            ) +
            H("div","background:#0a0a1a;border:1px solid #1a1a3a;border-radius:9px;padding:.7rem .9rem;margin-bottom:.4rem;",
                H("div","font-size:.85rem;font-weight:700;color:#4488ff;","⚔️ 전투 코어 (scheduler_trade)") +
                H("div","font-size:.78rem;color:#5577aa;margin-top:.25rem;","정규장 LOC 장전(17:05/18:05) · 스나이퍼 Vol>MA20 60초 감시(V23.06) · VWAP 분할 타격(60초)")
            ) +
            H("div","background:#1a0a00;border:1px solid #3a2000;border-radius:9px;padding:.7rem .9rem;",
                H("div","font-size:.85rem;font-weight:700;color:#ff9944;","💥 15:30 총초토화 + VWAP 재장전 (V23.04)") +
                H("div","font-size:.78rem;color:#5577aa;margin-top:.25rem;","전 주문 Nuke → 잭팟 LOC 재장전 → VWAP U-Curve Marketable Limit · VWAP 매도 락다운(V23.08)")
            ) +
            H("div","font-size:.77rem;color:#334455;margin-top:.5rem;text-align:center;","단일 책임 원칙(SRP) · 공수 완벽 분리 · V23.10")
        )
        st.markdown(card(arch, radius="14px", margin=".4rem 0 .5rem", pad="1rem 1.2rem"), unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # 탭3: 조종실
    # ════════════════════════════════════════════════════════
    with tab3:
        st.markdown(H("div","font-size:1rem;font-weight:700;color:#ddd;margin:.4rem 0 .8rem;","⚙️ 현재 설정값"), unsafe_allow_html=True)

        for ticker in tickers:
            rv  = get_reverse(ticker)
            ver = get_version(ticker)
            is_v = (ver=="V_VWAP")

            rows_data = [
                ("버전",       ver,                                                    "#00ccff" if is_v else "#44cc77"),
                ("시드",       "$"+f"{get_seed(ticker):,.0f}",                         "#ddd"),
                ("분할수",     str(int(get_split(ticker)))+"회",                        "#ddd"),
                ("목표수익률", f"{get_target(ticker):.1f}%",                            "#4ade80"),
                ("스나이퍼배율","x"+f"{get_sniper(ticker):.2f}",                        "#fbbf24"),
                ("리버스",     "🔄 ON" if rv.get("is_active") else "✅ OFF",
                               "#ff6666" if rv.get("is_active") else "#44cc77"),
            ]
            if rv.get("is_active"):
                rows_data += [
                    ("리버스 D+", "D+"+str(rv.get("day_count",0)), "#ffaa66"),
                    ("탈출 목표", f"{rv.get('exit_target',0.0):.1f}%", "#ffcc44"),
                ]

            inner = ""
            for i,(lbl,val,col) in enumerate(rows_data):
                bg2 = "#0d0d1c" if i%2==0 else "#111120"
                inner += H("div","display:flex;justify-content:space-between;align-items:center;padding:.7rem 1rem;background:"+bg2+";",
                    H("span","font-size:.88rem;color:#aaa;font-weight:500;",lbl) +
                    H("span","font-family:'Space Mono',monospace;font-size:.88rem;font-weight:700;color:"+col+";",val)
                )

            vwap_extra = ""
            if is_v:
                vwap_extra = H("span","background:#001a3a;border:1px solid #0055aa;border-radius:6px;padding:.1rem .45rem;font-size:.73rem;font-weight:700;color:#44aaff;margin-left:.4rem;","🌊 VWAP 자율주행","")

            head = H("div","padding:.65rem 1rem;background:#0a0a18;border-bottom:1px solid #1a1a30;display:flex;align-items:center;",
                H("span","font-size:.92rem;font-weight:700;color:#ccc;",ticker) + vwap_extra)

            st.markdown(
                H("div","background:#111120;border:1px solid #1e1e35;border-radius:14px;overflow:hidden;margin-bottom:.8rem;",head+inner),
                unsafe_allow_html=True
            )

        st.info("💡 설정 변경은 텔레그램 봇 명령어(/seed /mode /ticker 등)를 이용하세요.")

    # ════════════════════════════════════════════════════════
    # 탭4: 역사관
    # ════════════════════════════════════════════════════════
    with tab4:
        st.markdown(H("div","font-size:1rem;font-weight:700;color:#ddd;margin:.4rem 0 .8rem;","🏆 졸업 명예의 전당"), unsafe_allow_html=True)

        if not history:
            st.markdown(card(
                H("div","text-align:center;padding:1.5rem 0;",
                    H("div","font-size:1rem;color:#7788aa;","🎓 아직 완료된 사이클이 없습니다.") +
                    H("div","font-size:.88rem;color:#5566aa;margin-top:.3rem;","첫 번째 졸업을 기다리는 중...")
                )
            ), unsafe_allow_html=True)
        else:
            total_p = sum(h.get('profit',0) for h in history)
            st.markdown(
                H("div","background:#0a1a0a;border:1px solid #1a351a;border-radius:14px;padding:1rem;text-align:center;margin-bottom:.8rem;",
                    H("div","font-size:.85rem;color:#7799aa;margin-bottom:.2rem;font-weight:500;","📈 누적 실현 수익") +
                    H("div","font-family:'Space Mono',monospace;font-size:1.6rem;font-weight:700;color:#4ade80;","+$"+f"{total_p:,.2f}")
                ),
                unsafe_allow_html=True
            )
            for h in reversed(history):
                profit = h.get('profit',0); yld = h.get('yield',0)
                pc = "#4ade80" if profit>=0 else "#ff6666"
                st.markdown(
                    H("div","background:#111120;border:1px solid #1e1e35;border-radius:12px;padding:.85rem 1.1rem;margin-bottom:.5rem;display:flex;justify-content:space-between;align-items:center;",
                        H("div","",
                            H("div","font-weight:700;color:#ddd;font-size:.92rem;","#"+str(h.get('id',''))+" "+str(h.get('ticker',''))) +
                            H("div","font-size:.82rem;color:#7788aa;margin-top:.15rem;",str(h.get('end_date','-'))+" 졸업")
                        ) +
                        H("div","text-align:right;",
                            H("div","font-family:'Space Mono',monospace;font-weight:700;color:"+pc+";font-size:.95rem;","+$"+f"{profit:,.2f}") +
                            H("div","font-size:.83rem;color:"+pc+";margin-top:.1rem;",f"{yld:.2f}%")
                        )
                    ),
                    unsafe_allow_html=True
                )

    # 자동 갱신
    if auto:
        kst = pytz.timezone('Asia/Seoul')
        ts = datetime.datetime.now(kst).strftime("%Y.%m.%d %H:%M:%S")
        st.markdown(
            H("div","text-align:right;color:#445566;font-size:.78rem;margin-top:.5rem;","🕐 "+ts+" KST | 60초 후 자동 갱신"),
            unsafe_allow_html=True
        )
        time.sleep(60)
        st.rerun()

# ════════════════════════════════════════════════════════════════
# 진입점
# ════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    show_login()
else:
    show_dashboard()
