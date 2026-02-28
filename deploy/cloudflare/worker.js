/**
 * Cloudflare Worker - MediaCMS 视频代理
 *
 * 功能：
 *   1. 验证请求携带的 JWT（由 Django 颁发）
 *      - 优先从 URL 查询参数 ?token= 读取（HLS 分片场景）
 *      - 其次从 Authorization: Bearer <token> 读取
 *   2. 用 Worker 内置的 B2 密钥生成预签名 URL
 *   3. 代理 B2 视频流，支持 Range 请求（视频 seek）
 *   4. HLS m3u8 响应自动注入 ?token= 到所有相对 URI，实现无感刷新
 *
 * 环境变量（在 Cloudflare Dashboard → Worker → Settings → Variables 配置）：
 *   JWT_SECRET        - 与 Django SECRET_KEY 一致，或单独设置的共享密钥
 *   B2_KEY_ID         - B2 Application Key ID
 *   B2_APP_KEY        - B2 Application Key
 *   B2_BUCKET_NAME    - B2 私有桶名
 *   B2_ENDPOINT       - B2 S3 端点，如 s3.us-west-004.backblazeb2.com
 *   B2_REGION         - B2 区域，如 us-west-004
 *
 * 部署：
 *   wrangler deploy
 *   然后在 Django .env 中设置 CF_WORKER_BASE_URL 为此 Worker 地址
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ── 只代理 /media/ 路径 ──────────────────────────────────────────────────
    if (!url.pathname.startsWith('/media/')) {
      return new Response('Not Found', { status: 404 });
    }

    // ── CORS 预检 ────────────────────────────────────────────────────────────
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, HEAD',
          'Access-Control-Allow-Headers': 'Authorization, Range',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    // ── 验证 JWT ─────────────────────────────────────────────────────────────
    // 优先读 ?token= 参数（HLS m3u8/ts 分片场景），其次读 Authorization 头
    let token = url.searchParams.get('token') || null;
    if (!token) {
      const authHeader = request.headers.get('Authorization') || '';
      token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
    }

    if (!token) {
      return new Response('Unauthorized: missing token', { status: 401 });
    }

    const payload = await verifyJwt(token, env.JWT_SECRET);
    if (!payload) {
      return new Response('Unauthorized: invalid token', { status: 401 });
    }

    // ── 生成 B2 预签名 URL ───────────────────────────────────────────────────
    // url.pathname 形如 /media/encoded/1/user/abc.mp4
    const b2Key = url.pathname.slice('/media/'.length); // → encoded/1/user/abc.mp4

    let signedUrl;
    try {
      signedUrl = await generateB2PresignedUrl(b2Key, env);
    } catch (e) {
      return new Response(`B2 signing error: ${e.message}`, { status: 502 });
    }

    // ── 代理请求到 B2，透传 Range 头（支持视频 seek）────────────────────────
    const b2Request = new Request(signedUrl, {
      method: request.method,
      headers: {
        Range: request.headers.get('Range') || '',
      },
    });

    const b2Response = await fetch(b2Request);

    // 透传响应，追加 CORS 和缓存头
    const respHeaders = new Headers(b2Response.headers);
    respHeaders.set('Access-Control-Allow-Origin', '*');
    respHeaders.set('Cache-Control', 'private, max-age=3600');

    // ── HLS m3u8：重写相对 URI，注入 ?token= ─────────────────────────────────
    const isM3u8 = b2Key.endsWith('.m3u8');
    if (isM3u8 && b2Response.ok) {
      const bodyText = await b2Response.text();
      const rewritten = rewriteM3u8(bodyText, token);
      respHeaders.set('Content-Type', 'application/vnd.apple.mpegurl');
      respHeaders.delete('Content-Length');
      return new Response(rewritten, {
        status: b2Response.status,
        headers: respHeaders,
      });
    }

    return new Response(b2Response.body, {
      status: b2Response.status,
      headers: respHeaders,
    });
  },
};

// ── HLS m3u8 重写：为所有相对 URI 行追加 ?token= ────────────────────────────
function rewriteM3u8(text, token) {
  return text
    .split('\n')
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed) return line;
      // 处理含 URI="..." 的标签行（如 #EXT-X-KEY, #EXT-X-MAP）
      if (trimmed.startsWith('#') && trimmed.includes('URI="')) {
        return line.replace(/URI="([^"]+)"/g, (match, uri) => {
          if (uri.startsWith('http')) return match;
          const sep = uri.includes('?') ? '&' : '?';
          return `URI="${uri}${sep}token=${token}"`;
        });
      }
      // 普通注释行跳过
      if (trimmed.startsWith('#')) return line;
      // 普通 URI 行（相对路径：segment001.ts 或 video_720p/stream.m3u8）
      if (trimmed.startsWith('http')) return line; // 已是绝对 URL
      const sep = trimmed.includes('?') ? '&' : '?';
      return `${trimmed}${sep}token=${token}`;
    })
    .join('\n');
}

// ── JWT 验证（HS256）────────────────────────────────────────────────────────
async function verifyJwt(token, secret) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;

    const [headerB64, payloadB64, sigB64] = parts;
    const data = `${headerB64}.${payloadB64}`;

    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(secret),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify'],
    );

    const signature = base64UrlDecode(sigB64);
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      signature,
      new TextEncoder().encode(data),
    );

    if (!valid) return null;

    const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

    // 检查过期时间
    if (payload.exp && Date.now() / 1000 > payload.exp) return null;

    return payload;
  } catch {
    return null;
  }
}

function base64UrlDecode(str) {
  const base64 = str.replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// ── AWS SigV4 预签名 URL（B2 S3 兼容 API）──────────────────────────────────
async function generateB2PresignedUrl(key, env, expiresIn = 3600) {
  const region = env.B2_REGION;
  const bucket = env.B2_BUCKET_NAME;
  const host = env.B2_ENDPOINT; // e.g. s3.us-west-004.backblazeb2.com
  const accessKeyId = env.B2_KEY_ID;
  const secretKey = env.B2_APP_KEY;

  const now = new Date();
  const datestamp = now.toISOString().slice(0, 10).replace(/-/g, '');       // 20240101
  const amzdate = now.toISOString().replace(/[:-]/g, '').slice(0, 15) + 'Z'; // 20240101T000000Z

  const credentialScope = `${datestamp}/${region}/s3/aws4_request`;
  const credential = `${accessKeyId}/${credentialScope}`;

  const queryParams = new URLSearchParams({
    'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
    'X-Amz-Credential': credential,
    'X-Amz-Date': amzdate,
    'X-Amz-Expires': String(expiresIn),
    'X-Amz-SignedHeaders': 'host',
  });

  const canonicalUri = `/${key}`;
  const canonicalQueryString = queryParams.toString();
  const canonicalHeaders = `host:${host}\n`;
  const signedHeaders = 'host';
  const payloadHash = 'UNSIGNED-PAYLOAD';

  const canonicalRequest = [
    'GET',
    canonicalUri,
    canonicalQueryString,
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join('\n');

  const stringToSign = [
    'AWS4-HMAC-SHA256',
    amzdate,
    credentialScope,
    await sha256hex(canonicalRequest),
  ].join('\n');

  const signingKey = await getSigningKey(secretKey, datestamp, region, 's3');
  const signature = await hmacHex(signingKey, stringToSign);

  queryParams.set('X-Amz-Signature', signature);

  return `https://${host}/${bucket}/${key}?${queryParams.toString()}`;
}

async function sha256hex(message) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(message));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function hmacRaw(key, message) {
  const cryptoKey = await crypto.subtle.importKey(
    'raw', typeof key === 'string' ? new TextEncoder().encode(key) : key,
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  return crypto.subtle.sign('HMAC', cryptoKey, new TextEncoder().encode(message));
}

async function hmacHex(key, message) {
  const buf = await hmacRaw(key, message);
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function getSigningKey(secret, date, region, service) {
  const kDate = await hmacRaw(`AWS4${secret}`, date);
  const kRegion = await hmacRaw(kDate, region);
  const kService = await hmacRaw(kRegion, service);
  return hmacRaw(kService, 'aws4_request');
}
