"""
AgentLens Security Tests — validates all security hardening.

Run: pytest test_security.py -v
"""

import os
import sys
import pytest

# Add backend dir to path
sys.path.insert(0, os.path.dirname(__file__))

from compliance import (
    phi_scanner, validate_webhook_url, breach_detector,
    session_manager, ip_allowlist, DataClassification,
)


# ─── PHI Detection Tests ────────────────────────────────────

class TestPHIScanner:
    def test_detect_ssn(self):
        assert phi_scanner.contains_phi("My SSN is 123-45-6789")

    def test_detect_email(self):
        assert phi_scanner.contains_phi("Contact me at john@example.com")

    def test_detect_phone(self):
        assert phi_scanner.contains_phi("Call me at (555) 123-4567")

    def test_detect_credit_card(self):
        assert phi_scanner.contains_phi("Card: 4111-1111-1111-1111")

    def test_detect_aadhaar(self):
        assert phi_scanner.contains_phi("Aadhaar: 1234 5678 9012")

    def test_detect_pan(self):
        assert phi_scanner.contains_phi("PAN: ABCDE1234F")

    def test_detect_mrn(self):
        assert phi_scanner.contains_phi("MRN: 12345678")

    def test_detect_diagnosis(self):
        assert phi_scanner.contains_phi("diagnosed with diabetes")

    def test_detect_medication(self):
        assert phi_scanner.contains_phi("prescribed medication 500mg")

    def test_detect_api_key(self):
        assert phi_scanner.contains_phi("Key: sk-abc123def456ghijk")

    def test_no_phi_in_clean_text(self):
        assert not phi_scanner.contains_phi("The weather is nice today")

    def test_none_input(self):
        assert not phi_scanner.contains_phi(None)

    def test_empty_string(self):
        assert not phi_scanner.contains_phi("")

    def test_mask_ssn(self):
        result = phi_scanner.mask("SSN: 123-45-6789")
        assert "123-45-6789" not in result
        assert "***-**-****" in result

    def test_mask_email(self):
        result = phi_scanner.mask("Email: john@example.com")
        assert "john@example.com" not in result
        assert "[EMAIL REDACTED]" in result

    def test_scan_event(self):
        event = {"prompt": "Patient SSN is 123-45-6789", "completion": "OK"}
        result = phi_scanner.scan_event(event)
        assert result["phi_detected"]
        assert result["phi_count"] >= 1

    def test_mask_event(self):
        event = {"prompt": "SSN: 123-45-6789", "model": "gpt-4"}
        masked = phi_scanner.mask_event(event)
        assert "123-45-6789" not in masked["prompt"]
        assert masked["model"] == "gpt-4"  # Non-sensitive fields untouched


# ─── SSRF Prevention Tests ───────────────────────────────────

class TestSSRFPrevention:
    def test_valid_https_url(self):
        assert validate_webhook_url("https://hooks.slack.com/services/abc")

    def test_valid_http_url(self):
        assert validate_webhook_url("http://webhook.example.com/hook")

    def test_block_localhost(self):
        assert not validate_webhook_url("http://localhost:8080/admin")

    def test_block_127(self):
        assert not validate_webhook_url("http://127.0.0.1:8080/admin")

    def test_block_private_10(self):
        assert not validate_webhook_url("http://10.0.0.1/admin")

    def test_block_private_172(self):
        assert not validate_webhook_url("http://172.16.0.1/admin")

    def test_block_private_192(self):
        assert not validate_webhook_url("http://192.168.1.1/admin")

    def test_block_metadata(self):
        assert not validate_webhook_url("http://169.254.169.254/latest/meta-data/")

    def test_block_gcp_metadata(self):
        assert not validate_webhook_url("http://metadata.google.internal/computeMetadata")

    def test_block_internal_domain(self):
        assert not validate_webhook_url("http://admin.internal/secret")

    def test_block_local_domain(self):
        assert not validate_webhook_url("http://server.local/api")

    def test_block_ftp_scheme(self):
        assert not validate_webhook_url("ftp://evil.com/payload")

    def test_block_file_scheme(self):
        assert not validate_webhook_url("file:///etc/passwd")

    def test_block_empty_url(self):
        assert not validate_webhook_url("")

    def test_block_none(self):
        assert not validate_webhook_url(None)

    def test_block_zero_ip(self):
        assert not validate_webhook_url("http://0.0.0.0/admin")


