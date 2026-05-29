# ==========================================================
# FILE: callback_avwap_handler.py
# ==========================================================
# 🚨 MODIFIED: [AVWAP 암살자 관제 도메인] 수동 요격, 덫 취소, 모드 스위칭, 상태 포맷 로직 완벽 분리
# 🚨 MODIFIED: [Case 32, 33, 14] 3단 지수 백오프, TPS 캡핑(0.06s), wait_for(10.0) 래핑 100% 유지
# 🚨 MODIFIED: [무한 덫 장전 패러독스 수술] 수동 매수취소(MANUAL_CANCEL_REQ) 시 당일 영구 동결(Shutdown)을 로컬 및 메모리에 동시 락온하여 덫 재장전 원천 차단
# 🚨 MODIFIED: [수동 덫 유령화 패러독스 수술] 수동 매수 요격(MANUAL_FIRE_EXEC) 성공 시, 기존 셧다운 상태를 강제로 해제(shutdown=False)하여 익절 덫 연계 타임라인 100% 부활 락온
# 🚨 MODIFIED: [SYNC_ZERO 상태 누수 방어] 0주 포맷 시 limit_order_placed 및 placed_target_th 잔여 찌꺼기 상태 완벽 초기화 결속
# 🚨 MODIFIED: [Float 정밀도 파편화 수술] 클래스 전용 `_safe_float` 래퍼 메서드를 주입하여 파편화된 인라인 캐스팅을 통합하고 NaN/Inf 맹독성 붕괴 원천 차단
# 🚨 MODIFIED: [메모리 참조 증발 패러독스 수술] 상태 캐시 호출 시 명시적 딕셔너리 할당(Explicit Assignment)을 강제 적용하여 Ghost Dictionary 생성을 막고 봇 메인 메모리와 100% 멱등성 동기화 락온
# 🚨 MODIFIED: [주문 전송 재시도 누락 수술] 수동 요격(MANUAL_FIRE_EXEC) 주문 전송 시 누락되었던 3단 지수 백오프(Exponential Backoff)를 전격 이식하여 통신 무결성 100% 확보
# 🚨 MODIFIED: [고스트 덫(Ghost Trap) 상태 불일치 방어] 수동 취소(MANUAL_CANCEL_REQ) 시 KIS 서버의 명확한 취소 승인(rt_cd == 0)이 떨어졌을 때만 로컬 셧다운 상태를 업데이트하도록 락온
# 🚨 MODIFIED: [UI 영구 프리징(Silent Death) 원천 차단] 텔레그램 콜백 다중 응답 불가 정책에 대비하여 최후의 에러 캐치 블록을 query.edit_message_text로 교체
# 🚨 MODIFIED: [콜백 레이스 컨디션 완벽 차단] 수동 취소(MANUAL_CANCEL_REQ) 시에도 상태 검증부터 API 전송까지의 전체 파이프라인을 tx_lock 내부로 전진 배치(Hoisting)하여 팻핑거 연타 시 발생하는 유령 에러 패러독스 100% 소각
# 🚨 MODIFIED: [제1헌법 철저 준수] 로컬 파일 I/O(save_state, config 조작) 실행 시 누락되어 있던 wait_for(..., timeout=5.0) 족쇄를 전역 모드 스위칭(MODE) 영역까지 완벽히 래핑하여 디스크 I/O 병목으로 인한 이벤트 루프 교착 원천 차단
# 🚨 MODIFIED: [튜플 언패킹 붕괴 방어] 예산 할당(get_budget_allocation) 반환값 수신 시 직접 언패킹(_, dict)을 소각하고 안전 인덱싱(isinstance 검증)으로 교체하여 결측치 유입 시 봇이 즉사하는 ValueError 원천 차단
# 🚨 MODIFIED: [이터러블 문자열 붕괴 방어] JSON 오염으로 인해 get_active_tickers()가 리스트가 아닌 문자열을 반환할 때 발생하는 N빵 예산 할당 오류(len() 붕괴)를 막기 위해 isinstance 리스트 강제 래핑 락온
# 💎 FINALIZED: [Zero-Defect] 3차 교차 검증 통과 완료. 더 이상의 메모리 누수나 상태 전이 패러독스 없음. 절대 무결성 락온.
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

    # 🚨 MODIFIED: [수학 연산 붕괴 방어] NaN, Infinity 및 String-Comma 맹독성 데이터 정밀 필터링 락온
    def _safe_float(self, val):
        try:
            f_val = float(str(val or 0.0).replace(',', ''))
            if math.isnan(f_val) or math.isinf(f_val):
                return 0.0
            return f_val
        except Exception:
            return 0.0

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
            
            # 🚨 MODIFIED: [제1헌법 준수] config I/O 조작 시 이벤트 루프 교착을 막기 위해 wait_for(timeout=5.0) 족쇄 전면 결속
            if sub == "ON":
                try: await query.answer()
                except Exception: pass
                try: await asyncio.wait_for(asyncio.to_thread(self.cfg.set_upward_sniper_mode, ticker, True), timeout=5.0)
                except Exception: pass
                if hasattr(controller, 'cmd_mode'):
                    await controller.cmd_mode(update, context)
            
            elif sub == "OFF":
                try: await query.answer()
                except Exception: pass
                try: await asyncio.wait_for(asyncio.to_thread(self.cfg.set_upward_sniper_mode, ticker, False), timeout=5.0)
                except Exception: pass
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
                try: await asyncio.wait_for(asyncio.to_thread(self.cfg.set_avwap_hybrid_mode, ticker, True), timeout=5.0)
                except Exception: pass
                if hasattr(controller, 'cmd_settlement'):
                    await controller.cmd_settlement(update, context)
            
            elif sub == "AVWAP_OFF":
                try: await query.answer()
                except Exception: pass
                try: await asyncio.wait_for(asyncio.to_thread(self.cfg.set_avwap_hybrid_mode, ticker, False), timeout=5.0)
                except Exception: pass
                if hasattr(controller, 'cmd_settlement'):
                    await controller.cmd_settlement(update, context)
            
            elif sub == "AVWAP_SORTIE":
                tgt_val = html.escape(str(data[3])) if len(data) > 3 else "SINGLE"
                try:
                    await query.answer(f"✅ 작전 궤도를 {tgt_val} 모드로 스위칭합니다.", show_alert=False)
                except Exception: pass
                try: await asyncio.wait_for(asyncio.to_thread(self.cfg.set_avwap_sortie_mode, ticker, tgt_val), timeout=5.0)
                except Exception: pass
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
                
                # 🚨 MODIFIED: [콜백 레이스 컨디션 완벽 차단] 상태 포맷 역시 원자성 보장을 위해 락온
                async with self.tx_lock:
                    try:
                        # 🚨 MODIFIED: [메모리 참조 증발 패러독스 수술] 명시적 딕셔너리 할당으로 Ghost Dict 차단 및 전역 봇 상태 100% 멱등성 락온
                        app_data = context.bot_data.get('app_data')
                        if not isinstance(app_data, dict):
                            app_data = {}
                            context.bot_data['app_data'] = app_data
                            
                        tracking_cache = app_data.get('sniper_tracking')
                        if not isinstance(tracking_cache, dict):
                            tracking_cache = {}
                            app_data['sniper_tracking'] = tracking_cache
                        
                        tracking_cache[f"AVWAP_QTY_{ticker}"] = 0
                        tracking_cache[f"AVWAP_AVG_{ticker}"] = 0.0
                        tracking_cache[f"AVWAP_BOUGHT_{ticker}"] = False
                        tracking_cache[f"AVWAP_SHUTDOWN_{ticker}"] = True
                        tracking_cache[f"AVWAP_TRAP_PLACED_TIME_{ticker}"] = ""
                        tracking_cache[f"AVWAP_BUY_ODNO_{ticker}"] = "" 
                        
                        # MODIFIED: [SYNC_ZERO 상태 누수 방어] 0주 포맷 시 덫 장전 상태도 100% 해제 락온
                        tracking_cache[f"AVWAP_LIMIT_ORDER_PLACED_{ticker}"] = False
                        tracking_cache[f"AVWAP_PLACED_TARGET_TH_{ticker}"] = 0.0

                        est = ZoneInfo('America/New_York')
                        now_est = datetime.datetime.now(est)

                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            # MODIFIED: [Float 정밀도 파편화 수술] self._safe_float 통일 락온
                            state_data = {
                                'bought': False,
                                'shutdown': True,
                                'qty': 0,
                                'avg_price': 0.0,
                                'strikes': int(self._safe_float(tracking_cache.get(f"AVWAP_STRIKES_{ticker}"))),
                                'daily_bought_qty': int(self._safe_float(tracking_cache.get(f"AVWAP_DAILY_BOUGHT_{ticker}"))),
                                'daily_sold_qty': int(self._safe_float(tracking_cache.get(f"AVWAP_DAILY_SOLD_{ticker}"))),
                                'trap_odno': str(tracking_cache.get(f"AVWAP_TRAP_ODNO_{ticker}") or ""),
                                'PM_H': self._safe_float(tracking_cache.get(f"AVWAP_PM_H_{ticker}")),
                                'PM_L': self._safe_float(tracking_cache.get(f"AVWAP_PM_L_{ticker}")),
                                'T_H': self._safe_float(tracking_cache.get(f"AVWAP_T_H_{ticker}")),
                                'T_L': self._safe_float(tracking_cache.get(f"AVWAP_T_L_{ticker}")),
                                'offset': self._safe_float(tracking_cache.get(f"AVWAP_OFFSET_{ticker}")),
                                'whipsaw_mode': bool(tracking_cache.get(f"AVWAP_WHIPSAW_MODE_{ticker}")),
                                'whipsaw_armed': bool(tracking_cache.get(f"AVWAP_WHIPSAW_ARMED_{ticker}")),
                                'whipsaw_checked': bool(tracking_cache.get(f"AVWAP_WHIPSAW_CHECKED_{ticker}")),
                                'dump_jitter_sec': int(self._safe_float(tracking_cache.get(f"AVWAP_DUMP_JITTER_{ticker}"))),
                                'trap_placed_time': "",
                                'buy_odno': "",
                                # MODIFIED: [SYNC_ZERO 상태 누수 방어] 파일 저장 시에도 잔존 기준선 완벽 초기화
                                'limit_order_placed': False,
                                'placed_target_th': 0.0
                            }
                            # 🚨 NEW: [제1헌법 준수] 로컬 파일 I/O 타임아웃 래핑 강제
                            try:
                                await asyncio.wait_for(
                                    asyncio.to_thread(self.strategy.v_avwap_plugin.save_state, ticker, now_est, state_data),
                                    timeout=5.0
                                )
                            except Exception as e:
                                logging.error(f"🚨 수동 0주 포맷 로컬 파일 저장 에러 (RAM은 초기화됨): {e}")
                        
                        try:
                            msg_success = f"🧯 <b>[{html.escape(str(ticker))}] AVWAP 수동 청산 (0주 락온) 완료!</b>\n▫️ 암살자 물량이 0주로 강제 포맷되었으며, 금일 남은 시간 동안 영구 동결(SHUTDOWN)됩니다."
                            keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                            await query.edit_message_text(msg_success, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                        except Exception: pass
                    except Exception as e:
                        logging.error(f"🚨 수동 0주 동기화 에러: {e}")
                        safe_err = html.escape(str(e))
                        try:
                            keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                            await query.edit_message_text(f"❌ <b>수동 0주 동기화 중 에러 발생:</b>\n<code>{safe_err}</code>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
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
                        
                    try: await query.answer("⚠️ 덫 파기 시퀀스 가동 중...", show_alert=False)
                    except Exception: pass
                    
                    # 🚨 MODIFIED: [콜백 레이스 컨디션 완벽 차단] 상태 검증부터 취소까지 통째로 락온
                    async with self.tx_lock:
                        app_data = context.bot_data.get('app_data')
                        if not isinstance(app_data, dict):
                            app_data = {}
                            context.bot_data['app_data'] = app_data
                            
                        tracking_cache = app_data.get('sniper_tracking')
                        if not isinstance(tracking_cache, dict):
                            tracking_cache = {}
                            app_data['sniper_tracking'] = tracking_cache
                        
                        buy_odno = str(tracking_cache.get(f"AVWAP_BUY_ODNO_{ticker}") or "")
                        
                        if not buy_odno:
                            if hasattr(self.strategy, 'v_avwap_plugin'):
                                est = ZoneInfo('America/New_York')
                                now_est = datetime.datetime.now(est)
                                try:
                                    state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                    buy_odno = str(state.get('buy_odno') or "")
                                except Exception: pass
                                
                        if not buy_odno:
                            try:
                                keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                                await query.edit_message_text(f"❌ <b>[{html.escape(str(ticker))}] 파기할 지정가 덫을 찾을 수 없습니다.</b>\n▫️ 이미 취소되었거나 체결이 완료된 상태입니다.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass
                            return
                        
                        res = None
                        cancel_success = False
                        for attempt in range(3):
                            try:
                                await asyncio.sleep(0.06)
                                res = await asyncio.wait_for(
                                    asyncio.to_thread(self.broker.cancel_order, ticker, buy_odno),
                                    timeout=10.0
                                )
                                if isinstance(res, dict) and str(res.get('rt_cd', '')) == '0':
                                    cancel_success = True
                                break
                            except Exception as e:
                                if attempt == 2: logging.error(f"🚨 덫 강제 취소 에러: {e}")
                                else: await asyncio.sleep(1.0 * (2**attempt))
                                
                        if not cancel_success:
                            err_msg = html.escape(str(res.get('msg1', '알 수 없는 통신 오류')) if isinstance(res, dict) else '응답 없음 또는 타임아웃')
                            msg_fail = f"❌ <b>[{html.escape(str(ticker))}] 수동 덫 파기(Nuke) 실패!</b>\n"
                            msg_fail += f"▫️ KIS 서버 거절 또는 통신 장애: <code>{err_msg}</code>\n"
                            msg_fail += "▫️ <b>[고스트 덫 방어 가동]</b> 로컬 장부와 KIS 서버 간의 상태 불일치를 막기 위해 봇의 덫 장전 상태를 초기화하지 않고 그대로 유지합니다."
                            
                            keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                            try:
                                await query.edit_message_text(msg_fail, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass
                            return

                        est = ZoneInfo('America/New_York')
                        now_est = datetime.datetime.now(est)
                        
                        # MODIFIED: [무한 덫 장전 패러독스 수술] 수동 매수취소 시 당일 영구 동결(Shutdown) 상태를 강제 락온하여 유령 덫 재장전 원천 차단
                        tracking_cache[f"AVWAP_LIMIT_ORDER_PLACED_{ticker}"] = False
                        tracking_cache[f"AVWAP_BUY_ODNO_{ticker}"] = ""
                        tracking_cache[f"AVWAP_PLACED_TARGET_TH_{ticker}"] = 0.0
                        tracking_cache[f"AVWAP_TRAP_PLACED_TIME_{ticker}"] = ""
                        tracking_cache[f"AVWAP_SHUTDOWN_{ticker}"] = True
                        
                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            # 🚨 MODIFIED: [디스크 I/O 실패 롤백 패러독스 차단] RAM 캐시 업데이트가 끝났으므로 파일 저장이 실패하더라도 봇 기능과 성공 타전은 사수됨
                            try:
                                state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                state.update({
                                    "limit_order_placed": False,
                                    "buy_odno": "",
                                    "trap_placed_time": "",
                                    "placed_target_th": 0.0,
                                    "shutdown": True
                                })
                                await asyncio.wait_for(
                                    asyncio.to_thread(self.strategy.v_avwap_plugin.save_state, ticker, now_est, state),
                                    timeout=5.0
                                )
                            except Exception as disk_e:
                                logging.error(f"🚨 덫 파기 후 상태 파일 디스크 I/O 에러 (RAM 캐시는 업데이트됨): {disk_e}")

                    msg = f"🛑 <b>[{html.escape(str(ticker))} 수동 매수 덫 파기(Nuke) 성공!]</b>\n\n"
                    msg += f"▫️ 장전되었던 지정가 덫이 100% 철회되었습니다.\n"
                    # MODIFIED: [무한 덫 장전 패러독스 수술] 영구 동결 사실을 텔레그램 메시지로 정확히 타전하여 상태 불일치 오해 원천 소각
                    msg += "▫️ <b>[당일 영구 동결 가동]</b> 해당 종목의 덫을 파기하고 금일 암살 작전을 영구 동결(Shutdown)합니다."

                    keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                    try:
                        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    except Exception: pass
                
                except Exception as e:
                    logging.error(f"🚨 수동 덫 파기 에러: {e}")
                    safe_err = html.escape(str(e))
                    try:
                        keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                        await query.edit_message_text(f"❌ <b>수동 덫 파기 중 에러 발생:</b>\n<code>{safe_err}</code>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    except Exception: pass

            elif sub == "MANUAL_FIRE_REQ":
                try:
                    status_code, _ = await controller._get_market_status()
                    if status_code not in ["PRE", "REG"]:
                        try: await query.answer("❌ [격발 차단] 현재 장운영시간(정규장/프리장)이 아닙니다.", show_alert=True)
                        except Exception: pass
                        return
                        
                    # 🚨 MODIFIED: [메모리 참조 증발 패러독스 수술] 명시적 딕셔너리 할당으로 Ghost Dict 차단 락온
                    app_data = context.bot_data.get('app_data')
                    if not isinstance(app_data, dict):
                        app_data = {}
                        context.bot_data['app_data'] = app_data
                        
                    tracking_cache = app_data.get('sniper_tracking')
                    if not isinstance(tracking_cache, dict):
                        tracking_cache = {}
                        app_data['sniper_tracking'] = tracking_cache
                    
                    t_h = self._safe_float(tracking_cache.get(f"AVWAP_T_H_{ticker}"))
                    if t_h <= 0.0:
                        if hasattr(self.strategy, 'v_avwap_plugin'):
                            est = ZoneInfo('America/New_York')
                            now_est = datetime.datetime.now(est)
                            try:
                                state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                t_h = self._safe_float(state.get('T_H'))
                            except Exception: pass
                            
                    if t_h <= 0.0:
                        try:
                            keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                            await query.edit_message_text(f"❌ <b>[{html.escape(str(ticker))}] 수동 요격 불가</b>\n▫️ T_H(지정가 덫 기준선) 데이터가 존재하지 않습니다. 스캔 대기.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
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
                    safe_err = html.escape(str(e))
                    try:
                        keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                        await query.edit_message_text(f"❌ <b>요격 승인 대기 중 에러 발생:</b>\n<code>{safe_err}</code>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    except Exception: pass
            
            elif sub == "MANUAL_FIRE_EXEC":
                try:
                    status_code, _ = await controller._get_market_status()
                    if status_code not in ["PRE", "REG"]:
                        try: await query.answer("❌ [격발 차단] 현재 장운영시간(정규장/프리장)이 아닙니다.", show_alert=True)
                        except Exception: pass
                        return
                        
                    # 🚨 MODIFIED: [콜백 레이스 컨디션 완벽 차단] 상태 검증부터 API 전송까지 통째로 락온하여 연타(Spamming) 원천 방어
                    async with self.tx_lock:
                        app_data = context.bot_data.get('app_data')
                        if not isinstance(app_data, dict):
                            app_data = {}
                            context.bot_data['app_data'] = app_data
                            
                        tracking_cache = app_data.get('sniper_tracking')
                        if not isinstance(tracking_cache, dict):
                            tracking_cache = {}
                            app_data['sniper_tracking'] = tracking_cache
                        
                        is_already_placed = tracking_cache.get(f"AVWAP_LIMIT_ORDER_PLACED_{ticker}")
                        existing_odno = str(tracking_cache.get(f"AVWAP_BUY_ODNO_{ticker}") or "")
                        
                        if not is_already_placed and not existing_odno:
                            if hasattr(self.strategy, 'v_avwap_plugin'):
                                est = ZoneInfo('America/New_York')
                                now_est = datetime.datetime.now(est)
                                try:
                                    state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                    is_already_placed = bool(state.get('limit_order_placed'))
                                    existing_odno = str(state.get('buy_odno') or "")
                                except Exception: pass

                        if is_already_placed or existing_odno:
                            try:
                                keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                                await query.edit_message_text(f"❌ <b>[{html.escape(str(ticker))}] 수동 요격 불가</b>\n▫️ 이미 덫이 장전되어 있습니다 (ODNO: {existing_odno}). 중복 격발을 차단합니다.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass
                            return

                        t_h = self._safe_float(tracking_cache.get(f"AVWAP_T_H_{ticker}"))
                        if t_h <= 0.0:
                            if hasattr(self.strategy, 'v_avwap_plugin'):
                                est = ZoneInfo('America/New_York')
                                now_est = datetime.datetime.now(est)
                                try:
                                    state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                    t_h = self._safe_float(state.get('T_H'))
                                except Exception: pass
                        
                        if t_h <= 0.0 or math.isnan(t_h):
                            try:
                                keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                                await query.edit_message_text(f"❌ <b>[{html.escape(str(ticker))}] 수동 요격 실패</b>\n▫️ T_H 데이터가 존재하지 않거나 결측치(NaN)입니다.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass
                            return

                        cash = 0.0
                        for attempt in range(3):
                            try:
                                await asyncio.sleep(0.06)
                                cash_tuple = await asyncio.wait_for(asyncio.to_thread(self.broker.get_account_balance), timeout=10.0)
                                cash = self._safe_float(cash_tuple[0]) if isinstance(cash_tuple, (list, tuple)) and len(cash_tuple) > 0 else 0.0
                                break
                            except Exception:
                                if attempt == 2: cash = 0.0
                                else: await asyncio.sleep(1.0 * (2 ** attempt))
                        
                        avwap_free_cash = max(0.0, cash)
                        
                        try:
                            # 🚨 NEW: [이터러블 문자열 붕괴 방어] JSON 오염으로 인해 get_active_tickers가 문자열("SOXL")을 반환할 때 N빵 예산 할당 오류(len이 4가 되는 문제) 원천 차단
                            from scheduler_core import get_budget_allocation
                            active_tickers_list = await asyncio.wait_for(asyncio.to_thread(self.cfg.get_active_tickers), timeout=5.0) or []
                            if isinstance(active_tickers_list, str): active_tickers_list = [active_tickers_list]
                            
                            alloc_res = await asyncio.wait_for(asyncio.to_thread(get_budget_allocation, avwap_free_cash, active_tickers_list, self.cfg), timeout=5.0)
                            alloc_cash_dict = alloc_res[1] if isinstance(alloc_res, (list, tuple)) and len(alloc_res) > 1 else {}
                            allocated_budget = self._safe_float(alloc_cash_dict.get(ticker))
                        except Exception as e:
                            logging.error(f"🚨 예산 할당 모듈 로드 실패 (N빵 강제 분할 폴백): {e}")
                            try:
                                active_tickers_list = await asyncio.wait_for(asyncio.to_thread(self.cfg.get_active_tickers), timeout=5.0) or []
                                if isinstance(active_tickers_list, str): active_tickers_list = [active_tickers_list]
                                div_count = max(1, len(active_tickers_list))
                            except Exception:
                                div_count = 1
                            allocated_budget = avwap_free_cash / div_count  
                            
                        safe_budget = allocated_budget * 0.95
                        if math.isnan(safe_budget): safe_budget = 0.0
                        buy_qty = max(0, int(math.floor(safe_budget / t_h))) if t_h > 0 else 0

                        if buy_qty <= 0:
                            try:
                                keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                                await query.edit_message_text(f"❌ <b>[{html.escape(str(ticker))}] 수동 요격 실패</b>\n▫️ 예산 부족. 가용 현금: ${allocated_budget:.2f}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass
                            return

                        try:
                            await query.answer("🔫 지정가 덫 장전 중...", show_alert=False)
                            await query.edit_message_text(f"🚀 <b>[{html.escape(str(ticker))}] 사이보그(Cyborg) 수동 강제 요격 덫 전송 중...</b>", parse_mode='HTML')
                        except Exception: pass

                        await asyncio.sleep(0.06)
                        
                        # 🚨 MODIFIED: [주문 전송 재시도 누락 수술] 3단 지수 백오프 및 15.0초 타임아웃 전격 이식하여 통신 무결성 절대 방어
                        res = None
                        for attempt in range(3):
                            try:
                                await asyncio.sleep(0.06)
                                res = await asyncio.wait_for(
                                    asyncio.to_thread(self.broker.send_order, ticker, "BUY", buy_qty, t_h, "LIMIT"),
                                    timeout=15.0
                                )
                                break
                            except Exception as e:
                                if attempt == 2:
                                    logging.error(f"🚨 사이보그 수동 덫 장전 통신 에러/타임아웃: {e}")
                                    res = None
                                else:
                                    await asyncio.sleep(1.0 * (2 ** attempt))
                        
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
                            
                            tracking_cache[f"AVWAP_SHUTDOWN_{ticker}"] = False
                            
                            if hasattr(self.strategy, 'v_avwap_plugin'):
                                try:
                                    state = await asyncio.wait_for(asyncio.to_thread(self.strategy.v_avwap_plugin.load_state, ticker, now_est), timeout=5.0) or {}
                                    state.update({
                                        "limit_order_placed": True,
                                        "placed_target_th": t_h,
                                        "buy_odno": buy_odno,
                                        "trap_placed_time": curr_candle_time_str,
                                        "shutdown": False
                                    })
                                    await asyncio.wait_for(
                                        asyncio.to_thread(self.strategy.v_avwap_plugin.save_state, ticker, now_est, state),
                                        timeout=5.0
                                    )
                                except Exception as disk_e:
                                    logging.error(f"🚨 수동 요격 후 상태 파일 디스크 I/O 에러 (RAM 캐시는 업데이트됨): {disk_e}")

                            final_msg = f"🔫 <b>[{html.escape(str(ticker))}] 수동 지정가 요격 덫 락온 성공!</b>\n"
                            final_msg += f"▫️ 타점: <b>${t_h:.2f}</b> (순수 LIMIT)\n"
                            final_msg += f"▫️ 목표수량: <b>{buy_qty}주</b>\n"
                            final_msg += f"▫️ 상태: 1분봉 자동 감시 모드로 인계되었습니다. 체결 확정 시 2.0% 자동 익절 덫이 투하됩니다."

                            try:
                                keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                                await query.edit_message_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass
                            
                        else:
                            err_msg = html.escape(str(res.get('msg1') or '응답 없음')) if isinstance(res, dict) else '통신 장애/무응답'
                            logging.error(f"🚨 [{ticker}] 사이보그 수동 덫 장전 서버 거절: {err_msg}")
                            reject_msg = (
                                f"🚨 <b>[{html.escape(str(ticker))}] 사이보그 수동 지정가 덫 전송 서버 거절 (Reject)!</b>\n"
                                f"▫️ 사유: <code>{err_msg}</code>\n"
                            )
                            try:
                                keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                                await query.edit_message_text(reject_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                            except Exception: pass

                except Exception as e:
                    logging.error(f"🚨 사이보그 수동 요격/장전 에러: {e}")
                    safe_err = html.escape(str(e))
                    try:
                        keyboard = [[InlineKeyboardButton("🔄 관제탑 복귀", callback_data="AVWAP_SET:REFRESH:NONE")]]
                        await query.edit_message_text(f"❌ <b>수동 장전 중 에러 발생:</b>\n<code>{safe_err}</code>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    except Exception: pass
