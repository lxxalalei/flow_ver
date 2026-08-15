# Login Workflow Reference

## Turn boundary

```text
status → guide → open official login URL → ask for “已登录” → END TURN
user says “已登录” → verify official tab → capture (see below) → immediate save → status/probe
```

For cookie platforms the capture step is one `resource_session_capture_browser` call: the MCP reads
the managed browser's full cookie store over the local CDP endpoint (httpOnly included) and saves it
server-side, so credential values never transit the conversation and cannot be truncated by model
output limits. The relayed broad capture below remains for storage platforms and as the cookie
fallback when the managed browser's CDP endpoint is genuinely unavailable (then use the browser
cookie capability — never `document.cookie`, which cannot see httpOnly login cookies).

Browser observations never replace the explicit confirmation. Each platform in a multi-platform run
has its own confirmation gate.

An alternative branch exists only when the user voluntarily supplies a legally obtained canonical
Cookie/Token, names the supported platform and purpose, and explicitly authorizes saving:

```text
status/platform check → one immediate canonical save → status/probe
```

Do not solicit the value, combine this branch with browser capture, or automatically replay an
uncertain save.

## Broad capture contract

The browser/Skill may submit all cookies returned by the controlled browser context. For a storage
platform it may additionally submit every Web Storage entry visible to the active official origin:

```json
{
  "cookies": [
    {
      "name": "<browser-returned-name>",
      "value": "<browser-returned-value>",
      "domain": ".example.com",
      "path": "/",
      "expires": 1800000000,
      "httpOnly": true,
      "secure": true,
      "sameSite": "Lax",
      "priority": "High"
    }
  ],
  "storage_origin": "https://official-origin.example",
  "local_storage": {
    "<browser-returned-key>": "<browser-returned-string-value>"
  },
  "session_storage": {
    "<browser-returned-key>": "<browser-returned-string-value>"
  }
}
```

All values are placeholders. Web Storage values are strings; JSON remains a string and is parsed only
inside the platform extractor. `storage_origin` must be the active page's `location.origin`, not a URL
invented from platform metadata.

Canonical direct-import inputs remain supported:

```json
{"cookies": ["<cookie objects>"]}
```

```json
{"tokens": {"accessToken": "<already normalized value>"}}
```

Use them only with the user's explicit platform-, purpose-, and save-specific authorization. Do not
accept arbitrary headers, files, browser profiles, account passwords, CAPTCHA/MFA material, or unknown
fields, and do not combine direct import with a browser capture.

## Server-side extraction

The Skill does not prefilter browser data. The MCP:

- enforces total size and count limits;
- accepts only HTTP(S) storage origins and checks true DNS-label boundaries;
- filters Cookie domains to the selected platform;
- drops expired/out-of-scope Cookies and browser-only metadata;
- applies constrained platform storage-key and Cookie-name patterns;
- normalizes the selected credential into the platform's canonical session shape;
- persists only that canonical minimum, never the raw cookie/storage dump;
- returns counts and metadata without credential values.

For SmartEdu, dynamic storage extraction is limited to the configured official domain and the
constrained `ND_UC_AUTH-...&ncet-xedu&token` key family. Its JSON may contain a nested
`access_token`; the MCP normalizes it to canonical `tokens.accessToken`. Unrelated profile fields,
refresh tokens, storage keys, and Cookies are discarded. A constrained `UC_TOKEN-...-ncet-xedu`
Cookie may be used only as the server's fallback when storage yielded no access token.

## Status interpretation

| Local status | Probe status | Meaning | Next action |
|---|---|---|---|
| `missing` | `no_probe` | No saved session | Login if required |
| `expired` | `no_probe` | Local expiry passed | Re-login |
| `invalid` | `no_probe` | Local record unusable | Re-login |
| `stored` | `valid` | Local record exists and remote accepted it | Report confirmation |
| `stored` | `no_probe` | Local record exists; remote not checked/unsupported | State limitation |
| `stored` | `probe_error` | Local record exists; remote check inconclusive | Preserve, retry later |
| `stored` | `invalid` | Remote rejected the session | Offer one re-login |
| `not_required` | `not_required` | Public platform | Do not open login |

Only `probe_status=valid` is remote confirmation.

## Safe recovery

### No platform credential extracted

For browser capture, keep or reopen the official login page, ask the user to finish any redirect/consent
step, and require one new “已登录” before recapturing. Do not solicit a Cookie/Token or broaden server
patterns ad hoc. For direct import, stop without replaying or asking the user to resend; read status and
require fresh explicit authorization before any later write.

### Matching storage record is malformed or conflicting

The MCP returns `SESSION_PAYLOAD_INVALID` without the value. For browser capture only, retry once from
a freshly loaded official page; persistent failure requires an extractor update. For direct import,
read status and stop without replaying or asking the user to resend; any later write requires fresh
explicit authorization. Never print the raw submitted value for debugging in chat.

### Save succeeds but the probe is invalid

Treat the remote result as authoritative. Offer one clean re-login and stop after a second invalid
result.

### Secure storage unavailable

Stop whether the failure occurs during status, guide, save, delete, or post-save status. Native
Windows requires current-user DPAPI. Never fall back to a plaintext file or ask the user to resend
credentials.

## Credential-channel limitation

Browser-captured and explicitly authorized direct-import values still cross Agent/MCP arguments. They
must go only to the immediate save call and must never be narrated, logged, or forwarded. This is not
equivalent to an opaque host-side capture channel.
