
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import google.generativeai as genai
from datetime import datetime, timedelta
import time

# --- 設定頁面 ---
st.set_page_config(
    page_title="台股智謀 Ultimate V5.7 (Python Edition)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS 樣式 (模仿原版 Glassmorphism) ---
st.markdown("""
    <style>
    .stApp {
        background-color: #020617;
        color: #f1f5f9;
    }
    .metric-card {
        background-color: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 15px;
        padding: 15px;
        backdrop-filter: blur(10px);
        margin-bottom: 10px;
    }
    .big-font {
        font-size: 24px !important;
        font-weight: bold;
    }
    .up-text { color: #f43f5e; }
    .down-text { color: #10b981; }
    
    /* 調整 Tab 樣式 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(30, 41, 59, 0.6);
        border-radius: 10px;
        color: white;
        padding: 10px 20px;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background-color: #2563eb;
    }
    </style>
""", unsafe_allow_html=True)

# --- 輔助函數 ---

def get_symbol(code):
    """將台股代號轉換為 Yahoo Finance 格式"""
    if code.isdigit():
        return f"{code}.TW"
    if code.startswith("^"):
        return code
    return code

@st.cache_data(ttl=300)
def fetch_stock_data(symbol, period="1y"):
    """抓取股價資料"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            # 嘗試上櫃
            ticker = yf.Ticker(symbol.replace(".TW", ".TWO"))
            df = ticker.history(period=period)
        
        # 抓取基本資料
        info = ticker.info
        return df, info
    except Exception as e:
        return None, None

def calculate_indicators(df):
    """計算技術指標 (RSI, MA, BBands)"""
    if df is None or df.empty:
        return df
    
    # MA
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    df['BB_Mid'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_Mid'] - (2 * df['BB_Std'])
    
    return df

def calculate_score(df, info):
    """
    重現原版 score 計算邏輯
    0-100 分
    """
    if df is None or df.empty:
        return 50, "資料不足", []
        
    score = 50
    reasons = []
    
    current_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2]
    change_pct = ((current_price - prev_price) / prev_price) * 100
    
    ma20 = df['MA20'].iloc[-1]
    ma60 = df['MA60'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    avg_vol_5 = df['Volume'].tail(5).mean()
    
    # 漲跌幅邏輯
    if 3 < change_pct < 7:
        score += 8
        reasons.append("健康拉抬區間")
    elif change_pct >= 7:
        score += 5
        reasons.append("強勢但防回檔")
    elif change_pct < -4:
        score -= 8
        reasons.append("短線跌勢轉重")
        
    # 量能
    if vol > avg_vol_5 * 1.5:
        score += 5
        reasons.append("爆量攻擊訊號")
        
    # 均線
    if not np.isnan(ma20):
        if current_price > ma20:
            score += 10
            reasons.append("站上月線關鍵位")
            if not np.isnan(ma60) and ma20 > ma60:
                score += 10
                reasons.append("多頭排列格局")
        else:
            score -= 10
            reasons.append("跌破月線轉弱")
            
        # 乖離率
        bias = ((current_price - ma20) / ma20) * 100
        if bias > 10:
            score -= 5
            reasons.append("短線過熱警示")

    # 基本面 (Yahoo info 可能缺少某些欄位，做防呆)
    roe = info.get('returnOnEquity', 0)
    if roe and roe > 0.15:
        score += 8
        reasons.append("高ROE品質保證")
        
    pe = info.get('trailingPE', 0)
    if pe and 0 < pe < 20:
        score += 7
        reasons.append("估值仍在成長區")

    final_score = min(100, max(0, int(score)))
    
    action = "觀望"
    if final_score >= 80: action = "強力買進"
    elif final_score >= 65: action = "偏多操作"
    elif final_score >= 45: action = "中性觀望"
    elif final_score >= 25: action = "保守避險"
    
    return final_score, action, reasons

def generate_kline_narrative(df):
    """生成 K 線型態描述字串，供 AI 使用"""
    if df is None or len(df) < 5:
        return "資料不足"
    
    narrative = []
    # 取最近 5 天
    subset = df.tail(5)
    
    for i in range(len(subset)):
        row = subset.iloc[i]
        date_str = row.name.strftime('%m-%d')
        close = row['Close']
        open_p = row['Open']
        
        is_red = close > open_p
        body = abs(close - open_p)
        entity_range = row['High'] - row['Low']
        
        desc = "紅" if is_red else "黑"
        if entity_range > 0 and body / entity_range < 0.15:
            desc = "十字"
        
        change = 0
        if i > 0:
            prev_c = subset.iloc[i-1]['Close']
            change = ((close - prev_c) / prev_c) * 100
            
        narrative.append(f"[{date_str}] {close:.1f}({change:.1f}%): {desc}")
        
    return " -> ".join(narrative)

def generate_ai_report(symbol, df, info, score, action, k_narrative):
    """呼叫 Gemini API 生成報告"""
    
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return "❌ 請於 Streamlit Secrets 設定 GEMINI_API_KEY"
        
    try:
        client = genai.Client(api_key=api_key)
        
        # 準備數據 Context
        current_price = df['Close'].iloc[-1]
        
        # 關鍵價位
        recent_high = df['Close'].tail(60).max()
        recent_low = df['Close'].tail(60).min()
        
        # 嘗試尋找最大量 (主力成本參考)
        max_vol_row = df.loc[df['Volume'].tail(60).idxmax()]
        high_vol_price = max_vol_row['Close']
        cost_bias = ((current_price - high_vol_price) / high_vol_price) * 100

        # 基本面數據
        pe = info.get('trailingPE', 'N/A')
        roe = info.get('returnOnEquity', 'N/A')
        
        prompt = f"""
        角色設定：你是一位極度理性、奉行「機率思維」與「期望值」的傳奇對沖基金經理人。
        
        [Ace Trader V7 標的量化儀表板]
        - 標的：{info.get('longName', symbol)} ({symbol})
        - 現價：{current_price}
        - 量化評分：{score} (原始策略: {action})
        
        [K線型態密碼]
        - 近期走勢：{k_narrative}
        
        [籌碼與關鍵價位辯證]
        - 近季高點：{recent_high:.2f} | 近季低點：{recent_low:.2f}
        - 主力成本區 (爆量價)：{high_vol_price:.2f} (目前乖離：{cost_bias:.2f}%)
        
        [基本面]
        - PE: {pe} | ROE: {roe}

        任務：
        1. 綜合技術面、基本面進行全方位診斷。
        2. 【邏輯矛盾辯證】：尋找背離。
        3. 【勝率與賠率】：預估勝率與盈虧比。
        
        請輸出以下章節 (使用繁體中文)：
        
        【投資決策儀表板】
        - 投資訊號：(強力買進/拉回佈局/反彈空/觀望...)
        - 預估勝率：(例如 65% / 盈虧比 1:3)
        - 風險等級：(低/中/高)
        - 一句話快評：
        
        【風險深度解析】
        (條列 2 點風險)
        
        【多維度層層分析】
        1. 產業與基本面：
        2. 技術結構與主力意圖：(結合K線與關鍵價位)
        
        【操作建議與情境】
        - 樂觀情境：(若突破...)
        - 悲觀情境：(若跌破...)
        - 戰術執行：
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash', # 使用較新的模型
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"AI 分析發生錯誤: {str(e)}"

# --- 初始化 Session State ---
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = ['2330', '2317', '2454'] # 預設

if 'current_view' not in st.session_state:
    st.session_state.current_view = None

# --- Sidebar: 自選股管理 ---
with st.sidebar:
    st.title("⚡ 台股智謀 V5.7")
    
    # 新增股票
    new_stock = st.text_input("新增代號 (如 2330)", max_chars=10)
    if st.button("➕ 加入自選"):
        if new_stock and new_stock not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_stock)
            st.rerun()
            
    st.divider()
    st.caption("我的自選清單")
    
    # 顯示清單
    for stock_code in st.session_state.watchlist:
        col1, col2 = st.columns([4, 1])
        if col1.button(f"🔍 {stock_code}", key=f"btn_{stock_code}", use_container_width=True):
            st.session_state.current_view = stock_code
            st.rerun()
        
        if col2.button("🗑️", key=f"del_{stock_code}"):
            st.session_state.watchlist.remove(stock_code)
            st.rerun()

