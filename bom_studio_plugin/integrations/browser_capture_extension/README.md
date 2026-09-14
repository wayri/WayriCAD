# Optional WayriCAD evidence capture extension — 0.3.0 preview

Chrome / Edge: open the Extensions management page, enable Developer mode, select **Load unpacked**, then select this folder. This is a local unsigned extension, not a Chrome Web Store release.

Open an ordinary DigiKey or Mouser **single-product detail page** in your browser. Click the extension, then **Read this product page**. Review every populated value against the visible page, correct errors, enter the market (`IN` for India), and leave unknown numeric quantities blank. A generic "in stock" label is not a quantity. Save the reviewed JSON and import it in WayriCAD → Supplier evidence → Import. A second explicit import review is required there.

Permissions: `activeTab` and `scripting` only. No persistent host access, service worker, cookies, login capture, external requests, automatic page navigation, proxies or CAPTCHA circumvention. The extension reads public Product structured data and visible two-column attribute rows on the product page you authorize. It never extracts carts, account pages or BOM result lists. It does not submit orders or modify the supplier page. No credentials are requested.

Current limits: site markup varies by country and changes over time. Product fields often need manual correction. Numeric inventory may be absent; manual entry or supplier-table import is the fallback. The capture parser is tested on controlled HTML fixtures; actual DigiKey/Mouser production-page extraction and Chrome/Edge extension-host operation require target-system testing. Respect each website's applicable terms; this feature is user-initiated data capture, not permission to crawl a distributor. No live availability guarantee or authenticity certificate is created by clicking Reviewed.
