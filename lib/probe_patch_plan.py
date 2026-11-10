"""Conservative, opt-in kernel patch plans for non-installing USB probes.

The production installer always uses the full patch plan.  These variations
exist solely to isolate early boot failures before any filesystem writes.
"""

PROBE_VARIANTS = ('stock-kernel', 'lean-kernel')
LEAN_PREFIXES = ('kernel.amfi.trust-cache.', 'kernel.amfi.launch-constraints.')


def select_kernel_records(records, variant):
    """Return a diagnostic subset, refusing unknown variants."""
    if variant == 'full':
        return list(records)
    if variant == 'stock-kernel':
        return []
    if variant == 'lean-kernel':
        selected = [record for record in records
                    if record['id'].startswith(LEAN_PREFIXES)]
        if not selected:
            raise ValueError('lean-kernel selected zero AMFI records; refusing to build')
        return selected
    raise ValueError(f'unsupported kernel patch plan: {variant}')
