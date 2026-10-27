// Placeholder image generator: a labelled SVG data URI per listing, so image
// treatment (crop, aspect, rounding, overlay, broken-image fallback) is judgeable
// with zero external requests. shortcut: one gradient per marketplace, no per-
// listing variation; upgrade to real photos when real API data is available.

const GRADS: Record<string, [string, string]> = {
  eBay: ["#f5c97b", "#e08b2c"],
  Facebook: ["#8ec5ff", "#3b6fd4"],
  OfferUp: ["#9be3c0", "#2f9e6f"],
};

export function img(listing: {
  marketplace: string;
  title: string;
  image_url: string | null;
}): string {
  if (listing.image_url === "") {
    // deliberate broken-image fixture: exercises the fallback treatment
    return "not-an-image://broken";
  }
  const [a, b] = GRADS[listing.marketplace] ?? ["#cfd4dd", "#8b93a3"];
  const word = listing.title.slice(0, 18).replace(/[<>&]/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/>
</linearGradient></defs>
<rect width="600" height="600" fill="url(#g)"/>
<text x="300" y="312" font-family="system-ui" font-size="44" fill="rgba(0,0,0,.38)" text-anchor="middle">${word}</text>
</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function brokenImgFallback(): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">
<rect width="600" height="600" fill="#3f3f46"/>
<text x="300" y="312" font-family="system-ui" font-size="40" fill="#a1a1aa" text-anchor="middle">no photo</text>
</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
