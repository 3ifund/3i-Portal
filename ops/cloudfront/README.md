# CloudFront edge-auth JWT — single source of truth

The portal issues HS256 JWTs at `/auth/login`. Three consumers must validate them
with the **same** signing secret:

1. **Portal backend** — `JWT_SECRET` in `3i-portal-backend/.env` (signs + validates at origin).
2. **CloudFront function** `validate-data-management-jwt` — viewer-request auth on `/data-management/*`.
3. **CloudFront function** `validate-position-risk-management-jwt` — viewer-request auth on `/position_risk_management/*`.

Both functions are attached to distribution **E15RA0YW10O89Y** (`3ifundportal.com`) and
reject requests at the edge (401) before they reach the origin. If any of the three drifts,
that app breaks with `401 {"detail":"Invalid signature"}` even though the token is otherwise valid.
This happened on 2026-07-13: the PRM function had been published with an unfilled placeholder
secret, taking down all of Position Risk Management until the secret was corrected.

## Canonical source

The one true value lives in **AWS SSM Parameter Store** as a `SecureString`:

```
/3i-portal/jwt-secret        (region us-east-1, KMS-encrypted)
```

The two `*.template.js` files here are the **version-controlled source** of the functions.
`JWT_SECRET` in them is the literal placeholder `__JWT_SECRET__`; `sync-edge-jwt.ps1` substitutes
the SSM value at publish time. **Never** hand-edit the secret in the AWS console — that is exactly
what drifts.

## One-time setup

1. **Create the SSM parameter** seeded with the current production secret (the value already in
   the backend `.env`):

   ```powershell
   aws ssm put-parameter --name /3i-portal/jwt-secret --type SecureString `
     --value "<the JWT_SECRET from 3i-portal-backend/.env>" --region us-east-1
   ```

2. **Grant the CI runner role (`3i-Portal-GithubRunner`) read access** so the drift check can run:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       { "Effect": "Allow", "Action": ["ssm:GetParameter"], "Resource": "arn:aws:ssm:us-east-1:839629613662:parameter/3i-portal/jwt-secret" },
       { "Effect": "Allow", "Action": ["kms:Decrypt"], "Resource": "*" },
       { "Effect": "Allow", "Action": ["cloudfront:GetFunction"], "Resource": "arn:aws:cloudfront::839629613662:function/*" }
     ]
   }
   ```

   For `-Mode Apply` (manual publishing) also grant `cloudfront:DescribeFunction`,
   `cloudfront:UpdateFunction`, `cloudfront:PublishFunction` on the same function resource.

3. **Verify the templates match the live functions** before ever applying:

   ```powershell
   ./sync-edge-jwt.ps1 -Mode Export        # writes *.live.js next to the templates
   # diff each *.live.js against its *.template.js — they should differ only on the JWT_SECRET line
   ```

## Drift check (CI gate)

`.github/workflows/jwt-secret-drift-check.yml` runs `sync-edge-jwt.ps1 -Mode Check` every 6 hours,
on `workflow_dispatch`, and on pushes that touch this folder. It compares the SSM value against the
backend `.env` and both LIVE functions and **fails the job on any mismatch**. It prints a SHA-256
fingerprint per source, never the secret itself, so CI logs stay clean.

Run it locally any time:

```powershell
./sync-edge-jwt.ps1 -Mode Check
```

## Rotating the secret

1. Put the new value in SSM: `aws ssm put-parameter --name /3i-portal/jwt-secret --type SecureString --value "<new>" --overwrite --region us-east-1`
2. Update the backend to match and restart it (or set `JWT_SECRET` in `.env` from SSM at deploy — see below).
3. Publish both edge functions: `./sync-edge-jwt.ps1 -Mode Apply`
4. Confirm: `./sync-edge-jwt.ps1 -Mode Check` → `ALIGNED`.

Rotation invalidates every existing token, so all users re-login once. Do it in a maintenance window.

## Optional: source the backend `.env` from SSM at deploy

To make the backend track the canonical value automatically, add this step to
`.github/workflows/backend-deploy.yml` **before** the service restart (requires the same
`ssm:GetParameter` + `kms:Decrypt` read perms):

```powershell
$secret = aws ssm get-parameter --name /3i-portal/jwt-secret --with-decryption --region us-east-1 --query Parameter.Value --output text
$envPath = "C:\portal\3i-Portal\3i-portal-backend\.env"
$lines = Get-Content $envPath | Where-Object { $_ -notmatch '^\s*JWT_SECRET\s*=' }
($lines + "JWT_SECRET=$secret") | Set-Content -Path $envPath -Encoding utf8
```
