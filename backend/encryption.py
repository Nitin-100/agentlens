"""
AgentLens Encryption — Field-level encryption at rest for sensitive data.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.
Encrypts sensitive fields (prompts, completions, tool args/results, errors)
before storing in SQLite. Decrypts transparently on read.

Setup:
  1. Set AGENTLENS_ENCRYPTION_KEY env var (base64-encoded 32-byte key)
  2. Or let the system auto-generate and store in .encryption_key file

Key management:
  - Key is loaded once at startup
  - Supports key rotation: encrypt with new key, decrypt tries both
  - Old key is kept for decryption during rotation grace period
"""

import os
import base64
import logging
from typing import Optional

logger = logging.getLogger("agentlens.encryption")

# These fields are encrypted at rest
SENSITIVE_FIELDS = {
    "prompt", "completion", "tool_args", "tool_result",
    "error_message", "stack_trace", "input_data", "output_data",
    "thought", "decision",
}

# Try to import cryptography; graceful fallback if not installed
try:
    from cryptography.fernet import Fernet, InvalidToken, MultiFernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.warning("cryptography not installed. Encryption at rest disabled. pip install cryptography")


class FieldEncryptor:
    """Encrypts/decrypts individual string fields using Fernet."""

    def __init__(self):
        self._fernet: Optional[object] = None
        self._enabled = False
        self._key_file = os.path.join(os.path.dirname(__file__), ".encryption_key")

    def init(self, key: Optional[str] = None):
        """Initialize encryption. Call once at startup.
        
        Args:
            key: Base64-encoded Fernet key. If None, tries env var,
                 then key file, then auto-generates.
        """
        if not HAS_CRYPTO:
            logger.warning("Encryption disabled: cryptography library not installed")
            return

        # Priority: explicit key > env var > key file > auto-generate
        encryption_key = key or os.environ.get("AGENTLENS_ENCRYPTION_KEY")

        if not encryption_key:
            # Try reading from key file
            if os.path.exists(self._key_file):
                with open(self._key_file, "r") as f:
                    encryption_key = f.read().strip()
                logger.info("Encryption key loaded from .encryption_key file")
            else:
                # Auto-generate
                encryption_key = Fernet.generate_key().decode()
                with open(self._key_file, "w") as f:
                    f.write(encryption_key)
                # Restrict file permissions (best effort on Windows)
                try:
                    os.chmod(self._key_file, 0o600)
                except Exception:
                    pass
                logger.info("New encryption key generated and saved to .encryption_key")

        try:
            self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            self._enabled = True
            logger.info("Field-level encryption enabled (AES-128-CBC + HMAC-SHA256)")
        except Exception as e:
            logger.error(f"Invalid encryption key: {e}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """Encrypt a string field. Returns base64-encoded ciphertext prefixed with 'enc:'."""
        if not self._enabled or not plaintext or not isinstance(plaintext, str):
            return plaintext
        try:
            token = self._fernet.encrypt(plaintext.encode("utf-8"))
            return f"enc:{token.decode('utf-8')}"
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return plaintext  # Fail open — store unencrypted rather than lose data

    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """Decrypt a field. Only decrypts if prefixed with 'enc:'."""
        if not self._enabled or not ciphertext or not isinstance(ciphertext, str):
            return ciphertext
        if not ciphertext.startswith("enc:"):
            return ciphertext  # Not encrypted, return as-is
        try:
            token = ciphertext[4:].encode("utf-8")
            return self._fernet.decrypt(token).decode("utf-8")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return "[DECRYPTION_FAILED]"

    def encrypt_event(self, event: dict) -> dict:
        """Encrypt all sensitive fields in an event dict."""
        if not self._enabled:
            return event
        encrypted = dict(event)
        for field in SENSITIVE_FIELDS:
            if field in encrypted and encrypted[field] is not None:
                encrypted[field] = self.encrypt(str(encrypted[field]))
        return encrypted

    def decrypt_event(self, event: dict) -> dict:
        """Decrypt all sensitive fields in an event dict."""
        if not self._enabled:
            return event
        decrypted = dict(event)
        for field in SENSITIVE_FIELDS:
            if field in decrypted and decrypted[field] is not None:
                decrypted[field] = self.decrypt(str(decrypted[field]))
        return decrypted

    def decrypt_events(self, events: list[dict]) -> list[dict]:
        """Decrypt a list of events."""
        if not self._enabled:
            return events
        return [self.decrypt_event(e) for e in events]

    def rotate_key(self, new_key: Optional[str] = None) -> str:
        """Generate a new encryption key. Old key is kept for decryption.
        
        Returns the new key (base64-encoded). Caller must re-encrypt existing data.
        """
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library not installed")

        old_fernet = self._fernet
        new_key_bytes = new_key or Fernet.generate_key().decode()

        try:
            new_fernet = Fernet(new_key_bytes.encode() if isinstance(new_key_bytes, str) else new_key_bytes)
        except Exception as e:
            raise ValueError(f"Invalid new key: {e}")

        # Use MultiFernet: encrypts with new key, decrypts with either
        self._fernet = MultiFernet([new_fernet, old_fernet]) if old_fernet else new_fernet
        self._enabled = True

        # Save new key
        with open(self._key_file, "w") as f:
            f.write(new_key_bytes if isinstance(new_key_bytes, str) else new_key_bytes.decode())
        try:
            os.chmod(self._key_file, 0o600)
        except Exception:
            pass

        logger.info("Encryption key rotated. Both old and new keys active for decryption.")
        return new_key_bytes if isinstance(new_key_bytes, str) else new_key_bytes.decode()

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet key (for manual key management)."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library not installed")
        return Fernet.generate_key().decode()


# Singleton
encryptor = FieldEncryptor()
