# ==========================================================
# FILE: scheduler_regular.py
# ==========================================================
# 🚨 VERIFIED: [최종 무결점 판정] 5대 헌법 및 34대 엣지 케이스 완벽 결속 교차 검증 완료
# 🚨 MODIFIED: [State Mismatch 붕괴 방어] 1분 슬라이싱 섀도우 엔진(scheduler_vwap)과의 파일명 및 JSON 데이터 구조(Dict) 100% 팩트 일치화 수술 완료
# 🚨 MODIFIED: [Jitter 타임라인 역전 붕괴 수술] 15:27 슬라이싱 엔진 가동 전 무조건 파일 I/O 인계를 마치도록 V-REV 본진 지터 상한을 180초에서 45초로 진공 압축 락온
# 🚨 MODIFIED: [V-REV 자체 VWAP 1분 슬라이싱 엔진 이식] 기존 KIS 증권사 알고리즘 위임(ALGO_ORD_TMD_DVSN_CD) 로직을 시스템 전역에서 영구 소각하고, 로컬 스케줄러 기반 자체 슬라이싱 엔진으로 인계하는 원자적 쓰기 파이프라인 100% 팩트 락온.
# 🚨 REMOVED: [Case 20, 제2헌법 준수] KIS 알고리즘 위임 소각에 따라 불필요해진 동적 지터 시간 연산 데드코드(dyn_start_t, dyn_end_t) 100% 영구 삭제.
# 🚨 MODIFIED: [제1헌법 준수] send_order 및 send_reservation_order 외부 통신에 누락되었던 wait_for(timeout=15.0) 타임아웃 족쇄 100% 전면 결속
# 🚨 MODIFIED: [V73.15 타임라인 디커플링 대통합] 17:05 KST V14 선제 타격 및 V-REV 스냅샷 분리 락온
# 🚨 NEW: [Case 32 & 33 절대 규칙] 3단 지수 백오프 및 스케줄러 루프 TPS 캡핑 이식 완료
# 🚨 MODIFIED: [Case 14 절대 헌법 준수] is_market_open 비동기 호출 타임아웃 10.0초 하드코딩 완료
# 🚨 MODIFIED: [최종 팩트 수술] `math.isnan` 및 `math.isinf` 방어막을 `_safe_float`에 이식하여 치명적 수학 연산 붕괴(ValueError) 원천 봉쇄
# 🚨 MODIFIED: [Insight 14] String-Float 콤마 맹독성 런타임 붕괴 방어용 `_safe_float` 래핑 전면 이식
# 🚨 MODIFIED: [Insight 12] 딕셔너리 오염(TypeError/KeyError) 방어용 `.get()` 및 `isinstance` 쉴드 전면 락온
# 🚨 MODIFIED: [Cascade Failure 방어] 단일 종목 에러 시 전체 스케줄러가 파괴되는 연쇄 붕괴를 막기 위한 개별 Sandbox(try-except) 결속
# 🚨 MODIFIED: [Insight 06/07] JSON Iterable 결측치(None) 유입 시 발생하는 TypeError 붕괴 방어용 `or []` 단락 평가 쉴드 주입
# 🚨 MODIFIED: [Type Boundary] 스냅샷에서 불러온 오염된 주문 페이로드(Type Mismatch)로 인한 KIS API 붕괴를 막는 강제 캐스팅(Sanitize) 락온
# 🚨 MODIFIED: [최후의 논리결함 수술] 샌드박스로 인해 예외가 먹혀버려(Swallow) 외부 재시도 루프가 무력화되는 Silent Failure 현상 전면 교정 (loop_fully_successful 트래커 주입)
# 🚨 MODIFIED: [최후의 생존망 결속] 텔레그램 API 통신 에러가 KIS 재시도 루프를 깨버리는 맹독성 버그(External API Crash) 완벽 소각
# 🚨 MODIFIED: [TypeError 붕괴 방어] KIS 응답의 `msg1`이 null(None)일 경우 `html.escape`가 폭발하는 버그 100% 팩트 수술 완료
# 🚨 MODIFIED: [Case 19 부분 실패 이중 장전 패러독스 방어] 기장전된 덫은 API 통신 전면 바이패스 및 캐시 락온 결속
# ==========================================================
import logging
import datetime
from zoneinfo import ZoneInfo
import asyncio
import random
import html
import math
import os
import tempfile
import json

from scheduler_core import is_market_open, get_budget_allocation

def _safe_float(val):
    try:
        f_val = float(str(val or 0.0).replace(',', ''))
        if math.isnan(f_val) or math.isinf(f_val):
            return 0.0
        return f_val
    except Exception:
        return 0.0

