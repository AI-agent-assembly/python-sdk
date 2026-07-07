/*
  Suppress the GitHub "source facts" api.github.com noise (AAASM-3880, AAASM-4286).

  Material for MkDocs fetches repository "source facts" — stars, forks and the
  latest GitHub Release tag — for any element marked data-md-component="source".
  It issues TWO unauthenticated calls to api.github.com per page load:

    1. GET https://api.github.com/repos/<owner>/<repo>/releases/latest
       → 404, because this repo publishes no independent GitHub Releases
         (releases are coupled to the agent-assembly core tag).
    2. GET https://api.github.com/repos/<owner>/<repo>
       → 403 unauthenticated rate-limit on shared/office IPs, which causes
         Material's source-facts handler to throw
         `TypeError: Failed to construct 'URL'` when it tries to parse the
         missing next-page Link header.

  AAASM-3785 already removes the source marker server-side, so freshly built
  pages issue no request at all. This is a defense-in-depth network guard: it
  short-circuits BOTH source-facts requests before they leave the browser, so
  neither the console 404 nor the 403/URL TypeError can resurface — including
  on the frozen /stable/ and /pre-release/ mike snapshots once they are next
  rebuilt and redeployed (those snapshots predate the marker removal). A real
  network 404/403 cannot be hidden from the console after the request is sent,
  so the request must be intercepted, not merely its response handled.

  The patch is installed synchronously at end-of-body, before Material's bundle
  issues the (post-DOMContentLoaded) source-facts fetches. Scope is deliberately
  narrow: only api.github.com .../repos/<owner>/<repo> and
  .../repos/<owner>/<repo>/releases/latest are intercepted and resolved with an
  empty JSON body (so Material renders no source-facts badge); every other
  request — analytics, feedback, versions.json — passes straight through.
*/
(function () {
  var nativeFetch = window.fetch;
  if (typeof nativeFetch !== "function") {
    return;
  }

  var SOURCE_FACTS_URL =
    /^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+(?:\/releases\/latest)?$/;

  window.fetch = function (input, init) {
    var url =
      typeof input === "string"
        ? input
        : input && typeof input.url === "string"
          ? input.url
          : "";

    if (SOURCE_FACTS_URL.test(url)) {
      // No coupled-repo release or repo metadata to report: hand Material an
      // empty object so it renders no source-facts badge, without issuing the
      // 404/403-producing requests.
      return Promise.resolve(
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }

    return nativeFetch.apply(this, arguments);
  };
})();