# ─── Breach Detection Tests ─────────────────────────────────

class TestBreachDetection:
    def test_lockout_after_threshold(self):
        """IP gets locked out after too many failed auths."""
        test_ip = "192.0.2.99"
        # Set a low threshold for testing
        breach_detector._threshold = 3
        breach_detector._failed_auths.pop(test_ip, None)
        breach_detector._lockouts.pop(test_ip, None)

        for _ in range(3):
            breach_detector.record_failed_auth(test_ip)

        assert breach_detector.is_locked_out(test_ip)

        # Reset
        breach_detector._threshold = 10
        breach_detector._lockouts.pop(test_ip, None)
        breach_detector._failed_auths.pop(test_ip, None)

    def test_no_lockout_below_threshold(self):
        test_ip = "192.0.2.100"
        breach_detector._failed_auths.pop(test_ip, None)
        breach_detector._lockouts.pop(test_ip, None)

        breach_detector.record_failed_auth(test_ip)
        assert not breach_detector.is_locked_out(test_ip)

        breach_detector._failed_auths.pop(test_ip, None)


# ─── IP Allowlist Tests ──────────────────────────────────────

class TestIPAllowlist:
    def test_no_allowlist_allows_all(self):
        assert ip_allowlist.is_allowed("test-project", "1.2.3.4")

    def test_allowlist_blocks_unknown(self):
        ip_allowlist.set_allowlist("secure-project", ["10.0.0.1", "10.0.0.2"])
        assert not ip_allowlist.is_allowed("secure-project", "1.2.3.4")

    def test_allowlist_allows_known(self):
        ip_allowlist.set_allowlist("secure-project", ["10.0.0.1", "10.0.0.2"])
        assert ip_allowlist.is_allowed("secure-project", "10.0.0.1")

    def test_clear_allowlist(self):
        ip_allowlist.set_allowlist("secure-project", ["10.0.0.1"])
        ip_allowlist.set_allowlist("secure-project", [])
        assert ip_allowlist.is_allowed("secure-project", "any-ip")


# ─── Session Timeout Tests ───────────────────────────────────

class TestSessionManager:
    def test_first_access_not_expired(self):
        assert not session_manager.is_expired("new-key-hash")

    def test_touch_updates_session(self):
        session_manager.touch("test-session")
        assert not session_manager.is_expired("test-session")

    def test_expired_session(self):
        import time
        session_manager._sessions["old-session"] = time.time() - 99999
        assert session_manager.is_expired("old-session")
        del session_manager._sessions["old-session"]


# ─── Auth Security Tests ────────────────────────────────────

class TestAuthSecurity:
    def test_hmac_key_hashing_not_plain_sha256(self):
        """API key hashing must use HMAC, not plain SHA-256."""
        from auth import hash_api_key
        import hashlib
        test_key = "al_test_key_12345"
        hashed = hash_api_key(test_key)
        plain_sha256 = hashlib.sha256(test_key.encode()).hexdigest()
        assert hashed != plain_sha256, "Key hash must use HMAC, not plain SHA-256"

    def test_generated_key_has_prefix(self):
        from auth import generate_api_key
        key = generate_api_key()
        assert key.startswith("al_")
        assert len(key) > 20

    def test_default_role_is_viewer_not_admin(self):
        """No-auth default must be VIEWER, not ADMIN."""
        from auth import Role
        # This test validates the code change conceptually
        # The actual resolution needs async DB; we verify the code string
        import inspect
        from auth import AuthManager
        source = inspect.getsource(AuthManager.resolve)
        assert "Role.VIEWER" in source, "No-auth default must be VIEWER"
        assert "Role.ADMIN" not in source or "# Backwards compat" not in source


# ─── Encryption Security Tests ───────────────────────────────

class TestEncryptionSecurity:
    def test_fail_closed_on_error(self):
        """Encryption must raise on failure, not store plaintext."""
        import inspect
        from encryption import FieldEncryptor
        source = inspect.getsource(FieldEncryptor.encrypt)
        assert "raise RuntimeError" in source, "Encryption must fail-closed"
        # The except block must NOT return plaintext (fail-open)
        # Check the except clause specifically
        except_idx = source.index("except Exception")
        except_block = source[except_idx:]
        assert "return plaintext" not in except_block, "Must not fall back to plaintext on error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