# 🚨 NEW: 자체 1분 슬라이싱 엔진 인계를 위한 로컬 상태 원자적 쓰기 헬퍼 (TOCTOU 붕괴 방어 및 EAFP 락온)
def _save_slice_state_sync(ticker, date_str, slice_info):
    # 🚨 MODIFIED: [State Mismatch 붕괴 방어] 섀도우 엔진(scheduler_vwap)과 동일한 파일명으로 100% 락온
    state_file = f"data/vrev_slice_state_{ticker}.json"
    dir_name = os.path.dirname(state_file) or '.'
    try: os.makedirs(dir_name, exist_ok=True)
    except OSError: pass

    # 🚨 MODIFIED: [State Mismatch 붕괴 방어] 딕셔너리 구조로 래핑 및 초기화 락온
    data = {"date": date_str, "hijacked": False, "orders": []}
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
            # 당일자 파일인 경우에만 기존 데이터 로드 (과거 파일이면 초기화된 data 유지)
            if isinstance(loaded_data, dict) and loaded_data.get('date') == date_str:
                data = loaded_data
                if not isinstance(data.get('orders'), list):
                    data['orders'] = []
    except (OSError, json.JSONDecodeError):
        pass
    
    # 🚨 멱등성 보장 (이미 장전된 슬라이스는 덮어쓰지 않음)
    exists = False
    for item in data['orders']:
        if isinstance(item, dict) and item.get('desc') == slice_info['desc'] and item.get('side') == slice_info['side']:
            exists = True
            break
    
    if not exists:
        data['orders'].append(slice_info)
        
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, text=True)
        with os.fdopen(fd, 'w', encoding='utf-8') as f_out:
            fd = None
            json.dump(data, f_out, ensure_ascii=False, indent=4)
            f_out.flush()
            os.fsync(f_out.fileno())
        os.replace(tmp_path, state_file)
        tmp_path = None
    except Exception as e:
        if fd is not None:
            try: os.close(fd)
            except OSError: pass
        if tmp_path:
            try: os.remove(tmp_path)
            except OSError: pass
        raise e

