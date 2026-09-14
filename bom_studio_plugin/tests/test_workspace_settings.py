"""Editable native settings: persisted workspace, undo and CLI export contracts."""
from copy import deepcopy
import json
from unittest.mock import patch
import test_nativefirst_interfaces as interfaces
from bomstudio import nativefirst as nf
from bomstudio.engine import Workspace
from bomstudio.native import Project


class WorkspaceSettings(interfaces.NativeFirstInterfaces):
    def settings(self):
        c = nf.context(self.ws)
        result = deepcopy({'bom_settings': c['preset'], 'bom_fmt_settings': c['format']})
        result['bom_settings'].update(fields_ordered=[
            {'name':'Reference', 'label':'Designators', 'show':True, 'group_by':False},
            {'name':'Value', 'label':'Part value', 'show':True, 'group_by':True},
            {'name':'Footprint', 'label':'Package', 'show':False, 'group_by':True},
        ], group_symbols=True, exclude_dnp=True, sort_field='Value', sort_asc=False, filter_string='R*')
        result['bom_fmt_settings'].update(field_delimiter=';', ref_range_delimiter='~')
        return result

    def test_edit_columns_groups_and_format_survive_save(self):
        before = self.path.read_bytes()
        code, raw = self.request('bom-format/configure', {'settings': self.settings()})
        self.assertEqual(code, 200, raw)
        self.ws.save()
        options = nf.inherited_options(Workspace(Project(self.path)))
        self.assertEqual(options['fields'], ['Reference', 'Value'])
        self.assertEqual(options['labels'], ['Designators', 'Part value'])
        self.assertEqual(options['group_by'], ['Value', 'Footprint'])
        self.assertEqual(options['field_delimiter'], ';')
        self.assertFalse(options['sort_asc'])
        self.assertTrue(options['exclude_dnp'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_settings_auth_and_validation_leave_state_unchanged(self):
        before = self.ws._serialize()
        self.assertEqual(self.request('bom-format/configure', {'settings': self.settings()}, False)[0], 401)
        invalid = self.settings()
        for column in invalid['bom_settings']['fields_ordered']:
            column['show'] = False
        self.assertEqual(self.request('bom-format/configure', {'settings': invalid})[0], 400)
        self.assertEqual(self.ws._serialize(), before)

    def test_settings_undo_restores_original_authority(self):
        before = nf.inherited_options(self.ws)
        nf.configure_export(self.ws, self.settings())
        self.ws.undo()
        self.assertEqual(nf.inherited_options(self.ws), before)

    def test_cli_configure_persists_and_drives_native_export(self):
        config = self.dir / 'bom-settings.json'
        config.write_text(json.dumps(self.settings()), encoding='utf-8')
        code, _, err = self.call('bom-format', 'configure', self.path, '--config', config)
        self.assertEqual(code, 0, err)
        with patch('bomstudio.nativebom.generate', return_value={'data':b'Designators;Part value\r\n', 'notice':'contract'}) as generate:
            code, _, err = self.call('export', self.path, '--format', 'csv', '--acknowledge-saved-only', '--output', self.dir/'configured.csv')
        self.assertEqual(code, 0, err)
        self.assertEqual(generate.call_args.args[1]['group_by'], ['Value', 'Footprint'])
        self.assertEqual(generate.call_args.args[1]['field_delimiter'], ';')

    def test_corrupt_saved_settings_rejected_on_load(self):
        self.ws.save()
        state = json.loads(self.ws.sidecar.read_text(encoding='utf-8'))
        state['native_export_settings'] = {'bom_settings':{}, 'bom_fmt_settings':{}}
        self.ws.sidecar.write_text(json.dumps(state), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'native columns'):
            Workspace(Project(self.path))
