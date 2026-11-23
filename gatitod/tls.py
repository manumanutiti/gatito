#!/usr/bin/python3
"""HTTPS on the home network.

Gatito creates its own certificate authority (CA) once and, with it, a certificate for the
PC's IP and name. You install the CA on your phone (once) and the browser trusts
gatito: that way notifications work and the web UI is secure on the wifi.
If the PC's IP changes, the certificate is regenerated on startup (the CA is not).

Uses `cryptography` (the system's python3-cryptography package).
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import core
import hostinfo

DIR = core.STATE / 'tls'
CA_KEY, CA_CRT = DIR / 'ca.key', DIR / 'ca.crt'
KEY, CRT = DIR / 'server.key', DIR / 'server.crt'


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _save_key(path, key):
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def _load_key(path):
    return serialization.load_pem_private_key(path.read_bytes(), None)


def _ca():
    if CA_KEY.exists() and CA_CRT.exists():
        return _load_key(CA_KEY), x509.load_pem_x509_certificate(CA_CRT.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f'Gatito CA ({socket.gethostname()})')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(_now() - dt.timedelta(days=1))
            .not_valid_after(_now() + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(_limits(), critical=True)
            .sign(key, hashes.SHA256()))
    _save_key(CA_KEY, key)
    CA_CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def _limits() -> x509.NameConstraints:
    """A new CA is only valid for .local/localhost names and private IPs: a phone
    that trusts it is not exposed to it signing, e.g., a bank (if the key leaves
    this machine). CAs created earlier do not carry this and are left untouched."""
    networks = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', '127.0.0.0/8']
    return x509.NameConstraints(
        permitted_subtrees=[x509.DNSName('local'), x509.DNSName('localhost')]
        + [x509.IPAddress(ipaddress.ip_network(r)) for r in networks],
        excluded_subtrees=None)


def _inside(ca_cert, ips: list[str], names: list[str]) -> tuple[list[str], list[str]]:
    """With a constrained CA, only the names and IPs it admits (otherwise the phone
    would reject the whole certificate). Without constraints, everything."""
    try:
        nc = ca_cert.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return ips, names
    dns = [d.value.lower() for d in nc.permitted_subtrees or [] if isinstance(d, x509.DNSName)]
    networks = [d.value for d in nc.permitted_subtrees or [] if isinstance(d, x509.IPAddress)]
    names = [n for n in names if any(n.lower() == d or n.lower().endswith('.' + d) for d in dns)]
    ips = [i for i in ips if any(ipaddress.ip_address(i) in r for r in networks)]
    return ips, names


def _covers(cert, ips: list[str], names: list[str]) -> bool:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    have = {str(i) for i in san.get_values_for_type(x509.IPAddress)} | set(san.get_values_for_type(x509.DNSName))
    # cryptography < 42 has no not_valid_after_utc
    end = getattr(cert, 'not_valid_after_utc', None) or cert.not_valid_after.replace(tzinfo=dt.timezone.utc)
    fresh = end - _now() > dt.timedelta(days=30)
    return fresh and set(ips) | set(names) <= have


def ensure(ips: list[str]) -> tuple[str, str]:
    """Return the server's (certificate, key), creating them if needed."""
    DIR.mkdir(parents=True, exist_ok=True)
    host = socket.gethostname()
    names = sorted({'localhost', host, f'{host.split(".")[0]}.local', hostinfo.local_name()})
    ips = sorted(set(ips) | {'127.0.0.1'})
    ca_key, ca_cert = _ca()
    ips, names = _inside(ca_cert, ips, names)
    if CRT.exists() and KEY.exists():
        cur = x509.load_pem_x509_certificate(CRT.read_bytes())
        if _covers(cur, ips, names) and cur.issuer == ca_cert.subject:
            return str(CRT), str(KEY)
    key = ec.generate_private_key(ec.SECP256R1())
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f'gatito {host}')]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - dt.timedelta(days=1))
            .not_valid_after(_now() + dt.timedelta(days=820))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _save_key(KEY, key)
    CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(CRT), str(KEY)


def ca_der() -> bytes:
    """The CA in DER (.crt), the format Android and iOS install without complaint."""
    return x509.load_pem_x509_certificate(CA_CRT.read_bytes()).public_bytes(serialization.Encoding.DER)
