"""Serve TLS and existing HTTP clients on the same LAN firewall port."""
import socket
import ssl
from http.server import ThreadingHTTPServer


class MeetingServer(ThreadingHTTPServer):
    def __init__(self, address, handler, state):
        self.tls = None
        certificate = state/'https'/'server.pem'
        if certificate.exists():
            self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.tls.minimum_version = ssl.TLSVersion.TLSv1_2
            self.tls.load_cert_chain(certificate, state/'https'/'server.key')
        super().__init__(address, handler)

    def finish_request(self, request, address):
        request.settimeout(15)
        if self.tls and request.recv(1, socket.MSG_PEEK) == b'\x16':
            try:
                with self.tls.wrap_socket(request, server_side=True) as secure:
                    super().finish_request(secure, address)
            except (ssl.SSLError, ConnectionError, TimeoutError):
                pass
        else:
            super().finish_request(request, address)
