from revit_mcp_server.security.audit import _is_sensitive_key, _redact_text, redact_data


# --- _is_sensitive_key -------------------------------------------------

def test_is_sensitive_key_matches_prefixed_api_key():
    # anthropic_api_key normalizes to "anthropicapikey", which is not an
    # exact member of _SECRET_KEYS but ends in "apikey" - a prefixed/compound
    # secret-key name like this must still be caught.
    assert _is_sensitive_key("anthropic_api_key") is True


def test_is_sensitive_key_matches_other_prefixed_secret_names():
    assert _is_sensitive_key("openai_api_key") is True
    assert _is_sensitive_key("github_token") is True
    assert _is_sensitive_key("client_secret") is True


def test_is_sensitive_key_exact_matches_still_work():
    # Existing exact-match entries must continue to work unchanged.
    for key in [
        "authorization",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "token",
        "sessiontoken",
        "password",
        "clientsecret",
        "secret",
        "codeverifier",
        "apikey",
        "authorizationcode",
        "code",
        "rhinocomputekey",
    ]:
        assert _is_sensitive_key(key) is True


def test_is_sensitive_key_does_not_match_unrelated_keys():
    assert _is_sensitive_key("name") is False
    assert _is_sensitive_key("status") is False
    assert _is_sensitive_key("element_id") is False


def test_is_sensitive_key_suffix_match_can_overmatch_short_terms():
    # Accepted tradeoff: suffix-matching a short secret term like "code"
    # against a key like "barcode" is a false positive (redacting a
    # non-secret value). That is a low-cost error compared to the
    # alternative - a false negative that lets a real secret like
    # "anthropic_api_key" leak because we required an exact match. This
    # test documents/pins that intentional choice.
    assert _is_sensitive_key("barcode") is True


# --- redact_data (structured) ------------------------------------------

def test_redact_data_redacts_prefixed_api_key_value():
    redacted = redact_data({"anthropic_api_key": "sk-ant-real-secret-value"})
    assert redacted["anthropic_api_key"] == "<redacted>"
    assert "sk-ant-real-secret-value" not in str(redacted)


def test_redact_data_leaves_non_sensitive_keys_untouched():
    redacted = redact_data({"name": "diagrid-tower", "status": "ok"})
    assert redacted == {"name": "diagrid-tower", "status": "ok"}


# --- _redact_text (free-text) -------------------------------------------

def test_redact_text_redacts_prefixed_api_key_in_free_text():
    text = "anthropic_api_key: sk-ant-real-secret-value"
    redacted = _redact_text(text)
    assert "sk-ant-real-secret-value" not in redacted
    assert "<redacted>" in redacted


def test_redact_text_still_redacts_existing_plain_keyword_cases():
    # These are the pre-existing free-text patterns the regex already
    # handled (keyword at token start, not as a suffix) - must not regress.
    assert "<redacted>" in _redact_text("token: abc123xyz")
    assert "<redacted>" in _redact_text("api_key=sk-live-abcdef")
    assert "secretvalue123" not in _redact_text("password: secretvalue123")
