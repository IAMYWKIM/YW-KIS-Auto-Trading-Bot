"""
strategy.py v1.3 — 종가베팅 전략 스캔 및 매매 신호 생성

[v1.3 핵심 변경]
  문제: ka10023(당일 급증) API로는 "1~5일 전 급등, 오늘 눌림" 종목을 못 찾음
  해결: 후보 소스를 3가지로 다양화

  [소스 1] ka10016 — 52주 신고가 종목 (최근 강세 종목 직접 포착)
  [소스 2] ka10023 — 당일 거래량 급증 (조건 대폭 완화)
  [소스 3] ka10024 — 거래량 갱신 상위 (최근 거래 활발 종목)

  → 3소스 합산 후 일봉 데이터로 "최근 5일 내 5% 이상 급등" 확인
  → 오늘 -0.5% ~ -10% 눌림 중인 종목 선별

[조건 완화]
  거래대금: 500억 → 100억 (다날·보원케미칼·한패스 포함)
  눌림 범위: -5% → -10% (시장 급락일 대응)
  RSI 상한: 70 → 80
  신고가 범위: -10% → -20%
  수급 조건: OFF (눌림 구간엔 기관도 매도)
  정배열: MA5>MA20 (MA60 제외)
"""

import logging
from datetime import datetime
from typing import Optional

from broker import KiwoomBroker
from strategy_config import StrategyConfig

logger = logging.getLogger(__name__)


