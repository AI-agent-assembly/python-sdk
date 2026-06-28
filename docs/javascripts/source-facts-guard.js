/*
  Suppress the GitHub "source facts" releases/latest 404 (AAASM-3880).

  Material for MkDocs fetches repository "source facts" — stars, forks and the
  latest GitHub Release tag — for any element marked data-md-component="source".
  This repository publishes no independent GitHub Releases (releases are coupled
  to the agent-assembly core tag), so
  GET https://api.github.com/repos/<owner>/<repo>/releases/latest returns 404 on
  every page load and the browser logs it to the console.

  AAASM-3785 already removes the source marker server-side, so freshly built
  pages issue no request at all. This is a defense-in-depth network guard: it
  short-circuits the releases/latest request before it leaves the browser, so
  the console 404 cannot resurface — including on the frozen /stable/ and
  /pre-release/ mike snapshots once they are next rebuilt and redeployed (those
  snapshots predate the marker removal). A real network 404 cannot be hidden
  from the console after the request is sent, so the request must be
  intercepted, not merely its response handled.

  The patch is installed synchronously at end-of-body, before Material's bundle
  issues the (post-DOMContentLoaded) source-facts fetch. Scope is deliberately
  narrow: only api.github.com .../releases/latest is intercepted and resolved
  with an empty JSON body (so Material renders no version badge); every other
  request — analytics, feedback, versions.json — passes straight through.
*/
(function () {
  var nativeFetch = window.fetch;
  if (typeof nativeFetch !== "function") {
    return;
  }

  var RELEASES_LATEST =
    /^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+\/releases\/latest$/;

  window.fetch = function (input, init) {
    var url =
      typeof input === "string"
        ? input
        : input && typeof input.url === "string"
          ? input.url
          : "";

    if (RELEASES_LATEST.test(url)) {
      // No coupled-repo release to report: hand Material an empty object so it
      // renders no version, without issuing the 404-producing request.
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
