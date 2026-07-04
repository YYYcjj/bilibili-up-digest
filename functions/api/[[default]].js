/**
 * B站UP主视频速览 - Cloudflare Pages Functions
 * CORS 代理：转发所有请求到 B站，并返回跨域响应
 */

export async function onRequest(context) {
  const { request } = context;
  const url = new URL(request.url);
  
  // 提取目标 URL
  const targetUrl = url.searchParams.get('url');
  if (!targetUrl) {
    return new Response('Missing url param', { status: 400 });
  }
  
  // 构建转发请求头
  const headers = new Headers();
  const clientCookie = request.headers.get('Cookie');
  if (clientCookie) headers.set('Cookie', clientCookie);
  headers.set('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36');
  headers.set('Referer', 'https://www.bilibili.com/');
  
  // 转发请求
  const resp = await fetch(decodeURIComponent(targetUrl), {
    method: request.method,
    headers,
    body: request.method === 'POST' ? await request.text() : undefined
  });
  
  // 构建响应头，添加 CORS
  const responseHeaders = new Headers(resp.headers);
  responseHeaders.set('Access-Control-Allow-Origin', '*');
  responseHeaders.set('Access-Control-Allow-Headers', '*');
  responseHeaders.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  responseHeaders.set('Access-Control-Expose-Headers', 'Set-Cookie');
  
  return new Response(resp.body, { status: resp.status, headers: responseHeaders });
}
