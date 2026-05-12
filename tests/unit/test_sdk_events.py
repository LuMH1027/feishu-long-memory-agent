import sys
import types


def test_build_event_handler_registers_card_action_for_lark_oapi_1_5_5(monkeypatch):
    from feishu_bot import sdk_events

    calls = []

    class FakeBuilder:
        def register_p2_im_message_receive_v1(self, handler):
            calls.append("message")
            return self

        def register_p2_im_message_reaction_created_v1(self, handler):
            calls.append("reaction_created")
            return self

        def register_p2_im_message_reaction_deleted_v1(self, handler):
            calls.append("reaction_deleted")
            return self

        def register_p2_card_action_trigger(self, handler):
            calls.append("card")
            return self

        def build(self):
            calls.append("build")
            return "handler"

    class FakeEventDispatcherHandler:
        @staticmethod
        def builder(token, encrypt_key):
            calls.append(("builder", token, encrypt_key))
            return FakeBuilder()

    fake_lark = types.SimpleNamespace(EventDispatcherHandler=FakeEventDispatcherHandler)
    fake_im_v1 = types.SimpleNamespace(P2ImMessageReceiveV1=object)
    monkeypatch.setitem(sys.modules, "lark_oapi", fake_lark)
    monkeypatch.setitem(sys.modules, "lark_oapi.api", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "lark_oapi.api.im", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "lark_oapi.api.im.v1", fake_im_v1)

    assert sdk_events.build_event_handler(lambda payload: None) == "handler"
    assert calls[0][0] == "builder"
    assert calls[1:] == [
        "message",
        "reaction_created",
        "reaction_deleted",
        "card",
        "build",
    ]


def test_card_action_value_accepts_sdk_callback_action_object():
    from feishu_bot.sdk_events import _card_action_value

    action = types.SimpleNamespace(value={"action": "confirm_decision", "memory_id": "mem-1"})

    assert _card_action_value(action) == {"action": "confirm_decision", "memory_id": "mem-1"}


def test_card_action_value_accepts_real_lark_callback_action():
    from feishu_bot.sdk_events import _card_action_value
    from lark_oapi.event.callback.model.p2_card_action_trigger import CallBackAction

    action = CallBackAction({"value": {"action": "reject_decision", "memory_id": "mem-2"}})

    assert _card_action_value(action) == {"action": "reject_decision", "memory_id": "mem-2"}


def test_execute_card_action_returns_success_message(monkeypatch):
    from feishu_bot import sdk_events

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok", "action": "confirmed", "memory_id": "mem-1"}

    def fake_post(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse()

    monkeypatch.setattr(sdk_events.requests, "post", fake_post)

    toast_type, content, card = sdk_events._execute_card_action(
        {"action": "confirm_decision", "memory_id": "mem-1"},
        backend_url="http://backend",
    )
    assert (toast_type, content) == ("success", "已确认采纳该决策")
    assert card["header"]["title"]["content"] == "决策流程已结束：已确认采纳"
    assert all(action["disabled"] is True for action in card["elements"][2]["actions"])
    assert calls == [
        ("http://backend/api/v1/feishu/decision/confirm", {"memory_id": "mem-1"}, 5)
    ]


def test_execute_card_action_surfaces_backend_error(monkeypatch):
    from feishu_bot import sdk_events

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "error", "message": "未找到该决策"}

    monkeypatch.setattr(sdk_events.requests, "post", lambda *args, **kwargs: FakeResponse())

    assert sdk_events._execute_card_action(
        {"action": "reject_decision", "memory_id": "missing"},
        backend_url="http://backend",
    ) == ("error", "操作失败：未找到该决策", None)


def test_card_action_toast_returns_lark_response():
    from feishu_bot.sdk_events import _card_action_toast

    card = {"config": {"wide_screen_mode": True}, "elements": []}
    response = _card_action_toast("success", "已确认采纳该决策", card)

    assert response.toast.type == "success"
    assert response.toast.content == "已确认采纳该决策"
    assert response.card.type == "raw"
    assert response.card.data == card


def test_processed_decision_card_disables_decision_buttons():
    from feishu_bot.sdk_events import _processed_decision_card

    card = _processed_decision_card("reject_decision", "mem-2")

    assert card["header"]["title"]["content"] == "决策流程已结束：已打回"
    assert all(action["disabled"] is True for action in card["elements"][2]["actions"])
