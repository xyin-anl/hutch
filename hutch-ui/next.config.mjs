/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Static-export so the daemon can serve the bundle from disk without
  // needing a Node runtime. All pages are Client Components, so no SSR is
  // required at runtime.
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // NEXT_PUBLIC_HUTCH_DAEMON_URL is only forwarded when the user sets it
  // (e.g. for `pnpm dev` against a daemon on a different origin). When unset
  // — including for production builds embedded inside the daemon — the UI
  // uses same-origin fetches, so the daemon's port doesn't have to be baked
  // into the bundle.
};

export default nextConfig;
