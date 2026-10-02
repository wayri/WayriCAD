"""Reconstruct archived source bytes for verified adoption of older imports."""
from pathlib import Path
import hashlib
import json
import os
import zipfile
from . import sexpr as sx
from .model import SourceSpec, MergeError


def restore_source_backup(archive, alias, tempfolder):
    destination=Path(tempfolder).resolve()
    if destination.exists():
        raise MergeError('Archived source reconstruction requires a new folder.')
    with zipfile.ZipFile(archive) as package:
        names=package.namelist()
        if len(names)!=len(set(names)) or len(names)>60001:
            raise MergeError('Archive contains duplicate entries or exceeds the source-file limit.')
        if any(name.startswith(('/', '\\')) or '..' in name.replace('\\','/').split('/') or ':' in name for name in names):
            raise MergeError('Unsafe source archive member path.')
        if 'manifest.json' not in names:
            raise MergeError('Older import has no archived source provenance manifest.')
        if package.getinfo('manifest.json').file_size>32*1024**2:
            raise MergeError('Archived source manifest exceeds 32 MiB.')
        manifest=json.loads(package.read('manifest.json'))
        if not isinstance(manifest,list):
            raise MergeError('Invalid archived source manifest.')
        entries=[entry for entry in manifest if entry.get('source')==alias]
        if not entries:
            raise MergeError('Source alias has no archived provenance: '+alias)
        originals=[str(entry.get('original_path','')) for entry in entries]
        if any(not value or not Path(value).is_absolute() for value in originals) or len(originals)!=len(set(originals)):
            raise MergeError('Archived source paths are missing, relative or duplicated.')
        projects=[Path(value) for value in originals if value.lower().endswith('.kicad_pro')]
        if len(projects)!=1:
            raise MergeError('Archived source must contain exactly one unambiguous project root.')
        original_project=projects[0];root=original_project.parent
        mapping={};hashes={};payloads={};total=0
        for index,entry in enumerate(entries):
            original=Path(entry['original_path']);member=entry.get('archive_member','')
            if member not in names or not member.startswith(alias+'/'):
                raise MergeError('Archived source entry points outside its source namespace.')
            size=package.getinfo(member).file_size;total+=size
            if size>512*1024**2 or total>12*1024**3:
                raise MergeError('Archived reconstruction exceeds source resource limits.')
            data=package.read(member);digest=hashlib.sha256(data).hexdigest()
            if digest!=entry.get('sha256'):
                raise MergeError('Archived source hash mismatch: '+member)
            try:relative=original.relative_to(root)
            except ValueError:relative=Path('external')/f'{index:05d}'/original.name
            target=(destination/relative).resolve()
            if not target.is_relative_to(destination) or target in payloads:
                raise MergeError('Archived source paths collide or escape reconstruction.')
            mapping[str(original)]=str(target);hashes[str(original)]=digest;payloads[target]=data
        root_schematic=str(original_project.with_suffix('.kicad_sch'))
        if root_schematic not in mapping:
            raise MergeError('Archived source lacks its root schematic.')
        # Validate every sheet dependency before writing the reconstructed tree.
        parsed={}
        for original,target in mapping.items():
            if not original.lower().endswith('.kicad_sch'):
                continue
            tree=sx.loads(payloads[Path(target)].decode('utf-8-sig'))
            for sheet in sx.children(tree,'sheet'):
                field=sx.prop(sheet,'Sheetfile') or sx.prop(sheet,'Sheet file')
                if field is None:
                    raise MergeError('Archived schematic has a sheet without a file.')
                raw=str(field[2]).replace('${KIPRJMOD}',str(root))
                if '${' in raw:
                    raise MergeError('Archived external sheet path uses an unresolved variable.')
                dependency=Path(raw)
                if not dependency.is_absolute():dependency=Path(original).parent/dependency
                dependency=dependency.resolve()
                if str(dependency) not in mapping:
                    raise MergeError('Archived source lacks a referenced schematic: '+str(dependency))
                # Keep UUIDs and project-instance records intact; only file paths
                # move to the isolated reconstruction directory.
                field[2]=sx.q(os.path.relpath(mapping[str(dependency)],Path(target).parent).replace('\\','/'))
            parsed[Path(target)]=tree
        destination.mkdir(parents=True)
        for target,data in payloads.items():
            target.parent.mkdir(parents=True,exist_ok=True)
            if target in parsed:sx.save(target,parsed[target])
            else:target.write_bytes(data)
        project=Path(mapping[str(original_project)])
        spec=SourceSpec(str(project),alias,variant='<Default>',path_remaps=mapping)
        return {'spec':spec,'original_project':str(original_project),
                'original_filehashes':hashes,'restored_paths':mapping}
