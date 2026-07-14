/*
  Suppress the GitHub "source facts" api.github.com noise (AAASM-3880, AAASM-4286,
  AAASM-4318).

  Material for MkDocs fetches repository "source facts" — stars, forks and the
  latest GitHub Release tag — for any element marked data-md-component="source".
  It issues TWO unauthenticated calls to api.github.com per page load:

    1. GET https://api.github.com/repos/<owner>/<repo>/releases/latest
       → 404, because this repo publishes only pre-releases (0.0.1a4..0.0.1rc5,
         0.0.2); GitHub's /releases/latest endpoint excludes pre-releases and
         returns 404 when no non-prerelease exists. AAASM-4318 rewrites this
         request to /releases?per_page=1 and picks the newest so the badge can
         show the current pre-release tag rather than silently omitting.
    2. GET https://api.github.com/repos/<owner>/<repo>
       → 403 unauthenticated rate-limit on shared/office IPs, which causes
         Material's source-facts handler to throw
         `TypeError: Failed to construct 'URL'` when it tries to parse the
         missing next-page Link header. Still short-circuited with `{}`.

  AAASM-3785 already removes the source marker server-side, so freshly built
  pages issue no request at all. This is a defense-in-depth network guard: it
  intercepts BOTH source-facts requests before they leave the browser, so
  neither the console 404 nor the 403/URL TypeError can resurface — including
  on the frozen /stable/ and /pre-release/ mike snapshots once they are next
  rebuilt and redeployed (those snapshots predate the marker removal). A real
  network 404/403 cannot be hidden from the console after the request is sent,
  so the request must be intercepted, not merely its response handled.

  The patch is installed synchronously at end-of-body, before Material's bundle
  issues the (post-DOMContentLoaded) source-facts fetches. Scope is deliberately
  narrow: only api.github.com .../repos/<owner>/<repo> and
  .../repos/<owner>/<repo>/releases/latest are intercepted; every other request
  — analytics, feedback, versions.json — passes straight through.
*/
(function () {
  var nativeFetch = window.fetch;
  if (typeof nativeFetch !== "function") {
    return;
  }

  var LATEST_RELEASE_URL =
    /^(https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+)\/releases\/latest$/;
  var REPO_METADATA_URL =
    /^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+$/;

  var EMPTY_JSON = function () {
    return new Response("{}", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  window.fetch = function (input, init) {
    var url =
      typeof input === "string"
        ? input
        : input && typeof input.url === "string"
          ? input.url
          : "";

    var latestMatch = LATEST_RELEASE_URL.exec(url);
    if (latestMatch) {
      // /releases/latest 404s when the repo has only pre-releases. Rewrite the
      // request to /releases?per_page=1 and hand Material the newest release
      // (or `{}` if there are none, so no badge renders).
      return nativeFetch(latestMatch[1] + "/releases?per_page=1", init)
        .then(function (res) {
          if (!res || !res.ok) {
            return EMPTY_JSON();
          }
          return res.json().then(function (list) {
            var rel = list && list[0];
            if (!rel) {
              return EMPTY_JSON();
            }
            return new Response(JSON.stringify(rel), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            });
          });
        })
        .catch(EMPTY_JSON);
    }

    if (REPO_METADATA_URL.test(url)) {
      // Anonymous rate-limit on shared IPs still 403s; short-circuit to avoid
      // Material's Link-header TypeError. See AAASM-4286.
      return Promise.resolve(EMPTY_JSON());
    }

    return nativeFetch.apply(this, arguments);
  };
})();
