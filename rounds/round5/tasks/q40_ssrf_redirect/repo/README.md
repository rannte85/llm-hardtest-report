# Outbound SSRF redirect incident

`SafeHttpClient` fetches an untrusted absolute URL through injected DNS and HTTPS
transport adapters. It returns response bytes or raises `FetchError`.

The API is:

```python
SafeHttpClient(resolver, transport, max_redirects=5,
               max_body_bytes=1_048_576).get(url, headers=None)
```

- `resolver(host, port)` returns IP-address strings;
- `transport(ip, port, server_name, target, headers)` connects to the supplied
  numeric IP while preserving `server_name` for TLS SNI/Host authority, and returns
  `{"status": int, "headers": [(name, value), ...], "body": iterable_of_bytes}`;
- `headers` is an optional string-to-string mapping. The client owns `Host`.

Only absolute HTTPS URLs without credentials or fragments are allowed. Normalize DNS
hostnames with IDNA and one optional trailing dot. Resolve every hop exactly once,
reject an empty answer or any answer containing a non-global IPv4/IPv6 address
(including IPv4-mapped IPv6 and zone identifiers), then pin one approved numeric IP
into `transport`; the transport must never receive a hostname as its connection
address.

Follow only 301/302/303/307/308 with exactly one non-empty `Location`, resolve relative
locations, reapply the full URL/DNS policy before each network call, reject normalized
redirect loops, and allow at most `max_redirects` redirects. Strip `Authorization` and
`Cookie` on any origin change. Redirect bodies are not consumed.

Accept only final 2xx responses. Header names are ASCII tokens and values may not
contain CR/LF. Reject conflicting duplicate `Content-Length`; fail before reading when
its valid decimal value exceeds the limit. Otherwise stream byte chunks and stop as
soon as their total exceeds `max_body_bytes`. Invalid inputs, headers, DNS results, or
responses must not trigger a later transport call. Proxy configuration and certificate
verification are responsibilities of the injected transport.
