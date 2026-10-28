"""Import a bounded WayriCAD visualization bundle into Blender without solvers.

Run with Blender's Python: blender --background --python blender_import.py --
--scene scene.json --output visualization.blend [--render preview.png].
The script is self-contained so it can travel with an exported bundle. It does
not clear an existing scene or install executable frame-change handlers.
"""
from __future__ import annotations

import argparse
from array import array
import bisect
import json
import math
from pathlib import Path
import re
import sys
import textwrap


SCHEMA = 'wayricad.blender-scene/v1'
MAX_BYTES = 128 * 1024 * 1024
MAX_VERTICES = 400000
MAX_FACES = 200000
MAX_VALUES = 5000000
MAX_FRAMES = 1000
UNKNOWN = (0.48, 0.50, 0.53, 1.0)
PALETTE = ((0.267, 0.005, 0.329), (0.230, 0.322, 0.546),
           (0.128, 0.567, 0.551), (0.369, 0.789, 0.383),
           (0.993, 0.906, 0.144))


def _finite(value, label, *, optional=False):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number.')
    return float(value)


def validate_scene(document):
    """Check mesh indices, samples and storage budgets before touching Blender."""
    if not isinstance(document, dict) or document.get('schema') != SCHEMA:
        raise ValueError('Unsupported WayriCAD Blender scene schema.')
    objects = document.get('objects', [])
    traces = document.get('traces', [])
    if not isinstance(objects, list) or len(objects) > 10000 or not isinstance(traces, list) or len(traces) > 1000:
        raise ValueError('Scene object/trace count exceeds the supported budget.')
    vertices = faces = values = corners = 0
    animated_faces = animated_objects = 0
    timeline = set()
    for obj in objects:
        if not isinstance(obj, dict):
            raise ValueError('A scene object must be a mapping.')
        if not isinstance(obj.get('properties', {}), dict):
            raise ValueError('Object properties must be a mapping.')
        points, polygons = obj.get('vertices_mm'), obj.get('faces')
        if not isinstance(points, list) or not isinstance(polygons, list):
            raise ValueError('Scene meshes require vertices_mm and faces arrays.')
        vertices += len(points)
        faces += len(polygons)
        if vertices > MAX_VERTICES or faces > MAX_FACES:
            raise ValueError('Scene exceeds the geometry budget.')
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 3:
                raise ValueError('Each mesh vertex needs three millimetre coordinates.')
            if any(abs(_finite(v, 'Coordinate')) > 1000000 for v in point):
                raise ValueError('Coordinate exceeds the one-kilometre scene bound.')
        for face in polygons:
            if not isinstance(face, (list, tuple)) or not 3 <= len(face) <= 1024:
                raise ValueError('Each face needs 3–1024 vertex indices.')
            if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(points) for i in face):
                raise ValueError('Mesh face has an invalid vertex index.')
            corners += len(face)
            if corners > 1200000:
                raise ValueError('Scene exceeds 1.2 million mesh corners.')
        color = obj.get('color', [0.12, 0.32, 0.25, 1.0])
        if not isinstance(color, (list, tuple)) or len(color) != 4 or any(not 0 <= _finite(c, 'Color') <= 1 for c in color):
            raise ValueError('Object color must contain four values from zero to one.')
        field = obj.get('field')
        if field is None:
            continue
        if not isinstance(field, dict):
            raise ValueError('Field must be a mapping.')
        samples = [field.get('values')]
        frames = field.get('frames', [])
        if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
            raise ValueError('Too many field frames.')
        if frames:
            animated_faces += len(polygons)
            animated_objects += 1
        previous = -math.inf
        for frame in frames:
            if not isinstance(frame, dict):
                raise ValueError('Frame must be a mapping.')
            time = _finite(frame.get('time_s'), 'Frame time')
            if time < 0 or time <= previous:
                raise ValueError('Frame times must be nonnegative and strictly increasing.')
            previous = time
            timeline.add(time)
            samples.append(frame.get('values'))
        for sample in samples:
            if not isinstance(sample, list) or len(sample) != len(polygons):
                raise ValueError('Field samples must have one scalar per face.')
            values += len(sample)
            if values > MAX_VALUES:
                raise ValueError('Scene exceeds five million field/trace values.')
            for value in sample:
                _finite(value, 'Field value', optional=True)
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError('Trace must be a mapping.')
        times, data = trace.get('time_s'), trace.get('values')
        if not isinstance(times, list) or not isinstance(data, list) or len(times) != len(data):
            raise ValueError('Trace times and values must have equal length.')
        values += len(data)
        if values > MAX_VALUES:
            raise ValueError('Scene exceeds five million field/trace values.')
        previous = -math.inf
        for time, value in zip(times, data):
            time = _finite(time, 'Trace time')
            if time < 0 or time < previous:
                raise ValueError('Trace times must be nonnegative and nondecreasing; event sides may share a time.')
            previous = time
            _finite(value, 'Trace value', optional=True)
    if len(timeline) > MAX_FRAMES:
        raise ValueError('Combined field timeline exceeds 1000 stored states.')
    if len(timeline) * animated_faces > MAX_VALUES:
        raise ValueError('Combined texture animation exceeds five million face states.')
    if len(timeline) * animated_objects > 4096:
        raise ValueError('Animation exceeds 4096 atlas files; export fewer objects or stored states.')
    if not objects and not traces:
        raise ValueError('No visualization geometry or traces are available.')
    return sorted(timeline)


