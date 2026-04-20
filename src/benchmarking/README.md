# PeerDAS Benchmarks

CSV outputs are written to `benchmarking/results/`.

```bash
python -m src.benchmarking.benchmarks.peerdas.encode_kzg
python -m src.benchmarking.benchmarks.peerdas.verify_kzg
python -m src.benchmarking.benchmarks.peerdas.pairing_counts
```

All timings below are in **milliseconds (ms)**.

---

## Output CSV schemas

### `peerdas_encode_kzg.csv` — encoding benchmark

Produced by `python -m src.benchmarking.benchmarks.peerdas.encode_kzg`.
Times `_encode_matrix` (RS extension + KZG commitments + per-column multi-proofs).

| Column          | Meaning                                                                                                  |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| `phase`         | Fixed label `encode_kzg`, used when merging multiple benchmarks.                                         |
| `n_blobs`       | Number of rows in the blob matrix (PeerDAS `ell`).                                                       |
| `n_cols`        | Number of columns in the extended blob matrix (cells per blob).                                          |
| `block_bytes`   | Size of the raw input block being encoded.                                                               |
| `rs_available`  | `1` if the real Reed-Solomon encoder from `src.reedsolomon` is used, `0` for the stub fallback.          |
| `repetitions`   | Number of timed runs per config (one warmup run is done first so SRS setup is excluded).                 |
| `avg_encode_ms` | Average wall-clock time (ms) for one `_encode_matrix` call.                                              |

**Example:** `encode_kzg,4,16,2048,1,3,30631.11` — a 4×16 matrix over a 2 KB block took ~30.6 s per encode on average (3 runs).

---

### `peerdas_verify_kzg.csv` — verification benchmark

Produced by `python -m src.benchmarking.benchmarks.peerdas.verify_kzg`.
For each `L`, it runs `rounds` rounds; in every round it samples `L` random columns and calls `verify_column` once per column (no batching — each call performs `2 * n_blobs` pairings).

| Column              | Meaning                                                                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `phase`             | Fixed label `verify_kzg`.                                                                                               |
| `n_blobs`           | Row count `ell`. Each `verify_column` uses `2 * n_blobs` pairings.                                                      |
| `n_cols`            | Total columns in the extended matrix.                                                                                   |
| `columns_verified`  | Columns verified per round (`L`, actually `min(L, n_cols)`).                                                            |
| `rounds`            | Number of repeated rounds per `L`.                                                                                      |
| `block_bytes`       | Raw block size.                                                                                                         |
| `rs_available`      | Same as in the encode CSV.                                                                                              |
| `avg_ms_per_round`  | Mean time (ms) of one round = time to verify all `L` columns in that round, averaged across rounds.                    |
| `avg_ms_per_verify` | Mean time (ms) of a single `verify_column` call = `avg_ms_per_round / L`. Represents the steady-state per-column cost. |

**Example:** `verify_kzg,4,16,4,12,2048,1,148790,37197` — with 4 blobs × 16 cols, verifying 4 columns per round over 12 rounds: each round ~148.8 s, each single `verify_column` ~37.2 s (8 pairings inside).

---

### `peerdas_pairing_counts.csv` — analytical pairing cost model

Produced by `python -m src.benchmarking.benchmarks.peerdas.pairing_counts`.
Pure symbolic counts (no timing) that compare per-opening verification against batched verification.

| Column             | Meaning                                                                               |
| ------------------ | ------------------------------------------------------------------------------------- |
| `ell`              | Number of blob rows (naive scheme scales linearly in `ell`).                          |
| `L`                | Number of columns / openings verified in a single batch.                              |
| `naive_pairings`   | Pairings required by the naive path = `2 * L * ell` (2 pairings per `(opening, row)`). |
| `batched_pairings` | Pairings required by `batch_verify`, **always 2**, independent of `L` and `ell`.      |

**Example:** `8,16,256,2` — with `ell = 8, L = 16`, the naive path needs 256 pairings while batched verification always needs only 2.

---

## How the three files fit together

- **`encode_kzg`** measures producer-side cost.
- **`verify_kzg`** measures real verifier cost on the current naive path.
- **`pairing_counts`** gives the theoretical pairing counts; combined with `avg_ms_per_verify` you can estimate the per-pairing cost
  ```
  avg_ms_per_verify / (2 * n_blobs)
  ```
  and project how much time batching would save.

---

## Changing the input parameters

Each benchmark's input parameters live at the bottom of its own module, inside the `if __name__ == "__main__":` block. Edit those calls and re-run with `python -m ...`.

### 1. `encode_kzg` — producer cost

File: `src/benchmarking/benchmarks/peerdas/encode_kzg.py`

```python
if __name__ == "__main__":
    benchmark_encode_kzg(
        configs=[
            (2, 8),
            (4, 8),
            (4, 16),
        ],
        repetitions=3,
        block_bytes=2048,
    )
```

- `configs` — list of `(n_blobs, n_cols)` pairs to benchmark. Add/remove tuples here.
- `repetitions` — timed runs per config (one warmup is always done first).
- `block_bytes` — raw block payload size.

### 2. `verify_kzg` — verifier cost

File: `src/benchmarking/benchmarks/peerdas/verify_kzg.py`

```python
if __name__ == "__main__":
    benchmark_verify_kzg(
        n_blobs=4,
        n_cols=16,
        columns_per_round=[1, 2, 4, 8],
        rounds=12,
        block_bytes=2048,
    )
```

- `n_blobs`, `n_cols` — the single matrix geometry under test.
- `columns_per_round` — list of `L` values; each produces one CSV row. Values are auto-clamped to `n_cols`.
- `rounds` — how many rounds to average per `L`.
- `block_bytes` — raw block payload size.

> **Note:** this script is expensive (each `verify_column` does `2 * n_blobs` pairings). Keep `rounds` and the largest `L` small while iterating.

### 3. `pairing_counts` — analytical counts

File: `src/benchmarking/benchmarks/peerdas/pairing_counts.py`

```python
if __name__ == "__main__":
    benchmark_pairing_counts(ell=8, l_values=[1, 2, 4, 8, 16, 32, 64])
```

- `ell` — blob row count used in the naive formula.
- `l_values` — `L` values to tabulate.

### Calling them from your own script

The `benchmark_*` functions are normal, importable Python functions — you don't have to edit the modules:

```python
from src.benchmarking.benchmarks.peerdas.encode_kzg import benchmark_encode_kzg
from src.benchmarking.benchmarks.peerdas.verify_kzg import benchmark_verify_kzg

benchmark_encode_kzg(configs=[(8, 32)], repetitions=5, block_bytes=8192)
benchmark_verify_kzg(
    n_blobs=8,
    n_cols=32,
    columns_per_round=[1, 4, 16],
    rounds=5,
    block_bytes=8192,
)
```

Each call **appends** to the same CSVs under `benchmarking/results/` (the CSV path is built by `src.benchmarking.utils.paths.benchmark_csv`), so rows accumulate across runs — delete or rename the CSV if you want a clean file.
