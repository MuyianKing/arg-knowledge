from app.core.redact import redact_text


def test_redact_phone_id_and_bank_card() -> None:
    text = "电话 13800138000，身份证 110101199001011234，卡号 6222021234567890123，报销 80 元。"
    redacted = redact_text(text)
    assert "13800138000" not in redacted
    assert "110101199001011234" not in redacted
    assert "6222021234567890123" not in redacted
    assert "80" in redacted


def test_redact_leaves_normal_numbers_alone() -> None:
    assert redact_text("市内交通费每日上限 80 元。") == "市内交通费每日上限 80 元。"
