# ==========================================================
# FILE: market_data_provider.py
# ==========================================================
# 🚨 MODIFIED: [파사드 패턴 2단계] yfinance 및 KIS 시세 데이터 연산 도메인 분리
# 🚨 MODIFIED: [미래 참조 데이터 누수 전면 차단] get_amp_5d_data, get_5day_ma, get_atr_data 당일 미확정 라이브 캔들(Live Candle) 절단 100% 복제 이식.
# 🚨 MODIFIED: [선형 상속 락온] KisApiClient를 상속하여 공통 캐시 및 방어막(_safe_float, _call_api 등)을 100% 활용
# 🚨 MODIFIED: [Case 16] 시계열 데이터 원자적 쓰기 시 디렉토리 동적 파싱 보강 및 스토리지 고갈 방어 락온
# ==========================================================

import time
import datetime
import os
import math
import tempfile
import json
import logging
import yfinance as yf
import pandas as pd   
import numpy as np
import volatility_engine as ve
from zoneinfo import ZoneInfo
from kis_api_client import KisApiClient

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """ 🚨 [수술 완료] 야후 파이낸스 API 업데이트로 인한 MultiIndex 순서 붕괴 방어 """
    if isinstance(df.columns, pd.MultiIndex):
        if 'Ticker' in df.columns.names:
            df.columns = df.columns.droplevel('Ticker')
        elif df.columns.nlevels == 2:
            price_fields = {'Close', 'High', 'Low', 'Open', 'Volume', 'Adj Close'}
            level0_vals = set(df.columns.get_level_values(0))
            drop_level = 0 if not level0_vals.intersection(price_fields) else 1
            df.columns = df.columns.droplevel(drop_level)
    return df