# --- 主畫面 ---

# 1. 市場脈動 (Global Market Pulse)
st.subheader("🌐 全球市場脈動")
m_col1, m_col2, m_col3 = st.columns(3)

indices = {
    "^TWII": "加權指數",
    "^IXIC": "那斯達克",
    "^SOX": "費城半導體"
}

for i, (idx_code, idx_name) in enumerate(indices.items()):
    df_idx, _ = fetch_stock_data(idx_code, period="5d")
    if df_idx is not None and not df_idx.empty:
        curr = df_idx['Close'].iloc[-1]
        prev = df_idx['Close'].iloc[-2]
        change = curr - prev
        pct = (change / prev) * 100
        color = "normal"
        if change > 0: color = "off" # Streamlit metric color trick: 'normal', 'off'(greenish/redish depending on theme)
        
        with [m_col1, m_col2, m_col3][i]:
            st.metric(label=idx_name, value=f"{curr:,.0f}", delta=f"{pct:.2f}%")

st.divider()

# 2. 個股詳細分析
target_stock = st.session_state.current_view

if target_stock:
    symbol_tw = get_symbol(target_stock)
    
    # 資料獲取
    with st.spinner(f"正在分析 {target_stock} ..."):
        df, info = fetch_stock_data(symbol_tw)
        df = calculate_indicators(df)
        score, action, reasons = calculate_score(df, info)
    
    if df is not None:
        # Header
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; align-items:end;">
            <div>
                <span style="font-size:14px; color:#94a3b8; font-weight:bold;">STOCK ANALYSIS</span>
                <div class="big-font">{info.get('longName', target_stock)} ({target_stock})</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:36px; font-weight:900;" class="{'up-text' if df['Close'].iloc[-1] > df['Close'].iloc[-2] else 'down-text'}">
                    {df['Close'].iloc[-1]:.2f}
                </div>
                <div style="font-size:12px; background:#1e293b; padding:2px 8px; border-radius:5px;">
                    評分: {score} | {action}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Tabs
        tab1, tab2, tab3 = st.tabs(["📊 技術圖表", "🤖 AI 專家診斷", "📑 詳細數據"])
        
        with tab1:
            # Plotly Chart
            fig = go.Figure()
            
            # K線
            fig.add_trace(go.Candlestick(x=df.index,
                            open=df['Open'], high=df['High'],
                            low=df['Low'], close=df['Close'],
                            name='K線'))
            
            # MA線
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1), name='MA20'))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='purple', width=1), name='MA60'))
            
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=400,
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white')
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # 評分理由
            st.markdown("##### 🎯 評分依據")
            st.write(", ".join([f"`{r}`" for r in reasons]))

        with tab2:
            st.info("點擊下方按鈕啟動 Google Gemini Pro 深度分析")
            if st.button("✨ 啟動 AI 診斷"):
                with st.spinner("AI 專家正在解讀盤勢 (約需 5-10 秒)..."):
                    k_narrative = generate_kline_narrative(df)
                    report = generate_ai_report(target_stock, df, info, score, action, k_narrative)
                    st.markdown(report)
                    
        with tab3:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("RSI (14)", f"{df['RSI'].iloc[-1]:.1f}")
                st.metric("成交量", f"{df['Volume'].iloc[-1]/1000:.0f} 張")
            with col2:
                st.metric("PE 本益比", f"{info.get('trailingPE', 'N/A')}")
                st.metric("ROE", f"{info.get('returnOnEquity', 0)*100:.2f}%" if info.get('returnOnEquity') else "N/A")

    else:
        st.error(f"無法獲取 {target_stock} 資料，請確認代號是否正確。")

else:
    # Empty State
    st.markdown("""
    <div style="text-align:center; padding:50px; opacity:0.6;">
        <h1>⚡ 台股智謀 AI</h1>
        <p>請從左側選擇或新增股票以開始診斷</p>
    </div>
    """, unsafe_allow_html=True)
    
    # 顯示熱門推薦
    st.subheader("🔥 市場熱門關注")
    hot_stocks = [('2330', '台積電'), ('2317', '鴻海'), ('2454', '聯發科'), ('3231', '緯創')]
    cols = st.columns(4)
    for i, (code, name) in enumerate(hot_stocks):
        with cols[i]:
            if st.button(f"{name}\n{code}", key=f"hot_{code}", use_container_width=True):
                st.session_state.current_view = code
                st.rerun()
