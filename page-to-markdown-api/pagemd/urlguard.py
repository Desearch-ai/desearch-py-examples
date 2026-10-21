"""Validate public page URLs with an injectable DNS resolver, without fetching a page."""
import ipaddress
import re
import socket
from urllib.parse import unquote, urlsplit, urlunsplit


class URLValidationError(ValueError):
    pass


class URLUnreachableError(URLValidationError):
    """A syntactically safe hostname could not be resolved."""


BINARY = re.compile(r'\.(pdf|zip|exe|dmg|png|jpe?g|gif|webp|svg|ico|mp4|mp3|iso|tar|gz|bz2|xz|7z|rar|wav|avi|mov|woff2?|ttf|bin|msi|apk|docx?|xlsx?|pptx?)/?$', re.I)


def validate_url(value, resolver=socket.getaddrinfo):
    """Return a normalized URL only when every resolved address is public."""
    def reject():
        raise URLValidationError('Enter a public http or https page URL, without a file download.')
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        reject()
    value = value.strip()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        reject()
    try:
        p = urlsplit(value)
        host = p.hostname
        if p.scheme.lower() not in ('http', 'https') or not host or p.username is not None or p.password is not None:
            reject()
        port_message = 'Only standard web ports are allowed (http on 80, https on 443).'
        try:
            port = p.port
        except ValueError:
            raise URLValidationError(port_message)
        default_port = 443 if p.scheme.lower() == 'https' else 80
        if p.netloc.endswith(':') or (port is not None and port != default_port):
            raise URLValidationError(port_message)
        host = host.rstrip('.').encode('idna').decode().lower()
        if '.' not in host or host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            reject()
        if len(host) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
            reject()
        # inet_aton recognizes legacy decimal, octal, hex and shortened IPv4 forms.
        try:
            socket.inet_aton(host)
        except OSError:
            pass
        else:
            reject()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            reject()
        if BINARY.search(unquote(p.path)):
            reject()
        try:
            addresses = resolver(host, default_port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise URLUnreachableError('Could not resolve hostname') from e
        if not addresses:
            raise URLUnreachableError('Could not resolve hostname')
        for record in addresses:
            ip = ipaddress.ip_address(record[4][0])
            if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, 'ipv4_mapped', None):
                reject()
        return urlunsplit((p.scheme.lower(), host, p.path.rstrip('/'), p.query, ''))
    except URLValidationError:
        raise
    except (ValueError, OSError, UnicodeError):
        reject()