def scalar_range(field):
    """Use one scale across every stored frame, preserving unknown samples."""
    lo, hi = math.inf, -math.inf
    for sample in [field['values']] + [frame['values'] for frame in field.get('frames', [])]:
        for value in sample:
            if value is not None:
                lo = min(lo, value)
                hi = max(hi, value)
    return None if lo == math.inf else (lo, hi)


def field_key(field):
    """Keep physical quantities and units distinct when sharing color scales."""
    return str(field.get('name', 'Saved scalar')), str(field.get('unit', ''))


def shared_ranges(document):
    """Use one field/unit scale across objects and all their stored states.

    A constant-valued component must not receive the same midpoint color as a
    different-temperature component merely because both have zero local range.
    Unknown objects contribute no artificial zero to the common range.
    """
    result = {}
    for obj in document.get('objects', []):
        field = obj.get('field')
        if not field:
            continue
        key, limits = field_key(field), scalar_range(field)
        previous = result.get(key)
        if previous is None:
            result[key] = limits
        elif limits is not None:
            result[key] = min(previous[0], limits[0]), max(previous[1], limits[1])
    return result


def scalar_color(value, limits):
    """Map a saved scalar onto a fixed readable ramp; gray means unknown."""
    if value is None or limits is None:
        return UNKNOWN
    lo, hi = limits
    position = 0.5 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    position *= len(PALETTE) - 1
    index = min(int(position), len(PALETTE) - 2)
    fraction = position - index
    return tuple(PALETTE[index][c] * (1 - fraction) + PALETTE[index + 1][c] * fraction for c in range(3)) + (1.0,)


def held_sample(field, time):
    """Select an actual prior stored state; never interpolate simulation values."""
    frames = field.get('frames', [])
    index = bisect.bisect_right([row['time_s'] for row in frames], time) - 1
    return field['values'] if index < 0 else frames[index]['values']


def camera_scale(low, high, aspect=4 / 3):
    """Fit actual scene bounds without reserving an empty sidebar."""
    width = high[0] - low[0]
    height = high[1] - low[1]
    depth = high[2] - low[2]
    # Blender's horizontal sensor fit makes ortho_scale the frame width.
    return max(width, height * aspect, depth, 0.01) * 1.12


def object_group(row):
    """Keep component context and result geometry independently selectable."""
    properties = row.get('properties', {})
    if properties.get('reference') and properties.get('geometry_meaning'):
        return 'components'
    return 'fields' if row.get('field') else 'board'


def wire_envelope(row, tool):
    """Avoid hiding electrical fields behind illustrative component solids."""
    return (tool in {'pi', 'quick-pi', 'si', 'quick-si', 'signal-integrity'}
            and object_group(row) == 'components'
            and 'envelope' in str(row.get('properties', {}).get('geometry_meaning', '')).lower())


def _name(value, fallback='WayriCAD'):
    return str(value or fallback)[:160]


def _material(bpy, name, color=None, attribute=False, image=None, duration=1):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    if image is not None or attribute:
        shader = nodes.new('ShaderNodeEmission')
        shader.inputs['Strength'].default_value = 1.0
        source = nodes.new('ShaderNodeTexImage' if image is not None else 'ShaderNodeAttribute')
        if image is not None:
            source.image = image
            source.interpolation = 'Closest'
            source.extension = 'CLIP'
            source.image_user.frame_start = 1
            source.image_user.frame_duration = duration
            source.image_user.use_auto_refresh = True
            source.image_user.use_cyclic = False
        else:
            source.attribute_name = 'wayricad_scalar'
        material.node_tree.links.new(source.outputs['Color'], shader.inputs['Color'])
        material.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
    else:
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Roughness'].default_value = 0.62
        material.diffuse_color = color
        material.node_tree.links.new(shader.outputs['BSDF'], output.inputs['Surface'])
    return material


