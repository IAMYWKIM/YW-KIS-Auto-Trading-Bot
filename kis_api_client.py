# ==========================================================
# FILE: kis_api_client.py
# ==========================================================
# 🚨 MODIFIED: [파사드 패턴 1단계] KIS API 순수 통신 및 토큰 제어 도메인 분리
# 🚨 MODIFIED: [Case 08] TOCTOU 레이스 컨디션을 유발하는 os.path.exists 영구 소각 및 EAFP 패턴 락온
# 🚨 MODIFIED: [Case 16] 원자적 쓰기(Atomic Write) 강제 및 tempfile 스코프 전진 배치
# 🚨 MODIFIED: [Case 32 & 33] KIS API 초당 20건 통신 제한(TPS) 방어용 0.06초 캡핑 및 3단 지수 백오프 락온
# 🚨 MODIFIED: [Insight 14 & 25] NaN, Infinity 및 String-Comma 맹독성 데이터 정밀 필터링 절대 쉴드 내재화
# 🚨 MODIFIED: [제3헌법 준수] 토큰 만료 연산 시 잔존하던 KST 혼용 뇌관 전면 소각 및 EST 타임라인 100% 통합
# 🚨 MODIFIED: [AttributeError 궁극 수술] 서버 응답(msg1, msg_cd) NoneType 유입 시 .lower() 붕괴 원천 차단
# 🚨 MODIFIED: [로깅 증발 방어] 헤드리스(Headless) 환경에서 증발하는 print() 데드코드 전면 소각 및 logging 체계 100% 락온
# ==========================================================

import requests
import json
import time
import datetime
import os
import math
import tempfile
import logging
from zoneinfo import ZoneInfo

