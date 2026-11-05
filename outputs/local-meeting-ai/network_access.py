"""LAN binding and authentication; loopback remains usable without a password."""
import base64
import hmac
import ipaddress
import json


class NetworkAccess:
    def __init__(self, root):
        path = root / 'state/network.json'
        self.config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        self.enabled = self.config.get('enabled', False)
        if self.enabled and not self.config.get('password'):
            raise ValueError('Для доступа по сети нужен пароль в state/network.json.')

    @property
    def bind(self): return '0.0.0.0' if self.enabled else '127.0.0.1'

    def valid_host(self, host, port):
        names = {'127.0.0.1', 'localhost'}
        if self.enabled: names.update(self.config.get('hosts', []))
        return host in {f'{name}:{port}' for name in names}

    def authorized(self, address, authorization):
        address = ipaddress.ip_address(address)
        if address.is_loopback: return True
        if not self.enabled or not any(address in ipaddress.ip_network(n) for n in self.config.get('networks', [])):
            return False
        try:
            scheme, encoded = (authorization or '').split(' ', 1)
            if scheme.lower() != 'basic': return False
            supplied = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError): return False
        expected = (self.config.get('username', 'meeting') + ':' + self.config['password']).encode()
        return hmac.compare_digest(supplied, expected)
