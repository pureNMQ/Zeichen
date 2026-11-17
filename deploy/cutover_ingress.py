"""Temporary maintenance gates for the shared Zeichen ingress."""

import re


HTTP = "# ---------- HTTP:ACME"
MOCHI = "# ---------- 个人站 ----------"
ZEICHEN = "# ---------- 贼船 Zeichen ----------"
FALLBACK = "# ---------- 兜底:"


def gate(config: str, *, probes: bool) -> str:
    """Close both Zeichen listeners without changing ACME, Mochi, or fallback."""
    for marker in (HTTP, MOCHI, ZEICHEN, FALLBACK):
        if config.count(marker) != 1:
            raise RuntimeError("unrecognized shared ingress layout")
    http, mochi, zeichen, fallback = (config.index(label) for label in (HTTP, MOCHI, ZEICHEN, FALLBACK))
    if not http < mochi < zeichen < fallback:
        raise RuntimeError("unexpected shared listener order")
    http_block = config[http:mochi]
    tls_block = config[zeichen:fallback]
    for location, upstream in (("/api/", "api:8000"), ("/mcp", "mcp:8000")):
        pattern = re.compile(
            rf"(?ms)^(    location {re.escape(location)} \{{\r?\n)(.*?)(^    \}})"
        )
        matches = list(pattern.finditer(http_block))
        if len(matches) != 1 or f"proxy_pass http://{upstream}" not in matches[0][2]:
            raise RuntimeError(f"unrecognized Zeichen HTTP location {location}")
        match = matches[0]
        newline = "\r\n" if match[1].endswith("\r\n") else "\n"
        http_block = http_block[:match.start(2)] + "        return 503;" + newline + http_block[match.end(2):]
    if len(re.findall(r"(?m)^server \{", tls_block)) != 1 or not re.search(
        r"(?m)^    server_name zeichen\.mochigm\.cn;\r?$", tls_block
    ):
        raise RuntimeError("unrecognized Zeichen TLS listener")
    opening = re.search(r"(?m)^    location ", tls_block)
    if opening is None:
        raise RuntimeError("missing Zeichen TLS locations")
    if probes:
        restrictions = (
            '    if ($request_method !~ "^(GET|HEAD)$") { return 503; }\n'
            '    if ($uri !~ "^(/|/api/health|/[.]well-known/oauth-protected-resource/mcp)$") { return 503; }\n'
        )
        tls_block = tls_block[:opening.start()] + restrictions + tls_block[opening.start():]
    else:
        tls_block = tls_block[:opening.start()] + "    add_header Retry-After 120 always;\n    return 503;\n}\n\n"
    return config[:http] + http_block + config[mochi:zeichen] + tls_block + config[fallback:]
