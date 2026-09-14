# Synthetic analytics example

Every rate, mass, power, temperature and part number is fictional demonstration data. This is not an electrically validated circuit or a qualified part database. C3 intentionally has no mass observation; R4 has an unknown maximum temperature and is DNP. J1 has a deliberately low 70 C maximum for threshold demonstrations.

Open a temporary copy using `TRY_ANALYTICS_SAMPLE_WINDOWS.bat`, or `sh ./start_bom_studio.sh --analytics-demo`. In the app, choose **Cost, mass & power → Run analytics**. The launcher preloads this example profile into the temporary workspace. No original project is changed.

From the plugin folder, read-only CLI examples:

```sh
python cli.py analytics examples/analytics/BOM_Demo.kicad_pro --config examples/analytics/analytics-config.json --format xlsx --output /absolute/path/new-analytics.xlsx
python cli.py threshold examples/analytics/BOM_Demo.kicad_pro --field Temp_Max --condition "<80" --unit C --rows
python cli.py run examples/analytics/BOM_Demo.kicad_pro --config examples/analytics/pipeline-analytics.json --output-dir /absolute/path/new-run
```

Output parents must exist and outputs must not already exist. The strict pipeline intentionally fails on the missing mass (exit 3) and publishes diagnostic reports, not BOM exports. The default advisory pipeline does not treat the analytics report as engineering approval.

`report_examples/` contains generated snapshot outputs. Their provenance includes build-container paths; these are documentation samples, not hashes of files on your computer. Re-run after copying this example to obtain local provenance. The native fixture was generated/reloaded through WayriCAD's parser, not validated inside KiCad.
