// Cloudflare Web Analytics beacon: cookieless, no cross-site identifiers.
// Only on the deployed host, so dev servers and local previews aren't counted.
// The site token is public by design (it ships in every page). The CSP in
// _headers allows the beacon script and the host it reports to.

const HOST = "fdarecall.worksonmybench.dev";
const TOKEN = "9f5009455677487ea043da109658e0f2";

if (location.hostname === HOST) {
  const script = document.createElement("script");
  script.defer = true;
  script.src = "https://static.cloudflareinsights.com/beacon.min.js";
  script.dataset.cfBeacon = JSON.stringify({ token: TOKEN });
  document.head.append(script);
}
