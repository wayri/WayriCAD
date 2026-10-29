# WayriCAD 3.6.45

This release adds Quick EMerge as an independently installable **beta / testing**
plugin, plus Review conversations and project-local simulation saves.

- **Quick EMerge (beta):** antenna templates and bounded saved-PCB rule-area
  studies, native field inspection and probes, denser sampling, HTML/PDF reports
  and KiCad-specific offline Help / F1. See its [scope and validation](../quick_emerge_plugin/VALIDATION.md).
  Beta results are exploratory; compatibility checks do not certify numerical
  convergence, hardware performance or general multilayer/component extraction.
- **Review (testing):** message cards, replies, formatted drafts, GitHub/GitLab
  comments and a separate GitHub Discussions tab. Existing CLI sessions are
  verified before use; confirmed rejected GitLab sessions have an explicit
  reconnect flow. GitLab supports pasted image uploads; GitHub attachments use
  its browser editor. [Guide](../review_comments_plugin/README.md).
- **Simulation library:** Quick PI, Quick SI and QuickTherm can save complete
  numerical JSON in deterministic project-local files and reopen supported
  plots, probes and thermal frames without solving again. Matching, stale and
  unverified source states stay explicit. [Guide](PROJECT_RESULTS.md).
- **Portable results:** complete analysis exports retain original values and
  source bindings for supported Pocket KiView / KiCad GitHub viewer workflows.
  [Formats and limits](POCKET_KIVI_EXPORT.md).
- **All tools:** selected rows remain readable in light and dark themes, and
  search discovers independently installed Review/EMerge desktop launchers.
  Restart PCB Editor after updating the shared launcher.

The saved-board All tools route uses the originating editor's saved file. It
neither invents an IPC connection nor reads unsaved editor changes. Native
platform checks and numerical evidence are distinct from headless CI.
