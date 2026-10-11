"""Use the operating system's certificate store for all HTTPS made from Python.

On machines where antivirus or a proxy re-signs TLS traffic, Python's bundled `certifi` CAs
reject the connection (CERTIFICATE_VERIFY_FAILED) while browsers and curl work. `truststore`
makes `ssl` use the OS store instead. It is a no-op on machines without interception.
Call once at the start of every entry point (API, scripts, frontend).
"""

_done = False


def use_system_certificates() -> None:
    global _done
    if _done:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:  # optional: fall back to certifi
        pass
    _done = True
