"""Lossless, self-contained PNG figures for analysis reports."""
from __future__ import annotations

import io


def optimize_png(data):
    """Keep every decoded pixel and its size; return no more than input bytes.

    Opaque alpha channels are redundant. An exact palette is used only when
    every RGB colour fits, without quantization or gradient approximation.
    """
    from PIL import Image
    with Image.open(io.BytesIO(data)) as source:
        if source.format != 'PNG':
            raise ValueError('Report raster optimization requires a PNG image.')
        source.load()
        save_options = {key: source.info[key] for key in ('dpi', 'icc_profile') if key in source.info}
        image = source.copy()
    candidates = [image]
    if image.mode == 'RGBA' and image.getextrema()[3] == (255, 255):
        image = image.convert('RGB')
        candidates.append(image)
    if image.mode == 'RGB' and 'transparency' not in image.info:
        colours = image.getcolors(maxcolors=256)
        if colours is not None:
            palette = sorted(colour for _, colour in colours)
            indices = {colour: index for index, colour in enumerate(palette)}
            indexed = Image.new('P', image.size)
            indexed.putpalette([channel for colour in palette for channel in colour])
            pixels = image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()
            indexed.putdata([indices[colour] for colour in pixels])
            image = indexed
            candidates.append(image)
    best = data
    for candidate in candidates:
        output = io.BytesIO()
        candidate.save(output, format='PNG', optimize=True, compress_level=9, **save_options)
        if output.tell() < len(best):
            best = output.getvalue()
    return best


def figure_png(figure, **save_options):
    """Save a Matplotlib figure without changing its DPI, extent or colours."""
    stream = io.BytesIO()
    figure.savefig(stream, format='png', **save_options)
    return optimize_png(stream.getvalue())