class MarketDataProvider(KisApiClient):
    
    # 🚨 MODIFIED: [Case 33] 3단 지수 백오프 이식
    def get_daily_vwap_info(self, ticker):
        """ 기초자산의 정규장 거래 내역 기반 일자별 순수 VWAP 계산 """
        for attempt in range(3):
            try:
                time.sleep(0.06) # TPS 캡핑
                stock = yf.Ticker(ticker)
                df = stock.history(period="5d", interval="1m", prepost=False, timeout=10)
                if df.empty: 
                    if attempt == 2: return 0.0, 0.0
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                df = _flatten_columns(df)
                est = ZoneInfo('America/New_York') 
                if df.index.tz is None: df.index = df.index.tz_localize('UTC').tz_convert(est)
                else: df.index = df.index.tz_convert(est)
    
                regular_market = df.between_time('09:30', '15:59').copy()
                if regular_market.empty: return 0.0, 0.0
                regular_market['Typical_Price'] = (regular_market['High'] + regular_market['Low'] + regular_market['Close']) / 3.0
                regular_market['Vol_x_Price'] = regular_market['Typical_Price'] * regular_market['Volume']
        
                regular_market['Date'] = regular_market.index.date
               
                daily_stats = regular_market.groupby('Date').agg(Total_Vol_Price=('Vol_x_Price', 'sum'), Total_Vol=('Volume', 'sum'))
                # 🚨 MODIFIED: [Case 05] 결측치 방어용 0.0 강제 형변환
                daily_stats['VWAP'] = np.where(daily_stats['Total_Vol'] > 0, daily_stats['Total_Vol_Price'] / daily_stats['Total_Vol'], np.nan)
                daily_stats = daily_stats.dropna(subset=['VWAP'])
    
                if len(daily_stats) >= 2:
                    return round(self._safe_float(daily_stats['VWAP'].iloc[-2]), 4), round(self._safe_float(daily_stats['VWAP'].iloc[-1]), 4)
                elif len(daily_stats) == 1:
                    return 0.0, round(self._safe_float(daily_stats['VWAP'].iloc[-1]), 4)
                return 0.0, 0.0
            except Exception as e:
                if attempt == 2:
                    logging.error(f"⚠️ [Broker] 일별 VWAP 파싱 실패 ({ticker}): {e}")
                    return 0.0, 0.0
                time.sleep(1.0 * (2 ** attempt))
        return 0.0, 0.0

    # 🚨 MODIFIED: [Case 33] 3단 지수 백오프 이식
    def get_current_5min_candle(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                stock = yf.Ticker(ticker)
                df = stock.history(period="5d", interval="1m", prepost=True, timeout=5)
                if df.empty: 
                    if attempt == 2: return None
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                df = _flatten_columns(df)
                est = ZoneInfo('America/New_York')
                if df.index.tz is None: df.index = df.index.tz_localize('UTC').tz_convert(est)
                else: df.index = df.index.tz_convert(est)
       
                regular_market = df.between_time('09:30', '15:59')
                if regular_market.empty: return None
                today_date = pd.Timestamp.now(tz=est).normalize()
                regular_market = regular_market[regular_market.index >= today_date]
                if regular_market.empty: return None
                
                regular_market = regular_market.dropna(subset=['Volume', 'High', 'Low', 'Close'])
                typical_price = (regular_market['High'] + regular_market['Low'] + regular_market['Close']) / 3.0
                vol_price = typical_price * regular_market['Volume']
                cum_vol_price = vol_price.cumsum()
                cum_vol = regular_market['Volume'].cumsum()
                
                safe_cum_vol = np.where(cum_vol == 0, 1.0, cum_vol)
                vwap_array = np.where(cum_vol > 0, cum_vol_price / safe_cum_vol, np.nan)
                vwap_series = pd.Series(vwap_array, index=cum_vol.index).ffill() 
          
                current_vwap = self._safe_float(vwap_series.iloc[-1]) if not vwap_series.empty else 0.0
                if pd.isna(current_vwap) or current_vwap == 0.0: current_vwap = 0.0
        
                resampled = regular_market.resample('5min', label='left', closed='left').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
                if resampled.empty: return None
                resampled['Vol_MA10'] = resampled['Volume'].rolling(10, min_periods=1).mean()
                resampled['Vol_MA20'] = resampled['Volume'].rolling(20, min_periods=1).mean()
                last_candle = resampled.iloc[-1]
                latest_1m = regular_market.iloc[-1] 
      
                # 🚨 MODIFIED: [Float 붕괴 방어] 모든 연산 결과에 _safe_float 래핑 락온
                return {
                    'open': self._safe_float(last_candle['Open']), 
                    'high': self._safe_float(last_candle['High']), 
                    'low': self._safe_float(last_candle['Low']),    
                    'close': self._safe_float(latest_1m['Close']), 
                    'volume': self._safe_float(last_candle['Volume']), 
                    'vol_ma10': self._safe_float(last_candle.get('Vol_MA10', last_candle['Volume'])),
                    'vol_ma20': self._safe_float(last_candle.get('Vol_MA20', last_candle['Volume'])),
                    'vwap': self._safe_float(current_vwap)
                }
            except Exception as e:
                logging.debug(f"⚠️ [Broker] 실시간 5분봉 조회 실패 (시도 {attempt+1}/3): {e}")
                if attempt == 2: return None
                time.sleep(1.0 * (2 ** attempt))
        return None

    def get_current_price(self, ticker, is_market_closed=False):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                stock = yf.Ticker(ticker)
                hist = stock.history(period="1d", interval="1m", prepost=True, timeout=5)
                if not hist.empty: return self._safe_float(hist['Close'].iloc[-1])
                elif attempt == 2: raise ValueError("YF 실시간 데이터 응답 지연 (timeout)") 
            except Exception as e:
                logging.debug(f"⚠️ [야후] 현재가 에러 (시도 {attempt+1}/3): {e}")
                if attempt == 2: break
                time.sleep(1.0 * (2 ** attempt))

        for attempt in range(3):
            try:
                time.sleep(0.06)
                excg_cd = self._get_exchange_code(ticker, target_api="PRICE")
                params = {"AUTH": "", "EXCD": excg_cd, "SYMB": ticker}
                res = self._call_api("HHDFS76200200", "/uapi/overseas-price/v1/quotations/price", "GET", params=params)
                
                # 🚨 MODIFIED: [AttributeError 붕괴 방어] 명시적 None 및 문자열 오염 차단
                if res.get('rt_cd') == '0':
                    out = res.get('output') or {}
                    if not isinstance(out, dict): out = {}
                    return self._safe_float(out.get('last', 0.0))
                break
            except Exception:
                if attempt == 2: pass
                else: time.sleep(1.0 * (2 ** attempt))
        return 0.0

    def get_ask_price(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                excg_cd = self._get_exchange_code(ticker, target_api="PRICE")
                params = {"AUTH": "", "EXCD": excg_cd, "SYMB": ticker}
                res = self._call_api("HHDFS76200100", "/uapi/overseas-price/v1/quotations/inquire-asking-price", "GET", params=params)
         
                # 🚨 MODIFIED: [AttributeError 붕괴 방어]
                if res.get('rt_cd') == '0':
                    o2 = res.get('output2') or []
                    if isinstance(o2, dict): o2 = [o2]
                    if not isinstance(o2, list) or len(o2) == 0: return 0.0
                    item = o2[0]
                    if not isinstance(item, dict): return 0.0
                    return self._safe_float(item.get('pask1', 0.0))
                break
            except Exception:
                if attempt == 2: pass
                else: time.sleep(1.0 * (2 ** attempt))
        return 0.0

    def get_bid_price(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                excg_cd = self._get_exchange_code(ticker, target_api="PRICE")
                params = {"AUTH": "", "EXCD": excg_cd, "SYMB": ticker}
                res = self._call_api("HHDFS76200100", "/uapi/overseas-price/v1/quotations/inquire-asking-price", "GET", params=params)
                
                # 🚨 MODIFIED: [AttributeError 붕괴 방어]
                if res.get('rt_cd') == '0':
                    o2 = res.get('output2') or []
                    if isinstance(o2, dict): o2 = [o2]
                    if not isinstance(o2, list) or len(o2) == 0: return 0.0
                    item = o2[0]
                    if not isinstance(item, dict): return 0.0
                    return self._safe_float(item.get('pbid1', 0.0))
                break
            except Exception:
                if attempt == 2: pass
                else: time.sleep(1.0 * (2 ** attempt))
        return 0.0

    def get_previous_close(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                stock = yf.Ticker(ticker)
                hist = stock.history(period="5d", timeout=5)
                if not hist.empty:
                    est = ZoneInfo('America/New_York')
                    now_est = datetime.datetime.now(est)
                    cutoff_date = now_est.date()
                    if now_est.time() <= datetime.time(16, 0, 30): cutoff_date -= datetime.timedelta(days=1)
                    if hist.index.tzinfo is None: hist.index = hist.index.tz_localize('UTC').tz_convert(est)
                    else: hist.index = hist.index.tz_convert(est)
                    past_hist = hist[hist.index.date <= cutoff_date]
                    if not past_hist.empty: return self._safe_float(past_hist['Close'].dropna().iloc[-1])
                break
            except Exception as e:
                logging.debug(f"⚠️ [야후] 전일 종가 에러 (시도 {attempt+1}/3): {e}")
                if attempt == 2: break
                time.sleep(1.0 * (2 ** attempt))

        for attempt in range(3):
            try:
                time.sleep(0.06)
                excg_cd = self._get_exchange_code(ticker, target_api="PRICE")
                params = {"AUTH": "", "EXCD": excg_cd, "SYMB": ticker}
                res = self._call_api("HHDFS76200200", "/uapi/overseas-price/v1/quotations/price", "GET", params=params)
                
                # 🚨 MODIFIED: [AttributeError 붕괴 방어]
                if res.get('rt_cd') == '0': 
                    out = res.get('output') or {}
                    if not isinstance(out, dict): out = {}
                    return self._safe_float(out.get('base', 0.0))
                break
            except Exception:
                if attempt == 2: pass
                else: time.sleep(1.0 * (2 ** attempt))
        return 0.0
       
    def get_5day_ma(self, ticker):
        # 🚨 MODIFIED: [미래 참조 데이터 누수 차단] 당일 미확정 라이브 캔들 절단 및 D-1 타임라인 락온
        for attempt in range(3):
            try:
                time.sleep(0.06)
                stock = yf.Ticker(ticker)
                hist = stock.history(period="15d", timeout=5) 
                if not hist.empty:
                    est = ZoneInfo('America/New_York')
                    now_est = datetime.datetime.now(est)
                    cutoff_date = now_est.date()
                    
                    if now_est.time() <= datetime.time(16, 0, 30): 
                        cutoff_date -= datetime.timedelta(days=1)
                        
                    if hist.index.tzinfo is None: 
                        hist.index = hist.index.tz_localize('UTC').tz_convert(est)
                    else: 
                        hist.index = hist.index.tz_convert(est)
                        
                    past_hist = hist[hist.index.date <= cutoff_date]
                    if len(past_hist) >= 5:
                        ma_val = past_hist['Close'].dropna().tail(5).mean()
                        if not pd.isna(ma_val): return self._safe_float(ma_val)
                break
            except Exception:
                if attempt == 2: break
                time.sleep(1.0 * (2 ** attempt))
                
        for attempt in range(3):
            try:
                time.sleep(0.06)
                excg_cd = self._get_exchange_code(ticker, target_api="PRICE")
                params = {"AUTH": "", "EXCD": excg_cd, "SYMB": ticker, "GUBN": "0", "BYMD": "", "MODP": "1"}
                res = self._call_api("HHDFS76240000", "/uapi/overseas-price/v1/quotations/dailyprice", "GET", params=params)
                
                if res.get('rt_cd') == '0':
                    o2 = res.get('output2') or []
                    if isinstance(o2, dict): o2 = [o2]
                    if isinstance(o2, list) and len(o2) >= 5:
                        est = ZoneInfo('America/New_York')
                        now_est = datetime.datetime.now(est)
                        # 🚨 MODIFIED: [KIS API 폴백 오염 차단] 장 마감 이전이면 당일 라이브 주가 스킵
                        skip_today = 1 if now_est.time() <= datetime.time(16, 0, 30) else 0
                        
                        valid_items = [x for x in o2[skip_today:skip_today+5] if isinstance(x, dict)]
                        if len(valid_items) > 0:
                            closes = [self._safe_float(x.get('clos', 0)) for x in valid_items]
                            # 🚨 MODIFIED: [ZeroDivision 보호] closes 길이가 0인 경우 예외 차단
                            if len(closes) > 0:
                                return self._safe_float(sum(closes) / len(closes))
                break
            except Exception:
                if attempt == 2: pass
                else: time.sleep(1.0 * (2 ** attempt))
        return 0.0

    def get_1min_candles_df(self, ticker):
        """ 🚨 [제5경고] 하이킨아시 연산을 위한 open 컬럼 강제 보존 리턴 """
        for attempt in range(3):
            try:
                time.sleep(0.06)
                stock = yf.Ticker(ticker)
                df = stock.history(period="1d", interval="1m", prepost=True, timeout=5)
                if df.empty: 
                    if attempt == 2: return None
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                    
                df = _flatten_columns(df)
          
                est = ZoneInfo('America/New_York')
                if df.index.tz is None: df.index = df.index.tz_localize('UTC').tz_convert(est)
                else: df.index = df.index.tz_convert(est)
                df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
                df['time_est'] = df.index.strftime('%H%M00')
                
                try:
                    # 🚨 MODIFIED: [Float 붕괴 방어] max(), min() 결과에 _safe_float 래핑 강제 적용
                    max_high, min_low = self._safe_float(df['high'].max()), self._safe_float(df['low'].min())
                    time_high_idx, time_low_idx = df['high'].astype(float).idxmax(), df['low'].astype(float).idxmin()
                    
                    time_high_raw = df.loc[time_high_idx, 'time_est'] if not pd.isna(time_high_idx) else ""
                    time_high_str = str(time_high_raw.iloc[0] if isinstance(time_high_raw, pd.Series) else time_high_raw)
                    
                    time_low_raw = df.loc[time_low_idx, 'time_est'] if not pd.isna(time_low_idx) else ""
                    time_low_str = str(time_low_raw.iloc[0] if isinstance(time_low_raw, pd.Series) else time_low_raw)
        
                    cache_file = "data/avwap_cache.json"
                    cache_data = {}
                  
                    # 🚨 MODIFIED: [Case 08] TOCTOU 레이스 컨디션 차단 os.path.exists 소각 및 EAFP 적용
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f: 
                            cache_data = json.load(f)
                    except OSError: pass
                    except json.JSONDecodeError: pass

                    cache_data[ticker] = {'day_high': max_high, 'day_low': min_low, 'time_high': time_high_str, 'time_low': time_low_str, 'date': datetime.datetime.now(est).strftime("%Y-%m-%d")}
                    
                    # 🚨 MODIFIED: [Case 16] 디렉토리 파싱 무결성 강화 및 스토리지 고갈 방어 락온
                    dir_name = os.path.dirname(cache_file) or '.'
                    try: os.makedirs(dir_name, exist_ok=True)
                    except OSError: pass
                    
                    fd = None
                    tmp_path = None
                    try:
                        fd, tmp_path = tempfile.mkstemp(dir=dir_name, text=True)
                        with os.fdopen(fd, 'w', encoding='utf-8') as f_out:
                            fd = None
                            json.dump(cache_data, f_out, ensure_ascii=False, indent=4)
                            f_out.flush()
                            os.fsync(f_out.fileno())
                        os.replace(tmp_path, cache_file)
                        tmp_path = None
                    except Exception as e:
                        if fd is not None:
                            try: os.close(fd)
                            except OSError: pass
                        if tmp_path:
                            try: os.remove(tmp_path)
                            except OSError: pass
                        logging.debug(f"🚨 [{ticker}] 시계열 체력 팩트 캐싱 실패: {e}")
                except Exception as e: 
                    logging.debug(f"🚨 [{ticker}] 체력 팩트 캐싱 연산 에러: {e}")
                return df[['open', 'high', 'low', 'close', 'volume', 'time_est']]
            except Exception:
                if attempt == 2: return None
                time.sleep(1.0 * (2 ** attempt))

    def get_recent_stock_split(self, ticker, last_date_str):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                splits = yf.Ticker(ticker).splits
                if splits is not None and not splits.empty:
                    safe_last_date = last_date_str if last_date_str else (datetime.datetime.now(ZoneInfo('America/New_York')) - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
                    for dt, ratio in splits.items():
                        sd = dt[:10] if isinstance(dt, str) else pd.Timestamp(dt).strftime('%Y-%m-%d')
                        if sd > safe_last_date: return self._safe_float(ratio), sd
                break
            except Exception:
                if attempt == 2: break
                time.sleep(1.0 * (2 ** attempt))
        return 0.0, ""

    def get_dynamic_sniper_target(self, index_ticker):
        target_index = "SOXX" if index_ticker in ["SOXX", "SOXL"] else index_ticker
        try:
            class TargetFloat(float): pass
            if target_index == "SOXX":
                hv, w, td, ba = ve.get_soxl_target_drop_full()
                safe_w = self._safe_float(w)
                ret = TargetFloat(td); ret.metric_val, ret.weight, ret.base_amp, ret.metric_name, ret.metric_base = hv, w, ba, "SOXX HV", round(self._safe_float(hv)/safe_w, 2) if safe_w>0 else 25.0
            else:
                vxn, w, td, ba = ve.get_tqqq_target_drop_full()
                safe_w = self._safe_float(w)
                ret = TargetFloat(td); ret.metric_val, ret.weight, ret.base_amp, ret.metric_name, ret.metric_base = vxn, w, ba, "실시간 VXN", round(self._safe_float(vxn)/safe_w, 2) if safe_w>0 else 20.0
     
            ret.is_panic, ret.gap_pct = False, 0.0; return ret
        except:
            fb = -8.79 if target_index == "SOXX" else -4.95
            ret = TargetFloat(fb); ret.metric_val, ret.weight, ret.base_amp, ret.metric_name, ret.metric_base = 0.0, 1.0, fb, "통신오류", 25.0 if target_index == "SOXX" else 20.0
            ret.is_panic, ret.gap_pct = False, 0.0; return ret

    def get_day_high_low(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                hist = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=True, timeout=5)
                if not hist.empty:
                    hist = _flatten_columns(hist)
                    # 🚨 MODIFIED: [Float 오염 방어] _safe_float 래핑
                    return self._safe_float(hist['High'].max()), self._safe_float(hist['Low'].min())
                break
            except Exception:
                if attempt == 2: break
                time.sleep(1.0 * (2 ** attempt))
                
        for attempt in range(3):
            try:
                time.sleep(0.06)
                res = self._call_api("HHDFS76200200", "/uapi/overseas-price/v1/quotations/price", "GET", params={"AUTH": "", "EXCD": self._get_exchange_code(ticker, target_api="PRICE"), "SYMB": ticker})
                
                # 🚨 MODIFIED: [AttributeError 붕괴 방어] output 객체 추출 시 안전 단락 평가
                if res.get('rt_cd') == '0':
                    out = res.get('output') or {}
                    if not isinstance(out, dict): out = {}
                    return self._safe_float(out.get('high', 0.0)), self._safe_float(out.get('low', 0.0))
                break
            except Exception:
                if attempt == 2: pass
                else: time.sleep(1.0 * (2 ** attempt))
        return 0.0, 0.0

    # 🚨 MODIFIED: [미래 참조 데이터 누수 전면 차단] 당일 미확정 라이브 캔들 절단 및 D-1 타임라인 락온 복제
    def get_atr_data(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                hist = yf.Ticker(ticker).history(period="30d", prepost=False, timeout=5)
                if hist.empty:
                    if attempt == 2: return 0.0, 0.0
                    time.sleep(1.0 * (2 ** attempt))
                    continue

                # 🚨 EST 기준 타임존 맵핑 및 D-1 팩트 절단
                est = ZoneInfo('America/New_York')
                now_est = datetime.datetime.now(est)
                cutoff_date = now_est.date()

                if now_est.time() <= datetime.time(16, 0, 30):
                    cutoff_date -= datetime.timedelta(days=1)

                if hist.index.tzinfo is None:
                    hist.index = hist.index.tz_localize('UTC').tz_convert(est)
                else:
                    hist.index = hist.index.tz_convert(est)

                hist = hist[hist.index.date <= cutoff_date].copy()

                if hist.empty or len(hist) < 15:
                    if attempt == 2: return 0.0, 0.0
                    time.sleep(1.0 * (2 ** attempt))
                    continue

                hist['Prev_Close'] = hist['Close'].shift(1)
                hist = hist.dropna(subset=['High', 'Low', 'Close']).copy()

                hist['TR'] = hist.apply(lambda row: max(row['High']-row['Low'], abs(row['High']-row['Prev_Close']), abs(row['Low']-row['Prev_Close'])), axis=1)
                hist['ATR5'] = hist['TR'].rolling(window=5).mean()
                hist['ATR14'] = hist['TR'].rolling(window=14).mean()

                last = hist.iloc[-1]
                # 🚨 MODIFIED: [Float 오염 방어] _safe_float 래핑 (NaN 자동 폴백)
                atr5_val = self._safe_float(last['ATR5'])
                atr14_val = self._safe_float(last['ATR14'])
                close_val = self._safe_float(last['Close'])

                if close_val > 0:
                    return round((atr5_val / close_val) * 100, 1), round((atr14_val / close_val) * 100, 1)
                break
            except Exception:
                if attempt == 2: return 0.0, 0.0
                time.sleep(1.0 * (2 ** attempt))
        return 0.0, 0.0

    # 🚨 MODIFIED: [미래 참조 데이터 누수 차단] 당일 미확정 라이브 캔들 절단 및 D-1 타임라인 락온
    def get_amp_5d_data(self, ticker):
        for attempt in range(3):
            try:
                time.sleep(0.06)
                hist = yf.Ticker(ticker).history(period="20d", prepost=False, timeout=5)
                
                if hist.empty:
                    if attempt == 2: return 0.0
                    time.sleep(1.0 * (2 ** attempt))
                    continue

                # 🚨 EST 기준 타임존 맵핑 및 D-1 팩트 절단
                est = ZoneInfo('America/New_York')
                now_est = datetime.datetime.now(est)
                cutoff_date = now_est.date()
                
                # 정규장 마감(16:00) 직전/중 또는 프리장일 경우 당일 캔들을 배제하고 전일(D-1) 기준 확정 데이터로 락온
                if now_est.time() <= datetime.time(16, 0, 30): 
                    cutoff_date -= datetime.timedelta(days=1)
                    
                if hist.index.tzinfo is None: 
                    hist.index = hist.index.tz_localize('UTC').tz_convert(est)
                else: 
                    hist.index = hist.index.tz_convert(est)
                    
                hist = hist[hist.index.date <= cutoff_date].copy()

                if hist.empty or len(hist) < 6:
                    if attempt == 2: return 0.0
                    time.sleep(1.0 * (2 ** attempt))
                    continue
          
                hist['Prev_Close'] = hist['Close'].shift(1)
                hist = hist.dropna(subset=['High', 'Low', 'Prev_Close']).copy()
                hist['Prev_Close'] = hist['Prev_Close'].replace(0, np.nan)
                
                hist['Amp'] = (hist['High'] - hist['Low']) / hist['Prev_Close']
                hist['Amp_5d'] = hist['Amp'].rolling(window=5).mean()
                
                last = hist.iloc[-1]
                # 🚨 MODIFIED: [Float 오염 방어] _safe_float 래핑 (NaN 자동 폴백)
                amp_val = self._safe_float(last['Amp_5d'])
                if amp_val != 0.0:
                    return round(amp_val, 6)
                break
            except Exception as e:
                if attempt == 2:
                    logging.error(f"⚠️ [Broker] Amp 5MA 파싱 에러 ({ticker}): {e}")
                    break
                time.sleep(1.0 * (2 ** attempt))
        return 0.0
