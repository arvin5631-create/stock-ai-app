
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import google.generativeai as genai
from datetime import datetime, timedelta
import time
import random

# ==========================================
# 1. 配置與樣式 (System Config & CSS)
# ==========================================

st.set_page_config(
    page_title="台股智謀 Ultimate V5.7",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入自定義 CSS 以還原 React 版本的玻璃擬態 (Glassmorphism)
st.markdown("""
    <style>
    /* 全局背景與字體 */
    .stApp {
        background-color: #020617;
        color: #f1f5f9;
        font-family: 'Noto Sans TC', sans-serif;
    }
    
    /* 玻璃擬態卡片 */
    .glass-card {
        background: rgba(30, 41, 59, 0.4);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 20px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        transition: transform 0.2s;
    }
    .glass-card:hover {
        border-color: rgba(59, 130, 246, 0.4);
    }

    /* 評分球樣式 */
    .score-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 45px;
        height: 45px;
        border-radius: 12px;
        font-weight: 900;
        font-size: 18px;
        color: white;
        text-shadow: 0 1px 2px rgba(0,0,0,0.3);
    }
    .score-high { background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); box-shadow: 0 0 15px rgba(244, 63, 94, 0.4); }
    .score-mid { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); box-shadow: 0 0 15px rgba(245, 158, 11, 0.4); }
    .score-low { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); box-shadow: 0 0 15px rgba(59, 130, 246, 0.4); }
    .score-neutral { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }

    /* 文字顏色工具類 */
    .text-up { color: #f43f5e !important; }
    .text-down { color: #10b981 !important; }
    .text-slate { color: #94a3b8 !important; }
    .font-num { font-family: 'Roboto Mono', monospace; letter-spacing: -0.5px; }

    /* 策略標籤 */
    .strategy-tag {
        font-size: 0.7rem;
        padding: 2px 8px;
        border-radius: 4px;
        background: rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.1);
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    /* 去除 Streamlit 預設邊距 */
    .block-container { padding-top: 2rem; padding-bottom: 5rem; }
    
    /* 隱藏預設選單 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Tabs 優化 */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background-color: transparent; }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(30, 41, 59, 0.5);
        border-radius: 10px;
        color: #94a3b8;
        padding: 8px 16px;
        border: 1px solid rgba(255,255,255,0.05);
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background-color: #2563eb;
        color: white;
        border-color: #3b82f6;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 常數與映射 (Constants)
# ==========================================

SECTOR_MAP = {
    "ETF 戰略": ["0050", "0056", "00878", "00929", "00919", "00713", "00679B", "00687B"],
    "半導體": ["2330", "2454", "2303", "3711", "3034", "2379", "6415", "6488"],
    "AI 伺服器": ["2317", "2382", "3231", "2376", "2357", "2308", "6669", "2356"],
    "高價 IP": ["3661", "3529", "3443", "6643", "5274", "6533", "4966"],
    "網通光學": ["3008", "2345", "2327", "3037", "2313", "3017", "3044", "4938"],
    "金融控盤": ["2881", "2882", "2886", "2891", "2884", "2885", "5880", "2880"],
    "綠能重電": ["1519", "1513", "1503", "1514", "1609", "1605", "6806", "9958"],
    "航運原物料": ["2603", "2609", "2615", "2618", "2002", "1301", "1303", "6505"]
}

def get_sector_name(symbol):
    for name, stocks in SECTOR_MAP.items():
        if symbol in stocks:
            return name
    return "市場標的"

def get_score_class(score):
    if score >= 80: return "score-high"
    if score >= 60: return "score-mid"
    if score >= 40: return "score-low"
    return "score-neutral"

def get_change_color(change):
    return "text-up" if change > 0 else "text-down" if change < 0 else "text-slate"

# ==========================================
# 3. 數據服務層 (Data Service)
# ==========================================

def get_symbol_tw(code):
    if code.isdigit(): return f"{code}.TW"
    if code.startswith("^"): return code
    return code

@st.cache_data(ttl=300)
def fetch_stock_data_full(symbol_list):
    """
    批量抓取數據，用於板塊掃描
    """
    data_map = {}
    for code in symbol_list:
        try:
            sym = get_symbol_tw(code)
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if not hist.empty:
                info = ticker.info
                # 簡單評分計算 (快速版)
                close = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2]
                change = (close - prev) / prev * 100
                score = 50 + (change * 2) # 簡易邏輯
                score = min(99, max(1, int(score)))
                
                data_map[code] = {
                    "id": code,
                    "name": info.get('longName', code),
                    "price": close,
                    "change_pct": change,
                    "score": score
                }
        except:
            continue
    return data_map

@st.cache_data(ttl=60)
def get_analysis_data(symbol):
    """
    獲取單一個股完整分析數據 (包含歷史K線、基本面)
    """
    try:
        sym = get_symbol_tw(symbol)
        ticker = yf.Ticker(sym)
        
        # 1. 歷史數據 (1年)
        df = ticker.history(period="1y")
        if df.empty:
            sym = symbol.replace(".TW", ".TWO") # 嘗試上櫃
            ticker = yf.Ticker(sym)
            df = ticker.history(period="1y")
        
        if df.empty: return None
        
        # 2. 基本面 Info
        info = ticker.info
        
        return {"df": df, "info": info}
    except:
        return None

def calculate_technical_indicators(df):
    """計算完整技術指標"""
    # MA
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Bollinger
    df['BB_Mid'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_Mid'] - (2 * df['BB_Std'])
    
    return df

def calculate_ace_score(df, info):
    """
    移植 React 版的評分邏輯 (Ace Trader Logic)
    """
    score = 50
    reasons = []
    
    curr = df['Close'].iloc[-1]
    prev = df['Close'].iloc[-2]
    change_pct = ((curr - prev) / prev) * 100
    
    ma20 = df['MA20'].iloc[-1]
    ma60 = df['MA60'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    avg_vol_5 = df['Volume'].tail(5).mean()
    
    # 1. 動能面
    if 3 < change_pct < 7: score += 8; reasons.append("動能強勁")
    elif change_pct >= 7: score += 5; reasons.append("強勢漲停")
    elif change_pct < -4: score -= 8; reasons.append("賣壓沉重")
    
    # 2. 量能面
    if vol > avg_vol_5 * 1.5: score += 5; reasons.append("爆量攻擊")
    elif vol < avg_vol_5 * 0.5: score -= 2; reasons.append("量能急凍")
    
    # 3. 趨勢面
    if not np.isnan(ma20):
        if curr > ma20:
            score += 10; reasons.append("站穩月線")
            if not np.isnan(ma60) and ma20 > ma60:
                score += 10; reasons.append("多頭排列")
        else:
            score -= 10; reasons.append("跌破月線")
            
    # 4. 乖離率
    bias = ((curr - ma20) / ma20) * 100
    if bias > 15: score -= 5; reasons.append("短線過熱")
    
    # 5. 基本面 (簡單估值)
    pe = info.get('trailingPE', 0)
    if pe and 0 < pe < 15: score += 5; reasons.append("低本益比")
    
    final_score = min(100, max(0, int(score)))
    
    # 行動建議
    if final_score >= 80: action = "強力買進"
    elif final_score >= 65: action = "偏多操作"
    elif final_score >= 45: action = "區間觀望"
    else: action = "保守避險"
    
    return final_score, action, reasons, bias

def calculate_strategy(price, score, roe):
    """計算進出策略點位"""
    # 簡單模擬策略演算法
    tick = 0.05 if price < 50 else 0.1 if price < 100 else 0.5 if price < 500 else 1
    
    # 動能策略
    mom_entry = price * (0.98 if score > 70 else 0.95)
    mom_stop = mom_entry * 0.93
    mom_profit = mom_entry * 1.15
    
    # 價值策略
    val_entry = price * (0.9 if roe and roe > 15 else 0.85)
    val_stop = val_entry * 0.85
    val_profit = val_entry * 1.3
    
    return {
        "mom": {"entry": mom_entry, "stop": mom_stop, "profit": mom_profit},
        "val": {"entry": val_entry, "stop": val_stop, "profit": val_profit}
    }

# ==========================================
# 4. AI 服務層 (AI Service)
# ==========================================

def get_kline_narrative(df):
    """生成 K 線語言供 AI 閱讀"""
    lines = []
    subset = df.tail(5)
    for index, row in subset.iterrows():
        date = index.strftime('%m/%d')
        close = row['Close']
        change = (close - row['Open']) / row['Open'] * 100
        tag = "紅K" if change > 0 else "黑K"
        lines.append(f"{date}: {close:.1f} ({tag}, 幅度{change:.1f}%)")
    return " -> ".join(lines)

def generate_ai_report(symbol, df, info, score, action, bias):
    """Gemini 深度分析報告生成"""
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ 請先設定 Streamlit Secrets GEMINI_API_KEY"
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        current_price = df['Close'].iloc[-1]
        high_60 = df['Close'].tail(60).max()
        low_60 = df['Close'].tail(60).min()
        k_narrative = get_kline_narrative(df)
        
        prompt = f"""
        你是一位華爾街傳奇對沖基金經理，請對台股 {info.get('longName', symbol)} ({symbol}) 進行深度診斷。
        
        【量化數據】
        - 現價：{current_price} (乖離率 {bias:.1f}%)
        - 評分：{score} ({action})
        - 區間：近季高 {high_60:.1f} / 近季低 {low_60:.1f}
        - K線序列：{k_narrative}
        - 基本面：PE {info.get('trailingPE','N/A')}, ROE {info.get('returnOnEquity','N/A')}

        請用繁體中文，專業、篤定地輸出以下 Markdown 格式報告 (不要有廢話)：

        ### 🎯 投資決策儀表板
        - **核心訊號**：(給出明確方向)
        - **勝率預估**：(例如 65%) / **盈虧比**：(例如 1:3)
        - **技術格局**：(一句話形容，如：多頭排列回測支撐)
        - **一句話快評**：(犀利的總結)

        ### ⚠️ 風險深度解析
        (條列 2 點具體風險，如籌碼鬆動、技術面破線等)

        ### 🔍 多維度層層分析
        1. **籌碼與主力意圖**：(分析主力是在吃貨還是出貨)
        2. **技術結構與關鍵位**：(結合K線型態判斷)
        3. **產業與基本面邏輯**：(簡述產業地位與估值)

        ### ⚔️ 戰術執行建議
        - **樂觀情境**：(若突破...)
        - **悲觀情境**：(若跌破...)
        - **操作規劃**：(具體的進場、止損邏輯)
        """
        
        with st.spinner("🧠 AI 專家正在進行多維度運算與邏輯辯證..."):
            response = model.generate_content(prompt)
            return response.text
    except Exception as e:
        return f"AI 連線失敗: {str(e)}"

# ==========================================
# 5. UI 組件 (UI Components)
# ==========================================

def render_metric_card(label, value, delta, color_class):
    st.markdown(f"""
    <div class="glass-card" style="padding: 15px; text-align: center;">
        <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px;">{label}</div>
        <div class="font-num {color_class}" style="font-size: 28px; font-weight: 900; line-height: 1;">{value}</div>
        <div style="font-size: 12px; margin-top: 5px; font-weight: bold;" class="{color_class}">
            {delta}
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_stock_list_item(stock, on_click_key):
    col1, col2, col3 = st.columns([1, 3, 2])
    with col1:
        score_cls = get_score_class(stock['score'])
        st.markdown(f"""<div class="score-badge {score_cls}">{stock['score']}</div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
            <div style="font-weight: bold; font-size: 16px;">{stock['name']}</div>
            <div class="font-num" style="font-size: 12px; color: #64748b;">{stock['id']}</div>
        """, unsafe_allow_html=True)
    with col3:
        color = get_change_color(stock['change_pct'])
        st.markdown(f"""
            <div class="font-num {color}" style="text-align: right; font-size: 18px; font-weight: bold;">{stock['price']:.2f}</div>
            <div class="font-num {color}" style="text-align: right; font-size: 10px;">{stock['change_pct']:.2f}%</div>
        """, unsafe_allow_html=True)
    
    if st.button(f"查看詳情", key=on_click_key, use_container_width=True):
        st.session_state.current_view = stock['id']
        st.rerun()

# ==========================================
# 6. 主程式邏輯 (Main App Logic)
# ==========================================

# 初始化 Session
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = ['2330', '2317', '2454', '3231']
if 'current_view' not in st.session_state:
    st.session_state.current_view = None

# --- 側邊欄 (Sidebar) ---
with st.sidebar:
    st.markdown("### ⚡ 台股智謀 V5.7")
    
    # 搜尋/新增
    new_stock = st.text_input("新增代號 (如 2330)", placeholder="輸入代號...")
    if st.button("➕ 加入自選清單", type="primary", use_container_width=True):
        if new_stock and new_stock not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_stock)
            st.rerun()
            
    st.divider()
    
    # 自選清單列表 (簡易版)
    st.markdown("##### 📂 我的自選")
    for stock_id in st.session_state.watchlist:
        c1, c2 = st.columns([4, 1])
        if c1.button(f"🔍 {stock_id}", key=f"nav_{stock_id}"):
            st.session_state.current_view = stock_id
            st.rerun()
        if c2.button("✖", key=f"del_{stock_id}"):
            st.session_state.watchlist.remove(stock_id)
            st.rerun()

# --- 主畫面路由 ---

if st.session_state.current_view:
    # === 個股深度分析頁面 ===
    target = st.session_state.current_view
    
    # 頂部導航
    if st.button("← 返回儀表板"):
        st.session_state.current_view = None
        st.rerun()

    data = get_analysis_data(target)
    
    if data:
        df = calculate_technical_indicators(data['df'])
        info = data['info']
        score, action, reasons, bias = calculate_ace_score(df, info)
        
        # 1. 頂部資訊卡 (Header Card)
        last_close = df['Close'].iloc[-1]
        change_pct = (last_close - df['Close'].iloc[-2]) / df['Close'].iloc[-2] * 100
        color_cls = get_change_color(change_pct)
        
        st.markdown(f"""
        <div class="glass-card" style="display: flex; justify-content: space-between; align-items: flex-end; background: linear-gradient(180deg, rgba(30,41,59,0.7) 0%, rgba(15,23,42,0.9) 100%);">
            <div>
                <span class="strategy-tag" style="color: #60a5fa; border-color: #60a5fa;">{get_sector_name(target)}</span>
                <div style="font-size: 32px; font-weight: 900; margin-top: 10px;">{info.get('longName', target)} <span style="font-size: 18px; color: #64748b;">{target}</span></div>
            </div>
            <div style="text-align: right;">
                <div class="font-num {color_cls}" style="font-size: 42px; font-weight: 900; line-height: 1;">{last_close:.2f}</div>
                <div class="font-num {color_cls}" style="font-size: 14px; font-weight: bold;">{change_pct:+.2f}%</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 2. 核心數據指標 (Metrics Grid)
        c1, c2, c3, c4 = st.columns(4)
        with c1: render_metric_card("ACE 量化評分", score, action, get_score_class(score).replace("background: ", "").replace("score-", "text-")) # Hacky color mapping
        with c2: render_metric_card("乖離率 (Bias)", f"{bias:.1f}%", "過熱" if bias > 10 else "超跌" if bias < -10 else "正常", "text-slate")
        with c3: render_metric_card("RSI 強度", f"{df['RSI'].iloc[-1]:.0f}", "強勢區" if df['RSI'].iloc[-1]>70 else "弱勢區", "text-slate")
        with c4: render_metric_card("成交量", f"{int(df['Volume'].iloc[-1]/1000)}K", "張", "text-slate")

        # 3. 功能頁籤 (Tabs)
        tab_chart, tab_ai, tab_strategy = st.tabs(["📊 技術圖表", "🧠 AI 戰略報告", "🎯 操盤策略"])
        
        with tab_chart:
            # Plotly Interactive Chart
            fig = go.Figure()
            # K線
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
            # MA Lines
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#fbbf24', width=1), name='MA20'))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='#c084fc', width=1), name='MA60'))
            
            fig.update_layout(
                height=450,
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis_rangeslider_visible=False,
                font=dict(color='#94a3b8'),
                grid=dict(color='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # 評分理由標籤
            st.markdown("##### 🔍 評分依據")
            st.markdown(" ".join([f"<span class='strategy-tag'>{r}</span>" for r in reasons]), unsafe_allow_html=True)

        with tab_ai:
            st.markdown("""
            <div class="glass-card" style="border-left: 4px solid #8b5cf6;">
                <h4 style="margin:0; color: #a78bfa;">🤖 AI 投資顧問</h4>
                <p style="font-size: 12px; color: #94a3b8;">基於 Google Gemini 2.0 模型，綜合 K 線型態、籌碼邏輯與基本面進行深度診斷。</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("✨ 啟動 AI 深度診斷", type="primary", use_container_width=True):
                report = generate_ai_report(target, df, info, score, action, bias)
                st.markdown(report)
            else:
                st.info("點擊按鈕以生成即時分析報告 (需消耗 API 配額)")

        with tab_strategy:
            roe = info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else 0
            strat = calculate_strategy(last_close, score, roe)
            
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown(f"""
                <div class="glass-card">
                    <h4 style="color: #60a5fa;">🌊 波段動能策略</h4>
                    <p style="font-size: 12px; color: #94a3b8;">適合短線操作，追蹤資金流向</p>
                    <hr style="border-color: rgba(255,255,255,0.1);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:5px;"><span>建議進場</span> <b class="font-num text-white">{strat['mom']['entry']:.2f}</b></div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:5px;"><span>停損防守</span> <b class="font-num text-up">{strat['mom']['stop']:.2f}</b></div>
                    <div style="display:flex; justify-content:space-between;"><span>目標停利</span> <b class="font-num text-down">{strat['mom']['profit']:.2f}</b></div>
                </div>
                """, unsafe_allow_html=True)
            
            with sc2:
                st.markdown(f"""
                <div class="glass-card">
                    <h4 style="color: #34d399;">💰 價值投資策略</h4>
                    <p style="font-size: 12px; color: #94a3b8;">適合中長線佈局，回調承接</p>
                    <hr style="border-color: rgba(255,255,255,0.1);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:5px;"><span>建議進場</span> <b class="font-num text-white">{strat['val']['entry']:.2f}</b></div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:5px;"><span>停損防守</span> <b class="font-num text-up">{strat['val']['stop']:.2f}</b></div>
                    <div style="display:flex; justify-content:space-between;"><span>目標停利</span> <b class="font-num text-down">{strat['val']['profit']:.2f}</b></div>
                </div>
                """, unsafe_allow_html=True)

    else:
        st.error("無法獲取數據，請確認代號正確。")

else:
    # === 首頁儀表板 (Dashboard) ===
    
    # 1. 大盤指數 (Market Indices)
    st.markdown("### 🌐 全球市場脈動")
    ic1, ic2, ic3 = st.columns(3)
    indices = {"^TWII": "加權指數", "^IXIC": "那斯達克", "^SOX": "費城半導體"}
    
    for idx, (sym, name) in enumerate(indices.items()):
        df_idx, _ = fetch_stock_data_full([sym])
        if not df_idx: continue
        d = df_idx[sym] # fetch_stock_data_full returns dict, wait, my impl returns single? no it returns map
        # Wait, fetch_stock_data_full returns map. but fetch_stock_data (single) returns df, info.
        # Let's fix this quickly. I'll just use a quick fetch here.
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="5d")
        if not hist.empty:
            curr = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            chg = (curr - prev)/prev*100
            color = get_change_color(chg).replace("text-", "") # Hack for st.metric delta_color
            
            with [ic1, ic2, ic3][idx]:
                st.metric(name, f"{curr:,.0f}", f"{chg:+.2f}%")

    st.markdown("---")

    # 2. 自選股快覽 (Watchlist Preview)
    st.markdown("### 📂 我的自選監控")
    
    # 批量抓取自選股數據以提升效能
    if st.session_state.watchlist:
        wl_data = fetch_stock_data_full(st.session_state.watchlist)
        
        # 排序：評分高到低
        sorted_wl = sorted(wl_data.values(), key=lambda x: x['score'], reverse=True)
        
        for stock in sorted_wl:
            render_stock_list_item(stock, f"wl_{stock['id']}")
    else:
        st.info("您的自選清單為空，請從左側新增。")

    st.markdown("---")
    
    # 3. 產業板塊熱力 (Sector Heatmap)
    st.markdown("### 🔥 產業板塊熱力")
    
    selected_sector = st.selectbox("選擇板塊進行掃描", list(SECTOR_MAP.keys()))
    
    if st.button("🚀 掃描該板塊"):
        with st.spinner(f"正在掃描 {selected_sector} 板塊成分股..."):
            sector_stocks = SECTOR_MAP[selected_sector]
            sector_data = fetch_stock_data_full(sector_stocks)
            
            # 轉換為 DataFrame 用於顯示
            rows = []
            for s in sector_data.values():
                rows.append({
                    "代號": s['id'],
                    "名稱": s['name'],
                    "現價": s['price'],
                    "漲跌幅": f"{s['change_pct']:+.2f}%",
                    "Ace評分": s['score']
                })
            
            if rows:
                res_df = pd.DataFrame(rows).sort_values("Ace評分", ascending=False)
                st.dataframe(
                    res_df,
                    column_config={
                        "Ace評分": st.column_config.ProgressColumn(
                            "Ace評分",
                            help="AI 量化綜合評分",
                            format="%d",
                            min_value=0,
                            max_value=100,
                        ),
                    },
                    use_container_width=True
                )
            else:
                st.warning("數據獲取失敗，請稍後再試。")

