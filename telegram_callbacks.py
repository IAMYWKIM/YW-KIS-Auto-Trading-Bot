# ==========================================================
# FILE: telegram_callbacks.py
# ==========================================================
# 🚨 MODIFIED: [도메인 주도 라우팅] 2,000라인 이상의 God Object를 5개의 도메인 핸들러로 완벽히 분리
# 🚨 MODIFIED: [제1헌법 준수] 하위 핸들러 호출 시 이벤트 루프 블로킹이 발생하지 않도록 100% 비동기 체인 락온
# 🚨 MODIFIED: [결합도 최소화] 의존성 주입(Dependency Injection)을 통해 각 도메인 핸들러가 필요한 코어 엔진만 참조하도록 캡슐화
# ==========================================================
import html
import logging
from telegram import Update
from telegram.ext import ContextTypes

from callback_order_handler import CallbackOrderHandler
from callback_queue_handler import CallbackQueueHandler
from callback_avwap_handler import CallbackAvwapHandler
from callback_config_handler import CallbackConfigHandler

class TelegramCallbacks:
    def __init__(self, config, broker, strategy, queue_ledger, sync_engine, view, tx_lock):
        self.cfg = config
        self.broker = broker
        self.strategy = strategy
        self.queue_ledger = queue_ledger
        self.sync_engine = sync_engine
        self.view = view
        self.tx_lock = tx_lock

        # 🚨 [도메인 핸들러 초기화 (의존성 주입)]
        self.order_handler = CallbackOrderHandler(config, broker, strategy, queue_ledger, sync_engine, view, tx_lock)
        self.queue_handler = CallbackQueueHandler(config, queue_ledger, sync_engine, view)
        self.avwap_handler = CallbackAvwapHandler(config, broker, strategy, view, tx_lock)
        self.config_handler = CallbackConfigHandler(config, broker, strategy, queue_ledger, sync_engine, view, tx_lock)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, controller):
        query = update.callback_query
        chat_id = update.effective_chat.id
        data = query.data.split(":")
        action, sub = data[0], data[1] if len(data) > 1 else ""

        try:
            # 1️⃣ [수동/비상 주문 도메인 라우팅]
            if action in ["EMERGENCY_REQ", "EMERGENCY_EXEC", "EXEC", "CANCEL_EXEC"]:
                await self.order_handler.handle(update, context, controller, action, sub, data)
            
            # 2️⃣ [V-REV 큐 장부 조작 도메인 라우팅]
            elif action in ["QUEUE", "DEL_REQ", "DEL_Q", "EDIT_Q"]:
                await self.queue_handler.handle(update, context, controller, action, sub, data)
            
            # 3️⃣ [AVWAP 암살자 및 모드 스위칭 도메인 라우팅]
            elif action in ["AVWAP", "MODE", "AVWAP_SET"]:
                await self.avwap_handler.handle(update, context, controller, action, sub, data)
            
            # 4️⃣ [환경설정, 뷰어, 히스토리, 범용 도메인 라우팅]
            elif action in ["UPDATE", "VERSION", "RESET", "REC", "HIST", "TICKER", "SEED", "INPUT", "SET_VER", "SET_VER_CONFIRM"]:
                await self.config_handler.handle(update, context, controller, action, sub, data)
            
            # 5️⃣ [알 수 없는 엣지 라우팅 튕겨내기]
            else:
                safe_data = html.escape(str(data))
                await context.bot.send_message(chat_id, f"⚠️ <b>[알 수 없는 콜백 라우팅]</b> <code>{safe_data}</code>", parse_mode='HTML')

        except Exception as e:
            logging.error(f"🚨 [라우터 코어 에러] 콜백 라우팅 중 치명적 예외 발생: {e}")
            try:
                safe_err = html.escape(str(e))
                await context.bot.send_message(chat_id, f"❌ <b>[라우팅 에러]</b> <code>{safe_err}</code>", parse_mode='HTML')
            except Exception:
                pass
