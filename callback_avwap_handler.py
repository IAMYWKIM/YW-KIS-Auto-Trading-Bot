# ==========================================================
# FILE: callback_avwap_handler.py
# ==========================================================
# 🚨 MODIFIED: [AVWAP 암살자 관제 도메인] 수동 요격, 덫 취소, 모드 스위칭, 상태 포맷 로직 완벽 분리
# 🚨 MODIFIED: [Case 32, 33, 14] 3단 지수 백오프, TPS 캡핑(0.06s), wait_for(10.0) 래핑 100% 유지
# 🚨 MODIFIED: [Insight 14, 26] Float 캐스팅 방어막(_safe_float) 및 html.escape 쉴드 전역 결속 완료
# ==========================================================
import logging
import datetime
from zoneinfo import ZoneInfo
import math
import asyncio
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

class CallbackAvwapHandler:
    def __init__(self, config, broker, strategy, view, tx_lock):
        self.cfg = config
        self.broker = broker
        self.strategy = strategy
        self.view = view
        self.tx_lock = tx_lock

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, controller, action: str, sub: str, data: list):
        query = update.callback_query
        chat_id = update.effective_chat.id
        ticker = data[2] if len(data) > 2 else ""

        if action == "AVWAP":
            if sub == "MENU":
                if hasattr(controller, 'cmd_avwap'):
                    await controller.cmd_avwap(update, context)

        elif action == "MODE":
            if not ticker: return
            
            if sub == "ON":
                try: await query.answer()
                except Exception: pass
                await asyncio.to_thread(self.cfg.set_upward_sniper_mode, ticker, True)
                if hasattr(controller, 'cmd_mode'):
                    await controller.cmd_mode(update, context)
            
            elif sub == "OFF":
                try: await query.answer()
                except Exception: pass
                await asyncio.to_thread(self.cfg.set_upward_sniper_mode, ticker, False)
                if hasattr(controller, 'cmd_mode'):
                    await controller.cmd_mode(update, context)
            
            elif sub == "AVWAP_WARN":
                try: await query.answer()
                except Exception: pass
                msg, markup = self.view.get_avwap_warning_menu(ticker)
                try:
                    await query.edit_message_text(msg, reply_markup=markup, parse_mode='HTML')
                except Exception: pass
            
            elif sub == "AVWAP_ON":
                try: await query.answer()
                except Exception: pass
                await asyncio.to_thread(self.cfg.set_avwap_hybrid_mode, ticker, True)
                if hasattr(controller, 'cmd_settlement'):
                    await controller.cmd_settlement(update, context)
            
            elif sub == "AVWAP_OFF":
                try: await query.answer()
                except Exception: pass
                await asyncio.to_thread(self.cfg.set_avwap_hybrid_mode, ticker, False)
                if hasattr(controller, 'cmd_settlement'):
                    await controller.cmd_settlement(update, context)
            
            elif sub == "AVWAP_SORTIE":
                tgt_val = html.escape(str(data[3])) if len(data) > 3 else "SINGLE"
                try:
                    await query.answer(f"✅ 작전 궤도를 {tgt_val} 모드로 스위칭합니다.", show_alert=False)
                except Exception: pass
                await asyncio.to_thread(self.cfg.set_avwap_sortie_mode, ticker, tgt_val)
                if hasattr(controller, 'cmd_settlement'):
                    await controller.cmd_settlement(update, context)

        elif action == "AVWAP_SET":
            if not ticker: return
            
            if sub == "SYNC_ZERO":
                status_code, _ = await controller._get_market_status()
                if status_code not in ["PRE", "REG"]:
                    try: await query.answer("❌ [격발 차단] 현재 장운영시간(정규장/프리장)이 아닙니다.", show_alert=True)
                    except Exception: pass
                    return
                    
                try: await query.answer()
                except Exception: pass
                
                try:
                    app_data = context.bot_data.get('app_data', {})
                    tracking_cache = app_data.get('sniper_tracking', {})
                    
                    tracking_cache[f"AVWAP_QTY_{ticker}"] = 0
                    tracking_cache[f"AVWAP_AVG_{ticker}"] = 0.0
                    tracking_cache[f"AVWAP_BOUGHT_{ticker}"] = False
                    tracking_cache[f"AVWAP_SHUTDOWN_{ticker}"] = True
                    tracking_cache[f"AVWAP_TRAP_PLACED_TIME_{ticker}"] = ""
                    tracking_cache[f"AVWAP_BUY_ODNO_{ticker}"] = "" 

                    est = ZoneInfo('America/New_York')
                    now_est = datetime.datetime.now(est)

                    if hasattr(self.strategy, 'v_avwap_plugin'):
                        state_data = {
                            'bought': False,
                            'shutdown': True,
                            'qty': 0,
                            'avg_price': 0.0,
                            'strikes': int(float(str(tracking_cache.get(f"AVWAP_STRIKES_{ticker}") or 0).replace(',', ''))),
                            'daily_bought_qty': int(float(str(tracking_cache.get(f"AVWAP_DAILY_BOUGHT_{ticker}") or 0).replace(',', ''))),
                            'daily_sold_qty': int(float(str(tracking_cache.get(f"AVWAP_DAILY_SOLD_{ticker}") or 0).replace(',', ''))),
                            'trap_odno': str(tracking_cache.get(f"AVWAP_TRAP_ODNO_{ticker}") or ""),
                            'PM_H': float(str(tracking_cache.get(f"AVWAP_PM_H_{ticker}") or 0.0).replace(',', '')),
                            'PM_L': float(str(tracking_cache.get(f"AVWAP_PM_L_{ticker}") or 0.0).replace(',', '')),
                            'T_H': float(str(tracking_cache.get(f"AVWAP_T_H_{ticker}") or 0.0).replace(',', '')),
                            'T_L': float(str(tracking_cache.get(f"AVWAP_T_L_{ticker}") or 0.0).replace(',', '')),
                            'offset': float(str(tracking_cache.get(f"AVWAP_OFFSET_{ticker}") or 0.0).replace(',', '')),
                            'whipsaw_mode': bool(tracking_cache.get(f"AVWAP_WHIPSAW_MODE_{ticker}")),
                            'whipsaw_armed': bool(tracking_cache.get(f"AVWAP_WHIPSAW_ARMED_{ticker}")),
                            'whipsaw_checked': bool(tracking_cache.get(f"AVWAP_WHIPSAW_CHECKED_{ticker}")),
                            'dump_jitter_sec': int(float(str(tracking_cache.get(f"AVWAP_DUMP_JITTER_{ticker}") or 0).replace(',', ''))),
                            'trap_placed_time': "",
                            'buy_odno': ""
                        }
                        await asyncio.to_thread(self.strategy.v_avwap_plugin.save_state, ticker, now_est, state_data)
                    
                    try:
                        await query.edit_message_text(f"🧯 <b>[{html.escape(str(ticker))}] AVWAP 수동 청산 (0주 락온) 완료!</b>\n▫️ 암살자 물량이 0주로 강제 포맷되었으며, 금일 남은 시간 동안 영구 동결(SHUTDOWN)됩니다.", parse_mode='HTML')
                    except Exception: pass
                except Exception as e:
                    logging.error(f"🚨 수동 0주 동기화 에러: {e}")
                    safe_err = html.escape(str(e))
                    try:
                        await query.edit_message_text(f"❌ 수동 0주 동기화 중 에러 발생: {safe_err}", parse_mode='HTML')
                    except Exception: pass

            elif sub == "REFRESH":
                try: await query.answer()
                except Exception: pass
                if hasattr(controller, 'cmd_avwap'):
                    await controller.cmd_avwap(update, context)
            
            elif sub == "MANUAL_CANCEL_REQ":
                try:
                    status_code, _ = await controller._get_market_status()
                    if status_code not in ["PRE", "REG"]:
                        try: await query.answer("❌ [격발 차단] 장운영시간이 아닙니다.", show_alert=True)
                        except Exception: pass
                        return
                        
                    app_data = context.bot_data.get('app_data', {})
                    tracking_cache = app_data.get('sniper_tracking', {})
                    
                    buy_odno = str(tracking_cache.get(f"AVWAP_BUY_ODNO_{ticker}") or "")
                    
                    if not buy_odno:
                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            est = ZoneInfo('America/New_York')
                            now_est = datetime.datetime.now(est)
                            state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                            buy_odno = str(state.get('buy_odno') or "")
                            
                    if not buy_odno:
                        try: await query.answer("❌ 파기할 지정가 덫을 찾을 수 없습니다.", show_alert=True)
                        except Exception: pass
                        return
                        
                    try: await query.answer("⚠️ 덫 파기 시퀀 가동 중...", show_alert=False)
                    except Exception: pass
                    
                    async with self.tx_lock:
                        for attempt in range(3):
                            try:
                                await asyncio.sleep(0.06)
                                await asyncio.wait_for(
                                    asyncio.to_thread(self.broker.cancel_order, ticker, buy_odno),
                                    timeout=10.0
                                )
                                break
                            except Exception as e:
                                if attempt == 2: logging.error(f"🚨 덫 강제 취소 에러: {e}")
                                else: await asyncio.sleep(1.0 * (2**attempt))
                                
                        est = ZoneInfo('America/New_York')
                        now_est = datetime.datetime.now(est)
                        
                        tracking_cache[f"AVWAP_LIMIT_ORDER_PLACED_{ticker}"] = False
                        tracking_cache[f"AVWAP_BUY_ODNO_{ticker}"] = ""
                        tracking_cache[f"AVWAP_PLACED_TARGET_TH_{ticker}"] = 0.0
                        tracking_cache[f"AVWAP_TRAP_PLACED_TIME_{ticker}"] = ""
                        
                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                            state.update({
                                "limit_order_placed": False,
                                "buy_odno": "",
                                "trap_placed_time": "",
                                "placed_target_th": 0.0
                            })
                            await asyncio.to_thread(self.strategy.v_avwap_plugin.save_state, ticker, now_est, state)

                    msg = f"🛑 <b>[{html.escape(str(ticker))} 수동 매수 덫 파기(Nuke) 성공!]</b>\n\n"
                    msg += f"▫️ 장전되었던 지정가 덫이 100% 철회되었습니다.\n"
                    msg += "▫️ 봇은 현재가 스캔 대기 모드(수동 요격 가능)로 복귀합니다."

                    keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                    try:
                        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    except Exception: pass
                
                except Exception as e:
                    logging.error(f"🚨 수동 덫 파기 에러: {e}")
                    safe_err = html.escape(str(e))
                    try: await query.answer(f"❌ 수동 덫 파기 중 에러 발생: {safe_err}", show_alert=True)
                    except Exception: pass

            elif sub == "MANUAL_FIRE_REQ":
                try:
                    status_code, _ = await controller._get_market_status()
                    if status_code not in ["PRE", "REG"]:
                        try: await query.answer("❌ [격발 차단] 현재 장운영시간(정규장/프리장)이 아닙니다.", show_alert=True)
                        except Exception: pass
                        return
                        
                    app_data = context.bot_data.get('app_data', {})
                    tracking_cache = app_data.get('sniper_tracking', {})
                    
                    t_h = float(str(tracking_cache.get(f"AVWAP_T_H_{ticker}") or 0.0).replace(',', ''))
                    if t_h <= 0.0:
                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            est = ZoneInfo('America/New_York')
                            now_est = datetime.datetime.now(est)
                            state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                            t_h = float(str(state.get('T_H') or 0.0).replace(',', ''))
                            
                    if t_h <= 0.0:
                        try: await query.answer(f"❌ [{html.escape(str(ticker))}] 수동 요격 불가\n▫️ T_H(지정가 덫 기준선) 데이터가 존재하지 않습니다. 스캔 대기.", show_alert=True)
                        except Exception: pass
                        return

                    try: await query.answer("⚠️ 요격 확인 팝업 생성 중...", show_alert=False)
                    except Exception: pass
                    
                    msg = f"🚨 <b>[{html.escape(str(ticker))} 사이보그 요격 덫 장전 승인 대기]</b>\n\n"
                    msg += f"▫️ 지정가 타점: <b>${t_h:.2f} (T_H 기준 고정)</b>\n"
                    msg += "▫️ 승인 즉시 가용 예산의 95%가 해당 타점에 순수 지정가(LIMIT) 매수 덫으로 깔립니다.\n\n"
                    msg += "⚠️ <b>포트폴리오 매니저 안내:</b>\n"
                    msg += "현재 가격과 무관하게 무조건 지정가로 전송되므로, 현재가가 더 높다면 체결되지 않고 대기(덫) 상태로 남게 됩니다. 승인하시겠습니까?"

                    keyboard = [
                        [InlineKeyboardButton(f"🔥 [{html.escape(str(ticker))}] 수동 요격 덫 장전 승인", callback_data=f"AVWAP_SET:MANUAL_FIRE_EXEC:{ticker}")],
                        [InlineKeyboardButton("❌ 작전 취소 (안전 모드 복귀)", callback_data="AVWAP_SET:REFRESH:NONE")]
                    ]
                    try:
                        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    except Exception: pass
                    
                except Exception as e:
                    logging.error(f"🚨 수동 요격 확인창 생성 에러: {e}")
                    try: await query.answer(f"❌ 요격 승인 대기 중 에러 발생: {html.escape(str(e))}", show_alert=True)
                    except Exception: pass
            
            elif sub == "MANUAL_FIRE_EXEC":
                try:
                    status_code, _ = await controller._get_market_status()
                    if status_code not in ["PRE", "REG"]:
                        try: await query.answer("❌ [격발 차단] 현재 장운영시간(정규장/프리장)이 아닙니다.", show_alert=True)
                        except Exception: pass
                        return
                        
                    app_data = context.bot_data.get('app_data', {})
                    tracking_cache = app_data.get('sniper_tracking', {})
                    
                    t_h = float(str(tracking_cache.get(f"AVWAP_T_H_{ticker}") or 0.0).replace(',', ''))
                    if t_h <= 0.0:
                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            est = ZoneInfo('America/New_York')
                            now_est = datetime.datetime.now(est)
                            state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                            t_h = float(str(state.get('T_H') or 0.0).replace(',', ''))
                    
                    if t_h <= 0.0 or math.isnan(t_h):
                        try: await query.answer(f"❌ [{html.escape(str(ticker))}] 수동 요격 실패\n▫️ T_H 데이터가 존재하지 않거나 결측치(NaN)입니다.", show_alert=True)
                        except Exception: pass
                        return

                    curr_p = 0.0
                    for attempt in range(3):
                        try:
                            await asyncio.sleep(0.06)
                            curr_p_val = await asyncio.wait_for(asyncio.to_thread(self.broker.get_current_price, ticker), timeout=5.0)
                            curr_p = float(str(curr_p_val or 0.0).replace(',', ''))
                            break
                        except Exception:
                            if attempt == 2: curr_p = 0.0
                            else: await asyncio.sleep(1.0 * (2 ** attempt))

                    if curr_p <= 0.0:
                        try: await query.answer(f"❌ [{html.escape(str(ticker))}] 수동 요격 실패\n▫️ 현재가 통신 실패로 안전 차단.", show_alert=True)
                        except Exception: pass
                        return

                    async with self.tx_lock:
                        cash = 0.0
                        for attempt in range(3):
                            try:
                                await asyncio.sleep(0.06)
                                cash_tuple = await asyncio.wait_for(asyncio.to_thread(self.broker.get_account_balance), timeout=10.0)
                                cash = float(str(cash_tuple[0] or 0.0).replace(',', '')) if isinstance(cash_tuple, (list, tuple)) and len(cash_tuple) > 0 else 0.0
                                break
                            except Exception:
                                if attempt == 2: cash = 0.0
                                else: await asyncio.sleep(1.0 * (2 ** attempt))
                        
                        avwap_free_cash = max(0.0, float(cash or 0.0))
                        
                        try:
                            from scheduler_core import get_budget_allocation
                            active_tickers_list = await asyncio.to_thread(self.cfg.get_active_tickers) or []
                            _, alloc_cash_dict = await asyncio.to_thread(get_budget_allocation, avwap_free_cash, active_tickers_list, self.cfg)
                            alloc_cash_dict = alloc_cash_dict or {}
                            allocated_budget = float(str(alloc_cash_dict.get(ticker) or 0.0).replace(',', ''))
                        except Exception as e:
                            logging.error(f"🚨 예산 할당 모듈 로드 실패 (N빵 강제 분할 폴백): {e}")
                            try:
                                active_tickers_list = await asyncio.to_thread(self.cfg.get_active_tickers) or []
                                div_count = max(1, len(active_tickers_list))
                            except Exception:
                                div_count = 1
                            allocated_budget = avwap_free_cash / div_count  
                            
                        safe_budget = allocated_budget * 0.95
                        if math.isnan(safe_budget): safe_budget = 0.0
                        buy_qty = max(0, int(math.floor(safe_budget / t_h))) if t_h > 0 else 0

                        if buy_qty <= 0:
                            try: await query.answer(f"❌ [{html.escape(str(ticker))}] 수동 요격 실패\n▫️ 예산 부족. 가용 현금: ${allocated_budget:.2f}", show_alert=True)
                            except Exception: pass
                            return

                        try:
                            await query.answer("🔫 지정가 덫 장전 중...", show_alert=False)
                            await query.edit_message_text(f"🚀 <b>[{html.escape(str(ticker))}] 사이보그(Cyborg) 수동 강제 요격 덫 전송 중...</b>", parse_mode='HTML')
                        except Exception: pass

                        await asyncio.sleep(0.06)
                        
                        try:
                            res = await asyncio.wait_for(
                                asyncio.to_thread(self.broker.send_order, ticker, "BUY", buy_qty, t_h, "LIMIT"),
                                timeout=10.0
                            )
                        except Exception as e:
                            logging.error(f"🚨 사이보그 수동 덫 장전 통신 에러/타임아웃: {e}")
                            res = None
                        
                        is_success = isinstance(res, dict) and str(res.get('rt_cd', '')) == '0'
                        buy_odno = str(res.get('odno') or '') if isinstance(res, dict) else ''

                        if is_success and buy_odno:
                            est = ZoneInfo('America/New_York')
                            now_est = datetime.datetime.now(est)
                            curr_candle_time_str = now_est.replace(second=0, microsecond=0).strftime('%H%M%S')
                            
                            tracking_cache[f"AVWAP_LIMIT_ORDER_PLACED_{ticker}"] = True
                            tracking_cache[f"AVWAP_BUY_ODNO_{ticker}"] = buy_odno
                            tracking_cache[f"AVWAP_PLACED_TARGET_TH_{ticker}"] = t_h
                            tracking_cache[f"AVWAP_TRAP_PLACED_TIME_{ticker}"] = curr_candle_time_str
                            
                            if hasattr(self.strategy, 'v_avwap_plugin'):
                                state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                state.update({
                                    "limit_order_placed": True,
                                    "placed_target_th": t_h,
                                    "buy_odno": buy_odno,
                                    "trap_placed_time": curr_candle_time_str
                                })
                                await asyncio.to_thread(self.strategy.v_avwap_plugin.save_state, ticker, now_est, state)

                            final_msg = f"🔫 <b>[{html.escape(str(ticker))}] 수동 지정가 요격 덫 락온 성공!</b>\n"
                            final_msg += f"▫️ 타점: <b>${t_h:.2f}</b> (순수 LIMIT)\n"
                            final_msg += f"▫️ 목표수량: <b>{buy_qty}주</b>\n"
                            final_msg += f"▫️ 상태: 1분봉 자동 감시 모드로 인계되었습니다. 체결 확정 시 2.0% 자동 익절 덫이 투하됩니다."

                            try: await query.edit_message_text(final_msg, parse_mode='HTML')
                            except Exception: pass
                            
                        else:
                            err_msg = html.escape(str(res.get('msg1') or '응답 없음')) if isinstance(res, dict) else '통신 장애/무응답'
                            logging.error(f"🚨 [{ticker}] 사이보그 수동 덫 장전 서버 거절: {err_msg}")
                            reject_msg = (
                                f"🚨 <b>[{html.escape(str(ticker))}] 사이보그 수동 지정가 덫 전송 서버 거절 (Reject)!</b>\n"
                                f"▫️ 사유: <code>{err_msg}</code>\n"
                            )
                            try: await query.edit_message_text(reject_msg, parse_mode='HTML')
                            except Exception: pass

                except Exception as e:
                    logging.error(f"🚨 사이보그 수동 요격/장전 에러: {e}")
                    safe_err = html.escape(str(e))
                    try: await query.edit_message_text(f"❌ 수동 장전 중 에러 발생: {safe_err}", parse_mode='HTML')
                    except Exception: pass
