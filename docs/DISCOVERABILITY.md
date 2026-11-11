# WayriCAD Discoverability Maintenance

## Canonical Locations

| Resource | Maintained location |
|---|---|
| Product website | <https://wayri.github.io/wayricad/> |
| Source | <https://github.com/wayri/WayriCAD> |
| Downloads | <https://github.com/wayri/WayriCAD/releases/latest> |
| PCM feed | <https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json> |
| Website source | `wayri/wayri.github.io`: `wayricad.html` |
| Website tool descriptions and questions | `_data/wayricad.json` in the website repository |

The personal site uses Jekyll, `jekyll-seo-tag` and `jekyll-sitemap`. The product
layout already emits SEO metadata. Keep one canonical product URL; do not add a
parallel landing page, a second canonical tag or a competing full-site generator.
An unavailable `.html` URL is not the canonical permalink: use `/wayricad/`.

## Content Contract

- Explain actual engineering tasks: KiCad PCB fanout, via stitching, BOM editing,
  pin/harness documentation, PI/SI/thermal analysis, trace RLC and manufacturing
  review. Use natural language, not repeated keyword lists.
- Link product guides, installation, compatibility, runtime preparation, CLI and
  jobsets from useful visible sections. Important content must be present in
  rendered HTML without requiring JavaScript, login or an API request.
- Preserve one brand: WayriCAD. Mention “formerly KiWay” for legacy searches,
  not as another product. Do not fork installation instructions around old URLs.
- Separate development inventory from released packages. Derive counts from the
  relevant metadata/ref if a count is necessary. Prefer a stable catalogue
  anchor and release link over version/count text that quickly becomes stale.
- Show real screenshots with descriptive alt text, intrinsic dimensions and
  truthful captions. A geometry preview is not a solved field; a simulation is
  not a measurement. Retain attribution and sanitize private paths/board names.
- Keep title, concise description, canonical URL and social preview image
  accurate. Structured `SoftwareApplication` / `SoftwareSourceCode` metadata
  must agree with visible content. Never invent ratings, reviews, prices,
  certifications, download totals or supported platforms.

## Change Checklist

1. Read applicable guidance and dirty status in both repositories. Edit only
   owned page/data/style/script/test files; do not overwrite another task's
   template or source changes.
2. Compare the intended source/ref and latest published release. The local
   checkout may be older or contain unreleased work. Verify guide URLs before
   adding them; use the guide's actual filename/capitalization.
3. Update the existing product page and directory. Maintain a single entry per
   active tool and remove obsolete numbered catalogue anchors. Home/project
   cards should link to the canonical product page.
4. Run the website's focused Node tests. When Jekyll is available, build into a
   task-owned location with adequate disk reserve, then inspect the generated
   title, description, canonical, Open Graph, JSON-LD, robots and sitemap.
5. Check desktop/mobile rendering, images, keyboard navigation, directory
   filtering, empty results and clipboard failure. Do not install another
   runtime/browser just for a documentation change without checking storage.
6. Run `python tools/validate_docs.py --source-only` for repository doc changes.
   Report missing Jekyll/browser validation rather than presenting it as passed.
7. If publishing is requested, review/stage only scoped files, check remote
   changes, publish through the existing branch/workflow, then verify the live
   page. A local render, commit or push is not proof of deployment/indexing.

## Repository and Search Operations

The GitHub About homepage should point to the product URL rather than back to
its own README. A concise description and relevant GitHub topics can aid
discovery; preserve useful existing topics and verify inventory before stating
counts. Changing repository settings is separate from editing local source.

After a real deployment, verify `/wayricad/` and its images return successfully,
and that the generated sitemap includes the canonical URL. The site already
advertises its sitemap in `robots.txt`; do not replace it with a partial sitemap.
Search Console URL inspection/submission requires the site owner's verified
account. Do not claim that it was submitted or indexed without evidence.

SEO makes content easier to understand and discover; it does not guarantee
rankings or traffic. Record a baseline and review actual search performance
after deployment, rather than inventing a predicted improvement.

Primary references: [Google's SEO starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide),
[canonical URLs](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls),
and [Jekyll SEO Tag usage](https://github.com/jekyll/jekyll-seo-tag/blob/master/docs/usage.md).
