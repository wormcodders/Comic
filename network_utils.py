"""Bounded outbound HTTP with DNS pinning and redirect validation."""

import time
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter

from security_utils import UnsafeURLError, resolve_safe_url


class PinnedAddressAdapter(HTTPAdapter):
    """Connect to a vetted IP while checking TLS against the original hostname."""

    def __init__(self, parsed_url, address):
        self.hostname = parsed_url.hostname
        self.address = address
        self.scheme = parsed_url.scheme
        self.port = parsed_url.port or (443 if self.scheme == 'https' else 80)
        super().__init__(max_retries=0)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        host_params, pool_kwargs = self.build_connection_pool_key_attributes(request, verify, cert)
        host_params['host'] = self.address
        if self.scheme == 'https':
            pool_kwargs.update(assert_hostname=self.hostname, server_hostname=self.hostname)
        return self.poolmanager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)


def safe_request(method, url, *, max_bytes=1024 * 1024, timeout=30, allow_local=False, require_https=False, **kwargs):
    """Return a fully buffered Response after closing the socket and session.

    GET redirects are vetted individually. Credential-bearing POSTs never follow
    redirects. Environment proxies/netrc and shared cookies are deliberately unused.
    """
    method = method.upper()
    deadline = time.monotonic() + timeout
    for redirect_count in range(4):
        parsed, addresses = resolve_safe_url(url, allow_local=allow_local)
        if require_https and parsed.scheme != 'https':
            raise UnsafeURLError('HTTPS is required for credential-bearing requests')
        hostname = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
        if parsed.port is not None:
            hostname += f':{parsed.port}'
        headers = dict(kwargs.get('headers') or {})
        headers['Host'] = hostname
        request_kwargs = {**kwargs, 'headers': headers}
        with requests.Session() as session:
            session.trust_env = False
            adapter = PinnedAddressAdapter(parsed, addresses[0])
            session.mount(parsed.scheme + '://', adapter)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout('Remote request exceeded its time limit')
            with session.request(method, url, allow_redirects=False, stream=True,
                                 timeout=(min(10, remaining), min(30, remaining)), **request_kwargs) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    if method != 'GET' or redirect_count == 3 or not response.headers.get('Location'):
                        raise UnsafeURLError('Remote redirect is not permitted')
                    url = urljoin(url, response.headers['Location'])
                    continue
                length = response.headers.get('Content-Length')
                if length and length.isdecimal() and int(length) > max_bytes:
                    raise ValueError('Remote response exceeds the size limit')
                payload = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if time.monotonic() > deadline:
                        raise requests.Timeout('Remote request exceeded its time limit')
                    payload.extend(chunk)
                    if len(payload) > max_bytes:
                        raise ValueError('Remote response exceeds the size limit')
                response._content = bytes(payload)
                response._content_consumed = True
                return response
    raise UnsafeURLError('Too many remote redirects')


def download_remote_file(url, *, max_bytes=50 * 1024 * 1024, timeout=120):
    response = safe_request('GET', url, max_bytes=max_bytes, timeout=timeout)
    response.raise_for_status()
    if not response.content:
        raise ValueError('Remote file is empty')
    return response.content
