"""Bounded local mesh refinement through EMerge's public API.

One refinement per public call lets EMerge release that call's field history.
The requested pass count is not a numerical convergence certificate.
"""
import gc


def refine_mesh(model, config, progress=print):
    passes = config['adaptive_steps']
    for index in range(passes):
        progress(f'Local mesh refinement {index + 1}/{passes}.', flush=True)
        previous_tets = model.mesh.n_tets
        model.adaptive_mesh_refinement(
            max_steps=2, minimum_steps=2, min_refined_passes=2, growth=0.2,
            convergence=config['convergence'], max_tets=config['max_tets'],
            frequency=(config['f_start_hz'] + config['f_stop_hz']) / 2,
            show_mesh=False)
        if model.mesh.n_tets > config['max_tets']:
            raise ValueError('Refined mesh exceeds the reviewed tetrahedron limit.')
        if model.mesh.n_tets <= previous_tets:
            raise ValueError('No finer mesh was produced. Review the tetrahedron budget and solver log before requesting more passes.')
        gc.collect()
    if passes:
        progress('Local refinement complete; response and boundary convergence still require independent checks.', flush=True)
