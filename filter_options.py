"""Load actual labels from accessible parents linked to memos in the IC window.
No full-parent-object scan, guessed choice labels, metadata/file downloads or writes to DealCloud.
"""
from __future__ import annotations

FILTER_FIELDS = {
    'Primaries': [('Structure', []), ('AssetClass', []), ('Strategy', []), ('SubStrategy', [])],
    'CoInvestments': [('Structure Type', []), ('AssetClass', ['Private Equity']), ('Strategy', []), ('SubStrategy', []), ('Status', [])],
    'Secondaries': [('Structure', ['Secondary Transaction']), ('AssetClass', []), ('Strategy_1', []), ('SubStrategy', []), ('Status', [])],
}


def load_options(dc, engine, populations):
    if not populations or len(set(populations)) != len(populations) or any(p not in FILTER_FIELDS for p in populations):
        raise ValueError('Choose unique supported populations.')
    output = {}
    for population in populations:
        config = engine.POPULATION_CONFIG[population]
        try:
            print(f'Loading filter options: {population}', flush=True)
            _, raw = engine.read_windowed_memos(dc, config)
            available, unavailable = [], {}
            for field, _ in FILTER_FIELDS[population]:
                try:
                    engine.api_field_selection(dc, config['parent'], [field])
                    available.append(field)
                except KeyError:
                    unavailable[field] = 'Field not found in the accessible parent schema.'
            parents = engine.read_linked_parents(dc, config, raw,
                {field: ['__READ_FIELD_ONLY__'] for field in available})
            values = {}
            for field in available:
                column = engine.find_column(parents, [field])
                if column is None:
                    unavailable[field] = 'Field was requested but not returned by the parent read.'
                    continue
                labels = {label for cell in parents[column] for label in engine.human_values(cell) if label.strip()}
                values[field] = sorted(labels, key=lambda x: (x.casefold(), x))
            output[population] = {'values': values, 'unavailable': unavailable,
                                  'linked_parents': len(parents), 'memo_rows': len(raw)}
        except Exception as exc:
            output[population] = {'error': f'{type(exc).__name__}: {exc}'}
            print(f'Filter options failed for {population}: {type(exc).__name__}: {exc}', flush=True)
    return output
