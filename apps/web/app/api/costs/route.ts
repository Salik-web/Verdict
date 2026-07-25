// Server-side proxy for the pipeline's shared-secret cost endpoint.
//
// The browser cannot call GET /internal/costs directly: it's on the Python
// pipeline and guarded by x-internal-secret. This route runs server-side, holds
// the secret (never shipped to the browser), resolves the CALLER's accountId
// from their session (so you can't query another tenant by guessing an id), and
// forwards the pipeline's status + body verbatim.

export async function GET(req: Request): Promise<Response> {
  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000";
  const pipeUrl = process.env.PIPELINE_INTERNAL_URL ?? "http://localhost:8000";
  const secret = process.env.INTERNAL_SHARED_SECRET ?? "";
  const cookie = req.headers.get("cookie") ?? "";
  const days = new URL(req.url).searchParams.get("days") ?? "30";

  // 1. Who is calling? Resolve accountId from the session via the TS API.
  let accountId: string;
  try {
    const me = await fetch(`${apiBase}/auth/me`, { headers: { cookie } });
    if (!me.ok) {
      return Response.json(
        { error: "not authenticated to the API", status: me.status },
        { status: 401 },
      );
    }
    accountId = (await me.json()).accountId;
  } catch (e) {
    return Response.json(
      { error: `cannot reach API at ${apiBase}: ${String(e)}` },
      { status: 502 },
    );
  }

  // 2. Call the shared-secret cost endpoint on the pipeline, forward the result.
  try {
    const r = await fetch(
      `${pipeUrl}/internal/costs?account_id=${accountId}&days=${days}`,
      { headers: { "x-internal-secret": secret } },
    );
    const text = await r.text();
    return new Response(text, {
      status: r.status,
      headers: { "content-type": "application/json" },
    });
  } catch (e) {
    return Response.json(
      { error: `cannot reach pipeline at ${pipeUrl}: ${String(e)}` },
      { status: 502 },
    );
  }
}
