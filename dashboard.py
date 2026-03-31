# ==========================================================
# [dashboard.py] ❄️ Snowball TS 웹 대시보드 v5
# 실행: streamlit run dashboard.py
# 변경: 모바일 폰트 크기 확대 + 전체 가독성/대비 개선
# ==========================================================

import streamlit as st
import json, os, math, datetime, pytz, time
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Snowball TS",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# ── 공통 베이스 CSS ───────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=Space+Mono:wght@400;700&display=swap');

/* ── 모바일 뷰포트 최적화 ── */
@viewport { width: device-width; zoom: 1; }

/* ── 전역 기본 폰트 크기: 모바일에서 16px 기준으로 rem 계산 ── */
html {
    font-size: 19px !important;   /* 기준 (모바일 최적화) */
}

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stApp"] {
    background: #0d0d0f !important;
    color: #e8e8e8 !important;
    font-family: 'Noto Sans KR', sans-serif !important;
    -webkit-text-size-adjust: 100% !important;  /* iOS 자동 폰트 크기 조정 방지 */
}

/* ── Streamlit 기본 UI 숨김 ── */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
section[data-testid="stSidebar"],
.stDeployButton { display: none !important; }
#MainMenu, footer, header { visibility: hidden !important; }

/* ── 스크롤바 ── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #111; }
::-webkit-scrollbar-thumb { background: #3a3a55; border-radius: 4px; }

/* ── 탭 ── */
.stTabs [data-baseweb="tab-list"] {
    background: #111120 !important;
    border-radius: 12px !important;
    padding: 4px !important;
    gap: 4px !important;
}
.stTabs [data-baseweb="tab"] {
    color: #888 !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    font-family: 'Noto Sans KR', sans-serif !important;
    font-size: 0.95rem !important;       /* ↑ 탭 글자 크기 */
    padding: 0.5rem 0.8rem !important;   /* ↑ 탭 터치 영역 */
}
.stTabs [aria-selected="true"] {
    background: #1e1e35 !important;
    color: #fff !important;
    border-bottom: 2px solid #4488ff !important;
}

/* ── 버튼 ── */
.stButton > button {
    background: #1e1e2e !important;
    color: #ccc !important;
    border: 1px solid #2a2a45 !important;
    border-radius: 10px !important;
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;       /* ↑ */
    padding: 0.55rem 1rem !important;    /* ↑ 터치 영역 */
    transition: all 0.15s ease !important;
    min-height: 44px !important;         /* 모바일 최소 터치 높이 */
}
.stButton > button:hover {
    background: #252540 !important;
    border-color: #4444aa !important;
    color: #eee !important;
}

/* ── 토글 ── */
.stToggle label,
[data-testid="stToggleLabel"] {
    color: #bbb !important;              /* ↑ #aaa → #bbb */
    font-size: 0.92rem !important;       /* ↑ */
}

/* ── 텍스트 입력 ── */
.stTextInput > div > div > input {
    background: #1c1c28 !important;
    border: 1px solid #2a2a45 !important;
    border-radius: 10px !important;
    color: #e8e8e8 !important;
    font-family: 'Noto Sans KR', sans-serif !important;
    font-size: 1rem !important;          /* ↑ */
    padding: 0.7rem 1rem !important;     /* ↑ */
    min-height: 44px !important;
}
.stTextInput > div > div > input::placeholder {
    color: #555577 !important;
}
.stTextInput > div > div > input:focus {
    border-color: #3b6ff5 !important;
    box-shadow: 0 0 0 3px rgba(59,111,245,0.2) !important;
}

/* ── expander ── */
[data-testid="stExpander"] {
    background: #111118 !important;
    border: 1px solid #22223a !important;
    border-radius: 12px !important;
}
[data-testid="stExpander"] summary {
    color: #bbb !important;
    font-size: 0.92rem !important;       /* ↑ */
}

/* ── info 박스 ── */
[data-testid="stAlert"] {
    background: #111120 !important;
    border: 1px solid #22223a !important;
    border-radius: 10px !important;
    color: #bbb !important;              /* ↑ #aaa → #bbb */
    font-size: 0.92rem !important;       /* ↑ */
}

/* ── Metric ── */
div[data-testid="stMetric"] {
    background: #12121e;
    border: 1px solid #22223a;
    border-radius: 12px;
    padding: 0.9rem 1rem;
}
div[data-testid="stMetricValue"] {
    font-size: 1.15rem !important;
    color: #fff !important;
}
div[data-testid="stMetricLabel"] {
    color: #aaa !important;              /* ↑ */
    font-size: 0.82rem !important;       /* ↑ */
}
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# 데이터 헬퍼
# ════════════════════════════════════════════════════════
DATA_DIR = "data"

def load_json(f, d=None):
    p = os.path.join(DATA_DIR, f)
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as fp:
                return json.load(fp)
        except: pass
    return d if d is not None else {}