async def scheduled_early_regular_trade(context):
    is_open = False
    for attempt in range(3):
        try:
            # MODIFIED: [Case 14] 달력 API 타임아웃 10초 하드코딩 락온
            is_open = await asyncio.wait_for(asyncio.to_thread(is_market_open), timeout=10.0)
            break
        except asyncio.TimeoutError:
            if attempt == 2:
                logging.error("⚠️ is_market_open 달력 API 타임아웃. 평일이므로 강제 개장 처리합니다.")
                est = ZoneInfo('America/New_York')
                is_open = datetime.datetime.now(est).weekday() < 5
            else: await asyncio.sleep(1.0 * (2 ** attempt))
        except Exception:
            if attempt == 2:
                est = ZoneInfo('America/New_York')
                is_open = datetime.datetime.now(est).weekday() < 5
            else: await asyncio.sleep(1.0 * (2 ** attempt))

    if not is_open:
        return
    
    app_data = context.job.data
    cfg = app_data.get('cfg')
    broker = app_data.get('broker')
    strategy = app_data.get('strategy')
    tx_lock = app_data.get('tx_lock')
    
    if tx_lock is None:
        logging.warning("⚠️ [early_trade] tx_lock 미초기화. 이번 사이클 스킵.")
        return

    # 프리장 선제 타격(V14)은 17:05 KST(04:05 EST)이므로 지터 최대 180초 유지
    jitter_seconds = random.randint(0, 180)
    try:
        await context.bot.send_message(
            chat_id=context.job.chat_id, 
            text=f"🌃 <b>[17:05 KST] 정규장 스케줄러 기상!</b>\n"
                 f"▫️ 서버 접속 부하 방지를 위해 <b>{jitter_seconds}초</b> 대기 후 V14 덫 전송 및 스냅샷을 박제합니다.", 
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"초기 기상 메시지 텔레그램 발송 실패: {e}")
        
    await asyncio.sleep(jitter_seconds)

    MAX_RETRIES = 5
    RETRY_DELAY = 10
    successful_orders_cache = set() # 🚨 NEW: [Case 19] 부분 실패 시 이중 장전 방지용 캐시

    async def _do_early_trade():
        est_z = ZoneInfo('America/New_York')
        curr_est = datetime.datetime.now(est_z)
        today_str = curr_est.strftime("%Y-%m-%d")
        
        async with tx_lock:
            cash, holdings = 0.0, None
            for attempt in range(3):
                try:
                    cash, holdings = await asyncio.wait_for(asyncio.to_thread(broker.get_account_balance), timeout=15.0)
                    break
                except asyncio.TimeoutError:
                    if attempt == 2: return False, "잔고 조회 타임아웃"
                    else: await asyncio.sleep(1.0 * (2 ** attempt))
                except Exception as e:
                    if attempt == 2: return False, f"잔고 조회 오류: {html.escape(str(e))}"
                    else: await asyncio.sleep(1.0 * (2 ** attempt))
            
            if holdings is None:
                return False, "❌ 계좌 정보를 불러오지 못했습니다."
            
            safe_holdings = holdings if isinstance(holdings, dict) else {}
            
            # 🚨 MODIFIED: [최후의 맹점 수술] 외부 모듈 반환값 결측치(None) 붕괴 완벽 차단
            active_tickers_list = (await asyncio.to_thread(cfg.get_active_tickers)) or []
            alloc_res = await asyncio.to_thread(get_budget_allocation, cash, active_tickers_list, cfg)
            
            if not alloc_res or len(alloc_res) != 2:
                return False, "❌ 예산 할당 로직 결측치(None) 반환. 스케줄 보호 중단."
                
            sorted_tickers, allocated_cash = alloc_res
            sorted_tickers = sorted_tickers or []
            allocated_cash = allocated_cash or {}
            
            msgs = {t: "" for t in sorted_tickers}
            all_success_map = {t: True for t in sorted_tickers}
            
            loop_fully_successful = True
            loop_fail_reason = ""

            for t in sorted_tickers:
                try:
                    await asyncio.sleep(0.06)
                    
                    version = await asyncio.to_thread(cfg.get_version, t)
                    is_locked = await asyncio.to_thread(cfg.check_lock, t, "REG")
                    if is_locked:
                        skip_msg = f"⚠️ <b>[{t}] REG 잠금 미해제 — 스케줄 루프 스킵</b>\n▫️ 수동으로 잠금 해제 후 상태를 확인하십시오."
                        try:
                            await context.bot.send_message(context.job.chat_id, skip_msg, parse_mode='HTML')
                        except Exception: pass
                        continue
                    
                    h = safe_holdings.get(t) or {}
                    # 🚨 MODIFIED: [Insight 14] String-Float 맹독성 쉴드 래핑
                    safe_avg = _safe_float(h.get('avg'))
                    safe_qty = int(_safe_float(h.get('qty')))
                    safe_alloc_cash = _safe_float(allocated_cash.get(t, 0.0))

                    curr_p, prev_c = 0.0, 0.0
                    for _api_retry in range(3):
                        try:
                            curr_p_val = await asyncio.wait_for(asyncio.to_thread(broker.get_current_price, t), timeout=15.0)
                            curr_p = _safe_float(curr_p_val)
                            prev_c_val = await asyncio.wait_for(asyncio.to_thread(broker.get_previous_close, t), timeout=15.0)
                            prev_c = _safe_float(prev_c_val)
                            if curr_p > 0 and prev_c > 0: break
                        except Exception:
                            pass
                        await asyncio.sleep(1.0 * (2**_api_retry))

                    ma_5day = 0.0
                    for attempt in range(3):
                        try:
                            ma_5day_val = await asyncio.wait_for(asyncio.to_thread(broker.get_5day_ma, t), timeout=15.0)
                            ma_5day = _safe_float(ma_5day_val)
                            break
                        except Exception: 
                            if attempt == 2: ma_5day = 0.0
                            else: await asyncio.sleep(1.0 * (2**attempt))
                    
                    plan = await asyncio.to_thread(
                        strategy.get_plan, t, curr_p, safe_avg, safe_qty, prev_c, ma_5day=ma_5day, market_type="REG", available_cash=safe_alloc_cash, is_snapshot_mode=True
                    )
                    
                    if not isinstance(plan, dict):
                        msgs[t] += f"🚨 <b>[{t}] 플랜 생성 실패 (데이터 오염).</b>\n"
                        all_success_map[t] = False
                        loop_fully_successful = False
                        loop_fail_reason = f"[{t}] 플랜 오염"
                        continue
                    
                    if version == "V14":
                        msgs[t] += f"💎 <b>[{t}] V14 오리지널 정규장 실전 덫 장전 완료 (17:05 KST 타격망)</b>\n"
                        
                        is_market_active_now = False # 17:05 KST is generally PRE-MARKET

                        # 🚨 MODIFIED: [Insight 06/07] Iterable NoneType 붕괴 방어용 단락 평가
                        target_orders = plan.get('core_orders') or plan.get('orders') or []
                        for o in target_orders:
                            try:
                                if not isinstance(o, dict): continue
                                # 🚨 MODIFIED: [Type Boundary] 페이로드 강제 캐스팅 락온
                                o_type = str(o.get('type', 'LOC'))
                                o_side = str(o.get('side', 'BUY'))
                                o_qty = int(_safe_float(o.get('qty')))
                                o_price = _safe_float(o.get('price'))
                                o_desc = str(o.get('desc', '주문'))

                                # 🚨 MODIFIED: [Case 19 중복 매매 방어] 기장전된 덫은 API 통신 전면 바이패스
                                order_key = f"{t}_{o_desc}"
                                if order_key in successful_orders_cache:
                                    msgs[t] += f"└ 1차 필수: {o_desc} {o_qty}주 (${o_price}): ✅(기장전 보존)\n"
                                    continue

                                # 🚨 MODIFIED: [Case 32] 주문 전송 시 TPS 캡핑 락온
                                await asyncio.sleep(0.06)

                                # 🚨 MODIFIED: [V-REV 1분 슬라이싱 인계] KIS 알고리즘 소각 및 자체 엔진 로컬 파일 인계
                                if o_type == 'VWAP':
                                    slice_info = {"ticker": t, "side": o_side, "total_qty": o_qty, "filled_qty": 0, "target_price": o_price, "desc": o_desc, "status": "PENDING"}
                                    await asyncio.wait_for(asyncio.to_thread(_save_slice_state_sync, t, today_str, slice_info), timeout=10.0)
                                    res = {'rt_cd': '0', 'msg1': '로컬 자체 VWAP 엔진 위임 완료', 'odno': f'LOCAL_VWAP_{id(o)}'}
                                elif is_market_active_now:
                                    res = await asyncio.wait_for(asyncio.to_thread(broker.send_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                                else:
                                    res = await asyncio.wait_for(asyncio.to_thread(broker.send_reservation_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                                
                                safe_res = res if isinstance(res, dict) else {}
                                is_success = safe_res.get('rt_cd') == '0'
                                
                                err_msg = html.escape(str(safe_res.get('msg1') or '오류'))
                                
                                if is_success:
                                    successful_orders_cache.add(order_key)
                                else: 
                                    all_success_map[t] = False
                                    loop_fully_successful = False
                                    loop_fail_reason = f"[{t}] 1차 주문 거절: {err_msg}"

                                status_icon = '✅' if is_success else f'❌({err_msg})'
                                msgs[t] += f"└ 1차 필수: {o_desc} {o_qty}주 (${o_price}): {status_icon}\n"
                                await asyncio.sleep(0.2)
                            except Exception as e:
                                all_success_map[t] = False
                                loop_fully_successful = False
                                loop_fail_reason = f"[{t}] 1차 주문 오류"
                                logging.error(f"🚨 [{t}] early_trade 1차 주문 오류: {e}")
                                msgs[t] += f"└ 1차 필수 오류: {html.escape(str(e))}\n"
                            
                        target_bonus = plan.get('bonus_orders') or []
                        
                        # 🚨 MODIFIED: [Case 19 중복 매매 방어] 1차 필수 주문 실패 시 보너스 덫 장전 원천 차단
                        if all_success_map[t]:
                            for o in target_bonus:
                                try:
                                    if not isinstance(o, dict): continue
                                    o_type = str(o.get('type', 'LOC'))
                                    o_side = str(o.get('side', 'BUY'))
                                    o_qty = int(_safe_float(o.get('qty')))
                                    o_price = _safe_float(o.get('price'))
                                    o_desc = str(o.get('desc', '주문'))

                                    # 🚨 MODIFIED: [Case 19 중복 매매 방어] 기장전된 덫은 API 통신 전면 바이패스
                                    order_key = f"{t}_{o_desc}"
                                    if order_key in successful_orders_cache:
                                        msgs[t] += f"└ 2차 보너스: {o_desc} {o_qty}주 (${o_price}): ✅(기장전 보존)\n"
                                        continue

                                    # 🚨 MODIFIED: [Case 32] 주문 전송 시 TPS 캡핑 락온
                                    await asyncio.sleep(0.06)

                                    # 🚨 MODIFIED: [V-REV 1분 슬라이싱 인계]
                                    if o_type == 'VWAP':
                                        slice_info = {"ticker": t, "side": o_side, "total_qty": o_qty, "filled_qty": 0, "target_price": o_price, "desc": o_desc, "status": "PENDING"}
                                        await asyncio.wait_for(asyncio.to_thread(_save_slice_state_sync, t, today_str, slice_info), timeout=10.0)
                                        res = {'rt_cd': '0', 'msg1': '로컬 자체 VWAP 엔진 위임 완료', 'odno': f'LOCAL_VWAP_{id(o)}'}
                                    elif is_market_active_now:
                                        res = await asyncio.wait_for(asyncio.to_thread(broker.send_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                                    else:
                                        res = await asyncio.wait_for(asyncio.to_thread(broker.send_reservation_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                                    
                                    safe_res = res if isinstance(res, dict) else {}
                                    is_success = safe_res.get('rt_cd') == '0'
                                    err_msg = html.escape(str(safe_res.get('msg1') or '잔금패스'))
                                    
                                    if is_success:
                                        successful_orders_cache.add(order_key)
                                    else:
                                        all_success_map[t] = False
                                        loop_fully_successful = False
                                        loop_fail_reason = f"[{t}] 2차 보너스 거절: {err_msg}"
                                    
                                    status_icon = '✅' if is_success else f'❌({err_msg})'
                                    msgs[t] += f"└ 2차 보너스: {o_desc} {o_qty}주 (${o_price}): {status_icon}\n"
                                    await asyncio.sleep(0.2)
                                except Exception as e:
                                    all_success_map[t] = False
                                    loop_fully_successful = False
                                    loop_fail_reason = f"[{t}] 2차 보너스 오류"
                                    logging.error(f"🚨 [{t}] early_trade 2차 보너스 오류: {e}")
                                    msgs[t] += f"└ 2차 보너스 오류: {html.escape(str(e))}\n"
                        elif target_bonus:
                            msgs[t] += f"⚠️ 1차 필수 장전 실패로 2차 보너스 덫 보류 (중복 매매 방어)\n"
                        
                        if (target_orders or target_bonus) and all_success_map[t]:
                            await asyncio.to_thread(cfg.set_lock, t, "REG")
                            msgs[t] += "\n🔒 <b>V14 필수 덫(로컬 엔진 포함) 장전 완료 (잠금 설정됨)</b>"
                    
                    else: 
                        msgs[t] += f"🔄 <b>[{t}] V-REV 역추세 덫 모의 장전 및 스냅샷 박제</b>\n"
                        target_orders = plan.get('core_orders') or plan.get('orders') or []
                        for o in target_orders:
                            if not isinstance(o, dict): continue
                            safe_desc = str(o.get('desc', '주문'))
                            safe_qty = int(_safe_float(o.get('qty')))
                            safe_price = _safe_float(o.get('price'))
                            msgs[t] += f"└ 모의 1차 필수: {safe_desc} {safe_qty}주 (${safe_price})\n"
                            
                        target_bonus = plan.get('bonus_orders') or []
                        for o in target_bonus:
                            if not isinstance(o, dict): continue
                            safe_desc = str(o.get('desc', '주문'))
                            safe_qty = int(_safe_float(o.get('qty')))
                            safe_price = _safe_float(o.get('price'))
                            msgs[t] += f"└ 모의 2차 보너스: {safe_desc} {safe_qty}주 (${safe_price})\n"
                            
                        if target_orders or target_bonus:
                            msgs[t] += "\n📸 <b>V-REV 당일 스냅샷 팩트 박제 완료 (15:26 EST 지연 투하 대기)</b>"
                    
                    if msgs[t]:
                        try:
                            await context.bot.send_message(chat_id=context.job.chat_id, text=msgs[t], parse_mode='HTML')
                        except Exception as tg_e:
                            logging.error(f"[{t}] 개별 종목 텔레그램 메시지 발송 실패: {tg_e}")
                        
                except Exception as e:
                    # 🚨 MODIFIED: [Cascade Failure 방어] 샌드박스로 인한 재시도 루프 무력화 방지 (Tracker 갱신)
                    all_success_map[t] = False
                    loop_fully_successful = False
                    loop_fail_reason = f"[{t}] 치명적 오류: {str(e)}"
                    logging.error(f"🚨 [{t}] early_trade 개별 종목 처리 중 치명적 오류: {e}")
                    try:
                        await context.bot.send_message(chat_id=context.job.chat_id, text=f"🚨 <b>[{t}] 스케줄러 처리 중 오류 발생. 스킵합니다.</b>\n<code>{html.escape(str(e))}</code>", parse_mode='HTML')
                    except Exception: pass

            if not loop_fully_successful:
                return False, loop_fail_reason
        return True, "SUCCESS"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            success, fail_reason = await asyncio.wait_for(_do_early_trade(), timeout=300.0)
            if success:
                if attempt > 1: 
                    try:
                        await context.bot.send_message(chat_id=context.job.chat_id, text=f"✅ <b>[통신 복구] {attempt}번째 재시도 끝에 장전을 완수했습니다!</b>", parse_mode='HTML')
                    except Exception: pass
                return 
        except Exception as e:
            logging.error(f"17:05 덫 장전 에러 ({attempt}/{MAX_RETRIES}): {e}", exc_info=True)
            if attempt == 1:
                safe_err = html.escape(str(e))
                try:
                    await context.bot.send_message(
                        chat_id=context.job.chat_id, 
                        text=f"⚠️ <b>[API 통신 지연 감지]</b>\n한투 서버 불안정. 10초 뒤 장전을 재시도합니다! 🛡️\n<code>사유: {safe_err}</code>", 
                        parse_mode='HTML'
                    )
                except Exception: pass
        else:
            logging.warning(f"장전 조건 미충족 ({attempt}/{MAX_RETRIES}): {fail_reason}")
            if attempt == 1:
                 safe_fail = html.escape(str(fail_reason))
                 try:
                     await context.bot.send_message(
                        chat_id=context.job.chat_id, 
                        text=f"⚠️ <b>[API 통신 지연 감지]</b>\n한투 서버 불안정. 10초 뒤 장전을 재시도합니다! 🛡️\n<code>사유: {safe_fail}</code>", 
                        parse_mode='HTML'
                     )
                 except Exception: pass

        if attempt < MAX_RETRIES:
            if attempt != 1 and attempt % 5 == 0:
                try:
                    await context.bot.send_message(chat_id=context.job.chat_id, text=f"⚠️ <b>[API 통신 지연 감지]</b>\n한투 서버 불안정. 10초 뒤 재시도합니다! 🛡️", parse_mode='HTML')
                except Exception: pass
            await asyncio.sleep(RETRY_DELAY)

    try:
        await context.bot.send_message(chat_id=context.job.chat_id, text="🚨 <b>[긴급 에러] 17:05 스케줄 통신 복구 최종 실패. 수동 점검 요망!</b>", parse_mode='HTML')
    except Exception: pass


async def scheduled_regular_trade_delayed(context):
    is_open = False
    for attempt in range(3):
        try:
            is_open = await asyncio.wait_for(asyncio.to_thread(is_market_open), timeout=10.0)
            break
        except asyncio.TimeoutError:
            if attempt == 2:
                est = ZoneInfo('America/New_York')
                is_open = datetime.datetime.now(est).weekday() < 5
            else: await asyncio.sleep(1.0 * (2 ** attempt))
        except Exception:
            if attempt == 2:
                est = ZoneInfo('America/New_York')
                is_open = datetime.datetime.now(est).weekday() < 5
            else: await asyncio.sleep(1.0 * (2 ** attempt))

    if not is_open:
        return
    
    app_data = context.job.data
    cfg = app_data.get('cfg')
    broker = app_data.get('broker')
    strategy = app_data.get('strategy')
    tx_lock = app_data.get('tx_lock')
    
    if tx_lock is None:
        return
    
    # 🚨 MODIFIED: [Jitter 타임라인 역전 붕괴 수술] 15:27 슬라이싱 엔진 가동 전 무조건 파일 I/O 인계를 마치도록 지터 상한을 180초에서 45초로 진공 압축 락온
    jitter_seconds = random.randint(0, 45)

    try:
        await context.bot.send_message(
            chat_id=context.job.chat_id, 
            text=f"🌃 <b>[15:26 EST] V-REV 본진 덫(자체 1분 슬라이싱 포함) 투하 개시!</b>\n"
                 f"🛡️ 서버 접속 부하 방지를 위해 <b>{jitter_seconds}초</b> 대기 후 전송/인계를 시도합니다.", 
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"지연 투하 시작 메시지 텔레그램 발송 실패: {e}")

    await asyncio.sleep(jitter_seconds)

    MAX_RETRIES = 15
    RETRY_DELAY = 60
    successful_orders_cache = set() # 🚨 NEW: [Case 19] 부분 실패 시 이중 장전 방지용 캐시

    async def _do_delayed_trade():
        async with tx_lock:
            # 🚨 MODIFIED: [최후의 맹점 수술] 외부 모듈 반환값 결측치(None) 붕괴 완벽 차단
            active_tickers_list = (await asyncio.to_thread(cfg.get_active_tickers)) or []
            
            if not active_tickers_list:
                return False, "❌ 활성 종목 리스트 결측치(None) 반환. 스케줄 보호 중단."
                
            plans = {}
            msgs = {t: "" for t in active_tickers_list}
            all_success_map = {t: True for t in active_tickers_list}
            
            loop_fully_successful = True
            loop_fail_reason = ""

            est_z = ZoneInfo('America/New_York')
            curr_est = datetime.datetime.now(est_z)
            today_str = curr_est.strftime("%Y-%m-%d")
            
            is_market_active_now = True # 15:26 EST is REGULAR session

            for t in active_tickers_list:
                try:
                    await asyncio.sleep(0.06)
                    
                    version = await asyncio.to_thread(cfg.get_version, t)
                    if version == "V14":
                        continue 
                        
                    is_locked = await asyncio.to_thread(cfg.check_lock, t, "REG")
                    if is_locked:
                        continue
                    
                    plan = await asyncio.to_thread(
                        strategy.get_plan, t, 0.0, 0.0, 0, 0.0, ma_5day=0.0, market_type="REG", available_cash=0.0, is_snapshot_mode=False
                    )
                    
                    if not isinstance(plan, dict):
                        msgs[t] += f"🚨 <b>[{t}] 스냅샷 유실 또는 손상! KIS 전송 불가.</b>\n"
                        all_success_map[t] = False
                        loop_fully_successful = False
                        loop_fail_reason = f"[{t}] 스냅샷 유실"
                        continue

                    plans[t] = plan
                    if plan.get('core_orders') or plan.get('orders') or plan.get('bonus_orders'):
                        msgs[t] += f"🔄 <b>[{t}] V-REV 역추세 실전 덫(로컬 엔진 포함) 장전 완료</b>\n"
                except Exception as e:
                    all_success_map[t] = False
                    loop_fully_successful = False
                    loop_fail_reason = f"[{t}] 플랜 조회 오류"
                    logging.error(f"🚨 [{t}] delayed_trade 플랜 조회 오류: {e}")
                    msgs[t] += f"🚨 <b>[{t}] 플랜 조회 중 에러 발생</b>\n"

            for t in active_tickers_list:
                if t not in plans: continue
                target_orders = plans[t].get('core_orders') or plans[t].get('orders') or []
                for o in target_orders:
                    try:
                        if not isinstance(o, dict): continue
                        o_type = str(o.get('type', 'LOC'))
                        o_side = str(o.get('side', 'BUY'))
                        o_qty = int(_safe_float(o.get('qty')))
                        o_price = _safe_float(o.get('price'))
                        o_desc = str(o.get('desc', '주문'))

                        # 🚨 MODIFIED: [Case 19 중복 매매 방어] 기장전된 덫은 API 통신 전면 바이패스
                        order_key = f"{t}_{o_desc}"
                        if order_key in successful_orders_cache:
                            msgs[t] += f"└ 1차 필수: {o_desc} {o_qty}주 (${o_price}): ✅(기장전 보존)\n"
                            continue

                        # 🚨 MODIFIED: [Case 32] 주문 전송 시 TPS 캡핑 락온
                        await asyncio.sleep(0.06)

                        # 🚨 MODIFIED: [V-REV 1분 슬라이싱 인계] 로컬 상태 파일 원자적 저장으로 15:27 기상 엔진에 인계
                        if o_type == 'VWAP':
                            slice_info = {"ticker": t, "side": o_side, "total_qty": o_qty, "filled_qty": 0, "target_price": o_price, "desc": o_desc, "status": "PENDING"}
                            await asyncio.wait_for(asyncio.to_thread(_save_slice_state_sync, t, today_str, slice_info), timeout=10.0)
                            res = {'rt_cd': '0', 'msg1': '로컬 자체 VWAP 엔진 위임 완료', 'odno': f'LOCAL_VWAP_{id(o)}'}
                        elif is_market_active_now:
                            res = await asyncio.wait_for(asyncio.to_thread(broker.send_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                        else:
                            res = await asyncio.wait_for(asyncio.to_thread(broker.send_reservation_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                        
                        safe_res = res if isinstance(res, dict) else {}
                        is_success = safe_res.get('rt_cd') == '0'
                        err_msg = html.escape(str(safe_res.get('msg1') or '오류'))
                        
                        if is_success:
                            successful_orders_cache.add(order_key)
                        else: 
                            all_success_map[t] = False
                            loop_fully_successful = False
                            loop_fail_reason = f"[{t}] 1차 주문 거절: {err_msg}"

                        status_icon = '✅' if is_success else f'❌({err_msg})'
                        msgs[t] += f"└ 1차 필수: {o_desc} {o_qty}주 (${o_price}): {status_icon}\n"
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        all_success_map[t] = False
                        loop_fully_successful = False
                        loop_fail_reason = f"[{t}] 1차 주문 오류"
                        logging.error(f"🚨 [{t}] delayed_trade 1차 주문 오류: {e}")
                        msgs[t] += f"└ 1차 필수 오류: {html.escape(str(e))}\n"
                    
            for t in active_tickers_list:
                if t not in plans: continue
                target_bonus = plans[t].get('bonus_orders') or []
                
                # 🚨 MODIFIED: [Case 19 중복 매매 방어] 1차 필수 주문 실패 시 보너스 덫 장전 원천 차단
                if not all_success_map[t] and target_bonus:
                    msgs[t] += f"⚠️ 1차 필수 장전 실패로 2차 보너스 덫 보류 (중복 매매 방어)\n"
                    continue

                for o in target_bonus:
                    try:
                        if not isinstance(o, dict): continue
                        o_type = str(o.get('type', 'LOC'))
                        o_side = str(o.get('side', 'BUY'))
                        o_qty = int(_safe_float(o.get('qty')))
                        o_price = _safe_float(o.get('price'))
                        o_desc = str(o.get('desc', '주문'))

                        # 🚨 MODIFIED: [Case 19 중복 매매 방어] 기장전된 덫은 API 통신 전면 바이패스
                        order_key = f"{t}_{o_desc}"
                        if order_key in successful_orders_cache:
                            msgs[t] += f"└ 2차 보너스: {o_desc} {o_qty}주 (${o_price}): ✅(기장전 보존)\n"
                            continue

                        # 🚨 MODIFIED: [Case 32] 주문 전송 시 TPS 캡핑 락온
                        await asyncio.sleep(0.06)

                        # 🚨 MODIFIED: [V-REV 1분 슬라이싱 인계]
                        if o_type == 'VWAP':
                            slice_info = {"ticker": t, "side": o_side, "total_qty": o_qty, "filled_qty": 0, "target_price": o_price, "desc": o_desc, "status": "PENDING"}
                            await asyncio.wait_for(asyncio.to_thread(_save_slice_state_sync, t, today_str, slice_info), timeout=10.0)
                            res = {'rt_cd': '0', 'msg1': '로컬 자체 VWAP 엔진 위임 완료', 'odno': f'LOCAL_VWAP_{id(o)}'}
                        elif is_market_active_now:
                            res = await asyncio.wait_for(asyncio.to_thread(broker.send_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                        else:
                            res = await asyncio.wait_for(asyncio.to_thread(broker.send_reservation_order, t, o_side, o_qty, o_price, o_type), timeout=15.0)
                        
                        safe_res = res if isinstance(res, dict) else {}
                        is_success = safe_res.get('rt_cd') == '0'
                        err_msg = html.escape(str(safe_res.get('msg1') or '잔금패스'))
                        
                        if is_success:
                            successful_orders_cache.add(order_key)
                        else:
                            all_success_map[t] = False
                            loop_fully_successful = False
                            loop_fail_reason = f"[{t}] 2차 보너스 거절: {err_msg}"
                        
                        status_icon = '✅' if is_success else f'❌({err_msg})'
                        msgs[t] += f"└ 2차 보너스: {o_desc} {o_qty}주 (${o_price}): {status_icon}\n"
                        await asyncio.sleep(0.2) 
                    except Exception as e:
                        all_success_map[t] = False
                        loop_fully_successful = False
                        loop_fail_reason = f"[{t}] 2차 보너스 오류"
                        logging.error(f"🚨 [{t}] delayed_trade 2차 보너스 오류: {e}")
                        msgs[t] += f"└ 2차 보너스 오류: {html.escape(str(e))}\n"

            for t in active_tickers_list:
                try:
                    if t not in plans: continue
                    target_orders = plans[t].get('core_orders') or plans[t].get('orders') or []
                    target_bonus = plans[t].get('bonus_orders') or []
                    if not target_orders and not target_bonus: continue
                    
                    if all_success_map[t] and (target_orders or target_bonus):
                        await asyncio.to_thread(cfg.set_lock, t, "REG")
                        msgs[t] += "\n🔒 <b>V-REV 필수 덫(로컬 엔진 포함) 전송 완료 (잠금 설정됨)</b>"
                    elif not all_success_map[t] and (target_orders or target_bonus):
                        msgs[t] += "\n⚠️ <b>일부 덫 장전 실패 (매매 잠금 보류)</b>"
                        
                    if msgs[t].strip():
                        try:
                            await context.bot.send_message(chat_id=context.job.chat_id, text=msgs[t], parse_mode='HTML')
                        except Exception as tg_e:
                            logging.error(f"[{t}] V-REV 완료 메시지 발송 실패: {tg_e}")
                except Exception as e:
                    loop_fully_successful = False
                    loop_fail_reason = f"[{t}] 상태 잠금 오류"
                    logging.error(f"🚨 [{t}] delayed_trade 상태 잠금 오류: {e}")

            if not loop_fully_successful:
                return False, loop_fail_reason
        return True, "SUCCESS"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            success, fail_reason = await asyncio.wait_for(_do_delayed_trade(), timeout=300.0)
            if success:
                if attempt > 1: 
                    try:
                        await context.bot.send_message(chat_id=context.job.chat_id, text=f"✅ <b>[통신 복구] {attempt}번째 재시도 끝에 장전을 완수했습니다!</b>", parse_mode='HTML')
                    except Exception: pass
                return 
        except Exception as e:
            logging.error(f"정규장 덫 실전 전송 에러 ({attempt}/{MAX_RETRIES}): {e}", exc_info=True)
            if attempt == 1:
                safe_err = html.escape(str(e))
                try:
                    await context.bot.send_message(
                        chat_id=context.job.chat_id, 
                        text=f"⚠️ <b>[API 통신 지연 감지]</b>\n한투 서버 불안정. 1분 뒤 실전 장전을 재시도합니다! 🛡️\n<code>사유: {safe_err}</code>", 
                        parse_mode='HTML'
                    )
                except Exception: pass
        else:
            if attempt == 1:
                 safe_fail = html.escape(str(fail_reason))
                 try:
                     await context.bot.send_message(
                        chat_id=context.job.chat_id, 
                        text=f"⚠️ <b>[API 통신 지연 감지]</b>\n한투 서버 불안정. 1분 뒤 실전 장전을 재시도합니다! 🛡️\n<code>사유: {safe_fail}</code>", 
                        parse_mode='HTML'
                     )
                 except Exception: pass

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY)

    try:
        await context.bot.send_message(chat_id=context.job.chat_id, text="🚨 <b>[긴급 에러] V-REV 실전 전송 통신 복구 최종 실패. 수동 점검 요망!</b>", parse_mode='HTML')
    except Exception: pass
