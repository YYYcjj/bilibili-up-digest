export async function onRequest(context) {
  const { request } = context;
  const u = new URL(request.url);
  const t = u.searchParams.get('url');
  if (!t) return new Response('Missing url', { status: 400 });
  const h = new Headers();
  const c = request.headers.get('Cookie');
  if (c) h.set('Cookie', c);
  h.set('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36');
  h.set('Referer', 'https://www.bilibili.com/');
  const r = await fetch(decodeURIComponent(t), { method: request.method, headers: h });
  const rh = new Headers(r.headers);
  rh.set('Access-Control-Allow-Origin', '*');
  rh.set('Access-Control-Allow-Headers', '*');
  rh.set('Access-Control-Expose-Headers', 'Set-Cookie');
  return new Response(r.body, { status: r.status, headers: rh });
}