def get_seed(t):    return float(load_json("seed_config.json",   {"SOXL":6720.0,"TQQQ":6720.0}).get(t,6720.0))
def get_split(t):   return float(load_json("split_config.json",  {"SOXL":40.0,"TQQQ":40.0}).get(t,40.0))
def get_target(t):  return float(load_json("profit_config.json", {"SOXL":12.0,"TQQQ":10.0}).get(t,12.0))
def get_version(t): return load_json("version_config.json",      {"SOXL":"V14","TQQQ":"V14"}).get(t,"V14")
def get_tickers():  return load_json("active_tickers.json",      ["SOXL","TQQQ"])
def get_ledger():   return load_json("manual_ledger.json",       [])
def get_history():  return load_json("manual_history.json",      [])
def get_sniper(t):
    d = {"SOXL":1.0,"TQQQ":0.9}
    return float(load_json("sniper_multiplier.json", d).get(t, d.get(t,1.0)))
def get_reverse(t): return load_json("reverse_config.json",{}).get(t,{"is_active":False,"day_count":0,"exit_target":0.0})
def get_escrow(t):  return float(load_json("trade_locks.json",{}).get(f"ESCROW_{t}",0.0))

def calc_holdings(ticker, ledger):
    qty, invested = 0, 0.0
    for r in ledger:
        if r.get('ticker') != ticker: continue
        q, p = int(r.get('qty',0)), float(r.get('price',0))
        if r.get('side') == 'BUY':
            invested += q*p; qty += q
        else:
            if qty > 0: invested -= q*(invested/qty)
            qty -= q
    return qty, (invested/qty if qty>0 else 0.0)

def calc_v14(ticker, ledger):
    seed=get_seed(ticker); split=get_split(ticker)
    base=seed/split if split>0 else 1
    recs=[r for r in ledger if r.get('ticker')==ticker]
    h,inv,rem=0,0.0,seed
    for r in recs:
        q,p=int(r.get('qty',0)),float(r.get('price',0))
        if r.get('side')=='BUY':
            inv+=q*p; h+=q; rem-=q*p
        else:
            if h>0: inv-=q*(inv/h)
            h-=q; rem+=q*p
    avg=inv/h if h>0 else 0.0
    t=(h*avg)/base if base>0 else 0.0
    budget=rem/max(1.0,split-t) if h>0 else base
    if h==0: t=0.0
    return max(0.0,round(t,4)), max(0.0,budget), max(0.0,rem)

@st.cache_data(ttl=60)
def get_price(ticker):
    try:
        import yfinance as yf
        h=yf.Ticker(ticker).history(period="2d")
        if len(h)>=2:
            return {"price":float(h['Close'].iloc[-1]),"prev":float(h['Close'].iloc[-2]),
                    "high":float(h['High'].iloc[-1]),"low":float(h['Low'].iloc[-1])}
    except: pass
    return {"price":0.0,"prev":0.0,"high":0.0,"low":0.0}

def get_first_ledger_date(ticker, ledger):
    recs = [r for r in ledger if r.get('ticker')==ticker and r.get('side')=='BUY']
    if recs:
        return sorted([r.get('date','') for r in recs])[0]
    return ""