def _label(bpy, collection, text, location, size, name='Annotation'):
    data = bpy.data.curves.new(name, 'FONT')
    data.body = _name(text, '')
    data.size = size
    data.extrude = 0
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    material = bpy.data.materials.get('WayriCAD annotation ink')
    if material is None:
        material = bpy.data.materials.new('WayriCAD annotation ink')
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new('ShaderNodeOutputMaterial')
        shader = nodes.new('ShaderNodeEmission')
        shader.inputs['Color'].default_value = (0.015, 0.03, 0.045, 1)
        material.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
    data.materials.append(material)
    return obj


def _atlas(bpy, folder, prefix, samples, limits, face_count):
    """Bake texture frames so saved scenes animate without trusted Python code."""
    width = min(1024, max(1, face_count))
    height = max(1, math.ceil(face_count / width))
    folder.mkdir(parents=True, exist_ok=True)
    first = None
    for number, sample in enumerate(samples, 1):
        pixels = array('f', UNKNOWN * (width * height))
        for index, value in enumerate(sample):
            pixels[index * 4:index * 4 + 4] = array('f', scalar_color(value, limits))
        image = bpy.data.images.new(prefix + ' bake', width=width, height=height, alpha=False)
        image.colorspace_settings.name = 'sRGB'
        image.pixels.foreach_set(pixels)
        path = folder / (prefix + '-' + str(number).zfill(4) + '.png')
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)
        if first is None:
            first = path
    image = bpy.data.images.load(str(first), check_existing=False)
    image.source = 'SEQUENCE'
    return image, width, height


