// ─────────────────────────────────────────────────────────────────────────
// CloudFront Function — JWT validator for /data-management/*
//
// Attached at the viewer-request stage of the /data-management/* behavior on
// the 3ifundportal.com distribution (E15RA0YW10O89Y).
//
// Sibling of validate-position-risk-management-jwt — same HS256 signing secret
// (portal's JWT_SECRET from /auth/login), same role=admin contract. The only
// differences are the path prefix and the WWW-Authenticate realm. A single
// Portal login issues a token that works in both apps.
//
// SOURCE OF TRUTH: this file is the version-controlled source of the function.
// JWT_SECRET is a build-time placeholder (__JWT_SECRET__) that sync-edge-jwt.ps1
// substitutes from the SSM SecureString /3i-portal/jwt-secret before publishing.
// Never hand-edit the secret in the AWS console — rotate via the sync script so
// the backend and both edge functions stay aligned.
//
// NOTE: reconstructed from the position-risk-management sibling. Before the first
// `sync-edge-jwt.ps1 -Mode Apply`, run `-Mode Export` and diff this against the
// live function to confirm they are byte-identical apart from the secret.
//
// Logic:
//   1. Static files under /data-management/* pass through.
//   2. Only /data-management/api/* requires auth.
//   3. Auth = "Authorization: Bearer <jwt>" with HS256 signature matching
//      JWT_SECRET, exp in the future, and role == "admin".
//   4. On any failure, return 401 immediately (no origin round-trip).
// ─────────────────────────────────────────────────────────────────────────

import crypto from 'crypto';

var JWT_SECRET = "__JWT_SECRET__";

var REQUIRED_ROLE = 'admin';

function b64urlToB64(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    return s;
}

function decodePayload(b64url) {
    return JSON.parse(atob(b64urlToB64(b64url)));
}

function expectedSignature(headerB64, payloadB64) {
    var input = headerB64 + '.' + payloadB64;
    var b64 = crypto.createHmac('sha256', JWT_SECRET).update(input).digest('base64');
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function deny(reason) {
    return {
        statusCode: 401,
        statusDescription: 'Unauthorized',
        headers: {
            'content-type': { value: 'application/json' },
            'cache-control': { value: 'no-store' },
            'www-authenticate': { value: 'Bearer realm="data-management"' }
        },
        body: JSON.stringify({ error: 'Unauthorized', detail: reason })
    };
}

function handler(event) {
    var request = event.request;

    if (request.uri.indexOf('/data-management/api/') !== 0) {
        return request;
    }

    var headers = request.headers;
    var auth = headers['authorization'];
    if (!auth || !auth.value) return deny('Missing Authorization header');
    if (auth.value.indexOf('Bearer ') !== 0) return deny('Invalid auth scheme');

    var parts = auth.value.substring(7).split('.');
    if (parts.length !== 3) return deny('Malformed JWT');

    if (expectedSignature(parts[0], parts[1]) !== parts[2]) {
        return deny('Invalid signature');
    }

    var payload;
    try {
        payload = decodePayload(parts[1]);
    } catch (e) {
        return deny('Malformed payload');
    }

    var now = Math.floor(Date.now() / 1000);
    if (typeof payload.exp !== 'number' || payload.exp < now) {
        return deny('Token expired');
    }

    if (payload.role !== REQUIRED_ROLE) {
        return deny('Admin role required');
    }

    return request;
}
