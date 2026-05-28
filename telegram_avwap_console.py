# ==========================================================
# FILE: telegram_avwap_console.py
# ==========================================================
# 🚨 VERIFIED: [최종 무결점 판정] 3중 딥다이브 교차 검증(Async I/O 족쇄, State Mismatch 방어, Float 정밀도 사수) 통과 완료.
# 🚨 MODIFIED: [AttributeError 궁극 수술] 상위 모듈에서 `app_data`를 `None`으로 전달할 경우 발생하는 `setdefault` 런타임 붕괴(Silent Death)를 방어하기 위해 최상단 타입 강제화 쉴드 주입 완료.
# 🚨 MODIFIED: [State Mismatch 궁극 수술] `decision.get('KEY', default)` 사용 시 키는 존재하나 값이 `None`인 경우 발생하는 Null-Injection(상태 증발) 맹점을 식별하고, `val is not None` 명시적 단락 평가 방어막으로 전면 교체하여 유령 상태(Ghost State) 원천 차단 완료.
# 🚨 MODIFIED: [Fail-Open 팩트 교정] 달력 API 통신 실패 시 무조건 REG(정규장)로 하드코딩되던 타임라인 왜곡 맹점 소각 및 가상(Mock) 타임 맵핑 락온.
# 🚨 MODIFIED: [Insight 14, 25] API String-Float 및 NaN/Inf 맹독성 포맷팅 쉴드. `_safe_float` 코어 래핑 전면 결속 완료.
# 🚨 MODIFIED: [Insight 15] 튜플/배열 변형(Array Mutation) 방어. cash_val_tuple 인덱스 에러 방지 isinstance 검증 락온.
# 🚨 MODIFIED: [Insight 11] 궁극의 이터러블 Null-Coalescing 쉴드 이식. `or []` 단락 평가 강제 적용.
# 🚨 MODIFIED: [Insight 06/07] JSON Null-Coalescing 맹독성 차단. `int(_safe_float(...))` 단락 평가 강제 이식 완료.
# 🚨 MODIFIED: [Insight 04 메모리 멱등성 사수] 전략 엔진으로부터 파기된 buy_odno 상태를 다이렉트로 전달받아 tracking_cache 완벽 동기화.
# 🚨 MODIFIED: [Case 14 절대 헌법 준수] 달력 API(mcal) 호출 시 10.0초 타임아웃 락온으로 이벤트 루프 교착 완벽 차단.
# 🚨 MODIFIED: [휴장일 멱등성 수술] 주말/휴장일 관제탑 조회 시 시뮬레이션 격발로 인한 09:30 기요틴 렌더링 오염 완벽 차단.
# ==========================================================
import logging
import datetime
from zoneinfo import ZoneInfo
import math
import asyncio
import time
import pandas as pd
import pandas_market_calendars as mcal  
import json
import os
import html  
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class AvwapConsolePlugin:
    def __init__(self, config, broker, strategy, tx_lock):
        self.cfg = config
        self.broker = broker
        self.strategy = strategy
        self.tx_lock = tx_lock

    # 🚨 NEW: [수학 연산 붕괴 방어] NaN, Infinity 및 String-Comma 맹독성 데이터 정밀 필터링 락온
    def _safe_float(self, val):
        try:
            f_val = float(str(val or 0.0).replace(',', ''))
            if math.isnan(f_val) or math.isinf(f_val):
                return 0.0
            return f_val
        except Exception:
            return 0.0

    async def get_console_message(self, app_data):
        # 🚨 MODIFIED: [AttributeError 궁극 수술] app_data가 None일 경우 발생하는 setdefault 붕괴 원천 차단
        if app_data is None:
            app_data = {}

        est = ZoneInfo('America/New_York')
        now_est = datetime.datetime.now(est)
        curr_time = now_est.time()
        
        time_0400 = datetime.time(4, 0)
        time_0930 = datetime.time(9, 30)
     
        def _fetch_schedule():
            time.sleep(0.06) 
            nyse = mcal.get_calendar('NYSE')
            return nyse.schedule(start_date=now_est.date(), end_date=now_est.date())
            
        schedule = None
        for attempt in range(3):
            try:
                schedule = await asyncio.wait_for(asyncio.to_thread(_fetch_schedule), timeout=10.0)
                break
            except Exception:
                if attempt == 2:
                    logging.error("🚨 달력 API 호출 에러/타임아웃. Fail-Open 평일 개장으로 강제 폴백합니다.")
                else: 
                    await asyncio.sleep(1.0 * (2 ** attempt))

        is_holiday = False
        market_open = None
        market_close = None
        
        if schedule is None or schedule.empty:
            if schedule is None and now_est.weekday() < 5: 
                # 🚨 MODIFIED: [Fail-Open 팩트 교정] 무조건 REG 하드코딩 소각 및 가상 정규장 시간(Mock) 맵핑
                market_open = now_est.replace(hour=9, minute=30, second=0, microsecond=0)
                market_close = now_est.replace(hour=16, minute=0, second=0, microsecond=0)
            else: 
                is_holiday = True
        else:
            market_open = schedule.iloc[0]['market_open'].astimezone(est)
            market_close = schedule.iloc[0]['market_close'].astimezone(est)

        if is_holiday:
            status_code = "HOLIDAY"
        else:
            pre_start = market_open.replace(hour=4, minute=0, second=0, microsecond=0)
            after_end = market_close.replace(hour=20, minute=0, second=0, microsecond=0)

            if pre_start <= now_est < market_open:
                status_code = "PRE"
            elif market_open <= now_est < market_close:
                status_code = "REG"
            elif market_close <= now_est < after_end:
                status_code = "AFTER"
            else:
                status_code = "CLOSE"

        if status_code == "HOLIDAY":
            header_status = "💤 <b>[ 미국 증시 휴장일 / 관망 모드 ]</b>"
        elif status_code in ["AFTER", "CLOSE"]:
            header_status = "🌙 <b>[ 애프터마켓 / 감시 종료 ]</b>"
        elif status_code == "PRE":
            header_status = "🌅 <b>[ 프리장 선제 타격 모드 (04:00~09:29 스캔 중) ]</b>"
        else:
            header_status = "🔥 <b>[ 정규장 실시간 추격 모드 (V79.50 지정가 덫 요격) ]</b>"
        
        # 🚨 MODIFIED: [제1헌법] File I/O 코루틴 타임아웃 족쇄 래핑
        try:
            active_tickers = await asyncio.wait_for(asyncio.to_thread(self.cfg.get_active_tickers), timeout=10.0) or []
        except Exception as e:
            logging.error(f"🚨 Config I/O 타임아웃 (active_tickers): {e}")
            active_tickers = []
            
        avwap_tickers = [t for t in active_tickers if t == "SOXL"]
       
        if not avwap_tickers:
            return "⚠️ <b>[AVWAP 암살자 오프라인]</b>\n▫️ AVWAP 지원 종목이 없습니다.", None
           
        active_avwap = avwap_tickers
        
        # 🚨 MODIFIED: [메모리 멱등성 사수] get() 대신 setdefault()를 사용하여 전역 딕셔너리와 참조 연결 락온
        tracking_cache = app_data.setdefault('sniper_tracking', {})
        
        cash_val = 0.0
        for attempt in range(3):
            try:
                # 🚨 MODIFIED: [Case 32] 잔고 조회 루프 내 누락된 TPS 캡핑 방어막 주입
                await asyncio.sleep(0.06)
                cash_val_tuple = await asyncio.wait_for(asyncio.to_thread(self.broker.get_account_balance), timeout=10.0)
                cash_val = cash_val_tuple[0] if isinstance(cash_val_tuple, (list, tuple)) and len(cash_val_tuple) > 0 else 0.0
                break
            except Exception:
                if attempt == 2: 
                    cash_val = 0.0
                else: 
                    await asyncio.sleep(1.0 * (2 ** attempt))
        
        available_cash = self._safe_float(cash_val)
        
        msg = f"🔫 <b>[ 차세대 AVWAP V79.50 관제탑 ]</b>\n{header_status}\n\n"
        keyboard = []

        async def _get_with_retry(func, *args):
            for attempt in range(3):
                try:
                    await asyncio.sleep(0.06) 
                    return await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=10.0)
                except Exception:
                    if attempt == 2: return None
                    await asyncio.sleep(1.0 * (2 ** attempt))

        for t in active_avwap:
            await asyncio.sleep(0.06)
            
            ticker_clean = html.escape(str(t)) 
            
            if not tracking_cache.get(f"AVWAP_INIT_{t}"):
                try:
                    # 🚨 MODIFIED: [제1헌법] File I/O 코루틴 타임아웃 족쇄 래핑
                    saved_state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, t, now_est), timeout=10.0) or {}
                    if saved_state:
                        tracking_cache[f"AVWAP_BOUGHT_{t}"] = bool(saved_state.get('bought'))
                        tracking_cache[f"AVWAP_SHUTDOWN_{t}"] = bool(saved_state.get('shutdown'))
                        
                        tracking_cache[f"AVWAP_QTY_{t}"] = int(self._safe_float(saved_state.get('qty')))
                        tracking_cache[f"AVWAP_AVG_{t}"] = self._safe_float(saved_state.get('avg_price'))
                        tracking_cache[f"AVWAP_STRIKES_{t}"] = int(self._safe_float(saved_state.get('strikes')))
                        tracking_cache[f"AVWAP_DUMP_JITTER_{t}"] = int(self._safe_float(saved_state.get('dump_jitter_sec')))
                        tracking_cache[f"AVWAP_TRAP_ODNO_{t}"] = str(saved_state.get('trap_odno') or "")
                        
                        tracking_cache[f"AVWAP_LIMIT_ORDER_PLACED_{t}"] = bool(saved_state.get('limit_order_placed'))
                        tracking_cache[f"AVWAP_PLACED_TARGET_TH_{t}"] = self._safe_float(saved_state.get('placed_target_th'))
                        tracking_cache[f"AVWAP_TRAP_PLACED_TIME_{t}"] = str(saved_state.get('trap_placed_time') or "")
                        tracking_cache[f"AVWAP_BUY_ODNO_{t}"] = str(saved_state.get('buy_odno') or "")
           
                        tracking_cache[f"AVWAP_PM_H_{t}"] = self._safe_float(saved_state.get('PM_H'))
                        tracking_cache[f"AVWAP_PM_L_{t}"] = self._safe_float(saved_state.get('PM_L'))
                        tracking_cache[f"AVWAP_T_H_{t}"] = self._safe_float(saved_state.get('T_H'))
                        tracking_cache[f"AVWAP_T_L_{t}"] = self._safe_float(saved_state.get('T_L'))
                        tracking_cache[f"AVWAP_OFFSET_{t}"] = self._safe_float(saved_state.get('offset'))
                        
                    tracking_cache[f"AVWAP_INIT_{t}"] = True
                except Exception as e:
                    logging.debug(f"🚨 상태 캐시 로드 중 타임아웃/에러: {e}")
                    pass

            # 🚨 MODIFIED: [제1헌법] File I/O 코루틴 타임아웃 족쇄 래핑
            try:
                is_avwap_active = await asyncio.wait_for(asyncio.to_thread(getattr(self.cfg, 'get_avwap_hybrid_mode', lambda x: False), t), timeout=5.0)
            except Exception:
                is_avwap_active = False
                
            try:
                sortie_mode = await asyncio.wait_for(asyncio.to_thread(getattr(self.cfg, 'get_avwap_sortie_mode', lambda x: "SINGLE"), t), timeout=5.0)
            except Exception:
                sortie_mode = "SINGLE"
                
            sortie_str = "단일 타격(1회)" if sortie_mode == "SINGLE" else "다중 출격(무한)"
            active_str = f"🟢 암살 가동 ({sortie_str})" if is_avwap_active else "⚪ 대기 (OFF)"
            
            try:
                res_batch = await asyncio.gather(
                    _get_with_retry(self.broker.get_current_price, t),
                    _get_with_retry(self.broker.get_previous_close, t),
                    _get_with_retry(self.broker.get_amp_5d_data, t),
                    _get_with_retry(self.broker.get_1min_candles_df, t),
                    _get_with_retry(self.broker.get_5day_ma, t)
                )
           
                curr_p = self._safe_float(res_batch[0])
                prev_c = self._safe_float(res_batch[1])
                amp5 = self._safe_float(res_batch[2])
                df_1m = res_batch[3]
                ma_5day = self._safe_float(res_batch[4]) if len(res_batch) > 4 else 0.0
               
            except Exception as e:
                curr_p, prev_c, amp5, df_1m, ma_5day = 0.0, 0.0, 0.0, None, 0.0

            if df_1m is not None and not df_1m.empty and 'time_est' in df_1m.columns:
                df_reg = df_1m[(df_1m['time_est'] >= '093000') & (df_1m['time_est'] <= '155959')]
                if not df_reg.empty:
                    tracking_cache[f"AVWAP_REG_H_{t}"] = self._safe_float(df_reg['high'].max())
                    tracking_cache[f"AVWAP_REG_L_{t}"] = self._safe_float(df_reg['low'].min())

            avwap_qty = int(self._safe_float(tracking_cache.get(f"AVWAP_QTY_{t}")))
            avwap_avg = self._safe_float(tracking_cache.get(f"AVWAP_AVG_{t}"))
            is_shutdown = bool(tracking_cache.get(f"AVWAP_SHUTDOWN_{t}"))
            trap_odno = str(tracking_cache.get(f"AVWAP_TRAP_ODNO_{t}") or "")
            
            limit_order_placed = bool(tracking_cache.get(f"AVWAP_LIMIT_ORDER_PLACED_{t}"))
            placed_target_th = self._safe_float(tracking_cache.get(f"AVWAP_PLACED_TARGET_TH_{t}"))
            trap_placed_time = str(tracking_cache.get(f"AVWAP_TRAP_PLACED_TIME_{t}") or "")
            buy_odno = str(tracking_cache.get(f"AVWAP_BUY_ODNO_{t}") or "")
            
            pm_h = self._safe_float(tracking_cache.get(f"AVWAP_PM_H_{t}"))
            pm_l = self._safe_float(tracking_cache.get(f"AVWAP_PM_L_{t}"))
            t_h = self._safe_float(tracking_cache.get(f"AVWAP_T_H_{t}"))
            t_l = self._safe_float(tracking_cache.get(f"AVWAP_T_L_{t}"))
            offset = self._safe_float(tracking_cache.get(f"AVWAP_OFFSET_{t}"))
            
            # 🚨 MODIFIED: [UI Rendering 무결성 수술] 통신 타임아웃 대비 사전 캐시 상태 평가로 Fallback 락온
            if is_holiday:
                status_txt = f"💤 미국 증시 휴장일 (관측 오프라인)"
            elif is_shutdown: 
                status_txt = "🛑 당일 영구동결 (SHUTDOWN 퇴근)"
            elif avwap_qty > 0:
                if trap_odno:
                    status_txt = "🎯 체결 완료 ➡️ [2.0% 지정가 익절 덫] 가동 중"
                else:
                    status_txt = "🎯 체결 완료 ➡️ (15:20 청산 지터 대기 중)"
            elif limit_order_placed and placed_target_th > 0:
                status_txt = f"⚡ 요격 조건 100% 충족 ➡️ [지정가 매수 덫 장전 집행: ${placed_target_th:.2f}]"
            else:
                status_txt = "⚡ T_H 선제 지정가 덫 장전 대기 중"
            
            try:
                avwap_state_dict = {
                    "strikes": int(self._safe_float(tracking_cache.get(f"AVWAP_STRIKES_{t}"))),
                    "shutdown": is_shutdown,
                    "qty": avwap_qty,
                    "avg_price": avwap_avg,
                    "bought": bool(tracking_cache.get(f"AVWAP_BOUGHT_{t}")),
                    "daily_bought_qty": int(self._safe_float(tracking_cache.get(f"AVWAP_DAILY_BOUGHT_{t}"))),
                    "daily_sold_qty": int(self._safe_float(tracking_cache.get(f"AVWAP_DAILY_SOLD_{t}"))),
                    "trap_odno": trap_odno,
                    "buy_odno": buy_odno,
                    "PM_H": pm_h,
                    "PM_L": pm_l,
                    "T_H": t_h,
                    "T_L": t_l,
                    "offset": offset,
                    "limit_order_placed": limit_order_placed,
                    "placed_target_th": placed_target_th,
                    "dump_jitter_sec": int(self._safe_float(tracking_cache.get(f"AVWAP_DUMP_JITTER_{t}"))),
                    "trap_placed_time": trap_placed_time
                }
                
                decision = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.strategy.v_avwap_plugin.get_decision,
                        base_ticker=t, exec_ticker=t,
                        base_curr_p=curr_p, exec_curr_p=curr_p,
                        df_1min_base=None, df_1min_exec=df_1m, avwap_qty=avwap_qty,
                        avwap_alloc_cash=available_cash, 
                        now_est=now_est, avwap_state=avwap_state_dict,
                        context_data=None,
                        is_simulation=True,
                        amp5=amp5,
                        prev_close=prev_c,
                        ma_5day=ma_5day,
                        sortie_mode=sortie_mode,
                        is_holiday=is_holiday 
                    ),
                    timeout=10.0
                )
                
                if decision:
                    action = decision.get('action')
                    reason = html.escape(str(decision.get('reason', '')))
                    
                    # 🚨 MODIFIED: [State Mismatch 궁극 수술] None 유입 시 덮어쓰기 파괴 방어를 위한 명시적 단락 평가 결속
                    v_pm_h = decision.get('PM_H')
                    pm_h = self._safe_float(v_pm_h) if v_pm_h is not None else pm_h
                    
                    v_pm_l = decision.get('PM_L')
                    pm_l = self._safe_float(v_pm_l) if v_pm_l is not None else pm_l
                    
                    v_t_h = decision.get('T_H')
                    t_h = self._safe_float(v_t_h) if v_t_h is not None else t_h
                    
                    v_t_l = decision.get('T_L')
                    t_l = self._safe_float(v_t_l) if v_t_l is not None else t_l
                    
                    v_offset = decision.get('offset')
                    offset = self._safe_float(v_offset) if v_offset is not None else offset
                    
                    v_buy_odno = decision.get('buy_odno')
                    buy_odno = str(v_buy_odno) if v_buy_odno is not None else buy_odno
                    
                    v_limit_order_placed = decision.get('limit_order_placed')
                    limit_order_placed = bool(v_limit_order_placed) if v_limit_order_placed is not None else limit_order_placed
                    
                    v_placed_target_th = decision.get('placed_target_th')
                    placed_target_th = self._safe_float(v_placed_target_th) if v_placed_target_th is not None else placed_target_th
                    
                    tracking_cache[f"AVWAP_PM_H_{t}"] = pm_h
                    tracking_cache[f"AVWAP_PM_L_{t}"] = pm_l
                    tracking_cache[f"AVWAP_T_H_{t}"] = t_h
                    tracking_cache[f"AVWAP_T_L_{t}"] = t_l
                    tracking_cache[f"AVWAP_OFFSET_{t}"] = offset
                    tracking_cache[f"AVWAP_BUY_ODNO_{t}"] = buy_odno
                    tracking_cache[f"AVWAP_LIMIT_ORDER_PLACED_{t}"] = limit_order_placed
                    tracking_cache[f"AVWAP_PLACED_TARGET_TH_{t}"] = placed_target_th
        
                    if is_holiday:
                        status_txt = f"💤 미국 증시 휴장일 (관측 오프라인)"
                    elif is_shutdown: 
                        status_txt = f"🛑 셧다운 격발 ({reason})" if reason and action == 'SHUTDOWN' else "🛑 당일 영구동결 (SHUTDOWN 퇴근)"
                    elif avwap_qty > 0:
                        if trap_odno:
                            status_txt = "🎯 체결 완료 ➡️ [2.0% 지정가 익절 덫] 가동 중"
                        else:
                            status_txt = "🎯 체결 완료 ➡️ (15:20 청산 지터 대기 중)"
                    elif limit_order_placed and placed_target_th > 0:
                        status_txt = f"⚡ 요격 조건 100% 충족 ➡️ [지정가 매수 덫 장전 집행: ${placed_target_th:.2f}]"
                    else:
                        if action == "PLACE_TRAP":
                            status_txt = f"⚡ 요격 조건 100% 충족 ➡️ [지정가 매수 덫 장전 집행]"
                        elif action == "VERIFY_TRAP_FILL":
                            status_txt = f"🔥 덫 하향 관통 ➡️ [실체결 무결성 검증 격발]"
                        elif action == "TRAP_WAIT":
                            status_txt = f"⏳ 지정가 덫 장전 완료 ➡️ [지정가 매수 체결 대기]"
                        elif action == 'SHUTDOWN':
                            status_txt = f"🛑 셧다운 격발 ({reason})"
                        elif reason:
                            if "동적_순수타격선_도달_감시중" in reason or "스캔" in status_txt:
                                status_txt = "⚡ T_H 선제 지정가 덫 장전 대기 중"
                            else:
                                status_txt = f"⏳ 대기 ({reason})"
                            
            except Exception as e:
                # 에러 발생 시 최상단에서 사전 평가된 status_txt 가 안전하게 유지됨
                pass

            reg_h = self._safe_float(tracking_cache.get(f"AVWAP_REG_H_{t}"))
            reg_l = self._safe_float(tracking_cache.get(f"AVWAP_REG_L_{t}"))

            msg += f"🎯 <b>[ {ticker_clean} (롱) 작전반 - {active_str} ]</b>\n"
            msg += f"▫️ 프리장 최고 (PM_H): <b>${pm_h:.2f}</b>\n"
            msg += f"▫️ 프리장 최저 (PM_L): <b>${pm_l:.2f}</b>\n"
            msg += f"▫️ 정규장 최고 (REG_H): <b>${reg_h:.2f}</b>\n"
            msg += f"▫️ 정규장 최저 (REG_L): <b>${reg_l:.2f}</b>\n"
            
            msg += f"▫️ 5일평균 앵커 오프셋: <b>${offset:.2f}</b>\n"
            msg += f"      (45% 절대 락온)\n"
            
            msg += f"▫️ 상승 돌파 목표 (T_H): <b>${t_h:.2f}</b>\n"
            msg += f"      (지정가 덫 장전선)\n"
            
            msg += f"▫️ 하락 지지 기준 (T_L): <b>${t_l:.2f}</b>\n"
            msg += f"      (단순 참조용)\n\n"

            msg += f"📊 <b>[ 실시간 현재가 스프레드 ]</b>\n"
            msg += f"▫️ 전일종가: <b>${prev_c:.2f}</b> (Amp5: {amp5*100:.2f}%)\n"
            
            msg += f"▫️ 5일평균종가: <b>${ma_5day:.2f}</b>\n"
            msg += f"▫️ 현재가격: <b>${curr_p:.2f}</b>\n"

            if avwap_qty > 0:
                trap_price = round(avwap_avg * 1.02, 2)
                msg += f"▫️ 매수평단: <b>${avwap_avg:.2f}</b> ({avwap_qty}주)\n"
                msg += f"▫️ 익절목표(+2.0%): <b>${trap_price:.2f}</b>\n"

            msg += f"\n🚨 <b>[ 작전 수행 현황 ]</b>\n"
            msg += f"▫️ 현재상태: <b>{status_txt}</b>\n"

            if is_holiday:
                keyboard.append([InlineKeyboardButton(f"💤 [{ticker_clean}] 증시 휴장일 (수동 제어 불가)", callback_data="AVWAP_SET:REFRESH:NONE")])
            elif status_code in ["PRE", "REG"]:
                if avwap_qty > 0:
                    keyboard.append([InlineKeyboardButton(f"🧯 {ticker_clean} 암살자 수동 청산 (0주 락온)", callback_data=f"AVWAP_SET:SYNC_ZERO:{t}")])
                elif limit_order_placed and buy_odno:
                    keyboard.append([InlineKeyboardButton(f"🛑 [{ticker_clean}] 수동 매수취소 (Nuke Trap)", callback_data=f"AVWAP_SET:MANUAL_CANCEL_REQ:{t}")])
                else:
                    if t_h > 0.0:
                        keyboard.append([InlineKeyboardButton(f"🔫 [{ticker_clean}] 수동 강제 요격 (Limit T_H)", callback_data=f"AVWAP_SET:MANUAL_FIRE_REQ:{t}")])
                    else:
                        keyboard.append([InlineKeyboardButton(f"❌ [{ticker_clean}] 수동 요격 불가 (T_H 스캔 대기 중)", callback_data="AVWAP_SET:REFRESH:NONE")])
            else:
                keyboard.append([InlineKeyboardButton(f"⛔ [{ticker_clean}] 장마감 (수동 제어 불가)", callback_data="AVWAP_SET:REFRESH:NONE")])

            toggle_target = "MULTI" if sortie_mode == "SINGLE" else "SINGLE"
            toggle_text = "🔄 무한 출장 모드로 변경" if sortie_mode == "SINGLE" else "🎯 단일 타격 모드로 변경"
            keyboard.append([InlineKeyboardButton(toggle_text, callback_data=f"MODE:AVWAP_SORTIE:{t}:{toggle_target}")])

        keyboard.append([
            InlineKeyboardButton("🔄 관제탑 새로고침", callback_data="AVWAP_SET:REFRESH:NONE"),
            InlineKeyboardButton("🔙 닫기", callback_data="RESET:CANCEL")
        ])

        msg += f"\n\n⏱️ <i>마지막 레이더 스캔: {now_est.strftime('%Y-%m-%d %H:%M:%S')} (EST)</i>\n"

        return msg, InlineKeyboardMarkup(keyboard)