class Strategy:

    def __init__(self, broker: KiwoomBroker, strategy_cfg: StrategyConfig):
        self.broker = broker
        self.scfg   = strategy_cfg

    # ──────────────────────────────────────────────────────────
    # 1. 일봉 데이터 (MA + 거래량 + 거래대금 + 고가)
    # ──────────────────────────────────────────────────────────

    def get_daily_data(self, code: str) -> dict:
        """ka10081 — 주식일봉차트 (문서 p.201)"""
        try:
            data = self.broker._post(
                "ka10081",
                "/api/dostk/chart",
                {
                    "stk_cd":       code,
                    "base_dt":      datetime.now().strftime("%Y%m%d"),
                    "upd_stkpc_tp": "1",
                }
            )
            candles = data.get("stk_dt_pole_chart_qry", [])
            if not candles:
                return {}

            closes, volumes, trading_values, highs, lows = [], [], [], [], []
            for c in candles:
                try:
                    closes.append(abs(float(c.get("cur_prc",   "0").lstrip("+-") or "0")))
                    volumes.append(abs(int(  c.get("trde_qty", "0").lstrip("+-") or "0")))
                    # trde_prica: 백만원 단위 → 원 단위 변환
                    tv = abs(int(c.get("trde_prica", "0").lstrip("+-") or "0")) * 1_000_000
                    trading_values.append(tv)
                    highs.append(abs(float(c.get("high_pric", "0").lstrip("+-") or "0")))
                    lows.append( abs(float(c.get("low_pric",  "0").lstrip("+-") or "0")))
                except ValueError:
                    continue

            if len(closes) < 20:
                return {}

            cfg = self.scfg.get_scan()
            s, m, l = cfg["ma_short"], cfg["ma_mid"], cfg["ma_long"]
            ma5  = sum(closes[:s]) / s
            ma20 = sum(closes[:m]) / m
            ma60 = sum(closes[:min(l, len(closes))]) / min(l, len(closes))

            return {
                "ma5":            round(ma5, 2),
                "ma20":           round(ma20, 2),
                "ma60":           round(ma60, 2),
                "closes":         closes,
                "volumes":        volumes,
                "trading_values": trading_values,
                "highs":          highs,
                "lows":           lows,
            }
        except Exception as e:
            logger.error(f"[Strategy] {code} 일봉 조회 실패: {e}")
            return {}

    # 하위 호환
    def get_moving_averages(self, code: str) -> dict:
        return self.get_daily_data(code)

    # ──────────────────────────────────────────────────────────
    # 2. 최근 N일 내 급등 여부 확인 (핵심 필터)
    # ──────────────────────────────────────────────────────────

    def check_recent_surge(self, daily: dict) -> dict:
        """
        최근 N거래일 내에 하루 M% 이상 급등한 날이 있었는지 확인
        반환: {"has_surge": bool, "max_gain": float, "surge_days_ago": int}
        """
        cfg    = self.scfg.get_scan()
        days   = cfg.get("recent_surge_days", 5)
        min_pct = cfg.get("recent_surge_min_pct", 5.0)
        closes = daily.get("closes", [])

        if len(closes) < days + 2:
            return {"has_surge": False, "max_gain": 0.0, "surge_days_ago": -1}

        max_gain     = 0.0
        surge_day    = -1

        # index 0 = 오늘, index 1 = 전일, ...
        # 최근 N일 각 날의 전일 대비 수익률 계산
        for i in range(1, days + 1):
            if i + 1 >= len(closes):
                break
            prev  = closes[i + 1]
            today = closes[i]
            if prev <= 0:
                continue
            gain = (today - prev) / prev * 100
            if gain > max_gain:
                max_gain  = gain
                surge_day = i  # 며칠 전

        has_surge = max_gain >= min_pct
        return {
            "has_surge":      has_surge,
            "max_gain":       round(max_gain, 2),
            "surge_days_ago": surge_day,
        }

    # ──────────────────────────────────────────────────────────
    # 3. 정배열 확인 (MA5 > MA20)
    # ──────────────────────────────────────────────────────────

    def is_ma_aligned(self, code: str, ma_data: Optional[dict] = None) -> bool:
        if ma_data is None:
            ma_data = self.get_daily_data(code)
        if not ma_data:
            return False
        return ma_data["ma5"] > ma_data["ma20"]

    # ──────────────────────────────────────────────────────────
    # 4. 신고가 근접 확인
    # ──────────────────────────────────────────────────────────

    def is_near_high(self, code: str, ma_data: Optional[dict] = None) -> dict:
        try:
            if ma_data is None:
                ma_data = self.get_daily_data(code)
            if not ma_data:
                return {"is_high": False, "high_20d": 0, "pct_from_high": 0}

            cfg    = self.scfg.get_scan()
            n      = cfg.get("use_recent_high_days", 20)
            closes = ma_data.get("closes", [])
            if len(closes) < n:
                return {"is_high": False, "high_20d": 0, "pct_from_high": 0}

            high_nd = max(closes[:n])
            cur     = closes[0]
            if high_nd == 0:
                return {"is_high": False, "high_20d": 0, "pct_from_high": 0}

            pct       = (cur - high_nd) / high_nd * 100
            threshold = cfg.get("near_high_threshold_pct", -20.0)
            return {
                "is_high":       pct >= threshold,
                "high_20d":      high_nd,
                "pct_from_high": round(pct, 2),
            }
        except Exception as e:
            logger.error(f"[Strategy] {code} 신고가 확인 실패: {e}")
            return {"is_high": False, "high_20d": 0, "pct_from_high": 0}

    # ──────────────────────────────────────────────────────────
    # 5. RSI 계산
    # ──────────────────────────────────────────────────────────

    def calculate_rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(period):
            diff = closes[i] - closes[i + 1]
            gains.append(diff if diff > 0 else 0)
            losses.append(-diff if diff < 0 else 0)
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 1)

    # ──────────────────────────────────────────────────────────
    # 6. 외국인/기관 수급
    # ──────────────────────────────────────────────────────────

    def get_institution_foreign_flow(self, code: str) -> dict:
        try:
            data = self.broker._post(
                "ka10009", "/api/dostk/frgnistt", {"stk_cd": code}
            )
            def to_int(s):
                s = (s or "0").strip()
                if not s or s in ("-", "+"): return 0
                sign = -1 if s.startswith("-") else 1
                return sign * int(s.lstrip("+-0") or "0")
            return {
                "institution_net": to_int(data.get("orgn_daly_nettrde", "0")),
                "foreign_net":     to_int(data.get("frgnr_daly_nettrde", "0")),
                "positive":        True,
            }
        except:
            return {"institution_net": 0, "foreign_net": 0, "positive": True}

    # ──────────────────────────────────────────────────────────
    # 7-A. 소스1: 52주 신고가 종목 (ka10016)
    # ──────────────────────────────────────────────────────────

    def _source_52w_high(self) -> list[dict]:
        """
        ka10016 — 신고저가요청 (문서 확인 필요: URL /api/dostk/rkinfo)
        52주 신고가 근접 종목 → 최근 강세 종목의 핵심 소스
        """
        try:
            data = self.broker._post(
                "ka10016",
                "/api/dostk/rkinfo",
                {
                    "mrkt_tp":  "000",  # 전체
                    "sort_tp":  "1",    # 신고가
                    "stex_tp":  "3",    # KRX+NXT
                }
            )
            result = []
            # 응답 키는 실제 API 문서 확인 후 조정 필요
            raw = data.get("new_high_low", data.get("stk_hgst_lwst", []))
            for item in raw[:100]:
                code  = item.get("stk_cd", "").lstrip("A")
                name  = item.get("stk_nm", "")
                price = abs(int(item.get("cur_prc", "0").lstrip("+-") or "0"))
                if price > 0:
                    result.append({"code": code, "name": name, "cur_price": price,
                                   "source": "52W_HIGH"})
            logger.info(f"[Strategy] 소스1(52주신고가): {len(result)}개")
            return result
        except Exception as e:
            logger.warning(f"[Strategy] 소스1 실패: {e}")
            return []

    # ──────────────────────────────────────────────────────────
    # 7-B. 소스2: 당일 거래량 급증 (ka10023, 조건 완화)
    # ──────────────────────────────────────────────────────────

    def _source_volume_surge(self) -> list[dict]:
        """ka10023 — 거래량급증 (URL: /api/dostk/rkinfo, 문서 p.77)"""
        try:
            data = self.broker._post(
                "ka10023",
                "/api/dostk/rkinfo",
                {
                    "mrkt_tp":     "000",
                    "sort_tp":     "1",
                    "tm_tp":       "2",
                    "trde_qty_tp": "5",   # 5만주 이상
                    "tm":          "",
                    "stk_cnd":     "20",  # ETF+ETN+스팩 제외
                    "pric_tp":     "0",
                    "stex_tp":     "3",
                }
            )
            result = []
            for item in data.get("trde_qty_sdnin", []):
                code  = item.get("stk_cd", "").lstrip("A")
                name  = item.get("stk_nm", "")
                price = abs(int(item.get("cur_prc", "0").lstrip("+-") or "0"))
                if price > 0:
                    result.append({"code": code, "name": name, "cur_price": price,
                                   "source": "VOL_SURGE"})
            logger.info(f"[Strategy] 소스2(거래량급증): {len(result)}개")
            return result
        except Exception as e:
            logger.warning(f"[Strategy] 소스2 실패: {e}")
            return []

    # ──────────────────────────────────────────────────────────
    # 7-C. 소스3: 거래량 갱신 상위 (ka10024)
    # ──────────────────────────────────────────────────────────

    def _source_volume_renew(self) -> list[dict]:
        """
        ka10024 — 거래량갱신요청
        최근 거래 활발 종목 포착 (1~5일 전 급등 종목도 포함 가능)
        """
        try:
            data = self.broker._post(
                "ka10024",
                "/api/dostk/rkinfo",
                {
                    "mrkt_tp": "000",
                    "stex_tp": "3",
                }
            )
            result = []
            # 응답 키 확인 필요
            raw = data.get("trde_qty_renew", data.get("stk_vlm_renw", []))
            for item in raw[:100]:
                code  = item.get("stk_cd", "").lstrip("A")
                name  = item.get("stk_nm", "")
                price = abs(int(item.get("cur_prc", "0").lstrip("+-") or "0"))
                if price > 0:
                    result.append({"code": code, "name": name, "cur_price": price,
                                   "source": "VOL_RENEW"})
            logger.info(f"[Strategy] 소스3(거래량갱신): {len(result)}개")
            return result
        except Exception as e:
            logger.warning(f"[Strategy] 소스3 실패: {e}")
            return []

    # ──────────────────────────────────────────────────────────
    # 8. 후보 종목 심층 분석
    # ──────────────────────────────────────────────────────────

    def analyze_candidate(self, code: str, basic_info: dict,
                           daily: Optional[dict] = None) -> Optional[dict]:
        """
        최근 급등 확인 + MA + 신고가 + RSI 검증
        """
        cfg_scan  = self.scfg.get_scan()
        cfg_entry = self.scfg.get_entry()
        cur_price = basic_info.get("cur_price", 0)

        # 주가 범위 필터
        if cur_price > 0 and not (cfg_scan["min_price"] <= cur_price <= cfg_scan["max_price"]):
            return None

        daily = daily or self.get_daily_data(code)
        if not daily:
            return None

        closes = daily.get("closes", [])
        if len(closes) < 3:
            return None

        # ── 최근 급등 확인 (핵심 필터) ──────────────────────
        surge = self.check_recent_surge(daily)
        if not surge["has_surge"]:
            logger.debug(
                f"[Strategy] {code} 최근 급등 없음 "
                f"(최대:{surge['max_gain']:.1f}%) — 제외"
            )
            return None

        # ── 거래대금 확인 (전일 기준) ────────────────────────
        trading_values = daily.get("trading_values", [])
        prev_tv = trading_values[1] if len(trading_values) > 1 else 0
        if prev_tv < cfg_scan["min_trading_value"]:
            logger.debug(f"[Strategy] {code} 거래대금 부족 ({prev_tv//100_000_000}억) — 제외")
            return None

        # ── 정배열 (MA5 > MA20) ──────────────────────────────
        if cfg_scan["ma_alignment"] and not self.is_ma_aligned(code, daily):
            logger.debug(f"[Strategy] {code} 정배열 미충족 — 제외")
            return None

        # ── 신고가 근접 ──────────────────────────────────────
        high_info = self.is_near_high(code, daily)
        if cfg_scan["use_52w_high"] and not high_info["is_high"]:
            logger.debug(
                f"[Strategy] {code} 신고가 범위 초과 "
                f"({high_info['pct_from_high']:.1f}%) — 제외"
            )
            return None

        # ── RSI ──────────────────────────────────────────────
        rsi = self.calculate_rsi(closes, cfg_entry["rsi_period"])
        if not (cfg_entry["rsi_min"] <= rsi <= cfg_entry["rsi_max"]):
            logger.debug(f"[Strategy] {code} RSI {rsi} 범위 초과 — 제외")
            return None

        # ── 수급 (옵션) ──────────────────────────────────────
        flow = {"institution_net": 0, "foreign_net": 0}
        if cfg_entry.get("use_institution_buy") or cfg_entry.get("use_foreign_buy"):
            flow = self.get_institution_foreign_flow(code)

        volumes = daily.get("volumes", [])
        today_volume = volumes[0] if volumes else 0

        return {
            **basic_info,
            "trading_value":   prev_tv,
            "volume":          today_volume,
            "volume_ratio":    round(today_volume / max(volumes[1], 1), 1) if len(volumes) > 1 else 0,
            "ma5":             daily["ma5"],
            "ma20":            daily["ma20"],
            "ma60":            daily["ma60"],
            "rsi":             rsi,
            "high_20d":        high_info["high_20d"],
            "pct_from_high":   high_info["pct_from_high"],
            "surge_max_gain":  surge["max_gain"],
            "surge_days_ago":  surge["surge_days_ago"],
            "institution_net": flow["institution_net"],
            "foreign_net":     flow["foreign_net"],
        }

    # ──────────────────────────────────────────────────────────
    # 9. 종목 점수화
    # ──────────────────────────────────────────────────────────

    def score_candidate(self, c: dict) -> float:
        score = 0.0
        cfg   = self.scfg.get_scan()

        # 거래대금 (최대 35점)
        tv_score = min(
            (c["trading_value"] - cfg["min_trading_value"])
            / 490_000_000_000 * 35, 35
        )
        score += max(tv_score, 0)

        # 최근 급등 강도 (최대 30점) — 5%=0점, 30%+=30점
        surge_score = min((c.get("surge_max_gain", 0) - 5) / 25 * 30, 30)
        score += max(surge_score, 0)

        # 수급 (최대 20점)
        if c.get("institution_net", 0) > 0: score += 10
        if c.get("foreign_net", 0) > 0:     score += 10

        # 신고가 근접도 (최대 15점) — 0%=15점, -20%=0점
        pct = c.get("pct_from_high", -20)
        score += max((pct + 20) / 20 * 15, 0)

        return round(score, 2)

    # ──────────────────────────────────────────────────────────
    # 10. 전체 스캔 실행 (메인)
    # ──────────────────────────────────────────────────────────

    def scan_candidates(self) -> list[dict]:
        """
        3가지 소스에서 후보 수집 → 최근 급등 + 오늘 눌림 필터 → 점수 정렬
        """
        logger.info("[Strategy] 후보 종목 스캔 시작 (v1.3)...")
        cfg_entry = self.scfg.get_entry()

        # ── 3소스 합산 (중복 제거) ───────────────────────────
        pool: dict[str, dict] = {}
        for item in (
            self._source_volume_surge() +  # 소스2 먼저 (가장 안정적)
            self._source_52w_high() +       # 소스1
            self._source_volume_renew()     # 소스3
        ):
            code = item["code"]
            if code and code not in pool:
                pool[code] = item

        logger.info(f"[Strategy] 후보 풀: {len(pool)}개 (중복 제거 후)")

        # ── 심층 분석 (상위 80개만 — API 부하 제한) ──────────
        passed: dict[str, dict] = {}
        for code, item in list(pool.items())[:80]:
            daily  = self.get_daily_data(code)
            result = self.analyze_candidate(code, item, daily)
            if result:
                result["score"] = self.score_candidate(result)
                passed[code]    = result
                logger.info(
                    f"[Strategy] ✅ {result['name']}({code}) "
                    f"점수:{result['score']} "
                    f"소스:{result.get('source','?')} "
                    f"최근급등:{result['surge_max_gain']:.1f}%(D-{result['surge_days_ago']}) "
                    f"거래대금:{result['trading_value']//100_000_000}억 "
                    f"RSI:{result['rsi']}"
                )

        # ── 점수 정렬 후 최대 종목 수 반환 ───────────────────
        sorted_list = sorted(passed.values(), key=lambda x: x["score"], reverse=True)
        result      = sorted_list[:cfg_entry["max_positions"]]
        logger.info(f"[Strategy] 최종 후보: {len(result)}개 / 통과: {len(passed)}개")
        return result

    # ──────────────────────────────────────────────────────────
    # 11. 진입 신호 확인
    # ──────────────────────────────────────────────────────────

    def check_entry_signal(self, code: str, cur_price: int,
                           prev_close: int) -> dict:
        cfg = self.scfg.get_entry()
        now = datetime.now().strftime("%H:%M")

        if not (cfg["entry_start_time"] <= now <= cfg["entry_end_time"]):
            return {
                "signal":       False,
                "reason":       f"진입 시각 아님 ({now})",
                "pullback_pct": 0,
            }
        if prev_close <= 0:
            return {"signal": False, "reason": "전일 종가 없음", "pullback_pct": 0}

        pullback_pct = (cur_price - prev_close) / prev_close * 100

        if pullback_pct < cfg["pullback_min_pct"]:
            return {
                "signal":       False,
                "reason":       f"눌림 과다 ({pullback_pct:.1f}%)",
                "pullback_pct": round(pullback_pct, 2),
            }
        if pullback_pct > cfg["pullback_max_pct"]:
            return {
                "signal":       False,
                "reason":       f"눌림 부족/상승 중 ({pullback_pct:.1f}%)",
                "pullback_pct": round(pullback_pct, 2),
            }
        return {
            "signal":       True,
            "reason":       f"눌림 정상 ({pullback_pct:.1f}%)",
            "pullback_pct": round(pullback_pct, 2),
        }

    # ──────────────────────────────────────────────────────────
    # 12. 매도 신호 확인 (D+1)
    # ──────────────────────────────────────────────────────────

    def check_exit_signal(self, code: str, cur_price: int,
                          buy_price: int, held_qty: int,
                          day_high: int = 0) -> dict:
        cfg_risk = self.scfg.get_risk()
        cfg_sell = self.scfg.get_sell()
        now      = datetime.now().strftime("%H:%M")

        if buy_price <= 0 or held_qty <= 0:
            return {"signal": "HOLD", "reason": "포지션 없음", "qty": 0}

        profit_pct = (cur_price - buy_price) / buy_price * 100

        if profit_pct <= cfg_risk["stop_loss_pct"]:
            return {"signal": "FULL",
                    "reason": f"손절 ({profit_pct:.1f}%)", "qty": held_qty}

        if (cfg_sell["use_nxt_premarket"] and "08:00" <= now <= "08:50"
                and profit_pct >= cfg_sell["nxt_gap_target_pct"]):
            return {"signal": "FULL",
                    "reason": f"NXT 갭 익절 (+{profit_pct:.1f}%)", "qty": held_qty}

        if (now <= cfg_sell["morning_sell_end"]
                and profit_pct >= cfg_sell["morning_target_pct"]):
            qty = max(int(held_qty * cfg_risk["partial_sell_pct"] / 100), 1)
            return {"signal": "PARTIAL",
                    "reason": f"오전 1차 익절 (+{profit_pct:.1f}%)", "qty": qty}

        if profit_pct >= cfg_risk["take_profit_pct"]:
            return {"signal": "FULL",
                    "reason": f"목표 익절 (+{profit_pct:.1f}%)", "qty": held_qty}

        if cfg_risk["trailing_stop"] and day_high > 0:
            trail = (cur_price - day_high) / day_high * 100
            if trail <= -cfg_risk["trailing_gap_pct"]:
                return {"signal": "FULL",
                        "reason": f"트레일링 스탑 ({trail:.1f}%)", "qty": held_qty}

        if now >= cfg_sell["afternoon_cut_time"] and profit_pct < 0:
            qty = max(int(held_qty * cfg_sell["afternoon_cut_ratio"] / 100), 1)
            if qty < held_qty:
                return {"signal": "PARTIAL",
                        "reason": f"오후 손실 축소 ({profit_pct:.1f}%)", "qty": qty}

        if cfg_sell["eod_force_sell"] and now >= cfg_risk["force_sell_time"]:
            return {"signal": "FULL",
                    "reason": f"강제 청산 {now}", "qty": held_qty}

        return {"signal": "HOLD",
                "reason": f"보유 유지 ({profit_pct:.1f}%)", "qty": 0}

    # ──────────────────────────────────────────────────────────
    # 13. 매수 수량 계산
    # ──────────────────────────────────────────────────────────

    def calculate_buy_qty(self, code: str, cur_price: int,
                          available_cash: int) -> int:
        if cur_price <= 0:
            return 0
        cfg           = self.scfg.get_entry()
        target_amount = int(available_cash * cfg["position_size_pct"] / 100)
        qty           = target_amount // cur_price
        logger.info(f"[Strategy] {code} 매수: {target_amount:,}원 / @{cur_price:,}원 = {qty}주")
        return qty
