# ==========================================================
# FILE: queue_ledger.py
# ==========================================================
# 🚨 MODIFIED: [수수료 트랩 원천 차단] 1층 매도 총액(Gross)에서 왕복 수수료 및 슬리피지 버퍼(0.6%)를 선차감한 '순수 회수금(Net Cash)'만을 원가 차감에 반영하여 전체 사이클 마진 붕괴 패러독스 방어.
# 🚨 MODIFIED: [하위 지층 단가 상승 패러독스 원천 차단] 잔여 지층이 2개 이상일 때는 개별 평단가를 100% 보존하며, 오직 잔여 지층이 단 1개(len(q)==1) 남았을 때만 전체 투자금 기반 원가 차감(리앵커링)이 격발되도록 팩트 교정 완료.
# 🚨 MODIFIED: [평단가 리앵커링] AVWAP KIS 원장 100% 디커플링 및 순수 로컬 기반 잔여 지층 원가 차감(Cost Basis Reduction) 로직 전면 결속 완료.
# 🚨 MODIFIED: [Insight 14] 콤마(,) 및 NaN/Inf 맹독성 유입 시 ValueError 즉사 방어를 위한 `_safe_float` 쉴드 전면 내재화
# 🚨 MODIFIED: [Case 33] 파일 I/O 에러 재시도 시 하드코딩된 대기(0.1s)를 3단 지수 백오프(Exponential Backoff)로 규격 통일
# 🚨 MODIFIED: [Case 08] 백업 파일 복원 및 디렉토리 검증 시 레이스 컨디션을 유발하는 os.path.exists를 100% 소각하고 EAFP 패턴 락온
# 🚨 VERIFIED: [Case 16] 원자적 쓰기(Atomic Write) 실패 시 임시 파일 스코프 고아화 방어 100% 사수 완료
# 🚨 VERIFIED: [디렉토리 파싱 붕괴 방어] _ensure_file 내 os.path.dirname 반환값이 빈 문자열일 때 발생하는 os.makedirs 에러를 `or '.'` 단락 평가로 원천 차단
# 🚨 VERIFIED: [제4헌법 절대 사수] 메인 장부뿐만 아니라 백업 파일(.bak) 생성 시에도 임시 파일(.bak.tmp)을 거치는 원자적 복사(Atomic Copy)를 강제하여 OS 커널 패닉 시 백업본 오염 원천 차단
# 🚨 VERIFIED: [무한 디스크 I/O 패러독스 방어] 메인 파일 손상 후 백업에서 복원 시, 손상된 메인 장부를 즉각 덮어쓰는 자가 치유(Self-Healing) 로직 결속 완료
# 🚨 MODIFIED: [Indentation 붕괴 수술] apply_stock_split 내부 if changed: 하위 블록의 비표준 들여쓰기(17칸)를 16칸으로 100% 정밀 교정하여 컴파일 즉사 에러 소각
# ==========================================================
import os
import json
import time
import math
import threading
import shutil
import tempfile
from zoneinfo import ZoneInfo
from datetime import datetime
import logging