# ════════════════════════════════════════════════════════
# 🔐 로그인 화면
# ════════════════════════════════════════════════════════
def show_login():
    st.markdown("""
    <style>
    .block-container {
        padding: 0 !important; max-width: 100% !important;
        min-height: 100vh !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }
    .login-btn button {
        background: linear-gradient(135deg,#1a6fff,#0d4fd4) !important;
        color: #fff !important; border: none !important;
        border-radius: 12px !important; font-weight: 700 !important;
        font-size: 1.05rem !important;
        box-shadow: 0 4px 20px rgba(26,111,255,0.4) !important;
        min-height: 48px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 1.05, 1])
    with center:
        # ── 방패 카드 ───────────────────────────────────
        st.markdown("""
<div style="text-align:center; padding:2.5rem 2rem 2rem;
    background:linear-gradient(160deg,#0e0e1a,#13131f,#0a0a14);
    border:1px solid #22223a; border-radius:22px; margin-bottom:1.5rem;
    box-shadow:0 0 60px rgba(30,60,160,.12),0 4px 30px rgba(0,0,0,.5);
    position:relative; overflow:hidden;">
  <div style="position:absolute;top:-30px;left:50%;transform:translateX(-50%);
    width:220px;height:220px;
    background:radial-gradient(ellipse,rgba(30,80,220,.2) 0%,transparent 70%);
    pointer-events:none;"></div>

  <!-- 방패 SVG -->
  <div style="margin:0 auto 1.5rem;width:100px;height:100px;">
    <div style="width:100px;height:100px;
      background:radial-gradient(ellipse at 35% 35%,#1e3a8a 0%,#0d1f5c 50%,#060d2e 100%);
      border-radius:50%; display:flex;align-items:center;justify-content:center;
      box-shadow:0 0 0 1px rgba(60,100,255,.3),0 0 25px rgba(30,80,220,.4),0 0 55px rgba(30,80,220,.18),inset 0 1px 1px rgba(255,255,255,.1);">
      <svg viewBox="0 0 64 72" width="56" height="62" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="sg1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#ccddf5"/><stop offset="40%" stop-color="#8aaad8"/><stop offset="100%" stop-color="#4466a8"/>
          </linearGradient>
          <linearGradient id="sg2" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#e86040"/><stop offset="100%" stop-color="#b02818"/>
          </linearGradient>
          <clipPath id="sc2"><path d="M32 2 L58 12 L58 38 Q58 58 32 70 Q6 58 6 38 L6 12 Z"/></clipPath>
        </defs>
        <path d="M32 2 L58 12 L58 38 Q58 58 32 70 Q6 58 6 38 L6 12 Z" fill="url(#sg1)" stroke="rgba(200,220,255,.6)" stroke-width="1.2"/>
        <rect x="-10" y="18" width="84" height="26" fill="url(#sg2)" transform="rotate(-35,32,36)" clip-path="url(#sc2)" opacity=".9"/>
        <path d="M32 6 L54 14 L54 38 Q54 55 32 66 Q10 55 10 38 L10 14 Z" fill="none" stroke="rgba(255,255,255,.18)" stroke-width=".8"/>
      </svg>
    </div>
  </div>

  <!-- 텍스트 -->
  <div style="font-family:'Space Mono',monospace;font-size:.95rem;font-weight:700;
    color:#5599ff;letter-spacing:.28em;margin-bottom:.7rem;
    text-shadow:0 0 22px rgba(68,136,255,.6);">SNIPER COMMAND</div>

  <div style="font-size:1.45rem;font-weight:900;color:#fff;margin-bottom:.6rem;
    letter-spacing:.02em;">✨ 듀얼코어 하이브리드 ✨</div>

  <div style="display:inline-block;background:rgba(255,255,255,.06);
    border:1px solid rgba(255,255,255,.12);border-radius:20px;
    padding:.25rem 1rem;font-size:.82rem;color:#8899bb;
    margin-bottom:.5rem;letter-spacing:.03em;">V21.5 다이내믹 스노우볼 TrueSync</div>

  <div style="font-size:.88rem;color:#ee5555;margin-top:.4rem;font-weight:500;">
    인가된 총사령관만 접근을 허가합니다.</div>
</div>
""", unsafe_allow_html=True)

        # ── 입력 필드 ────────────────────────────────────
        st.markdown('<p style="color:#99aacc;font-size:.9rem;font-weight:600;margin-bottom:.25rem;">총사령관 ID</p>', unsafe_allow_html=True)
        st.text_input("총사령관 ID", placeholder="ID를 입력하세요 (pipiosbot 또는 hambot)",
                      key="login_id", label_visibility="collapsed")

        st.markdown('<p style="color:#99aacc;font-size:.9rem;font-weight:600;margin:.65rem 0 .25rem;">보안 암호를 입력하세요</p>', unsafe_allow_html=True)
        password = st.text_input("보안 암호", type="password", placeholder="••••••••",
                                 key="login_pw", label_visibility="collapsed")

        st.markdown('<div style="height:.6rem;"></div>', unsafe_allow_html=True)

        # ── 접속 버튼 ────────────────────────────────────
        st.markdown('<div class="login-btn">', unsafe_allow_html=True)
        if st.button("🚀  사령부 접속", use_container_width=True, key="login_btn"):
            secret = os.getenv("DASHBOARD_PASSWORD", "snowball2025")
            if password == secret:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.markdown("""
<div style="background:rgba(200,40,40,.18);border:1px solid rgba(240,80,80,.4);
  border-radius:10px;padding:.75rem 1rem;color:#ff8888;
  font-size:.95rem;text-align:center;margin-top:.6rem;font-weight:500;">
  ❌ 접근 거부 — 보안 암호가 올바르지 않습니다.
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # ── 힌트 ─────────────────────────────────────────
        st.markdown("""
<div style="text-align:center;margin-top:.9rem;color:#5566aa;font-size:.82rem;line-height:1.8;">
  기본 암호:
  <code style="color:#7788cc;background:rgba(80,100,200,.15);padding:.15rem .5rem;border-radius:4px;font-size:.82rem;">snowball2025</code><br>
  .env 에
  <code style="color:#7788cc;background:rgba(80,100,200,.15);padding:.15rem .5rem;border-radius:4px;font-size:.82rem;">DASHBOARD_PASSWORD=암호</code> 로 변경
</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# 📊 메인 대시보드
# ════════════════════════════════════════════════════════
def show_dashboard():
    st.markdown("""
    <style>
    .block-container {
        padding: 1rem 1rem 2rem !important;
        max-width: 620px !important;
        margin: 0 auto !important;
    }
    </style>
    """, unsafe_allow_html=True)

    ledger  = get_ledger()
    history = get_history()
    tickers = get_tickers()

    # ── 헤더 ─────────────────────────────────────────────
    st.markdown("""
<div style="display:flex;align-items:center;gap:.7rem;padding:.5rem 0 .3rem;">
  <span style="font-size:1.8rem;">☃️</span>
  <span style="font-size:1.6rem;font-weight:900;color:#fff;">Snowball TS</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("""
<div style="display:inline-block;
  background:linear-gradient(90deg,#2a2010,#3a2e08);
  border:1px solid #5a4a20;border-radius:22px;
  padding:.38rem 1.3rem;font-size:.95rem;font-weight:700;
  color:#e0b830;margin:.3rem 0 .7rem;
  box-shadow:0 2px 14px rgba(180,140,0,.22);">✨ 방치형 자동매매 ✨</div>
""", unsafe_allow_html=True)

    col_tog, col_user, col_out = st.columns([1.3, 1.8, 0.7])
    with col_tog:
        auto = st.toggle("🕐 1분 자동 갱신", value=True, key="auto_refresh")
    with col_user:
        admin_id = os.getenv("ADMIN_CHAT_ID", "")
        bot_name = "pipiosbot" if admin_id else "hambot"
        st.markdown(f"""
<div style="background:#1a1a2a;border:1px solid #28284a;border-radius:10px;
  padding:.45rem .9rem;font-size:.88rem;color:#ccc;
  display:flex;align-items:center;gap:.45rem;">
  <span>🤖</span>
  <span style="color:#ddd;font-weight:600;">{bot_name}(으)로 전환</span>
</div>""", unsafe_allow_html=True)
    with col_out:
        if st.button("🚪", key="logout_btn", help="로그아웃"):
            st.session_state.logged_in = False
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["  📊 현황판  ", "  ⚙️ 조종실  ", "  🏆 역사관  "])


    # ════════════════════════════════════════════════════
    # 탭1: 현황판
    # ════════════════════════════════════════════════════
    with tab1:

        # ── 계좌 요약 계산 ────────────────────────────────
        # 계좌 총액  = Σ(예수금잔액 + 보유주식 평가금액)
        # 가용 예산  = Σ(예수금잔액) − 에스크로
        # 예수금잔액 = 시드 − 총매수금액 + 총매도금액  ← calc_v14의 rem 값
        total_cash   = 0.0   # 예수금잔액 합계 (시드 - 매수 + 매도)
        total_eval   = 0.0   # 보유주식 평가금액 합계
        total_escrow = 0.0   # 에스크로 합계

        for t in tickers:
            _, _, rem = calc_v14(t, ledger)          # rem = 예수금잔액
            q, avg_   = calc_holdings(t, ledger)
            pd_       = get_price(t)
            curr_p    = pd_["price"] if pd_["price"] > 0 else avg_
            eval_val  = q * curr_p                   # 보유주식 평가금액
            esc       = get_escrow(t)

            total_cash   += rem
            total_eval   += eval_val
            total_escrow += esc

        # 총 매수금액 = Σ(수량 × 평단가)
        total_invested = sum(
            calc_holdings(t, ledger)[0] * calc_holdings(t, ledger)[1]
            for t in tickers
        )
        total_account = total_cash + total_eval       # 계좌 총액
        avail         = max(0, total_cash - total_escrow)  # 가용 예산

        st.markdown(f"""
<div style="background:#111120;border:1px solid #22223a;border-radius:14px;
  overflow:hidden;margin:.5rem 0 1.1rem;">
  <div style="display:flex;justify-content:space-between;align-items:center;
    padding:.9rem 1.2rem;border-bottom:1px solid #1a1a2e;">
    <span style="font-size:.95rem;color:#aaa;font-weight:500;">💵 계좌 총액</span>
    <div style="text-align:right;">
      <div style="font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:#fff;">${total_account:,.2f}</div>
      <div style="font-size:.78rem;color:#5566aa;margin-top:.1rem;">
        예수금 ${total_cash:,.2f} + 평가 ${total_eval:,.2f}
      </div>
    </div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center;
    padding:.9rem 1.2rem;border-bottom:1px solid #1a1a2e;">
    <span style="font-size:.95rem;color:#aaa;font-weight:500;">📦 총 매수금액</span>
    <div style="text-align:right;">
      <div style="font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:#ddd;">${total_invested:,.2f}</div>
      <div style="font-size:.78rem;color:#5566aa;margin-top:.1rem;">수량 × 평단가 합계</div>
    </div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center;
    padding:.9rem 1.2rem;border-bottom:1px solid #1a1a2e;">
    <span style="font-size:.95rem;color:#aaa;font-weight:500;">🔒 에스크로</span>
    <span style="font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;
      color:{'#ff6666' if total_escrow>0 else '#666688'};">{'−' if total_escrow>0 else ''}${total_escrow:,.2f}</span>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center;
    padding:.9rem 1.2rem;">
    <div>
      <span style="font-size:.95rem;color:#aaa;font-weight:500;">✅ 가용 예산</span>
      <div style="font-size:.78rem;color:#5566aa;margin-top:.1rem;">예수금 − 에스크로</div>
    </div>
    <span style="font-family:'Space Mono',monospace;font-size:1.05rem;font-weight:700;color:#4ade80;">${avail:,.2f}</span>
  </div>
</div>
""", unsafe_allow_html=True)

        # ── 종목 카드 루프 ────────────────────────────────
        for ticker in tickers:
            qty, avg  = calc_holdings(ticker, ledger)
            pd        = get_price(ticker)
            curr      = pd["price"];  prev_c = pd["prev"]
            high      = pd["high"];   low    = pd["low"]
            chg       = ((curr-prev_c)/prev_c*100) if prev_c>0 else 0.0
            high_pct  = ((high-prev_c)/prev_c*100) if prev_c>0 else 0.0
            low_pct   = ((low-prev_c)/prev_c*100)  if prev_c>0 else 0.0

            version   = get_version(ticker)
            split     = get_split(ticker)
            target    = get_target(ticker)
            seed      = get_seed(ticker)
            rev       = get_reverse(ticker)
            is_rev    = rev.get("is_active", False)
            escrow    = get_escrow(ticker)
            sniper_m  = get_sniper(ticker)

            t_val, budget, _ = calc_v14(ticker, ledger)
            progress  = min(100.0, round(t_val/split*100, 1)) if split>0 else 0.0
            dep       = 2.0/split if split>0 else 0.1
            star_r    = (target/100) - (target/100)*dep*t_val
            star_p    = math.ceil(avg*(1+star_r)*100)/100.0 if avg>0 else 0.0
            sniper_l  = math.floor(avg*(1-sniper_m*0.10)*100)/100.0 if avg>0 else 0.0
            q_qty     = math.ceil(qty/4) if qty>0 else 0
            N         = math.floor(budget/avg) if avg>0 else 0
            invest_a  = qty*avg
            start_date = get_first_ledger_date(ticker, ledger)

            chg_col   = "#ff6666" if chg>=0 else "#60a5fa"
            chg_sign  = "+" if chg>=0 else ""
            ver_color = "#ff6666" if is_rev else "#33cc66"

            # ── 종목 카드 상단 (웹앱3 스타일) ──────────
            st.markdown(f"""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:16px;
  padding:1.3rem 1.3rem .9rem;margin-bottom:.4rem;">

  <!-- 버전 배지 + 진행도 -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.7rem;">
    <div style="background:#1a2a1a;border:1px solid {ver_color}55;border-radius:8px;
      padding:.2rem .7rem;font-size:.82rem;font-weight:700;color:{ver_color};">Ver {version}</div>
    <div style="text-align:right;">
      <div style="font-size:.82rem;color:#999;line-height:1.2;font-weight:500;">진행도</div>
      <div style="font-family:'Space Mono',monospace;font-size:1.4rem;font-weight:700;color:#fff;line-height:1.1;">{progress}%</div>
      <div style="font-size:.8rem;color:#8888aa;">{t_val:.4f}T / {int(split)}</div>
    </div>
  </div>

  <!-- 티커명 크게 -->
  <div style="font-size:2.4rem;font-weight:900;color:#fff;line-height:1;margin-bottom:.5rem;
    letter-spacing:.02em;">{ticker}</div>

  <!-- 현재가 -->
  <div style="font-family:'Space Mono',monospace;font-size:1.9rem;font-weight:700;
    color:{chg_col};line-height:1.1;">${curr:,.2f}</div>
  <div style="font-size:.95rem;color:{chg_col};margin-bottom:.9rem;font-weight:500;">
    ({chg_sign}{chg:.2f}%)</div>

  <!-- 최고/최저 박스 -->
  <div style="display:flex;gap:.6rem;margin-bottom:.9rem;">
    <div style="flex:1;background:#1c0e0e;border:1px solid #441a1a;border-radius:9px;
      padding:.5rem .8rem;">
      <span style="font-size:.85rem;color:#cc8888;">최고 </span>
      <span style="font-size:.9rem;color:#ff8888;font-weight:700;">${high:,.2f}</span>
      <span style="font-size:.82rem;color:#ff8888;"> ({'+' if high_pct>=0 else ''}{high_pct:.2f}%)</span>
    </div>
    <div style="flex:1;background:#0a0e1e;border:1px solid #1a2855;border-radius:9px;
      padding:.5rem .8rem;">
      <span style="font-size:.85rem;color:#8899cc;">최저 </span>
      <span style="font-size:.9rem;color:#60a5fa;font-weight:700;">${low:,.2f}</span>
      <span style="font-size:.82rem;color:#60a5fa;"> ({'+' if low_pct>=0 else ''}{low_pct:.2f}%)</span>
    </div>
  </div>

  <!-- 시작일 -->
  {'<div style="font-size:.88rem;color:#7788aa;margin-bottom:.9rem;font-weight:500;">📅 ' + start_date + ' ~</div>' if start_date else ''}

  <!-- 기본 정보 -->
  <div style="background:#0d0d1c;border:1px solid #1a1a30;border-radius:11px;padding:.9rem 1rem;margin-bottom:.6rem;">
    <div style="font-size:.88rem;font-weight:700;color:#aaa;margin-bottom:.7rem;border-bottom:1px solid #1a1a30;padding-bottom:.4rem;">기본 정보</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;">
      <div>
        <div style="font-size:.8rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">총 시드</div>
        <div style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;color:#ddd;">${seed:,.2f}</div>
      </div>
      <div>
        <div style="font-size:.8rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">사용 중인 금고</div>
        <div style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;
          color:{'#ff7777' if escrow>0 else '#666688'};">${escrow:,.2f}</div>
      </div>
      <div>
        <div style="font-size:.8rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">오늘 예산</div>
        <div style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;color:#4ade80;">${budget:,.2f}</div>
      </div>
    </div>
  </div>

  <!-- 매입 정보 -->
  <div style="background:#0d0d1c;border:1px solid #1a1a30;border-radius:11px;padding:.9rem 1rem;">
    <div style="font-size:.88rem;font-weight:700;color:#aaa;margin-bottom:.7rem;border-bottom:1px solid #1a1a30;padding-bottom:.4rem;">매입 정보</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;">
      <div>
        <div style="font-size:.8rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">평단가</div>
        <div style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;color:#ddd;">${avg:,.2f}</div>
      </div>
      <div>
        <div style="font-size:.8rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">보유 수량</div>
        <div style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;color:#ddd;">{qty}주</div>
      </div>
      <div>
        <div style="font-size:.8rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">매입 금액</div>
        <div style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;color:#fbbf24;">${invest_a:,.2f}</div>
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

            # ── 무매 공식 + 스나이퍼 + 주문 계획 (웹앱4) ─
            if avg > 0:
                p_avg    = round(avg - 0.01, 2)
                p_star   = round(star_p - 0.01, 2)
                q_star   = math.floor(budget/p_star) if p_star>0 else 0
                q_sell   = math.ceil(qty/4) if qty>0 else 0
                base_n   = math.floor(budget/avg) if avg>0 else 0
                jup_orders = []
                for i in range(1, 6):
                    jp = math.floor(budget/(base_n+i)*100)/100.0 if (base_n+i)>0 else 0
                    jp = min(jp, avg-0.01)
                    if jp > 0.01:
                        jup_orders.append(jp)
                jup_min  = min(jup_orders) if jup_orders else 0
                jup_max  = max(jup_orders) if jup_orders else 0
                phase    = "전반전" if t_val < split/2 else "후반전"

                st.markdown(f"""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:16px;
  padding:1.1rem 1.3rem;margin-bottom:.4rem;">

  <!-- 무매 공식 -->
  <div style="background:#0d0d1c;border:1px solid #1a1a30;border-radius:11px;
    padding:.9rem 1rem;margin-bottom:.9rem;">
    <div style="font-size:.88rem;font-weight:700;color:#aaa;
      margin-bottom:.7rem;border-bottom:1px solid #1a1a30;padding-bottom:.4rem;">📐 무매 공식</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;text-align:center;">
      <div>
        <div style="font-size:.82rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">T</div>
        <div style="font-family:'Space Mono',monospace;font-size:.95rem;font-weight:700;color:#ddd;">{t_val:.4f}</div>
      </div>
      <div>
        <div style="font-size:.82rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">목표 수익률</div>
        <div style="font-family:'Space Mono',monospace;font-size:.95rem;font-weight:700;color:#4ade80;">{target:.1f}%</div>
      </div>
      <div>
        <div style="font-size:.82rem;color:#8899aa;margin-bottom:.2rem;font-weight:500;">별%가격</div>
        <div style="font-family:'Space Mono',monospace;font-size:.95rem;font-weight:700;color:#fbbf24;">${star_p:,.2f}</div>
      </div>
    </div>
  </div>

  <!-- 스나이퍼 방어선 -->
  {f'''<div style="background:#180a0a;border:1px solid #3a1818;border-radius:11px;
    padding:.9rem 1rem;margin-bottom:.9rem;">
    <div style="font-size:.88rem;color:#cc9999;font-weight:600;margin-bottom:.45rem;">
      🎯 스나이퍼 동적 방어선
      <span style="font-size:.82rem;color:#998888;font-weight:400;"> (−{sniper_m*10:.2f}% 하락 시)</span>
    </div>
    <div style="font-family:'Space Mono',monospace;font-size:1.0rem;font-weight:700;
      color:#ff7777;margin-bottom:.55rem;">${sniper_l:,.2f} 이하 지정가 장전 대기 중</div>
    <div style="font-size:.9rem;color:#e0c050;font-weight:600;">
      🦅 쿼터 스나이퍼: ${star_p:,.2f} 이상 대기</div>
  </div>''' if qty>0 else ''}

  <!-- 주문 계획 -->
  {f'''<div style="background:#0d0d1c;border:1px solid #1a1a30;border-radius:11px;padding:.9rem 1rem;">
    <div style="display:flex;justify-content:space-between;align-items:center;
      margin-bottom:.8rem;border-bottom:1px solid #1a1a30;padding-bottom:.5rem;">
      <div style="font-size:.88rem;font-weight:700;color:#aaa;">📋 주문 계획</div>
      <div style="display:flex;gap:.4rem;align-items:center;">
        <span style="background:#182818;border:1px solid #33aa5540;border-radius:6px;
          padding:.12rem .5rem;font-size:.8rem;font-weight:700;color:#33cc66;">Ver {version}</span>
        <span style="font-size:.82rem;color:#8899aa;font-weight:500;">[{phase}]</span>
      </div>
    </div>
    <div style="display:flex;align-items:flex-start;gap:.6rem;margin-bottom:.55rem;">
      <span style="color:#ff6666;font-size:.95rem;line-height:1.5;">🔴</span>
      <div>
        <div style="font-size:.9rem;font-weight:700;color:#ddd;">⚓ 평단매수</div>
        <div style="font-size:.85rem;color:#99aacc;margin-top:.1rem;">└ ${p_avg:,.2f} × {N}주 (LOC)</div>
      </div>
    </div>
    <div style="display:flex;align-items:flex-start;gap:.6rem;margin-bottom:.55rem;">
      <span style="color:#ff6666;font-size:.95rem;line-height:1.5;">🔴</span>
      <div>
        <div style="font-size:.9rem;font-weight:700;color:#ddd;">💫 별값매수</div>
        <div style="font-size:.85rem;color:#99aacc;margin-top:.1rem;">└ ${p_star:,.2f} × {q_star}주 (LOC)</div>
      </div>
    </div>
    <div style="display:flex;align-items:flex-start;gap:.6rem;">
      <span style="color:#60a5fa;font-size:.95rem;line-height:1.5;">🔵</span>
      <div>
        <div style="font-size:.9rem;font-weight:700;color:#ddd;">⭐ 별값매도</div>
        <div style="font-size:.85rem;color:#99aacc;margin-top:.1rem;">└ ${star_p:,.2f} × {q_sell}주 (LOC)</div>
      </div>
    </div>
  </div>''' if not is_rev and qty>0 else ''}

</div>
""", unsafe_allow_html=True)

            # ── 줍줍 + 장마감 + 거래 내역 (웹앱5) ──────
            recs = sorted([r for r in ledger if r.get('ticker')==ticker],
                          key=lambda x: x.get('id',0), reverse=True)

            if avg > 0 and jup_orders and qty > 0:
                st.markdown(f"""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:14px;
  padding:1rem 1.3rem;margin-bottom:.4rem;">
  <div style="display:flex;align-items:flex-start;gap:.6rem;">
    <span style="font-size:.95rem;color:#aaa;line-height:1.5;">🧹</span>
    <div>
      <div style="font-size:.9rem;font-weight:700;color:#ddd;">줍줍 ({len(jup_orders)}개)</div>
      <div style="font-size:.85rem;color:#99aacc;margin-top:.1rem;">└ ${jup_max:,.2f} ~ ${jup_min:,.2f} (LOC)</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

            # 장마감 상태 자동 감지
            try:
                import pandas_market_calendars as mcal
                est = pytz.timezone('US/Eastern')
                nyse = mcal.get_calendar('NYSE')
                today_est = datetime.datetime.now(est).date()
                sched = nyse.schedule(start_date=today_est, end_date=today_est)
                if not sched.empty:
                    mopen  = sched.iloc[0]['market_open'].astimezone(est)
                    mclose = sched.iloc[0]['market_close'].astimezone(est)
                    is_trading = mopen <= datetime.datetime.now(est) < mclose
                else:
                    is_trading = False
            except:
                is_trading = False

            if not is_trading:
                st.markdown("""
<div style="background:#1c0a0a;border:1px solid #3a1a1a;border-radius:11px;
  padding:.7rem 1.1rem;margin-bottom:.4rem;
  display:flex;align-items:center;gap:.6rem;">
  <span style="font-size:1.1rem;">⛔</span>
  <span style="font-size:.92rem;color:#cc9999;font-weight:500;">장마감 또는 애프터마켓 (현재 주문 불가)</span>
</div>
""", unsafe_allow_html=True)

            # 거래 내역 테이블
            if recs:
                buy_t  = sum(r['price']*r['qty'] for r in recs if r.get('side')=='BUY')
                sell_t = sum(r['price']*r['qty'] for r in recs if r.get('side')=='SELL')

                rows_html = ""
                for r in recs[:20]:
                    side     = r.get('side','')
                    side_col = "#ff7777" if side=="BUY" else "#60a5fa"
                    side_lbl = "매수" if side=="BUY" else "매도"
                    d_raw    = r.get('date','')
                    date_str = d_raw[-5:].replace('-','.') if len(d_raw)>=5 else d_raw
                    rows_html += f"""
<tr>
  <td style="padding:.5rem .55rem;color:#8899aa;font-size:.82rem;border-bottom:1px solid #181828;">{r.get('id','')}</td>
  <td style="padding:.5rem .55rem;color:{side_col};font-weight:700;font-size:.88rem;border-bottom:1px solid #181828;">{side_lbl}</td>
  <td style="padding:.5rem .55rem;color:#aabbcc;font-size:.85rem;border-bottom:1px solid #181828;">{date_str}</td>
  <td style="padding:.5rem .55rem;font-family:'Space Mono',monospace;color:#ddd;font-size:.85rem;border-bottom:1px solid #181828;">${r.get('price',0):,.2f}</td>
  <td style="padding:.5rem .55rem;font-family:'Space Mono',monospace;color:#ddd;font-size:.85rem;border-bottom:1px solid #181828;">{r.get('qty',0)}주</td>
</tr>"""

                st.markdown(f"""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:16px;
  padding:1.1rem 1.3rem;margin-bottom:.8rem;">
  <div style="font-size:.92rem;font-weight:700;color:#bbb;margin-bottom:.2rem;">
    🗒️ 거래 내역
    <span style="color:#8899aa;font-size:.82rem;font-weight:400;"> (자동 기록 장부)</span>
  </div>
  <div style="font-size:.85rem;color:#8899aa;margin-bottom:.8rem;">
    총 매수: <span style="color:#aabbcc;">${buy_t:,.2f}</span>
    &nbsp;&nbsp;|&nbsp;&nbsp;
    총 매도: <span style="color:#aabbcc;">${sell_t:,.2f}</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="border-bottom:1px solid #222235;">
        <th style="padding:.4rem .55rem;text-align:left;color:#778899;font-size:.8rem;font-weight:600;">#</th>
        <th style="padding:.4rem .55rem;text-align:left;color:#778899;font-size:.8rem;font-weight:600;">구분</th>
        <th style="padding:.4rem .55rem;text-align:left;color:#778899;font-size:.8rem;font-weight:600;">날짜</th>
        <th style="padding:.4rem .55rem;text-align:left;color:#778899;font-size:.8rem;font-weight:600;">가격</th>
        <th style="padding:.4rem .55rem;text-align:left;color:#778899;font-size:.8rem;font-weight:600;">수량</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
""", unsafe_allow_html=True)

            # 최신 데이터 불러오기 버튼
            if st.button(f"🔄  최신 데이터 수동 불러오기", key=f"refresh_{ticker}", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

            st.markdown('<div style="height:.6rem;"></div>', unsafe_allow_html=True)


    # ════════════════════════════════════════════════════
    # 탭2: 조종실
    # ════════════════════════════════════════════════════
    with tab2:
        st.markdown('<div style="font-size:1.05rem;font-weight:700;color:#ddd;margin:.6rem 0 1.1rem;">⚙️ 현재 설정값</div>', unsafe_allow_html=True)

        for ticker in tickers:
            rv = get_reverse(ticker)
            rows_data = [
                ("버전",       get_version(ticker),               "#44cc77"),
                ("시드",       f"${get_seed(ticker):,.0f}",       "#ddd"),
                ("분할수",     f"{int(get_split(ticker))}회",      "#ddd"),
                ("목표수익률", f"{get_target(ticker):.1f}%",       "#4ade80"),
                ("스나이퍼x",  f"x{get_sniper(ticker)}",           "#fbbf24"),
                ("리버스",     "🔄 ON" if rv.get("is_active") else "✅ OFF",
                               "#ff6666" if rv.get("is_active") else "#44cc77"),
            ]
            rows_html = ""
            for i,(label,val,col) in enumerate(rows_data):
                bg = "#0d0d1c" if i%2==0 else "#111120"
                rows_html += f"""
<div style="display:flex;justify-content:space-between;align-items:center;
  padding:.75rem 1.1rem;background:{bg};">
  <span style="font-size:.9rem;color:#aaa;font-weight:500;">{label}</span>
  <span style="font-family:'Space Mono',monospace;font-size:.92rem;font-weight:700;color:{col};">{val}</span>
</div>"""

            st.markdown(f"""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:14px;
  overflow:hidden;margin-bottom:1.1rem;">
  <div style="padding:.7rem 1.1rem;background:#0a0a18;border-bottom:1px solid #1a1a30;">
    <span style="font-size:.95rem;font-weight:700;color:#ccc;">{ticker}</span>
  </div>
  {rows_html}
</div>
""", unsafe_allow_html=True)

        st.info("💡 설정 변경은 텔레그램 봇 명령어(/seed /mode /ticker 등)를 이용하세요.")


    # ════════════════════════════════════════════════════
    # 탭3: 역사관
    # ════════════════════════════════════════════════════
    with tab3:
        st.markdown('<div style="font-size:1.05rem;font-weight:700;color:#ddd;margin:.6rem 0 1.1rem;">🏆 졸업 명예의 전당</div>', unsafe_allow_html=True)

        if not history:
            st.markdown("""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:14px;
  padding:2.2rem;text-align:center;">
  <div style="font-size:1.1rem;color:#7788aa;">🎓 아직 완료된 사이클이 없습니다.</div>
  <div style="font-size:.9rem;color:#5566aa;margin-top:.4rem;">첫 번째 졸업을 기다리는 중...</div>
</div>
""", unsafe_allow_html=True)
        else:
            total_profit = sum(h.get('profit',0) for h in history)
            st.markdown(f"""
<div style="background:#0a1a0a;border:1px solid #1a351a;border-radius:14px;
  padding:1.1rem;text-align:center;margin-bottom:1rem;">
  <div style="font-size:.9rem;color:#7799aa;margin-bottom:.25rem;font-weight:500;">📈 누적 실현 수익</div>
  <div style="font-family:'Space Mono',monospace;font-size:1.7rem;font-weight:700;color:#4ade80;">+${total_profit:,.2f}</div>
</div>
""", unsafe_allow_html=True)

            for h in reversed(history):
                profit = h.get('profit', 0)
                yld    = h.get('yield', 0)
                p_col  = "#4ade80" if profit >= 0 else "#ff6666"
                st.markdown(f"""
<div style="background:#111120;border:1px solid #1e1e35;border-radius:12px;
  padding:.9rem 1.1rem;margin-bottom:.55rem;
  display:flex;justify-content:space-between;align-items:center;">
  <div>
    <div style="font-weight:700;color:#ddd;font-size:.95rem;">#{h.get('id')} {h.get('ticker')}</div>
    <div style="font-size:.85rem;color:#7788aa;margin-top:.15rem;">{h.get('end_date','-')} 졸업</div>
  </div>
  <div style="text-align:right;">
    <div style="font-family:'Space Mono',monospace;font-weight:700;color:{p_col};font-size:1rem;">+${profit:,.2f}</div>
    <div style="font-size:.85rem;color:{p_col};margin-top:.1rem;">{yld:.2f}%</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── 자동 갱신 ─────────────────────────────────────────
    if auto:
        kst = pytz.timezone('Asia/Seoul')
        now_str = datetime.datetime.now(kst).strftime("%Y.%m.%d %H:%M:%S")
        st.markdown(f"""
<div style="text-align:right;color:#445566;font-size:.8rem;margin-top:.6rem;padding-bottom:.5rem;">
  🕐 {now_str} KST &nbsp;|&nbsp; 60초 후 자동 갱신
</div>
""", unsafe_allow_html=True)
        time.sleep(60)
        st.rerun()


# ════════════════════════════════════════════════════════
# 진입점
# ════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    show_login()
else:
    show_dashboard()
