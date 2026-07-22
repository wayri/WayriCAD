@echo off
setlocal
set "ROOT=%~dp0"
set "DEST=%APPDATA%\kicad\10.0\scripting\plugins"

echo KiWay Suite v2.10.0 local installer
echo Destination: %DEST%
if not exist "%DEST%" mkdir "%DEST%"

for %%P in (
  bulk_label_editor_plugin
  connector_icd_plugin
  extract_pins_plugin
  fanout_generator_plugin
  net_hygiene_plugin
  test_coverage_plugin
  test_point_descriptor_plugin
  trace_impedance_plugin
  via_stitching_plugin
) do (
  echo Installing %%P...
  if exist "%DEST%\%%P" rmdir /s /q "%DEST%\%%P"
  xcopy /e /i /q /y "%ROOT%%%P" "%DEST%\%%P" >nul
  if errorlevel 1 exit /b 1
)

echo.
echo Installed all nine KiWay packages.
echo Restart PCB Editor, then use Tools ^> External Plugins.
echo Use KiWay Interboard ^& Harness ^> Dependencies... for dependency checks.
exit /b 0