class KisApiClient:
    def __init__(self, app_key, app_secret, cano, acnt_prdt_cd="01"):
        self.app_key = app_key
        self.app_secret = app_secret
        self.cano = cano
        self.acnt_prdt_cd = acnt_prdt_cd
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.token_file = f"data/token_{cano}.dat" 
        self.token = None
        self._excg_cd_cache = {} 
        self._get_access_token()

    def _get_access_token(self, force=False):
        # 🚨 MODIFIED: [제3헌법 절대 락온] KST 혼용 파이프라인 전면 소각 및 EST 100% 매핑
        est = ZoneInfo('America/New_York')
        
        # 🚨 MODIFIED: [Case 08] os.path.exists 소각 및 EAFP 패턴으로 TOCTOU 레이스 컨디션 차단
        if not force:
            try:
                with open(self.token_file, 'r') as f:
                    saved = json.load(f)
               
                expire_time = datetime.datetime.strptime(saved['expire'], '%Y-%m-%d %H:%M:%S')
                now_est_naive = datetime.datetime.now(est).replace(tzinfo=None)
        
                if expire_time > now_est_naive + datetime.timedelta(hours=1):
                    self.token = saved['token']
                    return
            except OSError: pass
            except json.JSONDecodeError: pass
            except Exception: pass

        if force:
            try: os.remove(self.token_file)
            except OSError: pass

        url = f"{self.base_url}/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        
        # 🚨 MODIFIED: [Case 33] 3단 지수 백오프 토큰 발급 이식
        for attempt in range(3):
            try:
                # 🚨 NEW: [Case 32] KIS TPS 캡핑
                time.sleep(0.06)
                res = requests.post(url, headers={"content-type": "application/json"}, data=json.dumps(body), timeout=10)
                data = res.json()
                
                # 🚨 MODIFIED: [AttributeError 붕괴 방어] JSON 응답이 딕셔너리가 아닐 경우 빈 딕셔너리로 폴백
                if not isinstance(data, dict):
                    data = {}
     
                if 'access_token' in data:
                    self.token = data['access_token']
                    # 🚨 MODIFIED: [Float 붕괴 방어] expires_in 데이터 오염 시 ValueError 차단을 위한 _safe_float 래핑
                    safe_expires_in = int(self._safe_float(data.get('expires_in', 86400)))
                    expire_str = (datetime.datetime.now(est).replace(tzinfo=None) + datetime.timedelta(seconds=safe_expires_in)).strftime('%Y-%m-%d %H:%M:%S')
                
                    dir_name = os.path.dirname(self.token_file)
                    if dir_name:
                        try: os.makedirs(dir_name, exist_ok=True)
                        except OSError: pass
       
                    # 🚨 MODIFIED: [Case 16 & 제4헌법 준수] 원자적 쓰기(Atomic Write) 강제 및 POSIX 표준 os.replace 주입
                    fd = None
                    temp_path = None
                    try:
                        fd, temp_path = tempfile.mkstemp(dir=dir_name or '.', text=True)
                        with os.fdopen(fd, 'w', encoding='utf-8') as f:
                            fd = None
                            json.dump({'token': self.token, 'expire': expire_str}, f)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(temp_path, self.token_file)
                        temp_path = None
                    except Exception as inner_e:
                        if fd is not None:
                            try: os.close(fd)
                            except OSError: pass
                        if temp_path:
                            try: os.remove(temp_path)
                            except OSError: pass
                        raise inner_e
                    break # 성공 시 루프 탈출
                else:
                    if attempt == 2:
                        # 🚨 MODIFIED: [로깅 증발 방어] print() 소각 및 logging.error 락온
                        logging.error(f"❌ [Broker] 토큰 발급 실패: {data.get('error_description') or '알 수 없는 오류'}")
                    time.sleep(1.0 * (2 ** attempt))
            except Exception as e:
                if attempt == 2:
                    # 🚨 MODIFIED: [로깅 증발 방어] print() 소각 및 logging.error 락온
                    logging.error(f"❌ [Broker] 토큰 통신 에러: {e}")
                time.sleep(1.0 * (2 ** attempt))

    def _get_header(self, tr_id):
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }

    # 🚨 MODIFIED: [Case 32 & 33] 3단 지수 백오프 및 TPS 초과 방어 로직 주입
    def _api_request(self, method, url, headers, params=None, data=None):
        TOKEN_EXPIRY_KEYWORDS = frozenset([
            'expired', '인증', 'authorization', 'egt0001', 'egt0002', 'oauth', 
            '접근토큰이 만료', '토큰이 유효하지'
        ])
    
        for attempt in range(3): 
            try:
                # 🚨 NEW: [Case 32] 고성능 인스턴스 TPS 초과 방어 (KIS 서버 거절 차단)
                time.sleep(0.06)
                
                if method.upper() == "GET":
                    res = requests.get(url, headers=headers, params=params, timeout=10)
                else:
                    res = requests.post(url, headers=headers, data=json.dumps(data) if data else None, timeout=10)
                 
                if res.status_code == 429 or res.status_code >= 500:
                    raise Exception(f"HTTP Error {res.status_code}")
   
                resp_json = res.json()
                # 🚨 MODIFIED: [AttributeError 붕괴 방어] JSON 응답이 딕셔너리가 아닐 경우 빈 딕셔너리로 폴백
                if not isinstance(resp_json, dict):
                    resp_json = {}
         
                if resp_json.get('rt_cd') != '0':
                    # 🚨 MODIFIED: [AttributeError 궁극 수술] msg1, msg_cd가 None일 경우 발생하는 .lower() 즉사 버그 방어 쉴드
                    msg1_lower = str(resp_json.get('msg1') or '').lower()
                    msg_cd = str(resp_json.get('msg_cd') or '').lower()
       
                    if any(x in msg1_lower or x in msg_cd for x in TOKEN_EXPIRY_KEYWORDS):
                        if attempt == 0: 
                            old_token = self.token 
                            # 🚨 MODIFIED: [로깅 증발 방어] print() 소각 및 logging.warning 락온
                            logging.warning(f"🚨 [안전장치 가동] API 토큰 만료 감지! : {msg1_lower}")
                            self._get_access_token(force=True)
                            
                            if self.token == old_token or self.token is None:
                                logging.error("🚨 [Broker] 토큰 갱신 실패. 재시도 중단.")
                                return res, resp_json
                            
                            headers["authorization"] = f"Bearer {self.token}"
                            time.sleep(1.0)
                            continue
 
                return res, resp_json
            except Exception as e:
                logging.debug(f"⚠️ [Broker] API 통신 중 예외 발생 (시도 {attempt+1}/3): {e}")
                if attempt == 2: return None, {}
                # 🚨 NEW: [Case 33] 3단 지수 백오프 적용
                time.sleep(1.0 * (2 ** attempt))
        return None, {}

    def _call_api(self, tr_id, url_path, method="GET", params=None, body=None):
        headers = self._get_header(tr_id)
        url = f"{self.base_url}{url_path}"
        res, resp_json = self._api_request(method, url, headers, params=params, data=body)
        if not resp_json: return {'rt_cd': '999', 'msg1': '통신 오류 또는 최대 재시도 횟수 초과'}
        return resp_json

    def _ceil_2(self, value):
        if value is None: return 0.0
        return max(0.01, math.ceil(round(self._safe_float(value) * 100, 4)) / 100.0)

    # 🚨 MODIFIED: [Insight 14 & 25] NaN, Infinity 및 String-Comma 맹독성 데이터 정밀 필터링 절대 쉴드
    def _safe_float(self, value):
        try:
            f_val = float(str(value or 0.0).replace(',', ''))
            if math.isnan(f_val) or math.isinf(f_val):
                return 0.0
            return f_val
        except Exception:
            return 0.0

    def _get_exchange_code(self, ticker, target_api="PRICE"):
        if ticker in self._excg_cd_cache:
            codes = self._excg_cd_cache[ticker]
            return codes['PRICE'] if target_api == "PRICE" else codes['ORDER']

        price_cd = "NAS"
        order_cd = "NASD"
        dynamic_success = False

        for attempt in range(3):
            try:
                for prdt_type in ["512", "513", "529"]:
                    # 🚨 NEW: [Case 32] 동적 스캔 시에도 TPS 캡핑 강제
                    time.sleep(0.06)
                    params = {"PRDT_TYPE_CD": prdt_type, "PDNO": ticker}
                    res = self._call_api("CTPF1702R", "/uapi/overseas-price/v1/quotations/search-info", "GET", params=params)
                    
                    # 🚨 MODIFIED: [AttributeError 붕괴 방어] output 결측 또는 타입 오염 시 안전 우회
                    if res.get('rt_cd') == '0':
                        out = res.get('output')
                        if isinstance(out, dict):
                            excg_name = str(out.get('ovrs_excg_cd', '')).upper()
                    
                            if "NASD" in excg_name or "NASDAQ" in excg_name:
                                price_cd, order_cd = "NAS", "NASD"
                                dynamic_success = True
                                break
                            elif "NYSE" in excg_name or "NEW YORK" in excg_name:
                                price_cd, order_cd = "NYS", "NYSE"
                                dynamic_success = True
                                break
                            elif "AMEX" in excg_name:
                                price_cd, order_cd = "AMS", "AMEX"
                                dynamic_success = True
                                break
                if dynamic_success: break
            except Exception as e:
                if attempt == 2:
                    # 🚨 MODIFIED: [로깅 증발 방어] print() 소각 및 logging.warning 락온
                    logging.warning(f"⚠️ [Broker] 거래소 동적 획득 실패: {ticker} - {e}")
                time.sleep(1.0 * (2 ** attempt))

        if not dynamic_success:
            if ticker == "SOXL": price_cd, order_cd = "AMS", "AMEX"
            elif ticker == "TQQQ": price_cd, order_cd = "NAS", "NASD"

        self._excg_cd_cache[ticker] = {'PRICE': price_cd, 'ORDER': order_cd}
        return price_cd if target_api == "PRICE" else order_cd