class QueueLedger:
    def __init__(self, file_path="data/queue_ledger.json"):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._ensure_file()

    def _safe_float(self, value):
        try:
            val = float(str(value or 0.0).replace(',', ''))
            if math.isnan(val) or math.isinf(val):
                return 0.0
            return val
        except Exception:
            return 0.0

    def _ensure_file(self):
        try:
            dir_name = os.path.dirname(self.file_path) or '.'
            os.makedirs(dir_name, exist_ok=True)
        except OSError:
            pass

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                pass
        except FileNotFoundError:
            with self._lock:
                try:
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        pass
                except FileNotFoundError:
                    self._save_unsafe({})
        except Exception:
            pass

    def _get_trading_date_str(self):
        est = ZoneInfo('America/New_York')
        return datetime.now(est).strftime("%Y-%m-%d")

    def _load_unsafe(self):
        last_exc = None
        for attempt in range(3):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content.strip():
                        return {} 
                    return json.loads(content)
            except json.JSONDecodeError as e:
                last_exc = e
                # JSON 디코딩 실패 시 메인 파일이 완전히 손상된 것이므로 재시도를 멈추고 즉시 백업 복원망으로 폴백
                break
            except FileNotFoundError:
                return {}
            except Exception as e:
                last_exc = e
                time.sleep(1.0 * (2 ** attempt))
        
        backup_path = self.file_path + ".bak"
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logging.warning(f"🚨 [QueueLedger] JSON 손상 감지. 백업 파일({backup_path}) 복원 완료. 손상된 메인 장부를 즉시 자가 치유합니다.")
                try:
                    self._save_unsafe(data)
                except Exception as heal_e:
                    logging.error(f"🚨 [QueueLedger] 자가 치유 I/O 통신 에러: {heal_e}")
                return data
        except FileNotFoundError:
            pass
        except Exception as be:
            logging.error(f"🚨 [QueueLedger] 백업 복원도 실패: {be}")
        
        raise RuntimeError(f"🚨 [FATAL ERROR] {self.file_path} 장부 파일 읽기 실패. 데이터 유실 방지를 위해 시스템을 중단합니다. 원인: {last_exc}")

    def _save_unsafe(self, data):
        dir_name = os.path.dirname(self.file_path) or '.'
        try:
            os.makedirs(dir_name, exist_ok=True)
        except OSError:
            pass

        for attempt in range(3):
            fd = None
            tmp_path = None
            try:
                fd, tmp_path = tempfile.mkstemp(dir=dir_name, text=True)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    fd = None
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.file_path)
                tmp_path = None
                
                # 🚨 MODIFIED: [제4헌법 결속] 백업본(.bak) 생성 시에도 임시 파일을 통한 원자적 교체(Atomic Copy)를 강제하여 파일 손상 원천 봉쇄
                bak_path = self.file_path + ".bak"
                bak_tmp_path = bak_path + ".tmp"
                try: 
                    shutil.copy2(self.file_path, bak_tmp_path)
                    os.replace(bak_tmp_path, bak_path)
                except Exception:
                    try: os.remove(bak_tmp_path)
                    except OSError: pass
                
                return
            except Exception as e:
                logging.warning(f"⚠️ [QueueLedger] 장부 저장 재시도 ({attempt+1}/3): {e}")
                if fd is not None:
                    try: os.close(fd)
                    except OSError: pass
                if tmp_path:
                    try: os.remove(tmp_path)
                    except OSError: pass
                time.sleep(1.0 * (2 ** attempt))
                  
        logging.error(f"🚨 [QueueLedger] 장부 저장 최종 실패: {self.file_path} — 데이터 유실 위험!")

    def apply_stock_split(self, ticker, ratio):
        if ratio <= 0: return
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            changed = False
            for lot in q:
                raw_new_qty = self._safe_float(lot.get("qty", 0)) * ratio
                new_qty = math.floor(raw_new_qty + 0.5)
                if new_qty > 0:
                    lot["qty"] = new_qty
                    old_price = self._safe_float(lot.get("price", 0.0))
                    lot["price"] = round(old_price / ratio, 4)
                    changed = True
            if changed:
                data[ticker] = q
                self._save_unsafe(data)

    def get_queue(self, ticker):
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            return [lot for lot in q if int(self._safe_float(lot.get("qty"))) > 0]

    def add_lot(self, ticker, qty, price, lot_type="NORMAL"):
        qty = int(self._safe_float(qty))
        if qty <= 0: return
        
        price_f = self._safe_float(price)
        if price_f <= 0.0:
            logging.error(f"🚨 [QueueLedger] add_lot 중단: {ticker} — 유효하지 않은 매수 가격 (price={price}). 로트 추가 취소.")
            return
            
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            q = [lot for lot in q if int(self._safe_float(lot.get("qty"))) > 0] 
            
            today_str = self._get_trading_date_str()
            
            if q and str(q[-1].get("date", "")).startswith(today_str):
                old_qty = int(self._safe_float(q[-1].get("qty")))
                old_price = self._safe_float(q[-1].get("price"))
                
                new_qty = old_qty + qty
                new_price = ((old_qty * old_price) + (qty * price_f)) / new_qty if new_qty > 0 else 0.0
                
                q[-1]["qty"] = new_qty
                q[-1]["price"] = round(new_price, 4)
                q[-1]["date"] = datetime.now(ZoneInfo('America/New_York')).strftime("%Y-%m-%d %H:%M:%S")
            else:
                q.append({
                    "qty": qty,
                    "price": price_f, 
                    "date": datetime.now(ZoneInfo('America/New_York')).strftime("%Y-%m-%d %H:%M:%S"),
                    "type": lot_type
                })
                
            data[ticker] = q
            self._save_unsafe(data)

    def pop_lots(self, ticker, target_qty, sold_price=0.0):
        original_target = int(self._safe_float(target_qty))
        target_qty = original_target
        if target_qty <= 0: return 0
        
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            q = [lot for lot in q if int(self._safe_float(lot.get("qty"))) > 0] 
            
            if not q: return 0
            
            vrev_total_invested = sum(int(self._safe_float(item.get('qty'))) * self._safe_float(item.get('price')) for item in q)
            
            popped_total = 0
            realized_cash = 0.0

            while q and target_qty > 0:
                last_lot = q[-1]
                lot_qty = int(self._safe_float(last_lot.get("qty")))
                lot_price = self._safe_float(last_lot.get("price"))
                cp = sold_price if sold_price > 0 else lot_price
                
                if lot_qty == 0:
                    q.pop()
                    continue
                    
                if lot_qty <= target_qty:
                    popped = q.pop()
                    popped_qty = int(self._safe_float(popped.get("qty")))
                    popped_total += popped_qty
                    realized_cash += popped_qty * cp
                    target_qty -= popped_qty
                else:
                    last_lot["qty"] = lot_qty - target_qty
                    popped_total += target_qty
                    realized_cash += target_qty * cp
                    target_qty = 0
                    
            remaining_qty = sum(int(self._safe_float(item.get('qty'))) for item in q)
            if remaining_qty > 0 and popped_total > 0:
                # 🚨 MODIFIED: [단일 지층 Net Cash 차감] 0.6% 수수료/슬리피지 버퍼를 선차감하여 잔여 자본금(Capital Base) 과소 계상 차단
                if len(q) == 1:
                    net_realized_cash = realized_cash * 0.994  # 0.6% 차감
                    remaining_invested = vrev_total_invested - net_realized_cash
                    new_pure_price = round(max(0.01, remaining_invested / remaining_qty), 4)
                    q[0]["price"] = new_pure_price

            if popped_total < original_target:
                logging.error(f"🚨 [QueueLedger] pop_lots 미달: {ticker} — 요청 {original_target}주 중 {popped_total}주만 차감. 즉시 sync_with_broker 실행 권고.")

            data[ticker] = q
            self._save_unsafe(data)
            return popped_total

    def sync_with_broker(self, ticker, actual_qty, actual_avg=0.0, clear_price=0.0):
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            q = [lot for lot in q if int(self._safe_float(lot.get("qty"))) > 0] 
            
            current_q_qty = sum(int(self._safe_float(item.get("qty"))) for item in q)
            actual_qty = int(self._safe_float(actual_qty))

            if current_q_qty == actual_qty:
                return False 

            today_str = self._get_trading_date_str()

            if current_q_qty < actual_qty:
                diff = actual_qty - current_q_qty
                calib_price = self._safe_float(actual_avg)
                
                if calib_price <= 0.0:
                    calib_price = self._safe_float(q[-1].get("price")) if q else 0.0
                
                if calib_price <= 0.0:
                    logging.error(f"🚨 [QueueLedger] sync_with_broker CALIB_ADD 중단: {ticker} — 실제 평단가 불명 (actual_avg={actual_avg}). $0 로트 주입 방지.")
                    data[ticker] = q
                    self._save_unsafe(data)
                    return True
                
                if q and str(q[-1].get("date", "")).startswith(today_str):
                    old_qty = int(self._safe_float(q[-1].get("qty")))
                    old_price = self._safe_float(q[-1].get("price"))
                    
                    new_qty = old_qty + diff
                    new_price = ((old_qty * old_price) + (diff * calib_price)) / new_qty if new_qty > 0 else 0.0

                    q[-1]["qty"] = new_qty
                    q[-1]["price"] = round(new_price, 4)
                    q[-1]["date"] = datetime.now(ZoneInfo('America/New_York')).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    q.append({
                        "qty": diff,
                        "price": round(calib_price, 4), 
                        "date": datetime.now(ZoneInfo('America/New_York')).strftime("%Y-%m-%d %H:%M:%S"),
                        "type": "CALIB_ADD"
                    })
            else:
                diff = current_q_qty - actual_qty
                popped_total = 0
                realized_cash = 0.0
                
                vrev_total_invested = sum(int(self._safe_float(item.get('qty'))) * self._safe_float(item.get('price')) for item in q)
                
                while q and diff > 0:
                    last_lot = q[-1]
                    lot_qty = int(self._safe_float(last_lot.get("qty")))
                    lot_price = self._safe_float(last_lot.get("price"))
                    cp = clear_price if clear_price > 0 else lot_price
                    
                    if lot_qty == 0:
                        q.pop()
                        continue
                        
                    if lot_qty <= diff:
                        q.pop()
                        diff -= lot_qty 
                        popped_total += lot_qty
                        realized_cash += lot_qty * cp
                    else:
                        last_lot["qty"] = lot_qty - diff
                        popped_total += diff
                        realized_cash += diff * cp
                        diff = 0
                        
                remaining_qty = actual_qty
                if remaining_qty > 0 and popped_total > 0:
                    # 🚨 MODIFIED: [단일 지층 Net Cash 차감] 0.6% 수수료/슬리피지 버퍼를 선차감하여 잔여 자본금(Capital Base) 과소 계상 차단
                    if len(q) == 1:
                        net_realized_cash = realized_cash * 0.994  # 0.6% 차감
                        remaining_invested = vrev_total_invested - net_realized_cash
                        new_pure_price = round(max(0.01, remaining_invested / remaining_qty), 4)
                        q[0]["price"] = new_pure_price
                        
                if diff > 0:
                    logging.warning(f"⚠️ [QueueLedger] sync_with_broker CALIB_SUB 미달: {ticker} 큐 물량이 브로커보다 {diff}주 부족합니다. 큐가 초기화되었습니다.")

            data[ticker] = q
            self._save_unsafe(data)
            return True

    def delete_lot(self, ticker, target_date):
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            new_q = [lot for lot in q if str(lot.get('date', '')) != str(target_date)]
            data[ticker] = new_q
            self._save_unsafe(data)

    def edit_lot(self, ticker, target_date, qty, price):
        qty_int = int(self._safe_float(qty))
        price_f = self._safe_float(price)
        with self._lock:
            data = self._load_unsafe()
            q = data.get(ticker, [])
            for lot in q:
                if str(lot.get('date', '')) == str(target_date):
                    lot['qty'] = qty_int
                    lot['price'] = round(price_f, 4)
                    break
            data[ticker] = q
            self._save_unsafe(data)

    def clear_queue(self, ticker):
        with self._lock:
            data = self._load_unsafe()
            data[ticker] = []
            self._save_unsafe(data)

    def overwrite_queue(self, ticker, q_data):
        with self._lock:
            data = self._load_unsafe()
            sorted_q = sorted(q_data, key=lambda x: str(x.get('date', '0000-00-00')))
            data[ticker] = sorted_q
            self._save_unsafe(data)
