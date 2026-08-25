export function requireSameOrigin(request: Request): void {
  const origin = request.headers.get("origin");
  const requestUrl = new URL(request.url);
  const forwardedHost = request.headers.get("x-forwarded-host")?.split(",")[0]?.trim();
  const host = forwardedHost || request.headers.get("host");
  const forwardedProtocol = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const protocol = forwardedProtocol || requestUrl.protocol.replace(":", "");
  const publicOrigin = host ? `${protocol}://${host}` : requestUrl.origin;
  if (!origin || (origin !== requestUrl.origin && origin !== publicOrigin)) {
    throw new Error("Invalid request origin");
  }
}
