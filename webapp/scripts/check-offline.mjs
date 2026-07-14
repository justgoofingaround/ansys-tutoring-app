// Fails if the production bundle references any external URL — the app must
// run with zero network egress (NYU LAN / FERPA requirement).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist", import.meta.url));

// Inert strings, not network requests: React embeds error-decoder doc links in
// its production error messages, and Tailwind leaves a banner comment. Nothing
// is ever fetched from these.
const ALLOWED = ["reactjs.org", "react.dev", "tailwindcss.com", "www.w3.org"];
const offenders = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(js|css|html)$/.test(name)) {
      const text = readFileSync(p, "utf8");
      const matches = text.match(/https?:\/\/[a-z0-9.-]+/gi) ?? [];
      for (const m of matches) {
        const host = m.replace(/^https?:\/\//i, "");
        if (!ALLOWED.some((a) => host === a || host.endsWith("." + a))) {
          offenders.push(`${name}: ${m}`);
        }
      }
    }
  }
}

try {
  walk(dist);
} catch {
  console.error("dist/ not found — run `npm run build` first");
  process.exit(2);
}

if (offenders.length) {
  console.error("External URLs found in bundle:\n" + [...new Set(offenders)].join("\n"));
  process.exit(1);
}
console.log("offline check passed — no external URLs in dist/");
