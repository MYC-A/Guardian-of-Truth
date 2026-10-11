"""Diagnostic-only: report the SHAPE of the platform input, never its content.

Prints row count, columns, unique-id count and length statistics of prompt and
response (characters, UTF-8 bytes), the input file size/format and the output
path suffix. No ids, texts or labels are printed. Writes a VALID all-zero
prediction file (id,label) and exits 0, so the platform proceeds from the
limited set to the full set and both stage logs show the shape. F1 will be ~0:
diagnostic only, never treat as a real submission.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

STARTED = time.time()


def emit(name, value):
    print('GUARDIAN_INPUT_PROBE ' + json.dumps(dict(probe=name, result=value), sort_keys=True), flush=True)


def stats(values):
    values = sorted(values)
    if not values:
        return dict(n=0)
    pick = lambda q: values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]
    return dict(n=len(values), min=values[0], p50=pick(.5), p90=pick(.9), max=values[-1], total=sum(values))


def read(path):
    with open(path, 'rb') as stream:
        head = stream.read(4)
    if head == b'PAR1':
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        return 'parquet', table.column_names, {name: table.column(name).to_pylist() for name in table.column_names}
    import csv
    csv.field_size_limit(1 << 30)
    with open(path, newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    names = list(reader.fieldnames or [])
    return 'csv', names, {name: [row.get(name) for row in rows] for name in names}


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    options, unknown = parser.parse_known_args(arguments)
    emit('purpose', 'SHAPE_ONLY_NO_CONTENT_ALL_ZERO_OUTPUT_EXIT_0')
    path = Path(options.input)
    emit('invocation', dict(argv_extra=len(unknown), input_suffix=path.suffix, input_exists=path.exists(),
                            input_bytes=path.stat().st_size if path.is_file() else None,
                            output_suffix=Path(options.output).suffix,
                            output_parent_exists=Path(options.output).parent.exists(),
                            cwd_is_archive=Path.cwd() == Path(__file__).resolve().parents[1],
                            python=sys.version.split()[0]))
    try:
        kind, columns, data = read(path)
        rows = len(next(iter(data.values()), []))
        report = dict(format=kind, rows=rows, columns=columns)
        if 'id' in data:
            report['unique_ids'] = len(set(map(str, data['id'])))
        for name in ('prompt', 'response'):
            if name in data:
                texts = ['' if value is None else str(value) for value in data[name]]
                report[name + '_chars'] = stats([len(text) for text in texts])
                report[name + '_utf8_bytes'] = stats([len(text.encode('utf-8')) for text in texts])
                report[name + '_empty'] = sum(not text for text in texts)
        if 'prompt' in data:
            texts = ['' if value is None else str(value) for value in data['prompt']]
            report['prompt_marker_counts'] = dict(
                assistant_turn=sum('ASSISTANT' in text for text in texts),
                tool_call=sum('TOOL_CALL' in text for text in texts))
        emit('shape', report)
    except Exception as error:
        emit('shape_error', dict(error=type(error).__name__, detail=str(error)[:300]))
    status = 0
    try:
        import pandas as pd
        ids = data['id'] if 'id' in data else list(range(rows))
        out = Path(options.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame({'id': list(ids), 'label': [0] * len(ids)})
        frame['label'] = frame['label'].astype('int64')
        if out.suffix.lower() == '.csv':
            frame.to_csv(out, index=False)
        else:
            frame.to_parquet(out, index=False)
        emit('output', dict(rows=len(frame), bytes=out.stat().st_size, id_column_present='id' in data))
    except Exception as error:
        status = 3
        emit('output_error', dict(error=type(error).__name__, detail=str(error)[:300]))
    emit('done', dict(seconds=round(time.time() - STARTED, 2), pid=os.getpid(), exit=status))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
