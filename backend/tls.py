"""
AgentLens TLS Configuration — Built-in HTTPS support.

Instead of requiring nginx/Caddy as a reverse proxy, AgentLens can
terminate TLS directly using uvicorn's SSL support.

Setup:
  1. Generate or obtain SSL certificates
  2. Set environment variables:
     - AGENTLENS_TLS_CERT=/path/to/cert.pem
     - AGENTLENS_TLS_KEY=/path/to/key.pem
  3. Start normally: python run.py

For development, you can generate self-signed certs:
  python tls.py --generate-self-signed

For production, use Let's Encrypt or your organization's CA.
"""

import os
import sys
import logging
import argparse
import subprocess

logger = logging.getLogger("agentlens.tls")


def generate_self_signed_cert(output_dir: str = ".") -> tuple[str, str]:
    """Generate a self-signed TLS certificate for development.
    
    Uses the `cryptography` library if available, otherwise falls back to openssl CLI.
    Returns (cert_path, key_path).
    """
    cert_path = os.path.join(output_dir, "agentlens-cert.pem")
    key_path = os.path.join(output_dir, "agentlens-key.pem")

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        # Generate RSA key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Generate self-signed cert
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AgentLens Dev"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress_from_string("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        # Write key
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))

        # Write cert
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"Self-signed cert generated: {cert_path}, {key_path}")
        return cert_path, key_path

    except ImportError:
        logger.info("cryptography not available, trying openssl CLI...")

    # Fallback: use openssl CLI
    try:
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_path, "-out", cert_path,
            "-days", "365", "-nodes",
            "-subj", "/CN=localhost/O=AgentLens Dev",
        ], check=True, capture_output=True)
        logger.info(f"Self-signed cert generated via openssl: {cert_path}, {key_path}")
        return cert_path, key_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(
            "Cannot generate certificates. Install `cryptography` (pip install cryptography) "
            "or `openssl` CLI."
        )


def ipaddress_from_string(addr: str):
    """Helper to create IPv4Address for SAN."""
    import ipaddress
    return ipaddress.IPv4Address(addr)


def get_tls_config() -> dict:
    """Get TLS configuration from environment variables.
    
    Returns kwargs for uvicorn.run() if TLS is configured, empty dict otherwise.
    """
    cert = os.environ.get("AGENTLENS_TLS_CERT")
    key = os.environ.get("AGENTLENS_TLS_KEY")

    if cert and key:
        if not os.path.exists(cert):
            raise FileNotFoundError(f"TLS cert not found: {cert}")
        if not os.path.exists(key):
            raise FileNotFoundError(f"TLS key not found: {key}")

        logger.info(f"TLS enabled: cert={cert}")
        return {
            "ssl_certfile": cert,
            "ssl_keyfile": key,
        }

    return {}


def run_with_tls(host: str = "0.0.0.0", port: int = 8340):
    """Start AgentLens server with TLS support."""
    import uvicorn

    tls_config = get_tls_config()
    scheme = "https" if tls_config else "http"

    print(f"\n  AgentLens Server starting on {scheme}://{host}:{port}")
    if tls_config:
        print(f"  TLS cert: {tls_config['ssl_certfile']}")
    print(f"  Swagger UI: {scheme}://{host}:{port}/docs")
    print(f"  Dashboard:  {scheme}://{host}:{port}/dashboard\n")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        **tls_config,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentLens TLS Configuration")
    parser.add_argument("--generate-self-signed", action="store_true",
                        help="Generate self-signed TLS certificate for development")
    parser.add_argument("--output-dir", default=".", help="Output directory for certificates")
    parser.add_argument("--start", action="store_true", help="Start server with TLS")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8340)

    args = parser.parse_args()

    if args.generate_self_signed:
        cert, key = generate_self_signed_cert(args.output_dir)
        print(f"\nSelf-signed certificates generated:")
        print(f"  Cert: {cert}")
        print(f"  Key:  {key}")
        print(f"\nTo use them:")
        print(f"  set AGENTLENS_TLS_CERT={cert}")
        print(f"  set AGENTLENS_TLS_KEY={key}")
        print(f"  python tls.py --start")
    elif args.start:
        run_with_tls(args.host, args.port)
    else:
        parser.print_help()
