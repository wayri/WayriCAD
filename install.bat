@echo off
setlocal
set "ROOT=%~dp0"
set "DEST=%APPDATA%\kicad\10.0\scripting\plugins"

echo KiWay Suite local installer
echo Destination: %DEST%
if not exist "%DEST%" mkdir "%DEST%"

for %%P in (
  bulk_label_editor_plugin
  extract_pins_plugin
  fanout_generator_plugin
  harness_workbench_plugin
  heater_designer_plugin
  kilo_plugin
  manufacturing_readiness_plugin
  pdn_decoupling_plugin
  planar_magnetics_plugin
  portable_assets_plugin
  protocol_constraint_composer_plugin
  return_path_auditor_plugin
  signal_integrity_advisor_plugin
  test_point_descriptor_plugin
  trace_impedance_plugin
  variant_workbench_plugin
  via_stitching_plugin
) do (
  echo Installing %%P...
  if exist "%ROOT%%%P" (
    if exist "%DEST%\%%P" rmdir /s /q "%DEST%\%%P"
    xcopy /e /i /q /y "%ROOT%%%P" "%DEST%\%%P" >nul
    if errorlevel 1 exit /b 1
  ) else (
    echo   Skipping %%P - not found in repository.
  )
)

echo.
echo Installed all KiWay packages.
echo Restart PCB Editor, then use Tools ^> External Plugins.
echo Use KiWay Interboard ^& Harness ^> Dependencies... for dependency checks.
exit /b 0
