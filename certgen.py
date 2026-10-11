import datetime, ipaddress, os, socket, sys

cert, key = "cert.pem", "key.pem"
if os.path.exists(cert) and os.path.exists(key) and "--force" not in sys.argv:
    sys.exit(0)


def _get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


LAN_IP = _get_lan_ip()

try:
    import subprocess
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", key, "-out", cert, "-days", "3650", "-nodes",
        "-subj", "/CN=localhost",
        "-addext", f"subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{LAN_IP}"],
        check=True, capture_output=True)
    print("Certificate generated via openssl")
    sys.exit(0)
except Exception:
    pass

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    k = rsa.generate_private_key(65537, 2048)
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    c = (x509.CertificateBuilder()
        .subject_name(n).issuer_name(n)
        .public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address(LAN_IP)),
        ]), False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(k, hashes.SHA256()))
    with open(key, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(cert, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.PEM))
    print("Certificate generated via Python")
except ImportError:
    print("WARNING: openssl not found, skipping certificate generation")
    print("  The server will fall back to HTTP (microphone unavailable)")
    print("  Install openssl or 'pip install cryptography' to generate a certificate")
    sys.exit(1)
