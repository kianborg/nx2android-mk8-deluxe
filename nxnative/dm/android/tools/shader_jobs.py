"""Bounded translator batches, with progress and retained failure diagnostics."""
import concurrent.futures as cf
import json
from pathlib import Path
import re
import subprocess
import threading
import time


def translate(jobs, command, work, workers, timeout=600, report=print, batch_size=16):
    if workers < 1 or timeout <= 0 or batch_size < 1:
        raise ValueError('shader workers, timeout and batch size must be positive')
    work = Path(work)
    keys = list(jobs)
    if not keys:
        raise RuntimeError('no shaders selected for translation')
    chunks = [keys[i:i + batch_size] for i in range(0, len(keys), batch_size)]
    stop = threading.Event()

    def run(index, chunk):
        job_file = work / f'job_{index}.json'
        log_file = work / f'job_{index}.log'
        job_file.write_text(json.dumps([jobs[k] for k in chunk]), encoding='utf-8')
        started = time.monotonic()
        with log_file.open('w', encoding='utf-8') as log:
            proc = subprocess.Popen([*map(str, command), str(job_file), str(work)],
                                    stdout=log, stderr=subprocess.STDOUT)
            try:
                while proc.poll() is None:
                    if stop.wait(0.2):
                        raise RuntimeError('translation cancelled after another batch failed')
                    if time.monotonic() - started >= timeout:
                        raise RuntimeError(f'translator batch {index} timed out after {timeout:g}s; '
                                           f'shader keys: {", ".join(chunk)}; jobs: {job_file}; log: {log_file}. '
                                           'Retry with fewer --jobs or increase NX2A_SHADER_TIMEOUT (seconds).')
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
        output = log_file.read_text(encoding='utf-8', errors='replace')
        summary = re.search(r'^translated: (\d+) ok, (\d+) failed\s*$', output, re.M)
        # Exit 1 is the translator's documented per-shader failure result. A crash,
        # missing runtime or truncated run must not silently produce a partial bundle.
        if (not summary or sum(map(int, summary.groups())) != len(chunk)
                or proc.returncode != (1 if int(summary[2]) else 0)):
            raise RuntimeError(f'translator batch {index} exited {proc.returncode} without a complete result; '
                               f'shader keys: {", ".join(chunk)}; log: {log_file}\n{output[-4000:]}')
        return len(chunk), int(summary[1]), output

    completed = good = 0
    outputs = []
    with cf.ThreadPoolExecutor(min(workers, len(chunks))) as pool:
        pending = {pool.submit(run, i, chunk) for i, chunk in enumerate(chunks)}
        try:
            while pending:
                done, pending = cf.wait(pending, timeout=15, return_when=cf.FIRST_COMPLETED)
                for future in done:
                    count, ok, output = future.result()
                    completed += count
                    good += ok
                    outputs.append(output)
                report(f'translation progress: {completed}/{len(keys)} processed, {good} translated'
                       + ('; waiting for active batches' if not done else ''))
        finally:
            stop.set()
            for future in pending:
                future.cancel()
    return outputs
