"""Unrelated gateway cases must not depend on optional platform SDK setup."""


def test_generic_gateway_case_does_not_request_feishu_sdk_binding(request):
    # Inspect the actual resolved fixture closure, not sys.modules: a full
    # gateway collection may legitimately include Feishu integration modules.
    assert "_bind_lark_sdk_globals_when_installed" not in request.fixturenames