def _mesh(bpy, collection, row, index, timeline, texture_folder, scales):
    mesh = bpy.data.meshes.new(_name(row.get('name')))
    mesh.from_pydata([(p[0] * 0.001, -p[1] * 0.001, p[2] * 0.001) for p in row['vertices_mm']],
                     [], [tuple(reversed(face)) for face in row['faces']])
    mesh.update()
    obj = bpy.data.objects.new(_name(row.get('name')), mesh)
    collection.objects.link(obj)
    for key, value in row.get('properties', {}).items():
        if isinstance(value, (str, int, float, bool)):
            obj[_name(key)] = value[:1024] if isinstance(value, str) else value
    field = row.get('field')
    if not field:
        mesh.materials.append(_material(bpy, obj.name + ' material', row.get('color', [0.12, 0.32, 0.25, 1.0])))
        return obj, None
    local_limits = scalar_range(field)
    limits = scales[field_key(field)]
    obj['Field'] = _name(field.get('name'), 'Saved scalar')
    obj['Unit'] = _name(field.get('unit'), 'As recorded')
    obj['Unknown samples'] = 'Gray; not solved or not supplied'
    if local_limits:
        obj['Minimum'] = float(local_limits[0])
        obj['Maximum'] = float(local_limits[1])
    if limits:
        obj['Color scale minimum'] = float(limits[0])
        obj['Color scale maximum'] = float(limits[1])
    if field.get('frames') and timeline and row['faces']:
        samples = (held_sample(field, time) for time in timeline)
        image, width, height = _atlas(bpy, texture_folder, 'field-' + str(index).zfill(4), samples, limits, len(row['faces']))
        uv = mesh.uv_layers.new(name='Scalar atlas')
        for polygon in mesh.polygons:
            coordinate = ((polygon.index % width + 0.5) / width, (polygon.index // width + 0.5) / height)
            for loop_index in polygon.loop_indices:
                uv.data[loop_index].uv = coordinate
        mesh.materials.append(_material(bpy, obj.name + ' animated scalar', image=image, duration=len(timeline)))
    else:
        attribute = mesh.color_attributes.new(name='wayricad_scalar', type='FLOAT_COLOR', domain='CORNER')
        colors = array('f')
        for polygon in mesh.polygons:
            colors.extend(scalar_color(field['values'][polygon.index], limits) * len(polygon.loop_indices))
        attribute.data.foreach_set('color', colors)
        mesh.materials.append(_material(bpy, obj.name + ' scalar', attribute=True))
    return obj, limits


def _curve(bpy, collection, name, points, thickness, color):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = thickness
    data.bevel_resolution = 1
    spline = data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for vertex, point in zip(spline.points, points):
        vertex.co = (*point, 1)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    data.materials.append(_material(bpy, name + ' material', color))
    return obj


def import_scene(document, output, render=None):
    """Build a new collection and save a portable, interactive Blender scene."""
    timeline = validate_scene(document)
    import bpy
    from mathutils import Vector

    output = Path(output).resolve()
    if output.suffix.lower() != '.blend':
        raise ValueError('Output must end with .blend.')
    if output.exists():
        raise ValueError('Refusing to overwrite an existing Blender scene.')
    if not output.parent.is_dir():
        raise ValueError('Blender output directory must already exist.')
    if render is not None and Path(render).exists():
        raise ValueError('Refusing to overwrite an existing preview.')
    texture_folder = output.parent / (output.stem + '-textures')
    if texture_folder.exists():
        raise ValueError('Refusing to overwrite an existing texture directory.')
    # A separate scene prevents existing objects obscuring a millimetre-scale
    # board. Previous scenes and their objects remain intact in the blend file.
    scene = bpy.data.scenes.new(_name(document.get('title'), 'WayriCAD visualization'))
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    collection = bpy.data.collections.new(_name(document.get('title'), 'WayriCAD simulation'))
    scene.collection.children.link(collection)
    collection['Schema'] = SCHEMA
    collection['Tool'] = _name(document.get('tool'))
    collection['Coordinates'] = 'PCB mm (x, y, z) mapped to Blender metres (x, -y, z)'
    collection['Source'] = json.dumps(document.get('source', {}), ensure_ascii=True)[:8192]
    collection['Notes'] = '\n'.join(str(item) for item in document.get('notes', []))[:16000]
    collection['Animation'] = 'One Blender frame per stored time; held samples, no interpolated simulation values'
    groups = {}
    for key, name in (('fields', 'Simulation fields'),
                      ('board', 'Board context — saved geometry'),
                      ('components', 'Components — saved meshes and envelopes')):
        child = bpy.data.collections.new(name)
        collection.children.link(child)
        groups[key] = child
    groups['components']['Geometry'] = (
        'Saved meshes and declared footprint envelopes; inspect each object geometry_meaning. '
        'Envelope heights are illustrative and are not package solids.')
    groups['components']['Visibility'] = (
        'PI/SI envelopes default to viewport wireframe and are hidden from renders. '
        'Select an envelope and enable Show in Renders in Object visibility to include it. '
        'Toggle this collection in the Outliner to hide all component context.')
    meshes = []
    scales = shared_ranges(document)
    legend_rows = list(scales.items())
    for index, row in enumerate(document.get('objects', [])):
        obj, limits = _mesh(bpy, groups[object_group(row)], row, index, timeline, texture_folder, scales)
        if wire_envelope(row, document.get('tool')):
            obj.display_type = 'WIRE'
            obj.hide_render = True
        meshes.append(obj)
    coordinates = [vertex.co for obj in meshes for vertex in obj.data.vertices]
    if coordinates:
        low = Vector(tuple(min(p[i] for p in coordinates) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in coordinates) for i in range(3)))
    else:
        low, high = Vector((0, 0, 0)), Vector((0.12, 0.08, 0))
    extent = max(high.x - low.x, high.y - low.y, 0.02)
    text_size = extent * 0.028
    title_z = high.z + extent * 0.005
    title = '\n'.join(textwrap.wrap(str(document.get('title', 'WayriCAD simulation')), 70))
    _label(bpy, collection, title, (low.x, high.y + extent * 0.05, title_z), text_size * 1.1, 'Study title')
    y = low.y - extent * 0.055
    for (field, unit), limits in legend_rows[:24]:
        value = 'unknown' if limits is None else f'{limits[0]:.6g} to {limits[1]:.6g}'
        label = '\n'.join(textwrap.wrap(f'{field} [{unit}] {value}', 84))
        _label(bpy, collection, label, (low.x, y, title_z), text_size * 0.75, 'Field legend')
        y -= text_size * max(1, len(label.splitlines())) * 1.1
    _label(bpy, collection, 'Purple: lower / yellow: higher / gray: unknown',
           (low.x, y, title_z), text_size * 0.65, 'Scalar key')
    trace_origin = y - extent * 0.16
    for index, trace in enumerate(document.get('traces', [])):
        pairs = [(time, value) for time, value in zip(trace['time_s'], trace['values']) if value is not None]
        if len(pairs) < 2:
            continue
        tmin, tmax = pairs[0][0], pairs[-1][0]
        vmin, vmax = min(v for _, v in pairs), max(v for _, v in pairs)
        baseline = trace_origin - index * extent * 0.20
        # Separate null-delimited runs: missing values are not joined across gaps.
        runs = [[]]
        for time, value in zip(trace['time_s'], trace['values']):
            if value is None:
                if runs[-1]:
                    runs.append([])
                continue
            x = low.x + (0.5 if tmax == tmin else (time - tmin) / (tmax - tmin)) * extent
            height = 0.5 if vmax == vmin else (value - vmin) / (vmax - vmin)
            runs[-1].append((x, baseline + height * extent * 0.10, title_z))
        for run in runs:
            if len(run) > 1:
                _curve(bpy, collection, _name(trace.get('name'), 'Stored trace'), run, extent * 0.0006, (0.04, 0.55, 0.65, 1))
        _label(bpy, collection, f"{trace.get('name', 'Trace')} [{trace.get('unit', '')}] {vmin:.6g} to {vmax:.6g}; {tmin:.6g} to {tmax:.6g} s",
               (low.x, baseline - text_size, title_z), text_size * 0.65, 'Trace axes')
    # Text extents depend on glyphs, units and wrapping. Fit evaluated bounds
    # of what was actually added instead of estimating an oversized sidebar.
    bpy.context.view_layer.update()
    bounds = [obj.matrix_world @ Vector(corner)
              for obj in collection.all_objects if obj.type in {'MESH', 'FONT', 'CURVE'}
              for corner in obj.bound_box]
    if bounds:
        low = Vector(tuple(min(p[i] for p in bounds) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in bounds) for i in range(3)))
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'MILLIMETERS'
    scene.unit_settings.scale_length = 1.0
    scene.frame_start = 1
    scene.frame_end = max(1, len(timeline))
    scene.render.fps = 24
    for number, time in enumerate(timeline, 1):
        scene.timeline_markers.new(f't = {time:.9g} s (stored)', frame=number)
    if timeline:
        collection['Stored times / s'] = json.dumps(timeline)
    camera_data = bpy.data.cameras.new('WayriCAD inspection camera')
    camera = bpy.data.objects.new('WayriCAD inspection camera', camera_data)
    collection.objects.link(camera)
    center = (low + high) * 0.5
    span = max(high.x - low.x, high.y - low.y, extent)
    camera.location = center + Vector((0, -span * 0.35, span * 1.8))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.type = 'ORTHO'
    camera_data.sensor_fit = 'HORIZONTAL'
    camera_data.ortho_scale = camera_scale(low, high)
    camera_data.clip_start = 0.00001
    camera_data.clip_end = max(100, span * 10)
    scene.camera = camera
    light_data = bpy.data.lights.new('WayriCAD area light', 'AREA')
    light = bpy.data.objects.new('WayriCAD area light', light_data)
    collection.objects.link(light)
    light.location = center + Vector((0, 0, span * 2))
    light_data.energy = max(0.05, span * span * 35)
    light_data.shape = 'DISK'
    light_data.size = span * 3
    if scene.world is None:
        scene.world = bpy.data.worlds.new('WayriCAD background')
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get('Background')
    if background:
        background.inputs['Color'].default_value = (0.93, 0.96, 0.97, 1)
        background.inputs['Strength'].default_value = 0.8
    scene.render.engine = 'CYCLES'
    scene.render.use_stamp_filename = False
    scene.render.use_stamp_note = False
    scene.cycles.samples = 16
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = 'Standard'
    scene.frame_set(1)
    # Use relative texture paths so moving the complete bundle remains supported.
    for image in bpy.data.images:
        if image.source == 'SEQUENCE' and str(texture_folder) in image.filepath:
            image.filepath = '//'+texture_folder.name+'/'+Path(image.filepath).name
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'MATERIAL'
                region = area.spaces.active.region_3d
                region.view_location = center
                region.view_distance = span * 1.5
                region.view_rotation = camera.rotation_euler.to_quaternion()
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    if render is not None:
        scene.render.filepath = str(Path(render).resolve())
        scene.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True, scene=scene.name)
    return {'blend': str(output), 'objects': len(meshes), 'frames': len(timeline),
            'texture_directory': str(texture_folder) if texture_folder.exists() else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--render', type=Path)
    if argv is None:
        argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    try:
        if args.scene.stat().st_size > MAX_BYTES:
            raise ValueError('Scene JSON exceeds 128 MiB.')
        def reject(value):
            raise ValueError('Nonfinite JSON number: ' + value)
        document = json.loads(args.scene.read_text(encoding='utf-8-sig'), parse_constant=reject)
        print(json.dumps(import_scene(document, args.output, args.render), ensure_ascii=True))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print('WayriCAD Blender import failed: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
