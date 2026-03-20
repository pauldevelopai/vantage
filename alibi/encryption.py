"""
Alibi Encryption Layer

Transparent Fernet encryption for JSONL storage.
Backward-compatible: reads both plaintext and encrypted lines.
"""

import gzip
import json
import os
import stat
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable


class EncryptedJSONLWriter:
    """
    Drop-in encryption wrapper for JSONL file I/O.

    Each JSON line is individually encrypted with Fernet symmetric encryption.
    Existing plaintext lines are still readable (auto-detected).
    """

    def __init__(self, key: Optional[bytes] = None, key_file: str = "alibi/data/.encryption_key"):
        self._fernet = None
        self._enabled = False
        self._key_file = Path(key_file)

        # Try environment variable first
        env_key = os.environ.get("ALIBI_ENCRYPTION_KEY")
        if env_key:
            key = env_key.encode() if isinstance(env_key, str) else env_key

        # Try key file
        if key is None and self._key_file.exists():
            try:
                key = self._key_file.read_bytes().strip()
            except Exception as e:
                print(f"[Encryption] Warning: Could not read key file: {e}")

        # Auto-generate key if none exists
        if key is None:
            key = self._generate_key()

        if key:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(key)
                self._enabled = True
            except ImportError:
                print("[Encryption] Warning: 'cryptography' package not installed. Data will not be encrypted.")
                print("[Encryption] Install with: pip install cryptography")
            except Exception as e:
                print(f"[Encryption] Warning: Invalid key, encryption disabled: {e}")

    def _generate_key(self) -> Optional[bytes]:
        """Generate and save a new Fernet key."""
        try:
            from cryptography.fernet import Fernet
            key = Fernet.generate_key()

            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            self._key_file.write_bytes(key)

            # Restrict file permissions (owner read/write only)
            try:
                os.chmod(self._key_file, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass  # Windows or permission issue

            print(f"[Encryption] Generated new encryption key: {self._key_file}")
            return key
        except ImportError:
            return None
        except Exception as e:
            print(f"[Encryption] Warning: Could not generate key: {e}")
            return None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def encrypt_line(self, data: Dict[str, Any]) -> str:
        """Compress (gzip) then encrypt a dict as a string line."""
        json_str = json.dumps(data, separators=(",", ":"))  # Compact JSON
        json_bytes = json_str.encode()

        # Gzip compress (typically 60-70% savings on text-heavy JSON)
        compressed = gzip.compress(json_bytes, compresslevel=6)

        if self._enabled and self._fernet:
            encrypted = self._fernet.encrypt(compressed)
            return encrypted.decode()

        # No encryption — store as base64-encoded gzip
        import base64
        return "GZ:" + base64.b64encode(compressed).decode()


    def decrypt_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Decrypt a line. Handles all formats transparently:
        1. Plaintext JSON (legacy, backward compat)
        2. Fernet-encrypted plaintext JSON (legacy encrypted)
        3. GZ:base64 gzip-compressed JSON (no encryption)
        4. Fernet-encrypted gzip-compressed JSON (current)

        Returns None if the line cannot be parsed.
        """
        line = line.strip()
        if not line:
            return None

        # Try plaintext JSON first (fast path for backward compatibility)
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass

        # Try GZ: prefix (gzip without encryption)
        if line.startswith("GZ:"):
            try:
                import base64
                compressed = base64.b64decode(line[3:])
                decompressed = gzip.decompress(compressed)
                return json.loads(decompressed.decode())
            except Exception:
                pass

        # Try Fernet decryption
        if self._enabled and self._fernet:
            try:
                decrypted_bytes = self._fernet.decrypt(line.encode())

                # Try gzip decompress first (new format)
                try:
                    decompressed = gzip.decompress(decrypted_bytes)
                    return json.loads(decompressed.decode())
                except (gzip.BadGzipFile, OSError):
                    pass

                # Fall back to plain JSON (old encrypted format)
                return json.loads(decrypted_bytes.decode())
            except Exception:
                pass

        # Last resort: try plain JSON (for non-dict JSON)
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def write_line(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Encrypt and append a single record to a JSONL file."""
        encrypted = self.encrypt_line(data)
        with open(file_path, "a") as f:
            f.write(encrypted + "\n")

    def read_lines(self, file_path: Path) -> List[Dict[str, Any]]:
        """Read and decrypt all lines from a JSONL file."""
        results = []
        if not file_path.exists():
            return results

        with open(file_path, "r") as f:
            for line in f:
                record = self.decrypt_line(line)
                if record is not None:
                    results.append(record)
        return results

    def read_lines_filtered(
        self, file_path: Path, filter_fn: Callable[[Dict[str, Any]], bool]
    ) -> List[Dict[str, Any]]:
        """Read, decrypt, and filter lines from a JSONL file."""
        results = []
        if not file_path.exists():
            return results

        with open(file_path, "r") as f:
            for line in f:
                record = self.decrypt_line(line)
                if record is not None and filter_fn(record):
                    results.append(record)
        return results


# Global singleton
_writer_instance: Optional[EncryptedJSONLWriter] = None


def get_encrypted_writer() -> EncryptedJSONLWriter:
    """Get or create global encrypted JSONL writer."""
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = EncryptedJSONLWriter()
    return _writer_instance
