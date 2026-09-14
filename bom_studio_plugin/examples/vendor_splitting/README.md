# Fictional vendor-split demonstration

The synthetic DEMO MPNs and SKUs are not production parts. Do not place orders using this data.

From the installed plugin directory:

```powershell
py -3 .\cli.py vendors .\examples\vendor_splitting\BOM_Demo.kicad_pro --config .\examples\vendor_splitting\vendor-config.json --format zip --output .\example-vendor-boms.zip
```

Open a copy of this sample in WayriCAD to try vendor routing. Native-first BOM formatting remains unchanged. Three capacitor occurrences route to Mouser and other fitted parts to DigiKey; R4 is DNP. At 10 boards plus 5% attrition with compatible identities pooled, review the generated installed/required/order quantities. CSV and XLSX encode the same demand; they are alternatives, not separate orders. No API, quote or stock data is included.
