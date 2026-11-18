"""Equilibrated sparse thermal solves with checked backward error."""
import warnings


def solve_thermal_linear(matrix, rhs):
    import numpy as np
    from scipy.sparse import diags
    from scipy.sparse.linalg import splu

    diagonal = matrix.diagonal()
    if (not np.all(np.isfinite(matrix.data)) or not np.all(np.isfinite(rhs)) or
            not np.all(np.isfinite(diagonal)) or np.any(diagonal <= 0)):
        raise ValueError('Thermal matrix has nonfinite or unanchored conductances; review cooling and contacts.')
    # Congruence scaling preserves the network equations while reducing the
    # magnitude disparity between thin copper, dielectric and fixture paths.
    scale = 1 / np.sqrt(diagonal)
    scaling = diags(scale)
    balanced = (scaling @ matrix @ scaling).tocsc()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            factor = splu(balanced)
            solution = scale * factor.solve(scale * rhs)
            for _ in range(3):
                residual = rhs - matrix @ solution
                denominator = abs(matrix) @ abs(solution) + abs(rhs)
                error = np.max(abs(residual) / np.maximum(denominator, np.finfo(float).tiny))
                if np.all(np.isfinite(solution)) and np.isfinite(error) and error <= 1e-9:
                    return solution
                solution += scale * factor.solve(scale * residual)
    except (RuntimeError, RuntimeWarning) as exc:
        raise ValueError('Thermal matrix is singular or poorly conditioned; check disconnected '
                         'powered regions and fixture contact values.') from exc
    raise ValueError('Thermal linear residual exceeds tolerance; refine the model and review material/contact contrasts.')
