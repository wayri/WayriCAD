"""BOM validation for verified native project migration."""
from .migration import upgrade_copy

def upgrade_project_copy(selected,destination,*,cli=None,progress=None):
    """BOM entry point: publish only a hierarchy supported by native writeback."""
    from .native import Project
    def validate(root):
        status=Project(root).status()
        if not status['native_write_supported']:
            raise ValueError('Upgraded copy still requires annotation/hierarchy repair: '+
                             '; '.join(status['blockers'][:8]))
        # Legacy UUID grouping/instance paths changed. Retain the old workspace
        # for reference instead of silently applying its edits to new identities.
        sidecar=root.with_suffix('.wayricad-bom.json')
        archived=None
        if sidecar.exists():
            target=sidecar.with_name(sidecar.name+'.before-upgrade')
            if target.exists():raise ValueError('A previous workspace archive already exists; choose a clean source copy.')
            sidecar.rename(target);archived=target.name
        return {'native_write_supported':True,'components':status['components'],'files':status['files'],
                'archived_workspace':archived,
                'workspace_notice':'Prior workspace edits are preserved in the archive; review and reapply them to the upgraded copy.' if archived else ''}
    return upgrade_copy(selected,destination,cli=cli,validator=validate,progress=progress)
